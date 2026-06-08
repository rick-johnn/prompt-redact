# prompt-redact — System Review (v1)

> **Purpose:** a complete, accurate description of **what the software does today**, for architecture-team review. Grounded in the current code (2026-06-08), not aspiration. Where behavior is *tested*, *measured*, or *documented-only*, it says so. Annotate inline as needed.
>
> **Scale:** ~1,750 LOC source (Python + Go), ~1,860 LOC tests across 13 test files, 14 implementation specs, plus the compose stack. M0/M1/M2/M4 complete; runs via `docker compose up`.

> **Review note:** Second pass from the same three reviewers — Charles Petzold, Don Box, John Carmack — now against the implemented system rather than the packaging discussion. Two questions were put to them: *is the architecture sound* and *does this offer real value*. They largely agree on the first and productively disagree on the second; both threads are tagged inline.

---

## 1. What it is

An **on-prem PII/PHI redaction microservice**. Callers invoke it explicitly to anonymize text:

- `POST /redact` — text → redacted text + a token map
- `POST /unredact` — text + token map → rehydrated text
- `GET /healthz` — readiness

It does **not** call any LLM and holds **no state**. The calling application orchestrates (decides when to redact, what to do with the result) and **owns the token map**, round-tripping it on each call. Everything runs inside the adopter's environment — no third-party API in the redaction path. (ADR 0002.)

**Primary workload:** short interactive prompts in AI chat clients (not bulk/large documents — that assumption drives the packaging).

> 💬 **[Box]:** The workload question I raised in the packaging review got answered, and answered crisply — "interactive chat prompts," decision of record, dated. That is exactly the resolution I wanted. It also means the single synchronous `/redact` verb is now a *justified* choice rather than an unexamined default, which retroactively settles my "does bulk need its own verb" question: no, because bulk is explicitly not a target. Good. The doc closed its own open question between drafts; that's the system working.

> 💬 **[Carmack]:** This is the value question stated plainly, so I'll answer it plainly here and let the rest of my notes support it. The architecture is sound. Whether it offers *value* depends entirely on one thing the doc is admirably honest about in §5: this redacts names and places via a statistical model, not a guarantee. If your adopters understand they're buying "meaningfully less PII reaches the LLM," it's valuable. If anyone upstream thinks they're buying "PII cannot reach the LLM," you've built a liability, because that product is not buildable this way and §5 knows it. The engineering is fine. The positioning is the risk.

> 💬 **[Petzold]:** "Holds no state" is the most valuable sentence in this section and it's stated in passing. Statelessness is what makes the security story tractable, the scaling story trivial, and the test story honest. Everything good downstream in this document traces back to that one property. Worth promoting it from an adjective to a stated design principle.

---

## 2. Architecture

```
client --HTTP--> Go front-end (public, :8080) --HTTP, loopback--> Python sidecar (internal :8000)
                  - reverse proxy                                  - FastAPI app
                  - edge body-size cap (413)                       - prompt_redact_core
                  - no body logging                                - Microsoft Presidio + spaCy en_core_web_trf
```

- **Sidecar topology** (ADR 0001): a lean Go shell is the public face; the model-bearing Python process is internal-only (loopback / compose-internal network), never exposed.
- **Stateless** per request; horizontally scalable by replicas.
- **Three layers** of code: the pure-Python redaction library (`prompt_redact_core`), the FastAPI service that wraps it (`prompt_redact_service`), and the Go front-end (`frontend`). Plus the eval system (`evals`) and packaging (`deploy`).

> 💬 **[Carmack]:** In the packaging review I pushed hard on the Go front-end — asked what it prevents that a hardened single process wouldn't. The doc now answers: "its value is the trust topology, not speed" (§3.3), and §6/T11 backs it with a *test* that asserts the sidecar is unreachable from the host. That's the right answer and they earned it with a negative test rather than an assertion. I withdraw the objection. One residual: a reverse proxy that only adds a size cap is 14 MB of attack surface and a second language in the build. It's justified *here* because the size cap and the public/private split are the same boundary, but keep it that thin. The day someone wants to add auth or routing or TLS termination to the Go layer, re-litigate whether it should still be a separate process.

