# ──────────────────────────────────────────────────────────────────────────────
# Makefile  —  setup, services and environment guards
#
# Evaluation targets live in scenarios/scenarios.mk (included below).
#
# Usage:
#   make setup                    # Create venv and install the evaluation framework
#   make run-ols                  # Run the LightSpeed service container
#   make run-mcp                  # Start the Kiali MCP server
#   make all                      # Run all evaluation scenarios
#   make fix_bookinfo_fault_injection  # Run one scenario
#   make check_mesh_status             # Run one scenario
# ──────────────────────────────────────────────────────────────────────────────

SHELL := /bin/bash

# ── Configuration ─────────────────────────────────────────────────────────────
KIALI_ENDPOINT    ?= https://kiali-istio-system.apps-crc.testing/
MCP_CONFIG        ?= mcp_config.toml
OLS_IMAGE         ?= quay.io/openshift-lightspeed/lightspeed-service-api:latest
KIALI_RAG_VERSION ?= latest
KIALI_RAG_DB      ?= quay.io/kiali/kiali-byok:$(KIALI_RAG_VERSION)

OPENAI_KEY_FILE ?= $(HOME)/.openai/openai_api_key.txt
GEMINI_KEY_FILE ?= $(HOME)/.gemini/google_api_key.txt

# ── Include evaluation targets ─────────────────────────────────────────────────
include scenarios/scenarios.mk

.PHONY: setup setup-vector-db run-ols run-mcp \
        check-venv check-openai-key check-services check-bookinfo

# ── Environment guards ─────────────────────────────────────────────────────────

check-bookinfo:
	@oc get pods -n bookinfo --no-headers 2>/dev/null | grep -q "Running" || \
	  (printf '\033[0;31mERROR:\033[0m Bookinfo is not running in namespace "bookinfo".\n'; \
	   printf '  Deploy it: ./install-bookinfo-demo.sh -tg true\n'; exit 1)

check-openai-key:
	@if [ -n "$$OPENAI_API_KEY" ]; then \
	  printf 'OPENAI_API_KEY already set, skipping key file.\n'; \
	else \
	  printf 'OPENAI_API_KEY not set. Loading from %s\n' "$(OPENAI_KEY_FILE)"; \
	  [ -f "$(OPENAI_KEY_FILE)" ] || \
	    (printf '\033[0;31mERROR:\033[0m Key file not found: $(OPENAI_KEY_FILE)\n  Either export OPENAI_API_KEY or create the file.\n'; exit 1); \
	  export OPENAI_API_KEY=$$(cat "$(OPENAI_KEY_FILE)"); \
	fi

check-services:
	@nc -z localhost 8080 2>/dev/null || \
	  (printf '\033[0;31mERROR:\033[0m Port 8080 not open. Run: make run-ols\n'; exit 1)
	@nc -z localhost 8089 2>/dev/null || \
	  (printf '\033[0;31mERROR:\033[0m Port 8089 not open. Run: make run-mcp\n'; exit 1)

check-venv:
	@[ -d venv ] || \
	  (printf '\033[0;31mERROR:\033[0m venv not found. Run: make setup\n'; exit 1)

# ── Setup ──────────────────────────────────────────────────────────────────────

venv/bin/activate:
	@command -v python3 >/dev/null 2>&1 || \
	  (printf '\033[0;31mERROR:\033[0m python3 not found in PATH.\n'; exit 1)
	@python3 -c "import sys; sys.exit(0) if sys.version_info >= (3,11) else sys.exit(1)" || \
	  (printf '\033[0;31mERROR:\033[0m python3 >= 3.11 required (found %s).\n' \
	          "$$(python3 --version 2>&1)"; exit 1)
	python3 -m venv venv
	venv/bin/pip install git+https://github.com/lightspeed-core/lightspeed-evaluation.git

setup: venv/bin/activate

setup-vector-db:
	@if [ -d vector_db/kiali ] && [ -n "$$(ls -A vector_db/kiali 2>/dev/null)" ]; then \
	  printf '\033[0;33mSKIP\033[0m vector_db/kiali already exists. Remove it to re-extract: rm -rf vector_db/kiali\n'; \
	else \
	  mkdir -p vector_db; \
	  podman create --replace --name tmp-kiali-byok $(KIALI_RAG_DB) true; \
	  podman cp tmp-kiali-byok:/rag/vector_db/kiali vector_db/kiali || \
	    (podman rm -f tmp-kiali-byok; exit 1); \
	  podman rm -f tmp-kiali-byok; \
	  printf '\033[0;32m✓\033[0m Vector DB extracted to vector_db/kiali\n'; \
	fi

# ── Services ───────────────────────────────────────────────────────────────────

run-ols: setup-vector-db
	podman run -it --rm \
	  -v ./olsconfig:/app-root/config:Z \
	  -v ./vector_db:/app-root/vector_db:Z \
	  -v ~/.openai/openai_api_key.txt:/app-root/openai_api_key.txt:Z \
	  -v ~/.gemini/google_api_key.txt:/app-root/google_api_key.txt:Z \
	  -e OLS_CONFIG_FILE=/app-root/config/olsconfig-openai.yaml \
	  -p 8080:8080 \
	  $(OLS_IMAGE)

run-mcp:
	@tmpconf=$$(mktemp /tmp/mcp-config-XXXXXX.toml); \
	trap 'rm -f "$$tmpconf"' EXIT; \
	KIALI_ENDPOINT=$(KIALI_ENDPOINT) envsubst < $(MCP_CONFIG) > "$$tmpconf"; \
	printf 'Starting MCP server (KIALI_ENDPOINT=%s)\n' "$(KIALI_ENDPOINT)"; \
	npx kubernetes-mcp-server@latest --port 8089 --disable-multi-cluster --config "$$tmpconf"
