#!/usr/bin/env bash
# Compose smoke test (M4-03): bring up the stack, prove the round-trip works
# through the published front-end, and prove the sidecar is NOT reachable from
# the host (the T11 boundary as a test, not an assertion). Tears down after.
#   ./deploy/compose-smoke.sh
set -euo pipefail
cd "$(dirname "$0")/.."   # repo root

echo "== docker compose up --build =="
docker compose up --build -d
trap 'docker compose down -v >/dev/null 2>&1 || true' EXIT

echo "== wait for /healthz via the published front-end =="
for i in $(seq 1 120); do
  if curl -fs localhost:8080/healthz 2>/dev/null | grep -q ok; then echo "  ready after ${i}s"; break; fi
  sleep 1
done
curl -s localhost:8080/healthz; echo

echo "== round-trip through the front-end (:8080) =="
red=$(curl -s -H 'content-type: application/json' \
  -d '{"text":"Page Dr. John Doe re patient Jane Roe."}' localhost:8080/redact)
echo "  redact -> $red"
echo "$red" | grep -q '\[PERSON_1\]' || { echo "  FAIL: expected a redaction token"; exit 1; }

echo "== NEGATIVE: the sidecar must not be reachable from the host =="
if curl -fs --max-time 3 localhost:8000/healthz >/dev/null 2>&1; then
  echo "  FAIL: sidecar is reachable on host :8000"; exit 1
fi
echo "  ok: sidecar :8000 refused from host"
# `docker compose port` prints e.g. "invalid IP:0" (port 0) when nothing is
# published, so check the parsed port, not for an empty string.
published=$(docker compose port sidecar 8000 2>/dev/null || true)
port="${published##*:}"
if [ -n "$port" ] && [ "$port" -gt 0 ] 2>/dev/null; then
  echo "  FAIL: sidecar has a host port mapping: $published"; exit 1
fi
echo "  ok: no host port mapping for sidecar (compose port -> '${published:-<empty>}')"

echo "ALL GOOD"