> 💬 **[Box]:** The three-layer split is clean and the dependency direction is correct: `core` is pure and HTTP-free, the service wraps it, the front-end wraps the service. Pure domain logic at the center with no framework imports is the thing most teams claim and few achieve, and the lazy-import detail in §3.1 ("importing the package needs no ML stack") is how you can tell it's real — you can unit-test the token algebra without loading torch. That separation is the soundest thing in the architecture. My one structural question is the seam between `core` and `service`: the service catches the `RedactError` family and maps it to HTTP status codes. That mapping *is* an interface, and it's currently expressed as exception-handling code. If a fourth caller ever wants the core library directly (not over HTTP), the error-to-meaning contract lives only in the service layer and they'll have to reverse-engineer it. Worth a short table in `core` documenting which error means what, independent of HTTP.

> 💬 **[Petzold]:** The loopback HTTP hop between Go and Python is the one place the layering costs you something real — you're serializing to JSON and back to cross a process boundary inside one logical service. For short chat turns at 20 ms that overhead is in the noise, so it's fine. But it is the seam I'd watch first if latency ever becomes a complaint, and it's worth a sentence acknowledging that the loopback serialization is a deliberate cost paid for the trust boundary, not a free abstraction.

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

> 💬 **[Carmack]:** This is the core of the system and it's genuinely well-built. Three details that tell me someone thought hard rather than just shipping Presidio behind a route: (1) right-to-left splicing so offsets never invalidate mid-edit — that's the obvious-in-hindsight correct way and most people get it wrong with a left-to-right loop and an offset accumulator that drifts. (2) Token reuse keyed on literal text rather than entity type, with deterministic minting in offset order, so the same input always produces the same map regardless of detection order — that determinism is what makes the eval gate meaningful and the round-trip testable. (3) The checksum recognizers being pure functions with no Presidio import, so the precision-critical logic is unit-testable in isolation. That's the part that has to be *right*, and it's been isolated so it can be proven right. This is the most reassuring section in the document.

> 💬 **[Box]:** The decision to *not* implement MRN/member-ID/Rx because they have no checksum and would be "vanity metrics" is the most mature call in the whole codebase, and I want to flag it as such because it's the kind of decision that usually goes the other way. Most teams ship the regex that matches 70% of MRNs, report a number, and let everyone downstream believe MRNs are "handled." Declining to do that — and saying so in writing — is the difference between an honest system and a checkbox. Keep that discipline.

> 💬 **[Petzold]:** `assign_tokens` raising on "an original reachable from two tokens" is a subtle correctness guard that most reviewers will skim past, so I'll mark it: that's the case where the caller's map already maps `[PERSON_1] → John Doe` and `[PERSON_2] → John Doe`, and on the next turn a detection of "John Doe" can't decide which token to reuse. Failing loudly instead of guessing is correct. But it raises a question the doc should answer: how does a *caller* get into that state? If the only way is a buggy caller hand-editing the map, fine. If the service itself can ever mint two tokens for the same original across turns, that's a latent bug and this guard is catching your own mistake, not theirs. Worth confirming which.

### 3.2 `prompt_redact_service/app.py` — the FastAPI sidecar

- `create_app(analyzer_provider=…, max_body_bytes=…)` factory. **Lifespan** builds (and warms) the analyzer eagerly; on build failure the service stays **up but unready** (`/healthz` → 503) rather than crash-looping. Module-level `app` is the uvicorn entrypoint.
- **Endpoints:** `GET /healthz` (`200 {"status":"ok"}` once warm, else `503`); `POST /redact` (`{text, token_map?, language?}` → `{redacted_text, token_map}`); `POST /unredact` (`{text, token_map}` → `{text}`). Pydantic models; **flat `{token: original}` wire contract (v1)**.
- **Size cap (T9):** `BodySizeLimitMiddleware` (pure ASGI) → `413` on a declared `Content-Length` over the cap *and* a running byte count while buffering (covers chunked/missing length). Configurable via `PROMPT_REDACT_MAX_BODY_BYTES` (default 1 MB).
- **Error mapping:** request validation → **400** (handler overridden from FastAPI's default 422 and **deliberately generic — no input echoed**, T2); token-shaped input / invalid map / unsupported language → **400**; unknown token on unredact → **422**; not ready → **503**; unexpected (engine) failure → **500** generic, logging only the exception type and `raise … from None` so no traceback/message carrying input is logged or returned (T2/T3).
- **Language:** validated against the loaded analyzer's language; a mismatch is `400` (only the language code, not PII, appears).

> 💬 **[Petzold]:** "Up but unready on build failure rather than crash-looping" is exactly right, and it directly closes the readiness concern from the packaging review — the cold-start window now has *defined* behavior (503, gated by `/healthz`) instead of a hope. The size cap doing both a `Content-Length` check *and* a running byte count is the correct paranoid implementation: a `Content-Length` header is a claim, not a fact, and counting bytes while buffering is the only way to defend against a lying or absent one. Whoever wrote that middleware has been burned before, in a good way.

> 💬 **[Box]:** The error-mapping table is the real public contract and it's specified well — though notice `/redact` validation-failure is 400 while `/unredact` unknown-token is 422, which is a deliberate and defensible distinction (malformed request vs well-formed request referencing a token that doesn't exist). That's a genuine semantic choice and I like it. The thing I'd nail down: the 400 handler is "deliberately generic — no input echoed." Good for security (T2). But generic errors are murder to debug in production — when an integrator's request fails with an opaque 400, how do they find out *why* without you echoing their PII back at them? You probably want a correlation ID in the response that maps to a server-side log entry recording the *error type* (never the content). Otherwise every integration failure becomes a support ticket.

