# Architecture

## Problem

Healthcare-adjacent chat surfaces receive prompts that contain PHI (patient names, DOBs, MRNs, phone numbers, addresses). Forwarding those prompts directly to an LLM — even a self-hosted one — creates auditability and disclosure risk. We want a single chokepoint that strips identifiers before the model sees them and restores them in the response shown to the user.

## Goals

- **Block raw PHI from reaching the model.** The LLM should see anonymized tokens, never original identifiers.
- **Preserve a useful UX.** The user-visible response should still reference real names/dates where appropriate — redaction must be reversible for the client.
- **Drop into existing stacks.** Clients should be able to point at us by changing only a base URL (OpenAI-compatible API).
- **Run entirely on-prem.** No third-party API calls in the redaction path. Suitable for HIPAA-covered environments.
- **Be fast enough for interactive chat.** Added latency should be a small fraction of the LLM call itself.

## Non-goals (v1)

- Multi-tenant auth, rate limiting, audit logging. Provided by the surrounding infra.
- Training a custom PII model. We use Presidio's out-of-the-box recognizers plus regex add-ons.
- Detecting PHI in *images, audio, or attached files*. Text only.
- Detecting model-emitted hallucinated identifiers (model invents a name not in the input). Tracked as an open question.

## High-level design

```
┌────────┐   POST /v1/chat/completions   ┌────────────────────────────┐
│ Client │ ────────────────────────────▶ │ prompt-redact proxy        │
│        │                                │                            │
│        │ ◀──────────────────────────── │  1. redact request messages│
└────────┘   200 chat.completion          │  2. forward to upstream    │
                                          │  3. rehydrate response     │
                                          └────────────┬───────────────┘
                                                       │
                                                       ▼
                                          ┌────────────────────────────┐
                                          │ Upstream LLM               │
                                          │ (self-hosted, OpenAI-compat)│
                                          └────────────────────────────┘
```

## Implementation stack — **TBD**

| Decision | Status |
|---|---|
| Implementation language | **TBD** — see open question #0 |
| HTTP framework | TBD (follows from language) |
| Redaction engine | Presidio *(locked)* — note: Python-only library, so language choice is constrained to Python or a "Presidio sidecar + proxy in language X" split |
| Test framework | TBD (follows from language) |
| HTTP client (for upstream) | TBD (follows from language) |

Until the language is picked, treat the component descriptions below as language-agnostic shapes, not file/module layouts.

## Components

### 1. HTTP proxy
A small async HTTP server that exposes an OpenAI-compatible surface. Initial endpoints:

- `POST /v1/chat/completions` — the main path. Non-streaming for v1; streaming deferred (see open questions).
- `GET /healthz` — liveness.

The proxy is a thin shell: parse request → call redactor → forward to upstream → call rehydrator → return.

### 2. Redactor
Wraps Presidio's `AnalyzerEngine` and `AnonymizerEngine`. Responsibilities:

- Run analysis on each message's text content.
- Assign a stable token per unique original value within a request (e.g. `"John Doe"` always becomes `[PERSON_1]` in this request, even if it appears in turns 1 and 3).
- Emit the redacted text + a token → original mapping.

### 3. Token map (per-request, in-process)
A plain map scoped to a single chat completion request. No Redis, no cross-request persistence in v1.

**Rationale:** OpenAI chat completions are stateless — clients re-send the full message history each turn — so a per-request map is sufficient for both within-call and across-turn consistency. Adding a session store before we need it would be speculative complexity.

### 4. Upstream client
Forwards the redacted request to a configured upstream URL. Passes through `Authorization` and other relevant headers verbatim.

### 5. Rehydrator
Reverse-substitutes tokens in the upstream response's `choices[*].message.content` using the request's token map.

## Data flow

