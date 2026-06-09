#!/usr/bin/env bash
# Proves the chart's NetworkPolicy isolation on a real (policy-enforcing) cluster
# — e.g. k3d/k3s, or any cluster with a policy-aware CNI.
#
#   ./netpol-isolation-test.sh [release] [namespace]
#
# NON-VACUOUS by design: a NetworkPolicy under a CNI that doesn't enforce it is a
# silent no-op. So we install with the policy OFF, prove the attacker CAN reach
# the sidecar (the control), then `helm upgrade` the policy ON and prove it now
# CANNOT — while the allowed front-end path keeps working. Only the difference
# demonstrates enforcement. Exits non-zero (loudly) on any unexpected result,
# including "still reachable after the policy" (CNI not enforcing).
set -uo pipefail

REL=${1:-redact}
NS=${2:-redact}
HELM=${HELM:-helm}
DIR="$(cd "$(dirname "$0")" && pwd)"
CHART="$DIR/prompt-redact"
PROBE_IMAGE="busybox:1.36"
fails=0

note() { printf '\n=== %s ===\n' "$*"; }
pass() { printf '  PASS: %s\n' "$*"; }
fail() { printf '  FAIL: %s\n' "$*"; fails=$((fails + 1)); }

probe() {  # probe <name> <label> <url> -> prints REACHABLE | BLOCKED
  local name=$1 label=$2 target=$3
  kubectl -n "$NS" delete pod "$name" --ignore-not-found --now >/dev/null 2>&1
  kubectl -n "$NS" run "$name" --image="$PROBE_IMAGE" -l "$label" \
    --restart=Never --command -- \
    sh -c "wget -T 6 -qO- '$target' >/dev/null 2>&1 && echo REACHABLE || echo BLOCKED" \
    >/dev/null 2>&1
  kubectl -n "$NS" wait --for=jsonpath='{.status.phase}'=Succeeded \
    "pod/$name" --timeout=40s >/dev/null 2>&1 || true
  local out; out=$(kubectl -n "$NS" logs "$name" 2>/dev/null | tr -d '[:space:]')
  kubectl -n "$NS" delete pod "$name" --now >/dev/null 2>&1
  echo "${out:-NORESULT}"
}

expect() { if [ "$2" = "$3" ]; then pass "$4 ($2)"; else fail "$4 — wanted $3, got $2"; fi; }

# Like probe(), but retries until the result is REACHABLE (or attempts run out).
# Used for the allowed path: just after a policy change the CNI may not have
# programmed the allow-rules yet, so the first attempt can transiently fail.
probe_until_reachable() {
  local name=$1 label=$2 target=$3 r=""
  for _ in 1 2 3 4 5 6; do
    r=$(probe "$name" "$label" "$target")
    [ "$r" = "REACHABLE" ] && break
    sleep 5
  done
  echo "$r"
}

# Images are side-loaded into the test cluster (k3d image import), not pulled
# from a registry, so the test forces pullPolicy=Never. Real deployments keep
# the chart default (IfNotPresent) and pull from image.registry.
PULL_NEVER="--set sidecar.image.pullPolicy=Never --set frontend.image.pullPolicy=Never"

# --- install with policy OFF (control) -------------------------------------
note "Install chart with networkPolicy.enabled=false (control)"
$HELM upgrade --install "$REL" "$CHART" -n "$NS" --create-namespace $PULL_NEVER \
  --set networkPolicy.enabled=false --wait --timeout 5m
kubectl -n "$NS" rollout status deploy/sidecar --timeout=300s

note "Phase 1 — NO policy: the sidecar should be reachable"
r=$(probe attacker "app=attacker" "http://sidecar:8000/healthz")
expect control "$r" REACHABLE "attacker -> sidecar:8000 with no policy"
if [ "$r" != "REACHABLE" ]; then
  fail "control failed — cannot distinguish 'policy works' from 'never connected'. Aborting."
  exit 1
fi

# --- turn the policy ON via helm upgrade -----------------------------------
note "helm upgrade networkPolicy.enabled=true (+ egress)"
$HELM upgrade "$REL" "$CHART" -n "$NS" $PULL_NEVER \
  --set networkPolicy.enabled=true --set networkPolicy.egress.enabled=true --wait --timeout 2m
sleep 3
kubectl -n "$NS" get networkpolicy

note "Phase 2 — sidecar must stay Ready (policy must not break kubelet probes)"
if kubectl -n "$NS" rollout status deploy/sidecar --timeout=60s >/dev/null 2>&1; then
  pass "sidecar still Ready under the policy"
else
  fail "sidecar went NotReady under the policy (kubelet health probe likely blocked)"
fi

note "Phase 2 — the allowed path must still work"
# Run this first: retrying until REACHABLE rides out the rule-propagation window,
# and once it passes we know the policies are programmed — so the BLOCKED checks
# below are reliable, not racy.
expect allow "$(probe_until_reachable client "role=client" "http://frontend:8080/healthz")" REACHABLE \
  "client -> front-end:8080 -> sidecar (end-to-end) works"

note "Phase 2 — isolation must now be enforced"
expect enforce "$(probe attacker "app=attacker" "http://sidecar:8000/healthz")" BLOCKED \
  "attacker -> sidecar:8000 is now blocked"
expect enforce "$(probe client "role=client" "http://sidecar:8000/healthz")" BLOCKED \
  "arbitrary client -> sidecar:8000 is blocked (only front-end allowed)"

# --- verdict ---------------------------------------------------------------
note "Result"
if [ "$fails" -eq 0 ]; then
  echo "ALL CHECKS PASSED — chart NetworkPolicy isolation is enforced"
  echo "(reachable before, blocked after; allowed path intact)."
  exit 0
fi
echo "$fails CHECK(S) FAILED — see above."
exit 1