> 💬 **[Carmack]:** The `raise … from None` to sever the exception chain so no input-bearing traceback survives is a small, deliberate, correct thing. It's the kind of detail that's invisible when done right and a breach disclosure when done wrong. No notes — this section is solid.

### 3.3 `frontend/` — the Go public shell

- `httputil.ReverseProxy` to the loopback sidecar (`PROMPT_REDACT_UPSTREAM`), plus an **edge body-size cap** (`413` on `Content-Length` over `PROMPT_REDACT_MAX_BODY_BYTES`) and **no request-body logging**. stdlib-only. Config via env (`PROMPT_REDACT_LISTEN` / `_UPSTREAM` / `_MAX_BODY_BYTES`). The sidecar keeps the authoritative size enforcement, redaction logic, and error mapping; the front-end is intentionally thin (its value is the trust topology, not speed).

> 💬 **[Carmack]:** stdlib-only Go for the front-end is the right call — zero third-party dependencies on the public-facing process means the attack surface is the Go standard library and your ~200 lines, nothing else. The edge size cap being a *redundant* check (the sidecar is authoritative) is correct defense-in-depth, not duplication: you want to reject the 2 GB body before it crosses into the Python process, and you also don't trust the edge to be the only guard. Both layers checking is the point.

> 💬 **[Box]:** "Its value is the trust topology, not speed" — this single sentence resolves the entire thread I opened in the packaging review. The front-end isn't there to be fast, it's there to be the only thing exposed. Stated that plainly, the second process is no longer architecture for its own sake; it's the physical embodiment of the security boundary. I'm satisfied.

### 3.4 `evals/` — quality measurement

- **`generator.py`** — deterministic, seeded synthetic corpus. Offsets correct by construction; **checksum-valid** NPI/DEA + Luhn-valid Visa cards (so recognizers actually detect them); domains: healthcare, finance, pbm, generic, plus a no-PII template. Presidio-canonical type names.
- **`models.py`** — `Span`/`Example`, JSONL IO, `validate_example` (offsets in-bounds, slice == value, no overlaps).
- **`metrics.py`** — pure exact-offset scoring: per-entity recall/precision, leakage rate. `RECALL_TARGETS` per tier; `Report` carries the gate logic.
- **`run_eval.py`** — `evaluate(corpus, analyzer)` + a CLI gate (`python -m evals.run_eval`) that prints the report and **exits non-zero if any gated type misses target** (CI-ready).

> 💬 **[Carmack]:** Here's where I have to be the one who says it, because it's the crux of your "does this offer value" question. The eval corpus is *synthetic and self-generated*. You built the generator, you built the recognizers, and the generator plants "checksum-valid NPI/DEA + Luhn-valid Visa cards so recognizers actually detect them." Read that sentence again: the test data is constructed to contain exactly the things the detectors are built to find. A 1.000 recall against that corpus tells you the plumbing works end-to-end and the code has no regressions — which is real and worth having — but it tells you *almost nothing* about recall on real clinical notes or real chat transcripts, where names are misspelled, formats are weird, and context is messy. The doc says this (§5, twice, to its credit). But the number "1.000" on a quality table is going to get screenshotted into a slide and the caveats will not travel with it. If you want to know whether this is actually valuable, the single highest-value thing you can do next is run it against a few hundred *real* (or realistically messy, human-authored, adversarial) examples and see what the recall actually is. That number is the product. Everything in this document is infrastructure for producing that number, and that number does not yet exist.

