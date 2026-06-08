# M4 Packaging — Design Discussion

> **Purpose:** a discussion doc for the architecture team to review the **M4 (packaging) decisions** before we author any Dockerfiles. **Nothing here is decided yet** — the goal is to align on the open questions in the last section. The detailed milestone plan lives at [`docs/plans/m4-packaging.html`](docs/plans/m4-packaging.html); this restates it for review and goes deeper on the tradeoffs.

---

## Context (for readers new to the project)

**prompt-redact** is an on-prem PII/PHI redaction microservice. Callers invoke it explicitly:
- `POST /redact` — text → redacted text + a token map (`{ "[PERSON_1]": "John Doe" }`)
- `POST /unredact` — text + token map → rehydrated text

It does **not** call any LLM; the caller orchestrates. It runs entirely inside the adopter's environment (no third-party API in the redaction path).

**Architecture (the "sidecar" topology, [ADR 0001](docs/decisions/0001-language-and-topology.html)):**

```
client ──HTTP──▶ Go front-end (public) ──HTTP, loopback──▶ Python sidecar (internal)
                  - size cap, no body logging              - FastAPI + Microsoft Presidio
                                                           - spaCy model (NER)
```

- The **Go front-end** is the public shell (a thin reverse proxy + edge body-size cap).
- The **Python sidecar** holds the redaction logic and the spaCy/Presidio model. It is bound to loopback / the internal network only — never exposed.

