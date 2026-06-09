# prompt-redact — Claude Code instructions

## Project orientation

`prompt-redact` is an on-prem PII redaction microservice that callers invoke explicitly via `POST /redact` and `POST /unredact`. It does **not** proxy LLM calls — the caller orchestrates. The service is stateless; the token map is caller-owned and round-tripped on each call. See [`README.md`](README.md) for the elevator pitch, [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) for the system design, [`docs/decisions/0002-service-shape.html`](docs/decisions/0002-service-shape.html) for why the service shape is what it is, and [`docs/PLAN.html`](docs/PLAN.html) for the current milestone.

The project is in **design and planning phase** — there is no source code yet.

## How to work in this repo

1. **Design before code.** When the user asks for new functionality, the default first deliverable is a doc update (architecture, plan, or open-questions note), not a scaffold. Do not create `requirements.txt`, source files, or build configs unless the user has explicitly signaled "implement", "scaffold", or "build".
2. **Follow the Karpathy guidelines** in [`skills/karpathy-guidelines/SKILL.md`](skills/karpathy-guidelines/SKILL.md). The four principles — Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution — apply to every change in this repo, including doc edits.
3. **PII is the threat model.** Never propose sending input text to a third-party API for any reason (logging, telemetry, observability, redaction, evaluation). If a feature would require it, flag it as a compliance concern (HIPAA, PCI-DSS, GDPR, etc. depending on the deployment) and propose a self-hosted alternative.
4. **Match the locked architectural decisions** in [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) and the ADRs under [`docs/decisions/`](docs/decisions/). If a proposal conflicts with one of them (e.g. adding an LLM call inside the service, introducing a cloud DLP call, server-side session state), call out the conflict before writing it.
5. **The service does not call LLMs.** Per [ADR 0002](docs/decisions/0002-service-shape.html), the service is redaction-only — it never touches LLM endpoints, auth tokens, or responses. The caller orchestrates downstream calls. Reject any suggestion that adds an LLM call inside this service.

## Documentation format

- **`docs/` is HTML.** Architecture, plans, decisions, runbooks, and any other project documentation under `docs/` is authored as `.html` (minimal structure — `<!doctype html>`, `<html>`, `<head><title>…</title></head>`, `<body>`; no CSS/JS unless asked).
- **Markdown is reserved for:** top-level GitHub-rendered docs (`README.md`, `PITCH.md`, `BUSINESS_OVERVIEW.md`, and review notes such as `SYSTEM_REVIEW*.md`), `CLAUDE.md` (this file), and `skills/*/SKILL.md` (the skills framework expects markdown with frontmatter). Note: `docs/index.html` is the published GitHub Pages landing page (the styled web version of `PITCH.md`) and intentionally carries CSS/JS — the "no CSS/JS" rule above applies to the other `docs/` pages.
- Inter-doc links inside `docs/` should use `.html` suffixes.
- When editing a doc under `docs/` that is still in markdown, propose converting it as part of the change rather than perpetuating the format.

## Reviewing changes

For any PR or diff in this repo:
- Verify it traces to a documented decision in [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) or an item in [`docs/PLAN.html`](docs/PLAN.html). If not, ask whether the doc should be updated first.
- Check that no PHI/PII appears in fixtures, tests, or examples — use synthetic data only.