> 💬 **[Box]:** The eval system being structured as a CLI that exits non-zero on a miss is the right shape — it means "quality" is an executable contract, not a quarterly slide. But Carmack's point above is the one that matters, and I'll add the interface angle: the corpus generator and the recognizers share authorship and assumptions, so they're *coupled* in the way a test and the code-under-test should never be. The generator knows what a valid NPI looks like *because the same person taught the recognizer*. An independent corpus — even a small one, even hand-labeled by someone who never saw the recognizer code — would break that coupling and produce a number you could actually trust. Right now eval and implementation are two halves of one mind.

> 💬 **[Petzold]:** Deterministic and seeded is correct and I won't undersell it — a reproducible corpus is what makes the gate a *regression* detector, and regression detection is genuinely valuable: it tells you when a dependency bump or a refactor quietly broke detection. Keep it. Just don't let it masquerade as a measure of real-world quality, which the doc is careful not to do but a casual reader will.

### 3.5 `deploy/` + `docker-compose.yml` + `examples/`

- **`deploy/sidecar.Dockerfile`** — multi-stage `python:3.11-slim`; deps via `--require-hashes -r requirements.txt` (incl. `torch==2.12.0+cpu`); `trf` model pinned by release-wheel URL (with retry); runs **non-root** (uid 10001); `HEALTHCHECK` on `/healthz`. **3.01 GB.**
- **`frontend/Dockerfile`** — multi-stage Go → **distroless static nonroot**. **14.1 MB.**
- **`docker-compose.yml`** — front-end published on `:8080`; **sidecar internal-only** (`expose`, no host port); front-end gated on `depends_on: condition: service_healthy`.
- **`deploy/compose-smoke.sh`** — brings the stack up, runs the demo caller, and **tests the isolation boundary** (asserts the sidecar is unreachable from the host).
- **`examples/demo_caller.py`** — stdlib multi-turn demo caller (asserts cross-turn token stability + round-trip); doubles as the compose round-trip check.

> 💬 **[Petzold]:** Nearly every estimate from the packaging review is now a measured fact, and that is exactly the discipline I asked for. "~3–4 GB" became **3.01 GB**. "tens of MB" became **14.1 MB**. The tildes are gone. And the CPU-only torch wheel that Carmack flagged got adopted (`torch==2.12.0+cpu`) — which is why the image is 3.01 and not 4-something. This is the packaging discussion having actually done its job: the leanings got built, measured, and recorded. Credit where due.

> 💬 **[Carmack]:** `--require-hashes` on the deps plus `service_healthy` gating plus the non-root uid plus the isolation negative test — all four packaging-review concerns landed. The one I'll keep needling: the `trf` model is still pinned by *URL with retry*, not by hash (§6/T8, §9). "With retry" is a tell — it means the build reaches out to the network and sometimes fails, which is exactly the air-gap-hostile property the whole bake-in-at-build decision was meant to kill. For a fully offline adopter this is the one remaining crack. Mirror the wheel and hash-pin it; until then "no network in the redaction path" is true at runtime but not at build time, and some security reviewer is going to catch that distinction.

> 💬 **[Box]:** The `compose-smoke.sh` script testing the isolation boundary is the artifact I said in the last review would be the most valuable thing in M4, and it exists, and it's a negative test. The demo caller doubling as the round-trip check means your example code and your integration test are the same file — which is the good kind of coupling, because it means the example can never drift out of date without a test failing. That's how you keep documentation honest: make it executable.

---

## 4. API contract

| Endpoint | Request | Response | Errors |
|---|---|---|---|
| `POST /redact` | `{text, token_map?, language?}` | `{redacted_text, token_map}` | 400, 413, 503, 500 |
| `POST /unredact` | `{text, token_map}` | `{text}` | 400, 413, **422**, 503, 500 |
| `GET /healthz` | — | `{"status":"ok"}` / 503 | — |

**Token map (wire v1):** flat JSON `{ "[PERSON_1]": "John Doe" }` — identical to the in-memory shape; versioned only on a future breaking change. **It is the most sensitive object** (contains raw originals); the caller must protect it at the same trust level as the input (encrypt at rest, never log/forward — threat T6).

> 💬 **[Box]:** The token-map schema question I raised first thing in the packaging review is now explicitly addressed: "wire v1," "versioned only on a future breaking change," and a clear statement that it's the most sensitive object. That's the right treatment. One thing still unstated: there's no version *field* in the payload — it's "v1" by convention, not by a discriminator in the JSON. The moment you ship v2, every caller holding a v1 map needs a way to know which shape they have. A `"_v": 1` field (or a version in the response envelope) costs nothing now and saves a migration nightmare later. Add it before the first external adopter, because after that the flat shape is frozen forever.

