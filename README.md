# prompt-redact

**An on-prem PII/PHI redaction microservice.** Strip personal identifiers out of
text *before* it reaches an LLM — or your logs, analytics, eval sets, or any
other system not cleared to hold them — then reverse the substitution when it's
safe to. Self-hosted, stateless, and it never calls an LLM or phones home.

[![CI](https://github.com/rick-johnn/prompt-redact/actions/workflows/ci.yml/badge.svg)](https://github.com/rick-johnn/prompt-redact/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Landing page](https://img.shields.io/badge/overview-live-brightgreen.svg)](https://rick-johnn.github.io/prompt-redact/)

> **One-page overview:** https://rick-johnn.github.io/prompt-redact/ · **Pitch:** [PITCH.md](PITCH.md) · **Business case:** [BUSINESS_OVERVIEW.md](BUSINESS_OVERVIEW.md)

```
POST /redact    "Email John Smith at john@example.com."
             →  "Email [PERSON_1] at [EMAIL_ADDRESS_1]."
                + token_map { "[PERSON_1]": "John Smith", "[EMAIL_ADDRESS_1]": "john@example.com" }

POST /unredact  "Reply to [PERSON_1]."  + that token_map
             →  "Reply to John Smith."
```

---

## Contents

- [Why prompt-redact](#why-prompt-redact)
- [What you get](#what-you-get)
- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [Architecture & locked decisions](#architecture--locked-decisions)
- [Why not just use Presidio?](#why-not-just-use-presidio)
- [Project status](#project-status)
- [Documentation](#documentation)
- [Development](#development)
- [Contributing](#contributing)
- [Security](#security)
- [License](#license)
- [Attribution](#attribution)

---

## Why prompt-redact

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

## What you get

- **Two explicit verbs.** `POST /redact` and `POST /unredact` — the caller orchestrates everything else.
- **Reversible, LLM-friendly tokens.** Readable `[TYPE_N]` placeholders an LLM can reason about; the secret stays *out* of the text, in a caller-held map.
- **Cross-turn consistency.** The same entity gets the same token across every turn of a conversation, via a caller-owned token map round-tripped on each call.
- **Stateless by design.** The service stores nothing between requests — trivial to scale, simple to reason about.
- **Never leaves your walls.** No LLM calls, no third-party APIs, no telemetry in the redaction path. Required for HIPAA / PCI-DSS / GDPR-strict deployments.
- **Built on [Microsoft Presidio](https://github.com/microsoft/presidio)** with the `en_core_web_trf` transformer model, plus checksum-validated NPI/DEA recognizers and a measured eval harness.
- **Hardened to deploy.** `docker compose up` for local; a parameterized Helm chart with default-deny `NetworkPolicy` isolation (ingress + egress), non-root distroless/least-privilege containers, and a hash-pinned supply chain.

## Quick start

**Local (Docker Compose):**

```sh
docker compose up        # front-end on :8080, Presidio sidecar internal-only
```

```sh
# redact
curl -s localhost:8080/redact -H 'content-type: application/json' \
  -d '{"text":"Email John Smith at john@example.com."}'
# → {"redacted_text":"Email [PERSON_1] at [EMAIL_ADDRESS_1].",
#    "token_map":{"[PERSON_1]":"John Smith","[EMAIL_ADDRESS_1]":"john@example.com"}}

# unredact (round-trip) — pass the map back
curl -s localhost:8080/unredact -H 'content-type: application/json' \
  -d '{"text":"Reply to [PERSON_1].","token_map":{"[PERSON_1]":"John Smith"}}'
# → {"text":"Reply to John Smith."}
```

**Kubernetes (Helm):**

```sh
helm install redact deploy/helm/prompt-redact -n redact --create-namespace \
  --set image.registry=ghcr.io/yourorg
```

See the [caller integration guide](docs/CALLER_GUIDE.html) for the full API, error codes, the token-map contract, and the multi-turn pattern.

## How it works

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

The caller stores the returned token map for the lifetime of a conversation, passes it back on subsequent `/redact` calls (for cross-turn consistency), and calls `/unredact` on LLM responses to rehydrate identifiers for the user. The service itself holds no per-caller state.

## Architecture & locked decisions

| Decision | Choice |
|---|---|
| Service shape | Redaction microservice (`/redact` + `/unredact`); **not** an LLM proxy ([ADR 0002](docs/decisions/0002-service-shape.html)) |
| Hosting | On-prem / self-hosted only — no third-party APIs in the redaction path |
| Topology | **Go front-end + Python Presidio sidecar** over loopback IPC ([ADR 0001](docs/decisions/0001-language-and-topology.html)) |
| Redaction engine | [Microsoft Presidio](https://github.com/microsoft/presidio), `en_core_web_trf` by default (`en_core_web_lg` is a configurable fast/low-recall alternative) |
| Token map ownership | Caller-owned; round-tripped on each call. The service holds no per-caller state. |
| Reversibility | Reversible via `[TYPE_N]` tokens and an explicit `/unredact` endpoint |
| Packaging | Docker Compose for local; a Helm chart with `NetworkPolicy` isolation for Kubernetes |

Cloud DLP (GCP / AWS Macie) and Philter were considered and deferred. See [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html#alternatives-considered) for the full design and threat model.

## Why not just use Presidio?

Fair question — and the honest answer is that [Presidio](https://github.com/microsoft/presidio) does the hard part. It's the detection and anonymization **engine**: NER, recognizers, and regex that decide "`John Doe` is a PERSON, `12345` is an MRN," plus operators to replace/mask/hash/encrypt those spans. We deliberately lock Presidio as the engine and do **not** reimplement any of that.

What `prompt-redact` adds is the **integration, consistency, and operational layer around Presidio**, for teams who shouldn't have to assemble it themselves:

| What Presidio gives you | What `prompt-redact` adds on top |
|---|---|
| Anonymizes a **single** string, no memory between calls | **Cross-turn token stability** — a caller-owned token map, merged and round-tripped on each call, so the same entity gets the same `[PERSON_2]` across every turn |
| Reversibility via **encryption** (ciphertext blobs land in the text) | **LLM-friendly reversible tokens** — readable `[TYPE_N]` placeholders, with the secret kept *out* of the text in an external map; one `/unredact` endpoint owns the reversal |
| A **Python library** (plus sample REST images) | A coherent, language-agnostic **`/redact` + `/unredact` + map contract** any stack (Node, Go, …) can call |
| Unopinionated knobs | A **tuned, measured, compliance-defensible default** — an entity set aligned to HIPAA Safe Harbor, confidence thresholds, and an eval harness with stated recall targets |
| Engine primitives | **Operational hardening** — no-PII-in-logs discipline, correlation IDs, a token-collision guard, request size caps, hash-pinned deps, NetworkPolicy isolation |

**Being honest about the limits of that value:** if your caller is **already Python** and you're comfortable wiring Presidio's anonymizer + a counter yourself, the cross-turn pattern is a short lift straight from Presidio's cookbook, and the real value narrows to the tuned config + eval harness and the operational hardening. `prompt-redact` earns its keep when you call from a **non-Python stack**, want **stable reversible tokens across a conversation** without building that yourself, or want a redaction tier with a **defensible, measured quality bar** and **deployment hardening** out of the box.

## Project status

**v1 is complete and runs end-to-end** (`docker compose up` or `helm install`). The redactor core, the FastAPI service, the Go front-end, the eval/gate harness, the Docker images, the Compose stack, and the Helm chart are all built and CI-verified. CI runs the **real** detection path against the real model and fails loudly if those tests are skipped. See [`docs/PLAN.html`](docs/PLAN.html) for the milestone history.

The biggest open item is an **externally hand-labeled real-world corpus** for an honest recall number (the committed eval corpus shares authorship with the recognizers, so it measures consistency, not real-world recall). Real-PII corpora must live in the gitignored `evals/corpus/real/` and never be committed.

## Documentation

Project documentation under `docs/` is authored in HTML, not markdown (see [`CLAUDE.md`](CLAUDE.md#documentation-format)). Markdown is reserved for `README.md`, `CLAUDE.md`, `PITCH.md`, `BUSINESS_OVERVIEW.md`, and `skills/*/SKILL.md`.

- [`PITCH.md`](PITCH.md) — the short business/marketing pitch (styled web version: [`docs/index.html`](docs/index.html), published at <https://rick-johnn.github.io/prompt-redact/>)
- [`BUSINESS_OVERVIEW.md`](BUSINESS_OVERVIEW.md) — the business case in depth, with plain-language notes
- [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) — components, API surface, data flow, token-map handling, threat model, quality targets, k8s isolation, alternatives
- [`docs/CALLER_GUIDE.html`](docs/CALLER_GUIDE.html) — how to integrate: API, error codes, token-map handling, the trust boundary, multi-turn pattern
- [`docs/PLAN.html`](docs/PLAN.html) — milestones from design freeze through v1
- [`docs/decisions/`](docs/decisions/) — ADRs (0001 language & topology, 0002 service shape)
- [`docs/research/ner-engines-deep-dive.html`](docs/research/ner-engines-deep-dive.html) — research note informing ADR 0001

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

Run the redaction-quality gate (per-entity recall against the synthetic corpus):

```sh
python -m evals.run_eval            # defaults: 50 examples/template, seed 0
python -m evals.run_eval 500 0      # larger corpus for tighter estimates
```

`requirements.txt` is the committed **hash-pinned** lockfile, compiled from `requirements.in` and including the CPU torch wheel; the sidecar image installs it with `--require-hashes`. Regenerate it (in a Python 3.11 env) with:

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

## Contributing

Contributions are welcome. A few house rules that keep this codebase what it is:

- **Design before code.** Non-trivial changes start with a doc update (architecture/plan/ADR), then implementation. See [`CLAUDE.md`](CLAUDE.md) for the working conventions.
- **CI must stay green**, including the real-model integration job. Add tests with new behavior.
- **Synthetic data only** in tests, fixtures, and examples — never real PII/PHI. Real corpora belong in the gitignored `evals/corpus/real/`.
- **Never add a third-party API call to the redaction path** (logging, telemetry, evaluation, or otherwise). If a feature seems to need one, flag the compliance concern and propose a self-hosted alternative.
- **`docs/` is HTML; markdown is reserved** for the files listed above.

## Security

The redaction path makes no outbound calls and logs no request/response bodies; errors are generic with a correlation ID so failures are debuggable without leaking content. The [threat model](docs/ARCHITECTURE.html#threat-model) documents each threat as enforced / mitigated / documented, the supply chain is hash-pinned, and the Helm chart ships default-deny NetworkPolicy isolation (proven by [`deploy/helm/netpol-isolation-test.sh`](deploy/helm/netpol-isolation-test.sh)).

`prompt-redact` reduces exposure; it does not by itself make any deployment compliant. Adopters are responsible for validating redaction quality and regulatory fitness for their own use. To report a vulnerability, please open a [GitHub security advisory](https://github.com/rick-johnn/prompt-redact/security/advisories/new) rather than a public issue.

## License

[MIT](LICENSE) — free to use, modify, and self-host, including commercially. The software is provided "as is", without warranty; redaction quality and compliance fitness are the adopter's responsibility to validate for their deployment.

## Attribution

`skills/karpathy-guidelines/` is vendored from [`multica-ai/andrej-karpathy-skills`](https://github.com/multica-ai/andrej-karpathy-skills) (MIT). It can alternatively be installed as a Claude Code plugin:

```
/plugin marketplace add forrestchang/andrej-karpathy-skills
/plugin install andrej-karpathy-skills@karpathy-skills
```

If you switch to the plugin install, delete the vendored copy to avoid drift.