```
request.messages
   │
   ▼  for each message
┌────────────────────────────────────────┐
│ redactor.analyze(text)                 │
│   → [RecognizerResult{start,end,type}] │
└────────────────────────────────────────┘
   │
   ▼  assign tokens (stable within request)
┌────────────────────────────────────────┐
│ apply replacements right-to-left       │
│ update reverse_map[token] = original   │
└────────────────────────────────────────┘
   │
   ▼
forward to upstream
   │
   ▼
response.choices[*].message.content
   │
   ▼  for each token in reverse_map
text.replace(token, original)
   │
   ▼
return to client
```

## Token format

`[<ENTITY_TYPE>_<N>]` — e.g. `[PERSON_1]`, `[PHONE_NUMBER_2]`, `[DATE_TIME_1]`.

Chosen so the model:
- Sees a clear placeholder it can reason about ("the patient is [PERSON_1]").
- Can refer back to the same entity consistently.
- Won't be tempted to invent a value (it sees a non-natural string).

## Performance approach

Per the v0 notes, we want a hybrid path:
1. **Regex fast path** for structured identifiers (SSN, phone, email, MRN patterns).
2. **NLP slow path** (spaCy via Presidio) only for free-text spans that didn't fully match regex.

For v1 we ship with Presidio's default pipeline (which already runs regex recognizers before NER) and measure. The hybrid split becomes a real optimization only if profiling shows the NLP pass dominating.

## API surface

### `POST /v1/chat/completions`

Request body matches OpenAI's schema. v1 supports:

- `model` (passed through)
- `messages: [{role, content}]` — `content` must be a string; multipart content deferred
- `temperature`, `max_tokens`, `top_p`, `stop` — passed through unchanged
- `stream: false` — `true` rejected with 400 in v1

Response matches OpenAI's schema with `choices[*].message.content` rehydrated.

### `GET /healthz`

Returns `{"status": "ok"}` once the analyzer model is loaded.

## Threat model

| # | Threat | Mitigation | Status |
|---|---|---|---|
| T1 | PHI reaches the LLM in a user prompt | Redactor strips before forwarding; this is the core function | Core |
| T2 | PHI leaks via proxy request/response logs | No request/response body logging in default config; structured logs use token-form only; explicit redactor sanity-check on any field that *could* contain raw text before it reaches a log sink | Core |
| T3 | PHI leaks via panic/crash dumps or debug traces | Crash handlers must scrub message bodies before emitting; debug/verbose log levels are off in production by default | Open — needs implementation pattern |
| T4 | PHI leaks via upstream LLM provider telemetry | Upstream is self-hosted; no third-party endpoints in v1 | Core |
| T5 | PHI leaks via redactor false negative | Bounded by Presidio's recall; tracked under "Redaction quality targets" below — recall target, eval harness, confidence-threshold tuning | Open — gated on quality targets |
| T6 | Token collision (an identifier that already looks like our placeholder) | Token format `[TYPE_N]` is unlikely in clinical text; pre-scan inputs and either reject or escape any pre-existing token-shaped substrings | Open — implementation detail for M1 |
| T7 | Model-emitted PII (model invents a name not in the input) | Optionally run the redactor on assistant responses too. Trades a second NER pass for an extra layer of defense. Deferred — see open question #2 | Deferred to post-MVP |
| T8 | Insider with shell access to the proxy host can capture raw PHI in-flight | Out of scope for the proxy itself; mitigated by host-level access controls, audit logging, and least-privilege deploys. Document this boundary clearly so operators understand the trust assumption | Boundary — documented, not solved by code |
| T9 | Upstream LLM auth token or other secrets leak via env, logs, or core dumps | Read secrets from a secret manager (not env vars baked into images); never log header values; structured config redacts secret-keyed fields | Open — pick secret-management approach |
| T10 | Supply-chain compromise of the spaCy model or a Presidio dependency | Pin exact versions and hashes of the model file and Python deps; reproducible build; consider an internal mirror of the model artifact | Open — pin policy, mirror decision |
| T11 | DoS via oversized message bodies that explode the NER pass | Cap per-message and per-request size; reject above threshold with 413; surface metrics on input size distribution | Open — pick thresholds |
| T12 | Response caching (anywhere in the stack) outlives the per-request token map and rehydrates with stale or empty mappings | No caching layer in v1; if introduced later, cache key must scope to the *post-rehydration* response, not the upstream's tokenized response | Open — block any caching addition without a design |
| T13 | Token cardinality side-channel — the upstream model sees `[PERSON_1]` … `[PERSON_5]` and can infer the count of distinct patients in a session | Accept and document; mitigation (e.g. random token IDs) costs reasoning quality. Not exploitable without other access | Accepted |
| T14 | Tampered/malicious client bypasses redaction by claiming pre-redacted input | Proxy always runs the redactor regardless of client-asserted state; no "already redacted, skip" path | Core |

