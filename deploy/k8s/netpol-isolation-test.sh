#!/usr/bin/env bash
# Proves the NetworkPolicy isolation of the sidecar on a real (policy-enforcing)
# Kubernetes cluster — e.g. k3d/k3s, or any cluster with a policy-aware CNI.
#
#   ./netpol-isolation-test.sh
#
# The test is deliberately NON-VACUOUS: a NetworkPolicy under a CNI that doesn't
# enforce it is a silent no-op. So we first prove the attacker CAN reach the
# sidecar with NO policy in place (the control), then apply the policy and prove
# it now CANNOT. Only the *difference* demonstrates enforcement. We also prove
# the allowed path (client -> front-end -> sidecar) still works.
#
# Exit non-zero (loudly) on any unexpected result — including "still reachable
# after the policy," which means the CNI isn't enforcing and the isolation we'd
# claim does not exist.
set -uo pipefail

NS=redact
DIR="$(cd "$(dirname "$0")" && pwd)"
PROBE_IMAGE="busybox:1.36"
fails=0

note() { printf '\n=== %s ===\n' "$*"; }
pass() { printf '  PASS: %s\n' "$*"; }
fail() { printf '  FAIL: %s\n' "$*"; fails=$((fails + 1)); }

# Run a one-shot probe pod with the given label, curl/wget a target, print
# REACHABLE or BLOCKED. wget -T 6 bounds a blocked attempt to a 6s timeout.
probe() {
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

expect() {  # expect <what> <actual> <wanted> <message>
  if [ "$2" = "$3" ]; then pass "$4 ($2)"; else fail "$4 — wanted $3, got $2"; fi
}

# --- deploy ----------------------------------------------------------------
note "Deploy workloads (no policies yet)"
kubectl apply -f "$DIR/namespace.yaml" -f "$DIR/sidecar.yaml" -f "$DIR/frontend.yaml"
kubectl -n "$NS" delete networkpolicy --all >/dev/null 2>&1 || true   # clean slate
echo "waiting for deployments to become available (sidecar loads the trf model)..."
kubectl -n "$NS" rollout status deploy/frontend --timeout=120s
kubectl -n "$NS" rollout status deploy/sidecar --timeout=300s

# --- phase 1: control (no policy) -----------------------------------------
note "Phase 1 — NO policy (control): the sidecar should be reachable"
r=$(probe attacker "app=attacker" "http://sidecar:8000/healthz")
expect control "$r" REACHABLE "attacker -> sidecar:8000 with no policy"
if [ "$r" != "REACHABLE" ]; then
  fail "control failed — cannot distinguish 'policy works' from 'never connected'. Aborting."
  exit 1
fi

# --- phase 2: apply policy, prove it enforces ------------------------------
note "Phase 2 — apply NetworkPolicies"
kubectl apply -f "$DIR/networkpolicies.yaml"
sleep 3   # let the CNI program the rules
kubectl -n "$NS" get networkpolicy

note "Phase 2 — sidecar must stay Ready (policy must not break kubelet probes)"
if kubectl -n "$NS" rollout status deploy/sidecar --timeout=60s >/dev/null 2>&1; then
  pass "sidecar still Ready under the policy"
else
  fail "sidecar went NotReady under the policy (kubelet health probe likely blocked)"
fi

note "Phase 2 — isolation must now be enforced"
r=$(probe attacker "app=attacker" "http://sidecar:8000/healthz")
expect enforce "$r" BLOCKED "attacker -> sidecar:8000 is now blocked"

r=$(probe client "role=client" "http://sidecar:8000/healthz")
expect enforce "$r" BLOCKED "arbitrary client -> sidecar:8000 is blocked (only front-end allowed)"

note "Phase 2 — the allowed path must still work"
r=$(probe client "role=client" "http://frontend:8080/healthz")
expect allow "$r" REACHABLE "client -> front-end:8080 -> sidecar (end-to-end) works"

# --- verdict ---------------------------------------------------------------
note "Result"
if [ "$fails" -eq 0 ]; then
  echo "ALL CHECKS PASSED — sidecar isolation is enforced by the NetworkPolicy"
  echo "(reachable before, blocked after; allowed path intact)."
  exit 0
fi
echo "$fails CHECK(S) FAILED — see above."
exit 1
