# prompt-redact

An on-prem PII/PHI redaction proxy that sits between chat clients and an LLM backend. The proxy strips identifiers from user prompts before they reach the model and rehydrates them in the model's response, so the LLM never sees raw patient data while the user still gets a readable answer.

> **Status:** Design and planning. No implementation yet. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/PLAN.md`](docs/PLAN.md).

## Why

Healthcare chat surfaces routinely receive prompts containing PHI (names, DOBs, MRNs, phone numbers). Sending that text directly to an LLM — especially a hosted one — creates HIPAA exposure. A redaction proxy intercepts the prompt, anonymizes identifiers in-place, forwards only the anonymized text, and reverses the substitution on the way back to the user.

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
| Hosting | On-prem / self-hosted only (HIPAA) |
| Redaction engine | [Microsoft Presidio](https://github.com/microsoft/presidio) |
| Public API | OpenAI-compatible chat completions |
| Reversibility | Reversible via per-request token map |
| Implementation language | **TBD** — Presidio is Python, so the realistic options are full-Python or Presidio-as-sidecar + proxy in another language |

Cloud DLP (GCP / AWS Macie) and Philter were considered and deferred. See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md#alternatives-considered).

## Docs

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — components, data flow, threat model, alternatives, open questions
- [`docs/PLAN.md`](docs/PLAN.md) — milestones from M0 (design freeze) through MVP and beyond
- [`CLAUDE.md`](CLAUDE.md) — instructions for Claude Code when working in this repo
- [`skills/karpathy-guidelines/SKILL.md`](skills/karpathy-guidelines/SKILL.md) — vendored coding guidelines

## Attribution

`skills/karpathy-guidelines/` is vendored from [`multica-ai/andrej-karpathy-skills`](https://github.com/multica-ai/andrej-karpathy-skills) (MIT). It can alternatively be installed as a Claude Code plugin:

```
/plugin marketplace add forrestchang/andrej-karpathy-skills
/plugin install andrej-karpathy-skills@karpathy-skills
```

If you switch to the plugin install, delete the vendored copy to avoid drift.
