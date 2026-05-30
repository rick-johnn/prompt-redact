# prompt-redact

An on-prem PII redaction proxy that sits between chat clients and an LLM backend. The proxy strips identifiers from user prompts before they reach the model and rehydrates them in the model's response, so the LLM never sees raw personal data while the user still gets a readable answer.

> **Status:** Design and planning. No implementation yet. See [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) and [`docs/PLAN.html`](docs/PLAN.html).

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
┌────────┐   raw prompt    ┌──────────────────┐   anonymized prompt   ┌─────────┐
│ Client │ ──────────────▶ │ prompt-redact    │ ────────────────────▶ │ LLM     │
│        │ ◀────────────── │ (proxy)          │ ◀──────────────────── │ backend │
└────────┘  rehydrated     └──────────────────┘  anonymized response  └─────────┘
            response
                                 │
                                 ▼
                       per-request token map
                       (e.g. [PERSON_1] → "John Doe")
```

The proxy exposes an **OpenAI-compatible `/v1/chat/completions`** endpoint so existing clients change only their base URL.

## Architectural choices (locked for v1)

| Decision | Choice |
|---|---|
| Hosting | On-prem / self-hosted only (no third-party APIs in the redaction path — required for HIPAA, PCI-DSS, GDPR-strict, and similar regimes) |
| Redaction engine | [Microsoft Presidio](https://github.com/microsoft/presidio) |
| Public API | OpenAI-compatible chat completions |
| Reversibility | Reversible via per-request token map |
| Implementation language | **TBD** — Presidio is Python, so the realistic options are full-Python or Presidio-as-sidecar + proxy in another language |

Cloud DLP (GCP / AWS Macie) and Philter were considered and deferred. See [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html#alternatives-considered).

## Docs

Project documentation under `docs/` is authored in HTML, not markdown (see [`CLAUDE.md`](CLAUDE.md#documentation-format)). Markdown is reserved for `README.md`, `CLAUDE.md`, and `skills/*/SKILL.md`.

- [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) — components, data flow, threat model, redaction quality targets, deployment-target sketch, alternatives, open questions
- [`docs/PLAN.html`](docs/PLAN.html) — milestones from M0 (design freeze) through MVP and beyond
- [`docs/decisions/0001-language-and-topology.html`](docs/decisions/0001-language-and-topology.html) — ADR (status: Proposed) for the language and process-topology decision
- [`CLAUDE.md`](CLAUDE.md) — instructions for Claude Code when working in this repo
- [`skills/karpathy-guidelines/SKILL.md`](skills/karpathy-guidelines/SKILL.md) — vendored coding guidelines

## Attribution

`skills/karpathy-guidelines/` is vendored from [`multica-ai/andrej-karpathy-skills`](https://github.com/multica-ai/andrej-karpathy-skills) (MIT). It can alternatively be installed as a Claude Code plugin:

```
/plugin marketplace add forrestchang/andrej-karpathy-skills
/plugin install andrej-karpathy-skills@karpathy-skills
```

If you switch to the plugin install, delete the vendored copy to avoid drift.
