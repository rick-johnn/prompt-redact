# prompt-redact

An on-prem PII redaction microservice that calling applications invoke explicitly on text they want anonymized. The service exposes `POST /redact` (text → redacted text + token map) and `POST /unredact` (text + token map → rehydrated text). It does **not** proxy LLM calls — the caller decides whether to send redacted text to an LLM, log it, index it, throw it away, or show it back to the user.

> **Status:** **M1, M2, and M4 complete** (as of 2026-06-08). The redactor core passes its quality gate (default `en_core_web_trf`), the full sidecar (Go front-end → Python FastAPI sidecar) is built and tested, and the stack is packaged: **`docker compose up`** brings up the front-end + sidecar with a hash-pinned, CPU-only image. See [`docs/PLAN.html`](docs/PLAN.html) for milestones, [`docs/CALLER_GUIDE.html`](docs/CALLER_GUIDE.html) to integrate, and [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) for the design.
>
> The service shape changed on 2026-05-30 from a transparent OpenAI-compatible proxy to a standalone redaction microservice. See [`docs/decisions/0002-service-shape.html`](docs/decisions/0002-service-shape.html).

## Why

Chat surfaces in regulated industries routinely receive prompts containing identifiers that must not spread to systems not cleared to hold them. A third-party LLM is the obvious case, but rarely the only one. The exact category and the exact regulator change by domain, but the shape of the problem is the same:

| Domain | Examples of identifiers | Driving regime(s) |
|---|---|---|
| Healthcare | Patient names, DOBs, MRNs, ICD/CPT codes, clinical narratives | HIPAA (Safe Harbor / Expert Determination) |
| Finance | Account numbers, card PANs, SSNs, balances, transaction histories | PCI-DSS, GLBA, SOX, state privacy laws |
| Pharma & clinical research | Subject IDs, trial site codes, adverse-event narratives | HIPAA + GxP + sponsor data-use agreements |
| Legal & professional services | Client names, matter numbers, privileged content | Attorney–client privilege, bar association rules |
| Cross-border / EU | Anything that qualifies as personal data | GDPR, UK GDPR, regional equivalents |
| Public sector & education | Citizen records, case files, student records | Privacy Act, FERPA, state equivalents |

Sending that text to a hosted LLM creates compliance exposure regardless of which regime applies — but it isn't the whole problem. Even when an organization already holds a Business Associate Agreement (or equivalent) permitting one approved LLM, the same text still flows into systems that *aren't* covered: LLM observability and prompt-logging tools, analytics warehouses, evaluation harnesses, and any model that isn't on the approved list. `prompt-redact` exists so the caller can run a single redaction step up front — clean the text once, then use it safely across every downstream consumer (the LLM, logs, indexes, eval, archives) — and reverse the substitution with `/unredact` where rehydration is appropriate. The caller orchestrates; the service only redacts (see [ADR 0002](docs/decisions/0002-service-shape.html)).