> 💬 **[Carmack]:** The contract is small, which is the best property an API can have. Two verbs and a health check. Nothing to misuse, little to version, easy to reason about. I have no architectural complaint here — small surface, clear errors. The 422-vs-400 split is meaningful rather than decorative. This is what a service interface should look like.

---

## 5. Redaction quality (measured, not assumed)

Per-mechanism recall **targets**, and the **measured** gate result with the default `trf` model (synthetic corpus, real run 2026-06-07):

| Tier | Types | Target | Measured (`trf`) |
|---|---|---|---|
| Checksum/format | US_SSN, CREDIT_CARD, NPI, DEA, EMAIL_ADDRESS | ≥ 0.99 | 1.000 ✅ |
| Structured pattern | PHONE_NUMBER, DATE_TIME | ≥ 0.95 | 1.000 ✅ |
| Free-text NER | PERSON, LOCATION | ≥ 0.97 | 1.000 ✅ |
| Context-only ID | MRN, MEMBER_ID, RX_NUMBER | report-only | reported, not gated |

Gate **PASSES** with `trf`; leakage 0.003 on the corpus. With `en_core_web_lg` the gate **fails** (PERSON 0.96, DATE 0.90, PHONE 0.88) — which is why `trf` is the default.

**Two standing caveats (important for review):** (1) all numbers are recall **against the synthetic corpus** — a regression gate, **not a production guarantee**; real-world recall depends on how well the corpus mirrors real inputs. (2) The ≤ 1/10,000 end-to-end leakage bar was **retired as a gate** (reported only; bounded by the weakest gated type) — free-text identifiers (names/places) will leak at some rate, an accepted residual that deployments needing more must offset with compensating controls.

> 💬 **[Carmack]:** The two caveats are doing the most important honest work in this entire document, so I want to reinforce them rather than just nod. Caveat 1: a 1.000 against a corpus you generated is a statement about your code's consistency, not about reality — I made this point in §3.4 and it lands hardest right here under a table full of perfect scores. Caveat 2 is the one that actually answers your "real value" question, and it's brutal if you read it carefully: *names and places will leak at some rate, and that's accepted.* For a chat-redaction use case where the main thing people paste is names, that residual *is* the product's true quality, and it's currently unmeasured against anything real. So: is the architecture sound? Yes. Does it offer value? It offers value to an adopter who needs "best-effort PII reduction with a clean on-prem story and an honest accounting of limits." It offers *negative* value to anyone who reads "1.000" and stops there. The difference between those two outcomes is entirely in how loudly you communicate caveat 2. Put it on the same slide as the table, every time.

> 💬 **[Petzold]:** Retiring the 1-in-10,000 leakage bar as a gate is the correct and brave call — an end-to-end leakage guarantee on free-text NER is a promise no statistical model can keep, and gating on a number you can't actually hold would have been worse than not gating at all. But "retired as a gate, reported only" needs to be *louder* than a parenthetical in caveat 2, because the natural reading of this table is "everything is 1.000 and leakage is 0.003, therefore this is essentially perfect," and that is precisely the misreading that gets a deployment in trouble. I'd restructure §5 to lead with the caveats and *then* show the table, not the reverse.

