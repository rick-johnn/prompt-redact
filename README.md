# prompt-redact

An on-prem PII redaction microservice that calling applications invoke explicitly on text they want anonymized. The service exposes `POST /redact` (text → redacted text + token map) and `POST /unredact` (text + token map → rehydrated text). It does **not** proxy LLM calls — the caller decides whether to send redacted text to an LLM, log it, index it, throw it away, or show it back to the user.

> **Status:** Design and planning. No implementation yet. See [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) and [`docs/PLAN.html`](docs/PLAN.html).
>
> The service shape changed on 2026-05-30 from a transparent OpenAI-compatible proxy to a standalone redaction microservice. See [`docs/decisions/0002-service-shape.html`](docs/decisions/0002-service-shape.html).

## Why

Chat surfaces in regulated industries routinely receive prompts containing identifiers that must not leak to a third-party LLM. The exact category and the exact regulator change by domain, but the shape of the problem is the same:

| Domain | Examples of identifiers | Driving regime(s) |
|---|---|---|
| Healthcare | Patient names, DOBs, MRNs, ICD/CPT codes, clinical narratives | HIPAA (Safe Harbor / Expert Determination) |
| Finance | Account numbers, card PANs, SSNs, balances, transaction histories | PCI-DSS, GLBA, SOX, state privacy laws |
| Pharma & clinical research | Subject IDs, trial site codes, adverse-event narratives | HIPAA + GxP + sponsor data-use agreements |
| Legal & professional services | Client names, matter numbers, privileged content | Attorney–client privilege, bar association rules |
| Cross-border / EU | Anything that qualifies as personal data | GDPR, UK GDPR, regional equivalents |
| Public sector & education | Citizen records, case files, student records | Privacy Act, FERPA, state equivalents |

Sending that text directly to an LLM — especially a hosted one — creates compliance exposure regardless of which regime applies. A redaction proxy intercepts the prompt, anonymizes identifiers in-place, forwards only the anonymized text, and reverses the substitution on the way back to the user.

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
| Implementation language | **TBD** — Presidio is Python, so the realistic options are full-Python or Presidio-as-sidecar + service in another language. See [ADR 0001](docs/decisions/0001-language-and-topology.html). |

Cloud DLP (GCP / AWS Macie) and Philter were considered and deferred. See [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html#alternatives-considered).

## Docs

Project documentation under `docs/` is authored in HTML, not markdown (see [`CLAUDE.md`](CLAUDE.md#documentation-format)). Markdown is reserved for `README.md`, `CLAUDE.md`, and `skills/*/SKILL.md`.

- [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) — components, API surface, data flow, threat model, redaction quality targets, deployment-target sketch, alternatives, open questions
- [`docs/PLAN.html`](docs/PLAN.html) — milestones from M0 (design freeze) through MVP and beyond
- [`docs/decisions/0001-language-and-topology.html`](docs/decisions/0001-language-and-topology.html) — ADR (status: Proposed) for the language and process-topology decision
- [`docs/decisions/0002-service-shape.html`](docs/decisions/0002-service-shape.html) — ADR (status: Accepted) for the pivot from transparent LLM proxy to redaction microservice
- [`docs/research/ner-engines-deep-dive.html`](docs/research/ner-engines-deep-dive.html) — research note on spaCy, Presidio, ONNX, and alternative engines; informs ADR 0001
- [`CLAUDE.md`](CLAUDE.md) — instructions for Claude Code when working in this repo
- [`skills/karpathy-guidelines/SKILL.md`](skills/karpathy-guidelines/SKILL.md) — vendored coding guidelines

## Attribution

`skills/karpathy-guidelines/` is vendored from [`multica-ai/andrej-karpathy-skills`](https://github.com/multica-ai/andrej-karpathy-skills) (MIT). It can alternatively be installed as a Claude Code plugin:

```
/plugin marketplace add forrestchang/andrej-karpathy-skills
/plugin install andrej-karpathy-skills@karpathy-skills
```

If you switch to the plugin install, delete the vendored copy to avoid drift.
