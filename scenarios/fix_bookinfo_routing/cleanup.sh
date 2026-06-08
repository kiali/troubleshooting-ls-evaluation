#!/usr/bin/env bash
set -euo pipefail

FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"
WAIT_SECONDS=${WAIT_SECONDS:-180}  # override with: make all WAIT_SECONDS=60

echo "Removing fault injection manifests…"
oc delete -f "$FIXTURE_DIR/manifests.yaml" --ignore-not-found

echo "Waiting ${WAIT_SECONDS}s for Istio metrics to stabilise after fault removal…"
sleep "$WAIT_SECONDS"
echo "Cleanup complete — routing to 50/50 in v1/v2 removed."
