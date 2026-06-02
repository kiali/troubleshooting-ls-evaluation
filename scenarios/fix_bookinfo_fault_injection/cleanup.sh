#!/usr/bin/env bash
set -euo pipefail

FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"
WAIT_SECONDS=60   # time for Kiali/Istio to reflect the removal of the fault injection

echo "Removing fault injection manifests…"
oc delete -f "$FIXTURE_DIR/manifests.yaml" --ignore-not-found

echo "Waiting ${WAIT_SECONDS}s for Istio metrics to stabilise after fault removal…"
sleep "$WAIT_SECONDS"
echo "Cleanup complete — fault injection removed."
