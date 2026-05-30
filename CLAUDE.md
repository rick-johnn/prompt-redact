# prompt-redact — Claude Code instructions

## Project orientation

`prompt-redact` is an on-prem redaction proxy that sits between chat clients and an LLM, stripping PII/PHI on the way in and rehydrating it on the way out. See [`README.md`](README.md) for the elevator pitch, [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) for the system design, and [`docs/PLAN.html`](docs/PLAN.html) for the current milestone.

The project is in **design and planning phase** — there is no source code yet.

## How to work in this repo

1. **Design before code.** When the user asks for new functionality, the default first deliverable is a doc update (architecture, plan, or open-questions note), not a scaffold. Do not create `requirements.txt`, source files, or build configs unless the user has explicitly signaled "implement", "scaffold", or "build".
2. **Follow the Karpathy guidelines** in [`skills/karpathy-guidelines/SKILL.md`](skills/karpathy-guidelines/SKILL.md). The four principles — Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution — apply to every change in this repo, including doc edits.
3. **PHI is the threat model.** Never propose sending prompt text to a third-party API for any reason (logging, telemetry, observability, redaction, evaluation). If a feature would require it, flag it as a HIPAA concern and propose a self-hosted alternative.
4. **Match the locked architectural decisions** in [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html). If a proposal conflicts with one of them (e.g. introducing a cloud DLP call), call out the conflict before writing it.

## Documentation format

- **`docs/` is HTML.** Architecture, plans, decisions, runbooks, and any other project documentation under `docs/` is authored as `.html` (minimal structure — `<!doctype html>`, `<html>`, `<head><title>…</title></head>`, `<body>`; no CSS/JS unless asked).
- **Markdown is reserved for:** `README.md` (GitHub renders it), `CLAUDE.md` (this file), and `skills/*/SKILL.md` (the skills framework expects markdown with frontmatter).
- Inter-doc links inside `docs/` should use `.html` suffixes.
- When editing a doc under `docs/` that is still in markdown, propose converting it as part of the change rather than perpetuating the format.

## Reviewing changes

For any PR or diff in this repo:
- Verify it traces to a documented decision in [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) or an item in [`docs/PLAN.html`](docs/PLAN.html). If not, ask whether the doc should be updated first.
- Check that no PHI/PII appears in fixtures, tests, or examples — use synthetic data only.
