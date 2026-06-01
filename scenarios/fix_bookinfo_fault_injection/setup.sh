#!/usr/bin/env bash
set -euo pipefail

FIXTURE_DIR="$(cd "$(dirname "$0")/fixtures" && pwd)"
NAMESPACE="bookinfo"
WAIT_SECONDS=60   # time for Istio/Kiali to collect traffic stats after fault injection

# Apply the fault injection — DestinationRule + VirtualService with 100% 503 abort
oc apply -f "$FIXTURE_DIR/manifests.yaml"

# Verify the VirtualService was accepted by Istio
ATTEMPT=0
until [ "$ATTEMPT" -ge 10 ]; do
  ATTEMPT=$((ATTEMPT + 1))
  VS=$(oc get virtualservice ratings -n "$NAMESPACE" --no-headers 2>/dev/null | wc -l | tr -d ' ')
  if [ "$VS" -ge 1 ]; then
    echo "VirtualService ratings is active in namespace $NAMESPACE"
    break
  fi
  echo "attempt $ATTEMPT/10 — VirtualService not yet visible, waiting 3s…"
  sleep 3
done

if [ "$VS" -lt 1 ]; then
  echo "ERROR: VirtualService ratings was not created in namespace $NAMESPACE"
  exit 1
fi

# Wait for traffic stats to accumulate so Kiali reflects the fault injection
echo "Waiting ${WAIT_SECONDS}s for Istio metrics to propagate to Kiali…"
sleep "$WAIT_SECONDS"
echo "Setup complete — fault injection is active and traffic stats are ready."