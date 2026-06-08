#!/usr/bin/env bash
set -euo pipefail

FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"
NAMESPACE="bookinfo"
WAIT_SECONDS=${WAIT_SECONDS:-180}  # override with: make all WAIT_SECONDS=60

echo "Removing fault injection manifests…"
oc delete -f "$FIXTURE_DIR/manifests.yaml" --ignore-not-found

echo "Removing any AuthorizationPolicies created by the agent during the test…"
oc delete authorizationpolicy allow-reviews-to-ratings  -n "$NAMESPACE" --ignore-not-found || true
oc delete authorizationpolicy ratings-viewer             -n "$NAMESPACE" --ignore-not-found || true
oc get authorizationpolicy -n "$NAMESPACE" --no-headers 2>/dev/null \
  | grep -i ratings | awk '{print $1}' \
  | xargs -r oc delete authorizationpolicy -n "$NAMESPACE" --ignore-not-found || true

echo "Waiting ${WAIT_SECONDS}s for Istio metrics to stabilise after fault removal…"
sleep "$WAIT_SECONDS"
echo "Cleanup complete — fault injection and agent-created resources removed."