## Redaction quality targets

The proxy's only safety promise is that PHI does not reach the model. That promise is bounded by the redactor's **recall** on PHI entity types. Precision matters too — over-redaction degrades the LLM's answer — but recall is the hard constraint.

### What we measure

- **Per-entity recall** — for each HIPAA Safe Harbor entity type (names, geographic subdivisions smaller than a state, dates more specific than year, phone/fax, email, SSN, MRN, account/license numbers, vehicle/device identifiers, URLs, IPs, biometric identifiers, full-face photos, "any other unique identifying number, characteristic, or code"), the fraction of true positives the redactor catches at the chosen confidence threshold.
- **Per-entity precision** — for each entity type, the fraction of redactions that were correct.
- **Span-level F1** — using span boundaries, not token boundaries (a partial match that leaves part of a name visible counts as a miss).
- **End-to-end leakage rate** — over a labelled corpus, the fraction of inputs where *any* PHI span escaped redaction. This is the number the compliance review will actually care about.

### Targets (proposed, to be confirmed)

| Metric | Target |
|---|---|
| End-to-end leakage rate (any PHI escape) | **≤ 1 in 10,000** prompts on the eval corpus |
| Per-entity recall (Safe Harbor types) | **≥ 0.99** |
| Per-entity precision | **≥ 0.90** (lower acceptable; over-redaction degrades UX but doesn't violate HIPAA) |
| p95 redaction latency for a 500-token message | **≤ 50 ms** on the target deployment hardware |

These numbers are starting points — they need stakeholder sign-off (especially the leakage rate) before M1 can exit.

### Evaluation corpus

We need a labelled dataset to measure against. Options, in order of effort:

1. **Synthetic clinical prompts** generated by a script that composes realistic patient narratives with span-annotated PHI. Cheap to build; coverage matches what we choose to generate (and we'll over-fit to it if we're not careful).
2. **Public PHI benchmark sets** (e.g. i2b2/n2c2 de-identification challenges) under their data-use agreements. Higher signal; data-use review required.
3. **Held-out internal real corpus**, sampled from production with proper PHI-handling controls. Highest signal; requires a separate data-handling protocol that itself needs review.

Building (1) is a deliverable of its own. Treat the synthetic corpus and its labelling rubric as a separate artifact under `evals/` (path TBD pending language decision).

### Methodology notes

- Compare spans by character offset, not surface form, to avoid being fooled by tokenizer differences.
- Stratify recall reporting by entity type — overall recall hides catastrophic per-type failures (e.g. 99% overall, 60% on dates).
- Re-run the full eval on every change to recognizer config or confidence threshold. Treat it as a regression gate, not a one-time benchmark.

## Deployment target

This section is a sketch — the final choice is open question #5 below and needs stakeholder input on existing infrastructure.

### Candidate topologies

| Topology | Sketch | Implications |
|---|---|---|
| **k8s sidecar** to the chat backend | One `prompt-redact` container alongside the chat service in the same pod; chat service talks to it over localhost | Per-pod scaling, no network hop, no service-mesh policy needed for the call. Bigger pod image. |
| **Standalone k8s service** | `prompt-redact` deployment fronted by a ClusterIP service; chat backend calls it over the in-cluster network | Independent scaling, but adds a network hop and needs mesh-level mTLS / network policy to keep PHI off the wire in cleartext. |
| **VM / bare host** | One or more VMs running the proxy directly | Simplest if there's no orchestrator. Manual scaling, manual rolling deploys. |
| **On-device / edge** | Runs at the client edge (e.g. a clinical workstation) | Best latency, hardest deploy and update story; model size is a real constraint at the edge. |

### Common implications regardless of topology

- The proxy is stateless per request, so horizontal scaling is trivial.
- Cold start is non-trivial — the NER model takes seconds to load. Readiness probe must wait for the model to load, not just for the HTTP socket to open. Autoscaling tuning must account for the warm-up.
- Container image size is dominated by the spaCy/transformer model. Expect hundreds of MB. Worth a registry mirror inside the trust boundary.
- Secret material (upstream LLM auth tokens) reaches the proxy somehow — needs to integrate with whatever secret manager the deployment target uses. Don't bake into images.

### Open question for stakeholders

What's the surrounding infrastructure? k8s? VMs? Edge? The answer drives the M5 deliverables and the threat-model rows for T9 (secrets) and T10 (supply chain).

## Alternatives considered

- **Cloud DLP (GCP / AWS Macie).** Higher accuracy on medical data, managed, but adds network latency and per-request cost, and routes PHI to a third party. Ruled out by HIPAA posture for v1.
- **Philter (self-hosted PHI proxy).** Purpose-built for the use case. Deferred in favor of Presidio for customizability, community size, and a richer recognizer ecosystem.
- **Browser-side NER (e.g. `compromise.cool`).** Reduces network exposure but the client becomes a trust boundary — a tampered client can ship raw PHI. We keep the proxy as the authoritative chokepoint; browser-side scrubbing can be added later as defense-in-depth.

## Open questions

0. **Implementation language.** Presidio is a Python library, so the realistic options are: (a) write the whole proxy in Python; (b) run Presidio as a sidecar gRPC/HTTP service and write the proxy in Go / Rust / Node / etc.; (c) reconsider the engine choice if the team has a strong non-Python preference. Blocks every other code-level decision.
1. **Streaming.** Token reassembly across SSE chunks needs a buffered rehydrator (a token like `[PERSON_1]` can be split across chunks). Probably a small state machine that holds back any partial `[...` until it sees `]` or proves it isn't a token. Punted to a post-MVP milestone.
2. **Model-emitted identifiers.** If the model hallucinates a name that isn't in the token map, we won't redact it on the way out. Should we run the redactor on assistant responses too, or trust the upstream model to behave when only given tokens? Needs a decision before v1 ships to clinical users.
3. **Multipart message content.** OpenAI's newer schema allows `content` as a list of text/image parts. v1 strings only; multipart deferred.
4. **Confidence thresholds.** Presidio returns scores; the cutoff trades recall (more aggressive redaction) for precision (less spurious masking that confuses the model). Needs a small eval set of synthetic clinical prompts.
5. **Token uniqueness across speakers.** If both the user and a system message reference "John Doe", we want one token, not two. Current plan handles this (map keyed by original string), but worth a test fixture.
6. **What to do when redaction would empty a message.** A message that is *only* a phone number becomes `[PHONE_NUMBER_1]` — fine. But edge cases like a system prompt that's pure identifiers may degrade the LLM call. Probably accept and document.
7. **Deployment target** (sidecar vs standalone vs VM vs edge) — see "Deployment target" section above. Needs stakeholder input on existing infrastructure.
8. **Recall/precision targets — confirmed numbers.** The targets above are proposed; the leakage-rate number in particular needs compliance sign-off before M1 can exit.
