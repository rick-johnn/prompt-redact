# prompt-redact — Claude Code instructions

## Project orientation

`prompt-redact` is an on-prem redaction proxy that sits between chat clients and an LLM, stripping PII/PHI on the way in and rehydrating it on the way out. See [`README.md`](README.md) for the elevator pitch, [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) for the system design, and [`docs/PLAN.md`](docs/PLAN.md) for the current milestone.

The project is in **design and planning phase** — there is no source code yet.

## How to work in this repo

1. **Design before code.** When the user asks for new functionality, the default first deliverable is a doc update (architecture, plan, or open-questions note), not a scaffold. Do not create `requirements.txt`, source files, or build configs unless the user has explicitly signaled "implement", "scaffold", or "build".
2. **Follow the Karpathy guidelines** in [`skills/karpathy-guidelines/SKILL.md`](skills/karpathy-guidelines/SKILL.md). The four principles — Think Before Coding, Simplicity First, Surgical Changes, Goal-Driven Execution — apply to every change in this repo, including doc edits.
3. **PHI is the threat model.** Never propose sending prompt text to a third-party API for any reason (logging, telemetry, observability, redaction, evaluation). If a feature would require it, flag it as a HIPAA concern and propose a self-hosted alternative.
4. **Match the locked architectural decisions** in `docs/ARCHITECTURE.md`. If a proposal conflicts with one of them (e.g. introducing a cloud DLP call), call out the conflict before writing it.

## Reviewing changes

For any PR or diff in this repo:
- Verify it traces to a documented decision in `docs/ARCHITECTURE.md` or an item in `docs/PLAN.md`. If not, ask whether the doc should be updated first.
- Check that no PHI/PII appears in fixtures, tests, or examples — use synthetic data only.
