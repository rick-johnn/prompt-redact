# M4 Packaging — Design Discussion

> **Purpose:** a discussion doc for the architecture team to review the **M4 (packaging) decisions** before we author any Dockerfiles. **Nothing here is decided yet** — the goal is to align on the open questions in the last section. The detailed milestone plan lives at `docs/plans/m4-packaging.html`; this restates it for review and goes deeper on the tradeoffs.

> **Review note:** This pass carries inline comments from three reviewers — Charles Petzold, Don Box, and John Carmack — each tagged so it's clear who is making which note.

> **Resolution (2026-06-08):** The gating question is answered — the workload is **short interactive chat prompts, not large documents.** That settles the rest: **CPU-only, `trf`-only image** (no GPU, no shipped `lg` variant — `lg` stays a `--build-arg` escape hatch), **single synchronous `/redact`** (no batch verb), and the request size cap bounds oversized pastes (`413`). Token map stays flat-v1 (the M2 decision). See [`docs/plans/m4-packaging.html`](docs/plans/m4-packaging.html#resolved). The CPU `trf` sidecar image (M4-01) is now **built and verified** (3.01 GB, non-root, round-trip works).

---

## Context (for readers new to the project)

**prompt-redact** is an on-prem PII/PHI redaction microservice. Callers invoke it explicitly:
- `POST /redact` — text → redacted text + a token map (`{ "[PERSON_1]": "John Doe" }`)
- `POST /unredact` — text + token map → rehydrated text

It does **not** call any LLM; the caller orchestrates. It runs entirely inside the adopter's environment (no third-party API in the redaction path).

> 💬 **[Carmack]:** Worth stating the obvious invariant somewhere prominent: the token map is the sensitive artifact. The service is "no third-party API in the redaction path," but the *caller* now holds a `[PERSON_1] -> John Doe` dictionary and presumably ships the redacted text off to an LLM. The whole security value evaporates if a caller logs the map, or correlates it with the redacted text downstream. That's not your code, but it's the failure mode that will actually bite an adopter, so it belongs in the docs as a loud caller-contract note, not buried in an ARCHITECTURE.html appendix.

> 💬 **[Box]:** The contract is two verbs over HTTP with a map in the middle. Fine. But the map's shape is the real interface here — `{ "[PERSON_1]": "John Doe" }` — and that's the thing every caller couples to. Is that schema versioned? When you add `[ORG_1]` or change tokenization, every integrator's `/unredact` round-trip is a compatibility surface. The image-size debate below is loud; this quiet little JSON object is what you'll actually be supporting for five years.

**Architecture (the "sidecar" topology, ADR 0001):**

```
client --HTTP--> Go front-end (public) --HTTP, loopback--> Python sidecar (internal)
                  - size cap, no body logging              - FastAPI + Microsoft Presidio
                                                           - spaCy model (NER)
```

- The **Go front-end** is the public shell (a thin reverse proxy + edge body-size cap).
- The **Python sidecar** holds the redaction logic and the spaCy/Presidio model. It is bound to loopback / the internal network only — never exposed.

> 💬 **[Box]:** Two processes, two languages, one loopback hop, to ship what is essentially one function call. I'm not saying it's wrong — the public-shell/private-engine split is a defensible trust boundary — but the doc treats the topology as settled and spends all its energy on image size. The interface between Go and Python *is* a design decision: it's HTTP-over-loopback, which means you've now got serialization, timeouts, retries, and partial-failure semantics between two halves of one logical service. Where's that contract written down? "HTTP, loopback" is a deployment detail, not a protocol.

> 💬 **[Carmack]:** The Go front-end does a size cap and proxies. That's it. You're paying for a second language, a second image, and a network hop (even loopback isn't free under load) to do work an nginx config or ~50 lines in the Python process could do. The justification has to be the trust boundary — keep the model process off the public interface — and if that's the reason, say so plainly and measure it, because right now the front-end reads as architecture for its own sake. What does it actually *prevent* that a hardened single process wouldn't?

> 💬 **[Petzold]:** "no body logging" is asserted in a box-drawing comment. That is the single most important security property in this entire diagram and it's a label on an ASCII art box. How is it enforced? Is there a test that fails if a request body ever reaches a log sink? PII non-logging should be a guarantee with a test behind it, not a caption.

**Detection model:** the default is the **transformer model `en_core_web_trf`**. It is the only configuration that passes our redaction-quality gate (per-type recall targets — see ARCHITECTURE → quality targets). `en_core_web_lg` is a faster, lower-recall alternative and is selectable via config.

> 💬 **[Carmack]:** "Passes the quality gate" needs numbers right here, not a link. What's the recall delta between `trf` and `lg`? If `trf` is 96% and `lg` is 94%, the entire 3–4 GB image debate is being driven by two points of recall and nobody in this meeting can see that. Put the actual per-type recall table inline — the decision is unmakeable without it.

**Status:** M1 (redactor core) and M2 (service MVP, including the front-end) are complete and tested. **M4 (packaging) is the current milestone:** make `docker compose up` bring up the front-end + sidecar so the multi-turn round-trip works against the composed stack.

**Constraint on this work:** the dev sandbox has no Docker, so these artifacts will be *authored* and then **built/verified on a real Docker host** (we have Docker Desktop available for that).

> 💬 **[Petzold]:** "Authored, then verified elsewhere" is a polite way of saying "written but never run." Every Dockerfile, every compose file, every healthcheck `start_period` in this doc is a hypothesis until it executes on the real host. Treat all of M4's artifacts as unverified drafts and budget real time for the first build to fail in boring, surprising ways — base image tags, wheel availability, layer caching. The plan reads as if authoring is the work and verification is a rubber stamp. It's the reverse.

---

## The central tension: image size

Adopting `trf` as the default has a packaging consequence we need to confront. Approximate sizes:

| Image | Contents | Approx size |
|---|---|---|
| **Sidecar (`trf`)** | python-slim + presidio/spaCy + **transformers + torch (~1–2 GB)** + `trf` model (~430 MB) | **~3–4 GB** |
| Sidecar (`lg`) | python-slim + presidio/spaCy + `lg` model (~400 MB) | ~1–1.5 GB |
| Go front-end | static binary on distroless | tens of MB |

So the **default artifact is a 3–4 GB image**. For on-prem / air-gapped adopters mirroring it into an internal registry (threat **T8**), that's a real cost: pull time, storage, rebuild time. This is the decision that drives most of the others.

> ✅ **MEASURED (2026-06-07, Docker Desktop, x86_64, CPU-only torch)** — replacing the tildes (per Petzold/Carmack):
> - **`trf` sidecar = 3.91 GB.** CPU-only torch did **not** deflate it — torch + the transformer model are the bulk, not CUDA. Carmack's hypothesis doesn't hold here; the image-size tension is real.
> - **`lg`, built right (no torch), = 2.35 GB** (the naive shared build was 3.67 GB). That's bigger than the ~1–1.5 GB first guessed — lg's word-vector model + the spaCy/SciPy/presidio stack are ~2 GB on their own. So `lg` saves **~1.5 GB vs trf (3.91 → 2.35)**, a ~40% cut but still multi-GB. The **size** case for an `lg` variant is **weaker than hoped**; its real argument is *latency* on bulk inputs → the variant decision leans on the workload question. (Needs model-specific deps regardless — `measure/Dockerfile.lg`.)
> - **Cold start = 4.1 s** (not "tens of seconds"). **Latency:** ~20 ms short / ~470 ms for 500 tokens. The bulk-input concern is confirmed; the readiness concern largely dissolves.

> 💬 **[Carmack]:** Most of those 1–2 GB are torch's CUDA libraries, which on a CPU-default deployment (your own lean, item 3) you will never execute. Install the CPU-only torch wheel (`torch ... --index-url .../cpu`) and the image drops by something like a gigabyte before you've made a single hard tradeoff. That's a measurement to take *before* agonizing over `trf`-vs-`lg`. You may find the "central tension" is half as tense as the table implies.

> 💬 **[Petzold]:** "Approx size" / "~1–2 GB" / "~3–4 GB" — these are guesses presented in a decision table. The sandbox can't build images, fine, but somebody can run `docker images` on the Docker Desktop host *today* on a throwaway build and replace every one of these tildes with a real number. Don't hold a design meeting on estimated megabytes when the actual bytes are one build away.

## Decisions to work through

### 1. Which image(s) do we ship? *(the crux)*

| Option | Pros | Cons |
|---|---|---|
| **A. `trf` only** | One artifact; meets the quality bar; simplest to maintain | 3–4 GB default; heavy for constrained/air-gapped adopters |
| **B. `lg` only** | Small (~1–1.5 GB), fast | **Ships something that fails our own recall gate** — misleading as the default |
| **C. Two variants** — `:trf` (default/recommended) + `:lg` (fast/light) | Adopter picks by resources/latency vs accuracy | Two build paths to maintain/test |

**Lean:** **C** — default to `:trf` (the quality bar is the product's reason to exist), offer `:lg` for constrained or latency-sensitive deployments that accept lower recall (documented). The model is already a config knob, so a build-arg selects which model is baked in.

> 💬 **[Box]:** Option C ships two artifacts but the doc only commits to one *interface*. If `:lg` and `:trf` can ever return different token *types* for the same input — `:trf` catches an `[ORG]` that `:lg` misses — then they are not two builds of one service, they're two services wearing the same tag prefix. A caller's `/unredact` map must be portable across whichever variant happens to be deployed, or you've created a silent compatibility trap. Define "these variants are interface-identical, only recall differs" as a hard contract, or don't ship two.

> 💬 **[Carmack]:** B is correctly rejected but for a slightly soft reason. "Misleading as the default" is a marketing framing; the engineering framing is "ships a product that fails its own correctness bar by default," which is just shipping a bug. Say that. And for C, the maintenance cost everyone fears is mostly test-matrix cost — every test that asserts redaction quality now runs twice. That's the real recurring bill, not the second Dockerfile. Quantify it before signing up.

> 💬 **[Petzold]:** The build-arg approach means the *default* `docker build` produces the 3–4 GB image. Make sure the thing that happens when someone types the obvious command is the thing you want most people to get. Defaults are the only documentation most people read.

**Question for the team:** is the maintenance cost of two variants worth it, or do we ship `trf`-only and let advanced adopters rebuild with `lg`?

> 💬 **[Carmack]:** "Let advanced adopters rebuild with `lg`" is a real option you've buried in a question. If `lg` is genuinely a niche escape hatch for the resource-constrained, then `trf`-only + a documented one-line build-arg override is *less* code, *less* CI, and one artifact to sign and scan. Two official variants is the kind of thing that sounds cheap in a meeting and costs you every release thereafter. I'd want to see actual adopter demand for `lg` before committing to maintain it as a shipped artifact.

### 2. How is the model bundled into the image?

| Option | Pros | Cons |
|---|---|---|
| **Bake in at build** | No runtime network (on-prem/air-gap); reproducible; the image is the mirror-able artifact (T8) | Largest image; rebuilds re-fetch the model |
| Download at container start | Smaller image | **Runtime network dependency** — conflicts with on-prem/air-gap |
| Volume mount | Image stays lean; model shared across replicas | "Who populates/mirrors the volume?" operational burden |

**Lean:** **bake in at build** — best fit for the on-prem posture; download-at-start reintroduces exactly the network dependency we avoid.

> 💬 **[Petzold]:** Agreed, and the rationale is airtight: an air-gapped adopter *cannot* download-at-start by definition, so that option isn't a tradeoff, it's a non-starter for the stated audience. The "rebuilds re-fetch the model" con is solvable with a pinned model layer in the Dockerfile — order the layers so the model fetch caches and only busts when the model version actually changes. That turns the con into a one-time cost.

> 💬 **[Box]:** "Reproducible" is doing a lot of work in that pro column. Baking in only gives reproducibility if the model artifact is pinned by hash, same as your requirements. Is `en_core_web_trf` pinned to a version and digest, or are you `pip install`-ing whatever spaCy serves that day? An unpinned baked-in model is just a download-at-build with extra confidence.

### 3. CPU vs GPU

**Lean:** **CPU base image as the default**, with a documented **GPU variant** for low-latency on large inputs. Rationale depends entirely on the workload (next item): for short interactive turns, CPU `trf` measured ~30 ms p95 — fine. GPU only earns its complexity (CUDA, GPU hosts, even bigger images) for bulk/large-document redaction.

> 💬 **[Carmack]:** This ties directly to my image-size note: CPU-default means you ship CPU-only torch and the CUDA bloat goes away. A GPU variant is then a genuinely separate image with the CUDA wheel, which is honest — the user who needs GPU knowingly pulls the big one. That's a much cleaner story than one fat image carrying GPU libraries that 90% of deployments never touch. Just don't let the "documented GPU variant" become a third entry in a test matrix you already doubled in item 1.

> 💬 **[Petzold]:** 30 ms p95 for a transformer on CPU is a fine number — but it's a sandbox number, and the sandbox is the environment you've told me can't even run Docker. What's the CPU on the actual deploy target? p95 is also hiding the tail that matters for a sidecar: what's p99.9 when the model is cold or the host is under memory pressure? One warm-path measurement on dev hardware isn't a capacity plan.

### 4. The assumption under everything: what is the primary workload?

Most of the above assumes **short, interactive chat-turn redactions** (the original use case). Measured latencies (sandbox CPU):

| Input | `lg` | `trf` |
|---|---|---|
| short message (p95) | ~5 ms | **~30 ms** |
| ~500-token message | 65 ms | **437 ms** |

If the dominant input is instead **large documents / bulk batches**, the calculus flips: CPU `trf` at 437 ms/500 tokens hurts, GPU moves up the list, and `lg` (or the deferred M3 hybrid regex+NER) comes back into play.

**Question for the team:** what's the dominant input shape — interactive short turns, or bulk/large documents? This validates (or breaks) the CPU-default and even the `trf`-default choices.

> 💬 **[Carmack]:** This is the most important section in the document and it's question 4 of 7, framed as an "assumption under everything." It *is* everything. You cannot rationally choose the image, the model, or CPU-vs-GPU without knowing the workload — every other lean in this doc is downstream of an answer you don't have yet. Stop the meeting, get the workload distribution from whoever actually owns the calling application, then resume. Optimizing the packaging of a service whose load profile is unknown is how you spend three weeks shaving an image that then falls over on input shape number two.

> 💬 **[Petzold]:** Look at that `trf` column: 30 ms -> 437 ms is a 14x jump from "short" to 500 tokens, and 500 tokens is not a large document — it's a couple of paragraphs. The latency is roughly linear-or-worse in input length, which means "large document" isn't a different *quadrant*, it's the *same use case scaled up* until it times out. Whatever timeout the Go front-end enforces, somebody's 5,000-token paste will hit it. That ceiling needs to be a documented limit, not a surprise.

> 💬 **[Box]:** If both workloads are real — and in my experience they always both turn out to be real — then "redact one turn" and "redact a batch" are two different operations with two different latency contracts, and trying to serve both through one synchronous `POST /redact` is the design smell. A 437 ms synchronous call is already long; a bulk batch over the same endpoint is a timeout waiting to happen. That might argue for an async/batch verb, which is an *interface* decision M4 is quietly foreclosing by treating this purely as a packaging question.

### 5. Multi-arch

torch wheels are architecture-specific. Docker Desktop on Apple Silicon builds **arm64**; most on-prem servers are **x86_64**. An image built on a laptop may not run on the deploy target.

> 💬 **[Petzold]:** "May not run" undersells it — an arm64 image on an x86_64 host doesn't degrade, it fails to start, and depending on the runtime it may fail with an error message that has nothing to do with architecture. This is exactly the class of bug that "author here, verify there" invites: it'll build clean on the Apple Silicon laptop and die on the server. Build on x86_64 to match the target from day one, or you'll burn a verification cycle discovering this the hard way.

> 💬 **[Carmack]:** Don't build multi-arch until you have a second architecture that an actual adopter actually deploys on. buildx + QEMU cross-builds are slow and add a whole emulation failure surface for a benefit nobody in this doc has asked for. The deploy target is x86_64 servers. Build x86_64. If an arm64 adopter shows up, add it then — it's a build-config change, not an architecture you have to design for now.

> 💬 **[Box]:** The clean answer is to make the build host irrelevant by pinning the target platform explicitly in the build (`--platform linux/amd64`) rather than inheriting whatever the laptop happens to be. The architecture shouldn't be an emergent property of whose machine ran the build.

### 6. Compose shape *(mostly settled — confirm)*

Two services: the **front-end** (only published port) and the **sidecar** (internal network only, never published — T11). This is the reference topology; we'd ship exactly that, plus a small demo caller that exercises the round-trip.

> 💬 **[Petzold]:** "Never published" is a property you can actually test. After `docker compose up`, an automated check should attempt to reach the sidecar from outside the compose network and *assert that it fails*. A security boundary that's only enforced by remembering not to add a `ports:` line is one careless merge away from being gone. The demo caller is good — also make it the negative test.

> 💬 **[Box]:** The demo caller is the most valuable artifact in M4 and it's a parenthetical. It's the only executable specification of the contract — the one thing that proves the round-trip actually round-trips. Treat it as a first-class deliverable and keep it green in CI, because the day it breaks is the day your interface changed and you didn't notice.

### 7. Readiness / startup *(mostly settled — confirm)*

`trf` load takes tens of seconds. `/healthz` already flips ready only after model warmup; the compose healthcheck needs a generous `start_period` so the front-end doesn't receive traffic before the sidecar is up.

> 💬 **[Carmack]:** "Tens of seconds" to load is fine for a long-lived service but it's a real number for anything that restarts under orchestration — every crash-loop, every rolling deploy, every OOM-kill pays it again. Make sure the front-end's behavior during that window is *defined*: does it queue, fast-fail with a clear 503, or hang until timeout? "Doesn't receive traffic before the sidecar is up" describes the happy path; the interesting behavior is what the client sees during the 30-second warmup, and that should be a deliberate choice.

> 💬 **[Petzold]:** `start_period` only governs when *failing* healthchecks start counting against you — it doesn't delay traffic on its own. Make sure the front-end genuinely gates on `/healthz` returning ready (via `depends_on: condition: service_healthy`), not merely on the sidecar container having started. It's an easy thing to get subtly wrong and not notice until a cold start drops the first few requests.

---

## Related decisions this also lets us close

- **Hash-pinned `requirements.txt`** — compiled (with hashes, T8) in the real build environment under Python 3.11. M4 is where this finally happens; it's been deferred because the sandbox is Python 3.10.
- **CI memory** — running the full test suite loads `trf`/torch across several integration fixtures and can OOM a small runner. CI for the integration tests needs adequate RAM, or they should be sharded / run in separate processes. (Pure tests are unaffected.)

> 💬 **[Box]:** Pinning `requirements.txt` in Python 3.11 when the sandbox is 3.10 means your *pinned* set is compiled in an environment nobody develops in. Watch for the case where a 3.11-only wheel resolves differently than what devs see locally on 3.10 — the lockfile and the dev environment will quietly disagree, and the pin gives you false confidence that they don't.

> 💬 **[Petzold]:** The CI-OOM note is the same `trf` memory cost showing up in a third place — image size, runtime footprint, and now CI RAM are all the same underlying fact. That's worth saying out loud: choosing `trf` is choosing a memory-heavy dependency *everywhere it lives*, not just in the shipped image. Sharding the integration tests into separate processes is the more robust fix than just asking for a bigger runner, because the bigger runner just moves the ceiling.

> 💬 **[Carmack]:** Both of these are consequences of the torch dependency, and both reinforce the CPU-only-wheel point from item 1. Smaller dependency, smaller image, less RAM to load in CI, faster cold start. One measurement upstream resolves pressure in four downstream places. Take it first.

---

## Open questions for the architecture team (the decisions)

1. **Image strategy:** ship `trf`-only, or `trf` + `lg` variants? (image size vs meeting the quality bar)
2. **Primary workload:** interactive short turns, or bulk/large documents? (validates CPU-default and the `trf` default itself)
3. **Deploy target architecture** vs the build host — do we need multi-arch?
4. **Model bundling:** confirm bake-in-at-build (vs download / volume) for the on-prem posture.
5. **GPU:** confirm CPU default + GPU as a documented variant.

> 💬 **[Carmack]:** These five are not peers. #2 (workload) gates the answers to #1, #3, and #5 — you literally cannot answer them well without it. Reorder: answer #2 first, take the CPU-only-torch image measurement, *then* the other four mostly answer themselves. As written this list invites the meeting to debate all five in parallel and converge on nothing.

> 💬 **[Box]:** Every question here is about packaging an artifact; none is about the contract that artifact exposes. Before this milestone closes I'd want one more open question on the list: *is `POST /redact` the right interface for every workload we just identified, or does bulk need its own verb?* M4 is the moment that decision gets cheap to make and expensive to defer.

> 💬 **[Petzold]:** Add a sixth: *what are the actual measured numbers?* Real image sizes, real latencies on the real deploy hardware, real cold-start time. Half this document's tildes become facts after one build and one load test, and several of these "decisions" may turn out not to be decisions at all once the real numbers are on the table.

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

> 💬 **[Carmack]:** The last row is marked "needs confirming" and it's the load-bearing assumption for the other five rows. A summary table that lists its own foundation as unconfirmed is telling you the doc isn't ready to drive a decision yet — it's ready to drive the *measurement* that drives the decision.

> 💬 **[Petzold]:** Good that it's all marked provisional. Keep it that way until the build host has produced real artifacts. The leanings are reasonable engineering instincts; they are not yet results.

---

## Reviewer convergence (summary)

All three reviewers independently flagged that **workload (Q2) is the real gate** and everything else is downstream of it.

- **Carmack** — most actionable single item is the **CPU-only torch wheel**: one measurement that deflates the image-size tension and the CI-RAM problem at once. Reorder the open questions so workload is answered first.
- **Box** — recurring theme: M4 is silently making **interface decisions** (the token-map schema, variant compatibility, one-verb-for-all-workloads) while presenting itself as purely a packaging exercise. Add an interface question to the decision list before the milestone closes.
- **Petzold** — throughline is **"authored != verified"**: nearly every number in the doc is an estimate that one real build and one load test would turn into a fact. Replace the tildes before deciding.

## References

- `docs/plans/m4-packaging.html` — the M4 milestone plan (scope, spec breakdown M4-01…04, exit criteria)
- `docs/ARCHITECTURE.html` — system design, threat model (T8 supply chain, T11 IPC), quality targets
- `docs/decisions/0001-language-and-topology.html` — the sidecar topology + Go/HTTP-loopback decisions
- `docs/specs/m1-08-eval-harness.html` — the `lg` vs `trf` baseline numbers