> Throughout the design docs, healthcare/HIPAA appears as the most prescriptive example (it's the regime with the most specific entity list — the [Safe Harbor identifier list](https://www.hhs.gov/hipaa/for-professionals/privacy/special-topics/de-identification/index.html)). The architecture and threat model are not healthcare-specific; the entity set the redactor catches is configurable per deployment.

## Shape of the system

```
       ┌────────────────────────┐
       │  Caller                │   (chat app, batch job, indexer,
       │  - owns the token map  │    eval harness, audit pipeline…)
       │  - orchestrates        │
       └────────┬───────┬───────┘
                │       │
   POST /redact │       │ POST /unredact
                ▼       ▼
       ┌────────────────────────┐
       │  prompt-redact         │   (stateless; no LLM in the picture)
       │  Presidio + token map  │
       └────────────────────────┘
```

The caller is responsible for storing the returned token map for the lifetime of a conversation, passing it back on subsequent `/redact` calls (for cross-turn consistency), and calling `/unredact` on LLM responses if they want to rehydrate identifiers for the user. The service itself is stateless.

## Architectural choices (locked for v1)

| Decision | Choice |
|---|---|
| Service shape | Redaction microservice (`/redact` + `/unredact`); not an LLM proxy. See [ADR 0002](docs/decisions/0002-service-shape.html). |
| Hosting | On-prem / self-hosted only (no third-party APIs in the redaction path — required for HIPAA, PCI-DSS, GDPR-strict, and similar regimes) |
| Redaction engine | [Microsoft Presidio](https://github.com/microsoft/presidio) |
| Token map ownership | Caller-owned; round-tripped on each call. The service holds no per-caller state. |
| Reversibility | Reversible via `[TYPE_N]` tokens and an explicit `/unredact` endpoint |
| Implementation language & topology | **Sidecar** — a fast front-end (Go or TypeScript) + a Python Presidio sidecar over loopback IPC. Final front-end pick (Go vs TS) at M1 start. See [ADR 0001](docs/decisions/0001-language-and-topology.html). |

Cloud DLP (GCP / AWS Macie) and Philter were considered and deferred. See [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html#alternatives-considered).

## Why not just use Presidio?

Fair question — and the honest answer is that [Presidio](https://github.com/microsoft/presidio) does the hard part. It's the detection and anonymization **engine**: NER, recognizers, and regex that decide "`John Doe` is a PERSON, `12345` is an MRN," plus operators to replace/mask/hash/encrypt those spans. We deliberately lock Presidio as the engine and do **not** reimplement any of that. So if your question is "are you rebuilding detection?" — no.

What `prompt-redact` adds is the **integration, consistency, and operational layer around Presidio**, for teams who shouldn't have to assemble it themselves:

| What Presidio gives you | What `prompt-redact` adds on top |
|---|---|
| Anonymizes a **single** string, no memory between calls | **Cross-turn token stability** — a caller-owned token map, merged and round-tripped on each call, so the same entity gets the same `[PERSON_2]` across every turn of a conversation |
| Reversibility via **encryption** (ciphertext blobs land in the text) | **LLM-friendly reversible tokens** — readable `[TYPE_N]` placeholders an LLM can reason about, with the secret kept *out* of the text in an external map; one `/unredact` endpoint owns the reversal rules |
| A **Python library** (plus sample REST images) | A coherent, language-agnostic **`/redact` + `/unredact` + map contract** any stack (Node, Go, …) can call — not two generic engine APIs |
| Unopinionated knobs | A **tuned, measured, compliance-defensible default** — an entity set aligned to HIPAA Safe Harbor, confidence thresholds, and an eval harness with a stated leakage-rate target |
| Engine primitives | **Operational hardening** — no-PII-in-logs discipline, a token-collision guard, request size caps |

**Being honest about the limits of that value:**

- The cross-turn pattern (#1) is essentially a productized, hardened version of Presidio's own documented `InstanceCounterAnonymizer` / `InstanceCounterDeanonymizer` sample — a good pattern, not secret sauce.
- The HTTP layer (#3) builds on the fact that Presidio already ships sample REST images; our value is the *coherent contract*, not "wrapping it in HTTP."
- **If your caller is already Python**, items #1–#2 are a short lift straight from Presidio's cookbook, and the real value narrows to the tuned config + eval harness (#4) and operational hardening (#5). A full microservice may be more than you need — calling Presidio directly is a legitimate choice.

**You probably don't need `prompt-redact` if:** your app is Python, you're comfortable wiring Presidio's anonymizer + a counter yourself, and you don't need the measured compliance default. **You probably do** if you call from a non-Python stack, want stable reversible tokens across a conversation without building that yourself, or want a redaction tier with a defensible, measured quality bar out of the box.

## Docs

Project documentation under `docs/` is authored in HTML, not markdown (see [`CLAUDE.md`](CLAUDE.md#documentation-format)). Markdown is reserved for `README.md`, `CLAUDE.md`, and `skills/*/SKILL.md`.

- [`PITCH.md`](PITCH.md) — the short business/marketing pitch: the value, the proof it's production-hardened, and who it's for
- [`BUSINESS_OVERVIEW.md`](BUSINESS_OVERVIEW.md) — the business case in depth, with plain-language notes per section
- [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) — components, API surface, data flow, token-map handling (FAQ), threat model, redaction quality targets, deployment-target sketch, alternatives, open questions
- [`docs/PLAN.html`](docs/PLAN.html) — milestones from M0 (design freeze) through MVP and beyond
- [`docs/CALLER_GUIDE.html`](docs/CALLER_GUIDE.html) — how to integrate: API, error codes, token-map handling, the trust boundary, multi-turn pattern
- [`docs/decisions/0001-language-and-topology.html`](docs/decisions/0001-language-and-topology.html) — ADR (status: Accepted) for the language and sidecar-topology decision
- [`docs/decisions/0002-service-shape.html`](docs/decisions/0002-service-shape.html) — ADR (status: Accepted) for the pivot from transparent LLM proxy to redaction microservice
- [`docs/research/ner-engines-deep-dive.html`](docs/research/ner-engines-deep-dive.html) — research note on spaCy, Presidio, ONNX, and alternative engines; informs ADR 0001
- [`CLAUDE.md`](CLAUDE.md) — instructions for Claude Code when working in this repo
- [`skills/karpathy-guidelines/SKILL.md`](skills/karpathy-guidelines/SKILL.md) — vendored coding guidelines

## Development

Requires Python 3.11+. The redaction core (`prompt_redact_core/`) and the eval corpus (`evals/`) import nothing heavy on their own; Presidio and the spaCy model are only needed to actually run detection.

```sh
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt          # hash-pinned runtime deps (incl. CPU torch)
pip install -r requirements-dev.in       # test-only deps (pytest, httpx)
python -m spacy download en_core_web_trf # the default NER model
```

Run the tests — integration tests that need Presidio/the model **auto-skip** if it isn't installed, so the pure logic is testable with no ML stack:

```sh
pytest
```

In CI those skips are not silent: the integration job sets `PROMPT_REDACT_REQUIRE_MODEL=1`, which turns any skipped integration test into a **failure** (see [`tests/conftest.py`](tests/conftest.py) and [`.github/workflows/ci.yml`](.github/workflows/ci.yml)) — so a green build always means the real redaction path actually ran.

Run the redaction-quality gate (the M1 exit gate — per-entity recall ≥ 0.99 on the gated entity types):

```sh
python -m evals.run_eval            # defaults: 50 examples/template, seed 0
python -m evals.run_eval 500 0      # larger corpus for tighter estimates
```

`requirements.txt` is the committed **hash-pinned** lockfile (threat T8), compiled from `requirements.in` and including the CPU torch wheel; the sidecar image installs it with `--require-hashes`. Regenerate it (in a Python 3.11 env) with:

```sh
pip install pip-tools
pip-compile --generate-hashes --output-file=requirements.txt requirements.in
```

**Front-end (Go).** The public shell (`frontend/`) reverse-proxies to the Python sidecar over loopback. It needs Go 1.22+ and has no external dependencies:

```sh
cd frontend
go test ./...                                   # run its tests
go build -o frontend . && \
  PROMPT_REDACT_UPSTREAM=http://127.0.0.1:8000 ./frontend   # serves on :8080
```

## Attribution

`skills/karpathy-guidelines/` is vendored from [`multica-ai/andrej-karpathy-skills`](https://github.com/multica-ai/andrej-karpathy-skills) (MIT). It can alternatively be installed as a Claude Code plugin:

```
/plugin marketplace add forrestchang/andrej-karpathy-skills
/plugin install andrej-karpathy-skills@karpathy-skills
```

If you switch to the plugin install, delete the vendored copy to avoid drift.
