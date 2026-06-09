# prompt-redact — System Review (v1)

> **Purpose:** a complete, accurate description of **what the software does today**, for architecture-team review. Grounded in the current code (2026-06-08), not aspiration. Where behavior is *tested*, *measured*, or *documented-only*, it says so. Annotate inline as needed.
>
> **Scale:** ~1,750 LOC source (Python + Go), ~1,860 LOC tests across 13 test files, 14 implementation specs, plus the compose stack. M0/M1/M2/M4 complete; runs via `docker compose up`.

---

## 1. What it is

An **on-prem PII/PHI redaction microservice**. Callers invoke it explicitly to anonymize text:

- `POST /redact` — text → redacted text + a token map
- `POST /unredact` — text + token map → rehydrated text
- `GET /healthz` — readiness

It does **not** call any LLM and holds **no state**. The calling application orchestrates (decides when to redact, what to do with the result) and **owns the token map**, round-tripping it on each call. Everything runs inside the adopter's environment — no third-party API in the redaction path. (ADR 0002.)

**Primary workload:** short interactive prompts in AI chat clients (not bulk/large documents — that assumption drives the packaging).

---

## 2. Architecture

```
client ──HTTP──▶ Go front-end (public, :8080) ──HTTP, loopback──▶ Python sidecar (internal :8000)
                  · reverse proxy                                  · FastAPI app
                  · edge body-size cap (413)                       · prompt_redact_core
                  · no body logging                                · Microsoft Presidio + spaCy en_core_web_trf
```

- **Sidecar topology** (ADR 0001): a lean Go shell is the public face; the model-bearing Python process is internal-only (loopback / compose-internal network), never exposed.
- **Stateless** per request; horizontally scalable by replicas.
- **Three layers** of code: the pure-Python redaction library (`prompt_redact_core`), the FastAPI service that wraps it (`prompt_redact_service`), and the Go front-end (`frontend`). Plus the eval system (`evals`) and packaging (`deploy`).

---

## 3. Components & behavior

### 3.1 `prompt_redact_core/` — the redaction library (pure Python, no HTTP)

Importing the package needs no ML stack; Presidio/torch load lazily only when an analyzer is built.

- **`tokens.py` — token engine.** Token format `[<ENTITY_TYPE>_<N>]` (e.g. `[PERSON_1]`); entity type is `[A-Z][A-Z_]*` (no digits, so `_N` parses unambiguously), `N` a positive integer with no leading zeros.
  - `assign_tokens(detections, token_map)` — the **map-merge**: builds an `original → token` reverse index from the supplied map; a detected span whose **literal original text** is already known reuses its token (reuse is keyed on the text, *not* the entity type); a new original mints `max_existing_N + 1` for its type. Minting follows `(start, end)` offset order, so output is independent of detection order. Empty-text detections are skipped. The input map is never mutated; a fresh `new_map` is returned. Raises `MalformedTokenMapError` on a bad key or an original reachable from two tokens.
  - `apply_replacements(text, replacements)` — validates spans (in-bounds, `start ≤ end`, **non-overlapping**) and splices **right-to-left**, so offsets stay valid and inserted text is never re-scanned.
- **`guards.py` — the T5 guard.** `assert_no_token_shapes(text)` rejects input that already contains a minted-token-shaped substring (reuses the same `TOKEN_RE`), raising `TokenShapedInputError` carrying every offending match. Redact-path precondition only (never run on unredact input).
- **`recognizers.py` — custom recognizers.** Checksum-validated provider IDs Presidio lacks: **NPI** (10 digits; Luhn over `"80840"`+first 9) and **DEA** (2 letters + 7 digits; checksum on the 7th). Pure validators (`is_valid_npi`/`is_valid_dea`, no Presidio import) carry the precision-critical logic; `build_custom_recognizers()` wraps them as Presidio `PatternRecognizer`s lazily, using the `validate_result` checksum hook (valid → kept, invalid → discarded, independent of threshold). **MRN / member-ID / Rx are deliberately NOT implemented** (no checksum/format → would be vanity metrics; report-only).
- **`analyzer.py` — Presidio wrapper.** `RedactionAnalyzer(AnalyzerConfig)` returns analyzer-agnostic `Detection`s.
  - `AnalyzerConfig`: `language="en"`, `score_threshold=0.0` (Presidio defaults), `entities=None` (all types), `spacy_model="en_core_web_trf"` (default; `en_core_web_lg` selectable), `custom_recognizers=True`.
  - `resolve_overlaps` — Presidio returns overlapping spans (e.g. EMAIL vs URL); this picks a deterministic non-overlapping subset ranked by (score desc, length desc, start asc, type asc), since right-to-left replacement rejects overlaps.
  - Engine built **lazily** on first `analyze`; the M2 service builds it **eagerly at startup**. **Offline hardening:** pins `tldextract` to an offline extractor so the email recognizer makes no network call.
