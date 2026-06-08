#!/usr/bin/env bash
# Throwaway packaging measurement — real sidecar image size + cold-start + latency.
# Run from the repo ROOT on a machine with Docker. NOT a production script.
#   PLATFORM=linux/amd64 ./measure/measure.sh
set -euo pipefail

IMAGE="prompt-redact-sidecar:measure-trf"
PLATFORM="${PLATFORM:-linux/amd64}"   # match your deploy target arch

echo "== Building $IMAGE (CPU-only torch, en_core_web_trf) for $PLATFORM =="
docker build --platform "$PLATFORM" -f measure/Dockerfile -t "$IMAGE" .

echo
echo "== Image size (the central question: is CPU-only trf really ~3-4 GB?) =="
docker images "$IMAGE" --format '{{.Repository}}:{{.Tag}}  {{.Size}}'

echo
echo "== Cold start: time until /healthz is ready (the trf model load) =="
cid=$(docker run -d -p 8000:8000 "$IMAGE")
trap 'docker rm -f "$cid" >/dev/null 2>&1 || true' EXIT
start=$(date +%s.%N)
until curl -fs localhost:8000/healthz | grep -q '"ok"'; do sleep 0.5; done
end=$(date +%s.%N)
echo "  ready in $(python3 -c "print(round($end - $start, 1))")s"

echo
echo "== Latency: short message (5 calls) =="
short='{"text":"Email John Smith at john@example.com about MRN 12345."}'
for _ in 1 2 3 4 5; do
  curl -s -o /dev/null -w "  /redact short:  %{time_total}s\n" \
    -H 'content-type: application/json' -d "$short" localhost:8000/redact
done

echo
echo "== Latency: ~500-token message (3 calls) =="
long=$(python3 -c 'import json; print(json.dumps({"text":"Patient John Doe saw Dr Jane Roe in Boston on 03/04/2021. "*45}))')
for _ in 1 2 3; do
  curl -s -o /dev/null -w "  /redact 500tok: %{time_total}s\n" \
    -H 'content-type: application/json' -d "$long" localhost:8000/redact
done

echo
echo "Done. Record image size / cold-start / latencies in the M4 plan"
echo "(docs/plans/m4-packaging.html) and the baseline (docs/specs/m1-08-eval-harness.html)."
echo "Optional lg image SIZE: docker build --build-arg SPACY_MODEL=en_core_web_lg ... (size only)."