**Detection model:** the default is the **transformer model `en_core_web_trf`**. It is the only configuration that passes our redaction-quality gate (per-type recall targets — see [ARCHITECTURE → quality targets](docs/ARCHITECTURE.html#redaction-quality-targets)). `en_core_web_lg` is a faster, lower-recall alternative and is selectable via config.

**Status:** M1 (redactor core) and M2 (service MVP, including the front-end) are complete and tested. **M4 (packaging) is the current milestone:** make `docker compose up` bring up the front-end + sidecar so the multi-turn round-trip works against the composed stack.

**Constraint on this work:** the dev sandbox has no Docker, so these artifacts will be *authored* and then **built/verified on a real Docker host** (we have Docker Desktop available for that).

---

## The central tension: image size

Adopting `trf` as the default has a packaging consequence we need to confront. Approximate sizes:

| Image | Contents | Approx size |
|---|---|---|
| **Sidecar (`trf`)** | python-slim + presidio/spaCy + **transformers + torch (~1–2 GB)** + `trf` model (~430 MB) | **~3–4 GB** |
| Sidecar (`lg`) | python-slim + presidio/spaCy + `lg` model (~400 MB) | ~1–1.5 GB |
| Go front-end | static binary on distroless | tens of MB |

So the **default artifact is a 3–4 GB image**. For on-prem / air-gapped adopters mirroring it into an internal registry (threat **T8**), that's a real cost: pull time, storage, rebuild time. This is the decision that drives most of the others.

---

## Decisions to work through

### 1. Which image(s) do we ship? *(the crux)*

| Option | Pros | Cons |
|---|---|---|
| **A. `trf` only** | One artifact; meets the quality bar; simplest to maintain | 3–4 GB default; heavy for constrained/air-gapped adopters |
| **B. `lg` only** | Small (~1–1.5 GB), fast | **Ships something that fails our own recall gate** — misleading as the default |
| **C. Two variants** — `:trf` (default/recommended) + `:lg` (fast/light) | Adopter picks by resources/latency vs accuracy | Two build paths to maintain/test |

**Lean:** **C** — default to `:trf` (the quality bar is the product's reason to exist), offer `:lg` for constrained or latency-sensitive deployments that accept lower recall (documented). The model is already a config knob, so a build-arg selects which model is baked in.

**Question for the team:** is the maintenance cost of two variants worth it, or do we ship `trf`-only and let advanced adopters rebuild with `lg`?

### 2. How is the model bundled into the image?

| Option | Pros | Cons |
|---|---|---|
| **Bake in at build** | No runtime network (on-prem/air-gap); reproducible; the image is the mirror-able artifact (T8) | Largest image; rebuilds re-fetch the model |
| Download at container start | Smaller image | **Runtime network dependency** — conflicts with on-prem/air-gap |
| Volume mount | Image stays lean; model shared across replicas | "Who populates/mirrors the volume?" operational burden |

**Lean:** **bake in at build** — best fit for the on-prem posture; download-at-start reintroduces exactly the network dependency we avoid.

### 3. CPU vs GPU

**Lean:** **CPU base image as the default**, with a documented **GPU variant** for low-latency on large inputs. Rationale depends entirely on the workload (next item): for short interactive turns, CPU `trf` measured ~30 ms p95 — fine. GPU only earns its complexity (CUDA, GPU hosts, even bigger images) for bulk/large-document redaction.

### 4. The assumption under everything: what is the primary workload?

Most of the above assumes **short, interactive chat-turn redactions** (the original use case). Measured latencies (sandbox CPU):

| Input | `lg` | `trf` |
|---|---|---|
| short message (p95) | ~5 ms | **~30 ms** |
| ~500-token message | 65 ms | **437 ms** |

If the dominant input is instead **large documents / bulk batches**, the calculus flips: CPU `trf` at 437 ms/500 tokens hurts, GPU moves up the list, and `lg` (or the deferred M3 hybrid regex+NER) comes back into play.

**Question for the team:** what's the dominant input shape — interactive short turns, or bulk/large documents? This validates (or breaks) the CPU-default and even the `trf`-default choices.

### 5. Multi-arch

torch wheels are architecture-specific. Docker Desktop on Apple Silicon builds **arm64**; most on-prem servers are **x86_64**. An image built on a laptop may not run on the deploy target.

**Question for the team:** do we need **multi-arch builds** (buildx), or will the build host match the deploy arch?

### 6. Compose shape *(mostly settled — confirm)*

Two services: the **front-end** (only published port) and the **sidecar** (internal network only, never published — T11). This is the reference topology; we'd ship exactly that, plus a small demo caller that exercises the round-trip.

### 7. Readiness / startup *(mostly settled — confirm)*

`trf` load takes tens of seconds. `/healthz` already flips ready only after model warmup; the compose healthcheck needs a generous `start_period` so the front-end doesn't receive traffic before the sidecar is up.

---

## Related decisions this also lets us close

- **Hash-pinned `requirements.txt`** — compiled (with hashes, T8) in the real build environment under Python 3.11. M4 is where this finally happens; it's been deferred because the sandbox is Python 3.10.
- **CI memory** — running the full test suite loads `trf`/torch across several integration fixtures and can OOM a small runner. CI for the integration tests needs adequate RAM, or they should be sharded / run in separate processes. (Pure tests are unaffected.)

---

## Open questions for the architecture team (the decisions)

1. **Image strategy:** ship `trf`-only, or `trf` + `lg` variants? (image size vs meeting the quality bar)
2. **Primary workload:** interactive short turns, or bulk/large documents? (validates CPU-default and the `trf` default itself)
3. **Deploy target architecture** vs the build host — do we need multi-arch?
4. **Model bundling:** confirm bake-in-at-build (vs download / volume) for the on-prem posture.
5. **GPU:** confirm CPU default + GPU as a documented variant.

---

## Current leanings (summary — all provisional)

| Decision | Leaning |
|---|---|
| Image(s) | `:trf` default **+** `:lg` variant |
| Model bundling | Bake into the image at build |
| CPU vs GPU | CPU default + documented GPU variant |
| Base images | `python:3.11-slim` sidecar; distroless-static Go front-end |
| Compose | Front-end published; sidecar internal-only; generous readiness `start_period` |
| Workload assumption | Short interactive turns *(needs confirming)* |

---

## References

- [`docs/plans/m4-packaging.html`](docs/plans/m4-packaging.html) — the M4 milestone plan (scope, spec breakdown M4-01…04, exit criteria)
- [`docs/ARCHITECTURE.html`](docs/ARCHITECTURE.html) — system design, threat model (T8 supply chain, T11 IPC), quality targets
- [`docs/decisions/0001-language-and-topology.html`](docs/decisions/0001-language-and-topology.html) — the sidecar topology + Go/HTTP-loopback decisions
- [`docs/specs/m1-08-eval-harness.html`](docs/specs/m1-08-eval-harness.html) — the `lg` vs `trf` baseline numbers