- **`redactor.py` — `redact(text, token_map=None, *, analyzer)`.** Thin orchestration: T5 guard → `analyzer.analyze` → `assign_tokens` → `apply_replacements` → `(redacted_text, token_map)`. The analyzer is **injected** (it owns the heavy model; built once, reused). Returns a fresh map.
- **`unredactor.py` — `unredact(text, token_map)`.** `find_tokens` → look up each → **strict, all-or-nothing**: an unknown token raises `UnknownTokenError` (substitutes nothing). Single-pass right-to-left, so an original value that itself contains a token shape is spliced verbatim and never re-substituted.
- **`errors.py` — typed errors.** All derive from `RedactError` (so the service catches the family): `InvalidEntityTypeError`, `MalformedTokenMapError`, `OverlappingSpansError`, `TokenShapedInputError`, `UnknownTokenError`.

### 3.2 `prompt_redact_service/app.py` — the FastAPI sidecar

- `create_app(analyzer_provider=…, max_body_bytes=…)` factory. **Lifespan** builds (and warms) the analyzer eagerly; on build failure the service stays **up but unready** (`/healthz` → 503) rather than crash-looping. Module-level `app` is the uvicorn entrypoint.
- **Endpoints:** `GET /healthz` (`200 {"status":"ok"}` once warm, else `503`); `POST /redact` (`{text, token_map?, language?}` → `{redacted_text, token_map}`); `POST /unredact` (`{text, token_map}` → `{text}`). Pydantic models; **flat `{token: original}` wire contract (v1)**.
- **Size cap (T9):** `BodySizeLimitMiddleware` (pure ASGI) → `413` on a declared `Content-Length` over the cap *and* a running byte count while buffering (covers chunked/missing length). Configurable via `PROMPT_REDACT_MAX_BODY_BYTES` (default 1 MB). The cap exists at both layers (edge = cheap reject, sidecar = authoritative); how they relate and how to set them coherently is documented in [ARCHITECTURE — request size caps](docs/ARCHITECTURE.html#size-caps).
- **Error mapping:** request validation → **400** (handler overridden from FastAPI's default 422 and **deliberately generic — no input echoed**, T2); token-shaped input / invalid map / unsupported language → **400**; unknown token on unredact → **422**; not ready → **503**; unexpected (engine) failure → **500** generic, logging only the exception type and `raise … from None` so no traceback/message carrying input is logged or returned (T2/T3).
- **Correlation IDs (operability):** every response carries an `X-Correlation-ID` header and every *error* body includes the same `correlation_id`. A caller-supplied `X-Correlation-ID` (or `X-Request-ID`) is reused when log-safe (`[A-Za-z0-9._-]{1,128}`, which blocks log injection and unbounded values), otherwise the service mints a uuid4. The ID is logged next to the error *type and status only* — never the input — so an opaque generic 400 is traceable to a server-side log line without any PII crossing the boundary (addresses the review's "generic errors are murder to debug" concern). The `CorrelationIdMiddleware` is the outermost layer, so even the size-limit `413` is stamped.
- **Language:** validated against the loaded analyzer's language; a mismatch is `400` (only the language code, not PII, appears).

### 3.3 `frontend/` — the Go public shell

- `httputil.ReverseProxy` to the loopback sidecar (`PROMPT_REDACT_UPSTREAM`), plus an **edge body-size cap** (`413` on `Content-Length` over `PROMPT_REDACT_MAX_BODY_BYTES`) and **no request-body logging**. stdlib-only. Config via env (`PROMPT_REDACT_LISTEN` / `_UPSTREAM` / `_MAX_BODY_BYTES`). The sidecar keeps the authoritative size enforcement, redaction logic, and error mapping; the front-end is intentionally thin (its value is the trust topology, not speed).

### 3.4 `evals/` — quality measurement

- **`generator.py`** — deterministic, seeded synthetic corpus. Offsets correct by construction; **checksum-valid** NPI/DEA + Luhn-valid Visa cards (so recognizers actually detect them); domains: healthcare, finance, pbm, generic, plus a no-PII template. Presidio-canonical type names.
- **`models.py`** — `Span`/`Example`, JSONL IO, `validate_example` (offsets in-bounds, slice == value, no overlaps).
- **`metrics.py`** — pure exact-offset scoring: per-entity recall/precision, leakage rate. `RECALL_TARGETS` per tier; `Report` carries the gate logic.
- **`run_eval.py`** — `evaluate(corpus, analyzer)` + a CLI gate (`python -m evals.run_eval`) that prints the report and **exits non-zero if any gated type misses target** (CI-ready).

### 3.5 `deploy/` + `docker-compose.yml` + `examples/`

- **`deploy/sidecar.Dockerfile`** — multi-stage `python:3.11-slim`; deps via `--require-hashes -r requirements.txt` (incl. `torch==2.12.0+cpu`); the `trf` model wheel is **hash-pinned** (`requirements-model.txt`, installed `--require-hashes --no-deps` — its dep `spacy-curated-transformers` is in the lockfile, with retry); runs **non-root** (uid 10001); `HEALTHCHECK` on `/healthz`. **2.82 GB.**
- **`frontend/Dockerfile`** — multi-stage Go → **distroless static nonroot**. **14.1 MB.**
- **`docker-compose.yml`** — front-end published on `:8080`; **sidecar internal-only** (`expose`, no host port); front-end gated on `depends_on: condition: service_healthy`.
- **`deploy/compose-smoke.sh`** — brings the stack up, runs the demo caller, and **tests the isolation boundary** (asserts the sidecar is unreachable from the host).
- **`examples/demo_caller.py`** — stdlib multi-turn demo caller (asserts cross-turn token stability + round-trip); doubles as the compose round-trip check.

---

## 4. API contract

| Endpoint | Request | Response | Errors |
|---|---|---|---|
| `POST /redact` | `{text, token_map?, language?}` | `{redacted_text, token_map}` | 400, 413, 503, 500 |
| `POST /unredact` | `{text, token_map}` | `{text}` | 400, 413, **422**, 503, 500 |
| `GET /healthz` | — | `{"status":"ok"}` / 503 | — |

**Token map (wire v1):** flat JSON `{ "[PERSON_1]": "John Doe" }` — identical to the in-memory shape; versioned only on a future breaking change. **It is the most sensitive object** (contains raw originals); the caller must protect it at the same trust level as the input (encrypt at rest, never log/forward — threat T6).

---

## 5. Redaction quality (measured — read the caveats first)

**Before the numbers, the two caveats that bound what they mean** (deliberately placed *above* the table so they travel with it):

1. **The numbers are corpus-relative, not a production guarantee.** All figures are recall **against the synthetic corpus** — a *regression gate*. The corpus is self-authored and contains exactly the identifier shapes the detectors target, so a high score proves the pipeline is consistent and regression-free; it says little about real-world recall on messy/adversarial input. **First step taken (2026-06-08):** an independent-corpus harness (`evals/realworld.py`, report-only) scored against a hand-authored *adversarial* sample surfaced real gaps — obfuscated emails (EMAIL 0.67), space-separated SSN (0.00), full street addresses (LOCATION 0.00) — while PERSON held at 1.0 even on misspelled/lowercase/non-Western names. See `docs/specs/m1-10-realworld-recall.html`. Still synthetic-but-adversarial and small-n; a corpus **hand-labeled by someone who never saw the recognizers** remains the goal, and *that* number is the product.
2. **Free-text identifiers leak at an accepted rate.** The ≤ 1/10,000 end-to-end leakage bar was **retired as a gate** (reported only; bounded by the weakest gated type). Names and places **will leak** at some rate — for a chat workload where names dominate, that residual *is* the product's true quality, and deployments needing more must add compensating controls. This must be communicated as loudly as the table.

With those firmly in mind — the per-mechanism **targets** and the **measured** gate result (default `trf`, synthetic corpus, 2026-06-07):

| Tier | Types | Target | Measured (`trf`)* |
|---|---|---|---|
| Checksum/format | US_SSN, CREDIT_CARD, NPI, DEA, EMAIL_ADDRESS | ≥ 0.99 | 1.000 |
| Structured pattern | PHONE_NUMBER, DATE_TIME | ≥ 0.95 | 1.000 |
| Free-text NER | PERSON, LOCATION | ≥ 0.97 | 1.000 |
| Context-only ID | MRN, MEMBER_ID, RX_NUMBER | report-only | reported, not gated |

<sub>*corpus-relative, per caveat 1 — not a real-world figure.</sub>

Gate **PASSES** with `trf` (leakage 0.003 on the corpus). With `en_core_web_lg` it **fails** (PERSON 0.96, DATE 0.90, PHONE 0.88) — hence `trf` is the default.

---

## 6. Security & threat posture

| # | Threat | Status today |
|---|---|---|
| T2 | PII in request/response logs | **Enforced** — no body logging; error responses generic (never echo input). Tested: an engine error embedding the input returns a generic 500 with the input asserted absent. |
| T3 | PII via crash/traceback | **Mitigated** — unexpected errors are converted to a generic 500 with `from None`; only the exception type is logged. |
| T4 | Caller forgets to call `/redact` → leaks to LLM | **Documented boundary** — the service can't enforce its own use; the caller must. (CALLER_GUIDE.) Not solvable in-service. |
| T5 | Token-shaped substring in input | **Enforced + tested** — `assert_no_token_shapes` → 400. |
| T6 | Caller mishandles the token map | **Documented** — the map is sensitive; caller's responsibility (encrypt/never log). |
| T8 | Supply-chain (deps/model) | **Mitigated** — `requirements.txt` is a `--generate-hashes` lockfile (incl. CPU torch); image installs `--require-hashes`. *Remaining:* mirror the model wheel for fully-offline builds. |
| T9 | Oversized body DoS | **Enforced + tested** — size cap → 413 at both the front-end (edge) and the sidecar (authoritative). |
| T11 | IPC interception | **Mitigated + tested (compose + k8s)** — sidecar is internal-only: compose has no host port (negative test); k8s adds a default-deny `NetworkPolicy` admitting only the front-end, proven enforced by `deploy/k8s/netpol-isolation-test.sh` (reachable before the policy, blocked after; allowed path intact). |

Plus: containers run **non-root**; the sidecar makes **no network calls** while processing input (tldextract pinned offline).

---

## 7. Deployment & operations

- **`docker compose up`** brings up front-end (`:8080`) + sidecar (internal). Verified end-to-end on Docker.
- **Images:** sidecar 2.82 GB (CPU-only, fully hash-pinned incl. the model wheel, non-root); front-end 14.1 MB (distroless).
- **Cold start:** ~4–6 s (model load); `/healthz` gates readiness; compose uses `service_healthy`.
- **Latency (measured, CPU):** short message ~20 ms p95; ~500-token ~470 ms. (Latency target is **size-aware**: ≤ 50 ms for short chat-turn messages; large inputs are slower and bounded by the size cap, not handled.)
- **Config (env):** front-end `PROMPT_REDACT_LISTEN` / `_UPSTREAM` / `_MAX_BODY_BYTES`; sidecar `PROMPT_REDACT_MAX_BODY_BYTES`; model via `AnalyzerConfig.spacy_model`.
- **Scaling:** stateless → replicas. **Deploy target of record:** standalone k8s service (manifests not yet written — see §9).

---

## 8. Testing

- **Python:** 13 test files, ~217 tests. Pure-logic tests (token engine, map-merge, guards, unredactor, recognizer checksums, eval corpus/metrics, service behavior via fake analyzers) run with no ML stack; **integration tests** exercise real Presidio/`trf` and the FastAPI app. They **auto-skip** if the model is absent (so a contributor without the ML stack still gets the pure tests) — but in **CI they fail loud**: the integration job sets `PROMPT_REDACT_REQUIRE_MODEL=1`, and `tests/conftest.py` converts any integration *skip* into a *failure* (and fails if integration tests were selected but none ran). A green build can no longer mean "silently skipped the hardest tests."
- **Go:** `frontend/proxy_test.go` (proxy forwarding, 413 cap, healthz, bad-upstream).
- **Stack:** `deploy/compose-smoke.sh` (compose up → demo caller round-trip → sidecar-isolation negative test).
- **Quality gate:** `python -m evals.run_eval` (non-zero exit on miss).
- **CI:** `.github/workflows/ci.yml` — three jobs: **unit** (pure-logic, no ML stack), **integration** (installs the hash-pinned runtime + model and runs the real path in fail-loud strict mode), and **go** (front-end). The OOM risk (loading `trf`/torch across several session fixtures) is handled by running the integration files **one per process**, so peak memory is bounded to one model at a time.

---

## 9. Known limitations & deferred items (none blocking v1)

- **Context-only IDs (MRN, member-ID, Rx) are report-only** — no recognizer; they redact only incidentally. Dedicated context-anchored recognizers are deferred (need corpus tuning).
- **Bulk / large documents are not a target** — bounded by the size cap (413), not handled; ~500-token latency is ~470 ms on CPU.
- **Single language (en)** — per-call `language` is validated, not multi-model.
- **No auth / rate limiting / multi-tenant** — by design, handled by surrounding infra (ADR 0002 non-goals).
- **Model wheel hash-pinned; mirroring is a deployment step** — the `trf` model wheel is now SHA256-pinned (`requirements-model.txt`, `--require-hashes`) and its dep `spacy-curated-transformers` is in the lockfile, so the whole image is hash-verified. For a *fully air-gapped* build, mirror the wheel inside your trust boundary and swap the URL (the hash still verifies) — that mirroring step is deployment-specific, not shipped.
- **k8s: starter manifests + proven isolation, not a packaged deploy.** `deploy/k8s/` has the namespace, ClusterIP Services, and NetworkPolicies, with `netpol-isolation-test.sh` proving east-west isolation on k3d/k3s (T11). Still future work: a packaged Helm/Kustomize chart, resource tuning, PodSecurity/egress policies, and a k8s deploy pipeline. CI exists (`.github/workflows/ci.yml`, fail-loud integration job).
- **M3 (hybrid regex+NER) parked** — low value with `trf` (PERSON still needs the full NER pass).
- **`lg` is a build-arg escape hatch only** — not a shipped/tested variant; it fails the recall gate.

---

## 10. Decisions of record

- **ADR 0002** — redaction-only microservice, not an LLM proxy; caller owns the map; stateless.
- **ADR 0001** — sidecar topology; Go front-end + Python/Presidio sidecar over loopback HTTP.
- **Per-type recall targets** (2026-06-07) — by detection mechanism, replacing one 0.99 bar; leakage reported not gated.
- **`en_core_web_trf` default** (2026-06-07) — the only config that passes the gate; measured cost recorded.
- **Workload = interactive chat prompts** (2026-06-08) — settled CPU-only, `trf`-only, single sync verb, size-cap-bounds-pastes.

## 11. Where to look

`docs/ARCHITECTURE.html` (design, threat model, quality targets) · `docs/CALLER_GUIDE.html` (integration) · `docs/PLAN.html` (milestones + decision log) · `docs/specs/m1-*..m2-*.html` (per-feature specs) · `docs/plans/*.html` (milestone plans) · `M4_PACKAGING_DISCUSSION.md` (packaging review + measured numbers).
