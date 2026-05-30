# ADR 0001 — Implementation language and process topology

- **Status:** Proposed *(awaiting decision)*
- **Date opened:** 2026-05-30
- **Owners:** rick-johnn
- **Supersedes:** —
- **Superseded by:** —

## Context

`prompt-redact` is a redaction proxy that sits between chat clients and an LLM backend. Earlier M0 decisions locked Microsoft Presidio as the redaction engine and an OpenAI-compatible API as the public surface.

Presidio is a **Python-only library**. That single fact narrows the topology decision to a small number of viable shapes, and every other code-level choice (HTTP framework, test framework, container layout, deployment story) follows from it. We therefore need to make this decision deliberately, not by drift.

This decision is intentionally kept open until the missing inputs below are answered. The doc presents the options and tradeoffs; it does not pick.

## Inputs we don't have yet

These will dominate the right answer:

1. **Team's primary language(s)** and on-call ergonomics. A "best" stack the on-call rotation can't debug at 2am is the wrong stack.
2. **Expected throughput and latency budget.** Order-of-magnitude estimate of peak chat req/s per pod, and the acceptable proxy-added p95 latency.
3. **Existing deployment conventions.** Do we already run Python services? Is there an established sidecar pattern? A service mesh we'd plug into?
4. **Future surface.** Is this only ever a redaction proxy, or will it grow to include evaluation harnesses, audit log pipelines, batch redaction jobs, embeddings endpoints? Python's NLP ecosystem (spaCy, HuggingFace, datasets) becomes increasingly valuable as scope grows.

## Criteria

| Criterion | Why it matters here |
|---|---|
| Presidio integration cost | Either in-process (Python) or over IPC (anything else). IPC adds a contract, a deploy unit, and a failure mode. |
| Operational simplicity | One image vs two. Fewer moving parts = easier audit, which matters under HIPAA. |
| Performance envelope | The bottleneck on a chat request is the LLM call (hundreds of ms to seconds), then the NER pass (tens of ms). The proxy shell itself is rarely the long pole. |
| Team familiarity | Highest-leverage factor for velocity and maintainability. |
| Container size & cold start | spaCy/transformer model loading drives image size and warm-up time. Affects every container in the system. |
| Audit/compliance surface | More services = more boundaries to threat-model, more secrets to rotate. |

## Options

### Option A — Full Python (single service)

A single async Python service hosts the HTTP proxy and the Presidio analyzer in-process.

**Likely stack:** FastAPI or Starlette or LiteStar, `httpx` for upstream calls, `pytest` for tests, `uv` or `poetry` for deps.

| Pros | Cons |
|---|---|
| Zero IPC — call Presidio as a library | Python perf ceiling (GIL); concurrent NER calls block within a worker |
| One container, one deploy, one set of logs | Image size dominated by spaCy/transformer model |
| Trivially matches Presidio's own update cadence | Cold start = model load time (seconds) |
| Smallest team surface; easiest to audit | If team has zero Python on-call expertise, this is the wrong choice |
| Python's NLP ecosystem available for future scope | — |

**Best when:** Team is Python-comfortable, expected throughput per pod is modest (≤ ~100 req/s), no extreme latency-floor requirement.

### Option B — Go proxy + Python Presidio sidecar

A Go HTTP proxy handles the request/response surface and calls a Python process exposing a small gRPC or HTTP-over-loopback API for redaction.

| Pros | Cons |
|---|---|
| Fastest proxy hot path; tiny proxy binary | Two languages, two deploy units, two CI pipelines |
| Goroutine concurrency for the proxy shell | New IPC boundary needs its own threat model (loopback only? mutual TLS?) |
| Clean separation of concerns | Local dev story is more complex |
| Easy horizontal scaling of just the proxy | Saves at most a few ms in the proxy shell while LLM dominates |

**Best when:** Team has real Go expertise, expecting very high throughput, or the proxy will sit alongside an existing Go-heavy service stack.

### Option C — Node/TypeScript proxy + Python sidecar

Same shape as Option B but with a Node proxy.

| Pros | Cons |
|---|---|
| Plays well if the consuming stack is already Node/TS | Two languages, same as Option B |
| Streaming SSE story is well-trodden in Node | Node perf < Go for the proxy shell |
| Strong types via TS catch contract drift early | Same two-deploy operational cost |

**Best when:** Team is JS/TS-first; the chat surface itself is also Node, making a single deployable hard.

### Option D — Rust proxy + Python sidecar

Same shape, with Rust.

| Pros | Cons |
|---|---|
| Lowest overhead, smallest binary, sharpest tail latency | Steepest learning curve, longest dev cycle |
| Strong correctness guarantees | Overkill for chat-rate traffic when the LLM dominates |
| Excellent for embedded/edge deployments | Slowest path to v1 |

**Best when:** Truly perf-critical or on-device scenarios where binary size and tail latency matter.

### Option E — Drop Presidio

Reopen the engine decision so we're free to pick a non-Python stack without the IPC tax.

| Pros | Cons |
|---|---|
| Free language choice | Lose Presidio's recognizer ecosystem and community |
| If Philter (JVM) is acceptable, Java/Kotlin proxy becomes viable | Engine pick was made for good reasons; re-litigating costs time |
| Regex-only first cut is also possible if the team accepts the recall hit | A regex-only engine almost certainly fails the recall bar for HIPAA Safe Harbor |

**Best when:** The team has a hard non-Python constraint that outweighs Presidio's value, OR the recall bar is low enough that a simpler engine suffices (it almost certainly is not).

## Honest take (lean, not a decision)

For chat-rate traffic (likely well under 100 req/s per pod) and the latency profile of an LLM call, the proxy shell is not the bottleneck — the LLM call is, and the NER pass is the next-most-expensive thing. Both are bounded by Python. Switching to Go or Rust gains you a few ms in the proxy shell while paying for two languages, two deploys, and a new IPC boundary that needs auditing.

**The default that fits the constraints is Option A — full Python.** The cases where another option clearly wins are:
- Team has zero Python operational experience → Option B/C/D, picked by team familiarity
- Throughput is expected to be in the thousands of req/s per pod → Option B
- Already a Node-heavy stack with strong reasons not to deploy a Python service → Option C

If none of those apply, Option A is the simpler answer.

## Consequences (whichever way we go)

Locking this decision will:
- Pin the HTTP framework, test framework, and HTTP client choices in ARCHITECTURE.md
- Determine the contents of `.gitignore`
- Determine the Dockerfile shape and base image
- Determine whether M5 deploys one container or two
- Determine whether the IPC boundary in Options B/C/D becomes a new row in the threat-model table

Reversing this decision after M2 (proxy MVP shipped) would be a significant rewrite — the cost grows with each milestone that compounds on top of the choice.

## Decision

— *(to be filled in once stakeholders weigh in on the missing inputs above)*

## References

- [ARCHITECTURE.md](../ARCHITECTURE.md) — "Implementation stack — TBD" table and open question #0
- [PLAN.md](../PLAN.md) — M0 checklist
- Presidio: https://github.com/microsoft/presidio
