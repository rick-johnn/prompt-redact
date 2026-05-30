# Plan

Milestone-based. Each milestone has an exit criterion — a concrete observable that says "this is done."

## M0 — Design freeze *(current)*

- [x] Architectural decisions recorded in [`ARCHITECTURE.md`](ARCHITECTURE.md): on-prem, Presidio, OpenAI-compatible, reversible per-request token map.
- [x] Karpathy guidelines vendored into `skills/karpathy-guidelines/`.
- [x] Repo initialized; `CLAUDE.md` orienting future sessions.
- [x] GitHub remote created: `rick-johnn/prompt-redact` (private).
- [x] Threat model expanded to cover insider risk, log discipline, secrets, supply chain, DoS, caching, and side-channels.
- [x] Redaction quality targets drafted (recall, precision, leakage rate, latency) with eval-corpus options.
- [x] Deployment-target sketch added with candidate topologies (sidecar / standalone / VM / edge).
- [ ] **Pick implementation language and topology.** See [`decisions/0001-language-and-topology.md`](decisions/0001-language-and-topology.md). Blocks every milestone below.
- [ ] **Confirm redaction quality targets.** The leakage-rate number in particular needs compliance sign-off. See ARCHITECTURE.md "Redaction quality targets".
- [ ] **Pick deployment target.** Needs stakeholder input on existing infrastructure. See ARCHITECTURE.md "Deployment target".
- [ ] **Open questions** in `ARCHITECTURE.md` reviewed by stakeholders (streaming, model-emitted identifiers, multipart content, etc.).

**Exit:** Language ADR decided, quality targets signed off, deployment target chosen, remaining open questions either resolved or explicitly deferred to a named milestone.

## M1 — Redactor core

> Specific tooling (test framework, module layout) finalized after the language decision in M0.

Goal: a standalone redactor that takes text + a token map, returns redacted text and a mutated map. No HTTP, no proxy.

- Presidio analyzer + custom anonymization that emits `[TYPE_N]` tokens.
- Stable token assignment: same original string in the same request → same token.
- Unit tests covering:
  - Names, phone numbers, emails, dates, addresses, MRN-shaped IDs.
  - Repeated identifiers get the same token.
  - Empty / all-PII / no-PII inputs.
  - Token format doesn't collide with text that already contains brackets.

**Exit:** tests green; redactor round-trips a synthetic clinical prompt set with ≥ target recall (target TBD in M0).

## M2 — Proxy MVP (non-streaming)

> HTTP framework picked after M0.

Goal: a runnable service that proxies `POST /v1/chat/completions` to a configured upstream, redacting on the way in and rehydrating on the way out.

- `POST /v1/chat/completions` (non-streaming only — reject `stream: true` with 400).
- `GET /healthz`.
- Upstream URL + auth header pass-through configured via env vars.
- Integration test against a stub upstream that echoes its received messages back, verifying the upstream never sees raw PHI.

**Exit:** `curl` against the proxy with a PHI-laden prompt returns a rehydrated response; tcpdump / logs on the upstream stub show only tokens.

## M3 — Streaming support

Goal: handle `stream: true` SSE responses with safe token rehydration.

- Buffered rehydrator: hold back any trailing `[` until it can prove the partial isn't one of our tokens, then flush.
- Backpressure / cancellation handled.
- Test fixtures that split known tokens across chunk boundaries at every position.

**Exit:** A streaming client sees rehydrated names appear in the stream, with no token leakage and no measurable latency penalty on chunks that contain no tokens.

## M4 — Performance: hybrid regex + NER

Only do this if M2/M3 profiling shows the NER pass dominates request latency.

- Pre-filter messages with a fast regex pass for structured identifiers.
- Only invoke the spaCy pipeline on messages that still contain free-text spans.
- Bench harness comparing pre- and post-optimization on a fixed corpus.

**Exit:** Documented p50/p95 redaction latency improvement on the bench corpus.

## M5 — Deployment

- Dockerfile (multi-stage, slim runtime).
- `docker-compose.yml` for local dev: proxy + a self-hosted LLM (e.g. vLLM or Ollama).
- Readiness probe that waits for the spaCy model to load.

**Exit:** `docker compose up` brings up the stack; the smoke test from M2 passes against the composed stack.

## Open questions

These block specific milestones rather than the plan as a whole:

- **Implementation language** (blocks M1 and everything after) — see ARCHITECTURE.md open question #0.
- **Streaming approach** (blocks M3) — see ARCHITECTURE.md open question #1.
- **Model-emitted identifiers** (blocks shipping to real clinical users) — see ARCHITECTURE.md open question #2.
- **Confidence thresholds and recall target** (blocks M1 exit) — see ARCHITECTURE.md open question #4.

## Deferred / out of scope

- Multi-tenant auth, rate limiting, audit logging — handled by surrounding infra.
- Multipart `content` arrays in chat completions (images, file refs).
- A `/v1/embeddings` or `/v1/completions` surface — add when a real client needs it.
- Cross-request session state / a session-keyed token store — only if a use case appears that the per-request map can't satisfy.

## Decision log

- **2026-05-30** — Locked on-prem-only hosting, Presidio engine, OpenAI-compatible API, reversible per-request token map. *(See [[project-prompt-redact]] memory.)*
- **2026-05-30** — Vendored Karpathy guidelines under `skills/karpathy-guidelines/` rather than relying on plugin install, to keep the repo self-contained. Plugin install remains a supported alternative; see `README.md`.
- **2026-05-30** — Created GitHub remote `rick-johnn/prompt-redact` (private). Visibility can be flipped to public later if/when this is ever open-sourced.
- **2026-05-30** — Opened ADR [`decisions/0001-language-and-topology.md`](decisions/0001-language-and-topology.md) (status: Proposed) instead of silently picking Python. Decision deferred until missing inputs (team familiarity, throughput target, deployment conventions, future scope) are answered.
