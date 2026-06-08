# `measure/` — throwaway packaging measurements

**Not production artifacts.** This exists to replace the *estimated* numbers in the [M4 packaging plan](../docs/plans/m4-packaging.html) with real ones, per the architecture-team review (["authored != verified"; "measure before deciding"](../M4_PACKAGING_DISCUSSION.md)). Run it on a machine with Docker (e.g. Docker Desktop) — the design sandbox can't build images.

## What it answers

- **Real sidecar image size** with the **CPU-only torch wheel.** The review's key hypothesis (Carmack): most of the estimated 1–2 GB is CUDA libraries a CPU deployment never runs, so the real image may be far smaller than the ~3–4 GB the plan assumes. One build settles it.
- **Cold start** — time from container start until `/healthz` is ready (the `trf` model load), which every restart / rolling deploy pays.
- **Latency** — `/redact` for a short message and a ~500-token message, **on your actual hardware** (the plan's numbers are sandbox-CPU).

## Run

```sh
# from the repo root
PLATFORM=linux/amd64 ./measure/measure.sh     # set to match your deploy-target arch
```

## What to capture

Record the printed **image size**, **cold-start seconds**, and the **/redact times** into the M4 plan and the baseline (`docs/specs/m1-08-eval-harness.html`), replacing the estimates. Those facts may make several "decisions" disappear.

## Caveats (read before trusting it as anything more than a probe)

- **Throwaway**: unpinned deps, single-stage, runs as root. The production sidecar (M4-01) will use the hash-pinned `requirements.txt`, pin the model by digest, and harden the image. This is for **numbers only**.
- The `SPACY_MODEL` build-arg controls which model is **downloaded** (for an `lg` vs `trf` size comparison). The running app uses its default (`trf`), so **latency here is `trf`**. An `lg` *latency* comparison needs a small runtime model-env knob (a follow-up); we already have indicative sandbox numbers for `lg` (short ~5 ms, 500-tok ~65 ms).
- `--platform linux/amd64` is set so an Apple-Silicon build matches x86_64 servers — change it if your target differs.