> 💬 **[Box]:** The `lg`-fails-the-gate detail (PERSON 0.96, DATE 0.90, PHONE 0.88) is exactly the inline number I asked for in the packaging review — it makes the `trf`-default decision legible to anyone reading. And it answers the old "ship two variants?" question by demonstration: `lg` literally fails your own bar, so it's correctly demoted to a build-arg escape hatch (§9), not a shipped variant. The doc argued the decision with data instead of asserting it. That's the standard.

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
| T11 | IPC interception | **Mitigated + tested** — sidecar is internal-only (compose negative test asserts it's unreachable from the host); loopback/internal network only. |

Plus: containers run **non-root**; the sidecar makes **no network calls** while processing input (tldextract pinned offline).

> 💬 **[Petzold]:** This table has the property I care about most: it distinguishes **Enforced + tested** from **Mitigated** from **Documented**, honestly, per threat. T2 has a test that asserts the input is absent from an error response — that's the "no body logging" guarantee I demanded in the packaging review, now backed by an executing test instead of a caption on an ASCII box. T4 and T6 are correctly marked "Documented boundary / caller's responsibility" rather than overclaimed as solved — and they are the two threats that actually matter most for the real-world value question, because they're the ones a careless caller trips over. The service is honest that it cannot save a caller from themselves. That honesty is worth more than a false "Enforced."

> 💬 **[Carmack]:** T4 is the whole ballgame and the table is right that it's not solvable in-service. The service can't force a caller to actually call it before shipping text to an LLM. Which means the security value of this entire system is gated on caller discipline that lives outside this codebase. That's not a flaw — it's the correct boundary — but it's the reason I keep saying the *positioning* is the risk, not the engineering. You've built a sound lock. T4 says whether the door gets used is up to someone else. Make sure whoever's buying this understands they're buying a lock, not a guard.

> 💬 **[Box]:** "No network calls while processing input" with the tldextract-pinned-offline detail is a real, specific, verifiable property and it's the kind of claim that distinguishes a serious on-prem product from one that merely runs on-prem. The remaining T8 gap (model wheel not yet hash-pinned/mirrored) is correctly disclosed here *and* in §9 — same gap, listed in both places, not buried. Consistent disclosure across sections is itself a quality signal.

---

## 7. Deployment & operations

- **`docker compose up`** brings up front-end (`:8080`) + sidecar (internal). Verified end-to-end on Docker.
- **Images:** sidecar 3.01 GB (CPU-only, hash-pinned, non-root); front-end 14.1 MB (distroless).
- **Cold start:** ~4–6 s (model load); `/healthz` gates readiness; compose uses `service_healthy`.
- **Latency (measured, CPU):** short message ~20 ms p95; ~500-token ~470 ms. (Latency target is **size-aware**: ≤ 50 ms for short chat-turn messages; large inputs are slower and bounded by the size cap, not handled.)
- **Config (env):** front-end `PROMPT_REDACT_LISTEN` / `_UPSTREAM` / `_MAX_BODY_BYTES`; sidecar `PROMPT_REDACT_MAX_BODY_BYTES`; model via `AnalyzerConfig.spacy_model`.
- **Scaling:** stateless → replicas. **Deploy target of record:** standalone k8s service (manifests not yet written — see §9).

> 💬 **[Petzold]:** Cold start dropped from the packaging review's "tens of seconds" to a measured 4–6 s — either the earlier estimate was pessimistic or something improved, and either way it's now a fact instead of a fear, gated by `service_healthy`. The size-aware latency target is the right framing: ≤ 50 ms for the workload you actually serve (short turns at 20 ms, comfortably under), and an explicit acknowledgment that large inputs are bounded by the cap rather than handled. That's honest capacity planning — it states what it's good at and refuses to pretend about the rest.

> 💬 **[Carmack]:** 20 ms p95 on the real workload is fine and the 470 ms at 500 tokens confirms the linear-ish degradation I flagged before — which is exactly why "bulk is not a target, bounded by the size cap" is the correct scope decision rather than a cop-out. You measured the cliff and then drew the boundary in front of it. Good. The k8s manifests being unwritten (§9) is the real operational gap: "deploy target of record: k8s" with "manifests not yet written" means the *shipped* artifact (compose) and the *intended production* artifact (k8s) are not the same thing, and the compose isolation guarantees (the internal-only sidecar negative test) will need re-proving under k8s NetworkPolicies, which are a completely different and easier-to-misconfigure mechanism. Don't assume the compose security model transfers for free.

> 💬 **[Box]:** Config-by-env across both processes is clean and twelve-factor-correct, and the fact that the same `_MAX_BODY_BYTES` knob exists on both the front-end and the sidecar mirrors the defense-in-depth from §3.3 — same boundary, enforced twice, configured consistently. The one thing I'd document: what happens if the two caps are set to *different* values? Front-end cap higher than sidecar cap means the sidecar rejects what the edge allowed (fine, just a wasted hop); the reverse means the edge rejects what the sidecar would've accepted (also fine, but surprising). State the intended relationship so an operator doesn't set them inconsistently and spend a day debugging 413s.

---

## 8. Testing

- **Python:** 13 test files, ~217 tests. Pure-logic tests (token engine, map-merge, guards, unredactor, recognizer checksums, eval corpus/metrics, service behavior via fake analyzers) run with no ML stack; **integration tests** exercise real Presidio/`trf` and the FastAPI app (auto-skip if the model is absent — but **run** in a Docker/CI env with it).
- **Go:** `frontend/proxy_test.go` (proxy forwarding, 413 cap, healthz, bad-upstream).
- **Stack:** `deploy/compose-smoke.sh` (compose up → demo caller round-trip → sidecar-isolation negative test).
- **Quality gate:** `python -m evals.run_eval` (non-zero exit on miss).
- **Known CI consideration:** running the full Python suite loads `trf`/torch across several fixtures and can OOM a small runner — shard or provision RAM.

> 💬 **[Carmack]:** ~217 tests against ~1,750 LOC, with the pure-logic layer testable without the ML stack via fake analyzers — that test-to-source ratio and that structure are both right. The fake-analyzer pattern is what lets you test the token algebra and error mapping fast and deterministically without loading torch, and it's the direct payoff of the clean `core`/`service` separation Box praised in §2. The one honest gap: "integration tests auto-skip if the model is absent." That means on a dev laptop without the model, the suite goes green having *not* run the tests that exercise the real detector. A green checkmark that silently skipped the hardest tests is a trap — make sure CI fails loudly if the model is missing rather than skipping, so "tests pass" means the same thing everywhere.

> 💬 **[Petzold]:** The CI-OOM consideration I raised in the packaging review survived into the implementation notes, which means it wasn't forgotten — but it's still listed as a "consideration," not a solved problem, and §9 confirms there's no CI pipeline yet. So the OOM risk is *known and documented* but not yet *handled*, because there's no CI to handle it in. That's an accurate status, just don't mistake "documented" for "done" when the pipeline gets built.

> 💬 **[Box]:** The Go test covering "bad-upstream" behavior is the one I'm happiest to see, because it tests the front-end's behavior when the sidecar is *down* — which is the partial-failure semantics question I raised about the loopback seam in the packaging review. You're testing what the public face does when the private engine is unavailable. That's the seam that matters in production, and it has a test.

---

## 9. Known limitations & deferred items (none blocking v1)

- **Context-only IDs (MRN, member-ID, Rx) are report-only** — no recognizer; they redact only incidentally. Dedicated context-anchored recognizers are deferred (need corpus tuning).
- **Bulk / large documents are not a target** — bounded by the size cap (413), not handled; ~500-token latency is ~470 ms on CPU.
- **Single language (en)** — per-call `language` is validated, not multi-model.
- **No auth / rate limiting / multi-tenant** — by design, handled by surrounding infra (ADR 0002 non-goals).
- **Model wheel not yet hash-pinned/mirrored** — deps are; the `trf` model is pinned by version URL (remaining T8 nicety).
- **No k8s manifests** (compose is the shipped artifact); **no CI pipeline** yet.
- **M3 (hybrid regex+NER) parked** — low value with `trf` (PERSON still needs the full NER pass).
- **`lg` is a build-arg escape hatch only** — not a shipped/tested variant; it fails the recall gate.

> 💬 **[Box]:** This is the most valuable section in the document for answering "is the architecture sound," because a system's soundness is measured as much by what it *refuses* to do as by what it does. Every item here is a scope boundary drawn on purpose: no auth (infra's job), no multi-tenant, no bulk, single language, MRN report-only. None of these are accidental gaps — they're decisions, and they're consistent with the ADR 0002 non-goals. A system that knows its own boundaries this precisely is architecturally sound almost by definition. The two I'd treat as actual pre-adopter must-dos rather than "deferred niceties": the model-wheel hash-pin (it undercuts the offline story) and *something* for CI (because "no CI pipeline" plus "tests can OOM" plus "integration tests auto-skip" compounds into "we don't actually know the tests pass in a clean environment").

> 💬 **[Carmack]:** "None blocking v1" is the right call for everything here *except* possibly the model-wheel pin, and only because it's load-bearing for the central selling point. Everything else — k8s manifests, CI, M3, multi-language — is honest deferral of work that doesn't change what the system *is*. The model pin is different in kind: it's the gap between "fully offline" (what an air-gapped buyer thinks they're getting) and "offline at runtime, networked at build" (what they're actually getting). For most adopters that's a footnote. For the air-gapped healthcare adopter who is your most natural customer, it might be the whole deal. Rank it above the rest.

> 💬 **[Petzold]:** Honest, complete, and self-aware. A limitations section this candid is itself evidence the architecture is sound, because unsound systems don't know where their edges are. The discipline of writing "report-only," "not handled," "not a shipped variant," "no CI pipeline yet" — in a document meant to be reviewed by people deciding whether the thing has value — is the opposite of the vanity-metrics temptation the team correctly resisted in §3.1. Same discipline, document-wide.

---

## 10. Decisions of record

- **ADR 0002** — redaction-only microservice, not an LLM proxy; caller owns the map; stateless.
- **ADR 0001** — sidecar topology; Go front-end + Python/Presidio sidecar over loopback HTTP.
- **Per-type recall targets** (2026-06-07) — by detection mechanism, replacing one 0.99 bar; leakage reported not gated.
- **`en_core_web_trf` default** (2026-06-07) — the only config that passes the gate; measured cost recorded.
- **Workload = interactive chat prompts** (2026-06-08) — settled CPU-only, `trf`-only, single sync verb, size-cap-bounds-pastes.

> 💬 **[Box]:** A dated decision log with the *reasoning* attached (not just the choice) is what lets the next architect understand why, not just what — and it's what prevents someone re-opening "why not lg?" or "why two processes?" in six months. The packaging review's open questions are now traceable to dated decisions here. That's the loop closing properly: discussion → decision → record. This is how institutional memory is supposed to work.

> 💬 **[Carmack]:** The 2026-06-08 workload decision is the keystone — once "interactive chat prompts" is settled, CPU-only and `trf`-only and single-sync-verb all follow deductively, and the doc shows that chain. That's the difference between a pile of choices and an architecture: the decisions depend on each other in a stated order, rooted in one decision about what the thing is *for*. Sound.

---

## 11. Where to look

`docs/ARCHITECTURE.html` (design, threat model, quality targets) · `docs/CALLER_GUIDE.html` (integration) · `docs/PLAN.html` (milestones + decision log) · `docs/specs/m1-*..m2-*.html` (per-feature specs) · `docs/plans/*.html` (milestone plans) · `M4_PACKAGING_DISCUSSION.md` (packaging review + measured numbers).

---

## Reviewer verdict (summary)

Two questions were asked: *is the architecture sound*, and *does this offer real value*. The reviewers converged on the first and gave a qualified, conditional answer on the second.

**Is the architecture sound? — Yes, with consensus.**

- **Petzold:** The system's soundness shows most in what it refuses to do and how honestly it labels its own edges — *enforced* vs *mitigated* vs *documented*, *measured* vs *target*, *shipped* vs *escape-hatch*. Statelessness is the root property that makes everything else tractable. The packaging review's estimates all became measured facts. Sound.
- **Box:** The `core`/`service`/`frontend` layering is clean with correct dependency direction and genuinely framework-free domain logic at the center. The trust-topology justification for the second process resolves cleanly. The decision log closes the loop from discussion to decision to record. Sound — fix the missing token-map version field before the first external adopter.
- **Carmack:** The core redaction logic (right-to-left splicing, deterministic text-keyed token reuse, pure-function checksum recognizers) is well-built and the right design. Every packaging-review concern landed. Sound.

**Does it offer real value? — Conditional, and the condition is honesty about limits, not more engineering.**

This is where the three press hardest, in agreement:

- The headline quality numbers (1.000 recall, 0.003 leakage) are measured against a **synthetic, self-authored corpus** where the test data is built to contain what the detectors are built to find. That proves the plumbing and guards against regressions — real value — but says little about real-world recall. **Carmack:** the single highest-value next step is running it against a few hundred realistically messy or hand-labeled examples; *that* number is the product, and it does not yet exist. **Box:** the corpus and recognizers share authorship, so they're coupled the way test and code-under-test never should be; an independent corpus would produce a number you could trust.
- The genuine quality of the product for its actual chat workload is **caveat 2 in §5**: names and places will leak at some accepted rate. For a use case where names are the main thing pasted, that residual *is* the product's true quality — currently unmeasured against anything real. Its value depends entirely on communicating this as loudly as the 1.000 table.
- **T4** (caller forgets to redact) is unsolvable in-service by design, which means the system's real-world value is gated on caller discipline that lives outside this codebase. It's a sound lock, not a guard. The positioning risk — letting anyone believe they bought a guarantee — is larger than any engineering risk in the codebase.

**Net:** architecturally sound and unusually honest; valuable to an adopter who needs best-effort, on-prem PII reduction with a clear-eyed account of limits; actively risky only if the 1.000 headline travels without its caveats. The next move that most changes the value picture is not more code — it's one real-world recall measurement.