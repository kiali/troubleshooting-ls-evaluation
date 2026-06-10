# ──────────────────────────────────────────────────────────────────────────────
# Makefile  —  setup, services and environment guards
#
# Evaluation targets live in scenarios/scenarios.mk (included below).
#
# Usage:
#   make setup                         # Create venv and install the evaluation framework
#   make setup-dashboard               # Clone and install the web dashboard
#   make run-ols                       # Run the LightSpeed service container
#   make run-mcp                       # Start the Kiali MCP server
#   make run-dashboard                 # Start the web dashboard (port 5173)
#   make run-dashboard OLS_ENV=true    # OSSM dashboard (ossm/conversations.yaml)
#   make all                           # Run all evaluation scenarios
#   make fix_bookinfo_fault_injection  # Run one scenario
#   make check_mesh_status             # Run one scenario
# ──────────────────────────────────────────────────────────────────────────────

SHELL := /bin/bash

# ── Cluster type ──────────────────────────────────────────────────────────────
# CLUSTER=openshift  (default) — uses oc and CRC/OCP endpoints
# CLUSTER=kind       — uses kubectl and localhost port-forwards
CLUSTER ?= openshift

ifeq ($(CLUSTER),kind)
  KUBECTL        ?= kubectl
  KIALI_ENDPOINT ?= http://localhost:20001/
  # Get a short-lived token from the kiali service account
  _KIALI_TOKEN   = $(shell kubectl -n istio-system create token kiali --duration=8h 2>/dev/null)
else
  KUBECTL        ?= oc
  KIALI_ENDPOINT ?= https://kiali-istio-system.apps-crc.testing/
  _KIALI_TOKEN   = $(shell oc whoami -t 2>/dev/null)
endif

# ── Configuration ─────────────────────────────────────────────────────────────
MCP_CONFIG        ?= mcp_config.toml
OLS_IMAGE         ?= quay.io/openshift-lightspeed/lightspeed-service-api:latest
KIALI_RAG_VERSION ?= latest
KIALI_RAG_DB      ?= quay.io/kiali/kiali-byok:$(KIALI_RAG_VERSION)
LSE_TAG           ?= main       # lightspeed-evaluation tag/branch for the dashboard
LSE_REPO          = https://github.com/lightspeed-core/lightspeed-evaluation.git

OPENAI_KEY_FILE ?= $(HOME)/.openai/openai_api_key.txt
GEMINI_KEY_FILE ?= $(HOME)/.gemini/google_api_key.txt

# ── Provider selection ─────────────────────────────────────────────────────────
# Usage: make run-ols PROVIDER=google   make all PROVIDER=openai
PROVIDER ?= openai

ifeq ($(PROVIDER),openai)
  OLS_PROVIDER_CONFIG_FILE = olsconfig-openai.yaml
  SYSTEM_CONFIG             = system/system_openai.yaml
else ifeq ($(PROVIDER),google)
  OLS_PROVIDER_CONFIG_FILE = olsconfig-google.yaml
  SYSTEM_CONFIG             = system/system_google.yaml
else
  # "all" is handled at the shell level (make all loops over providers).
  # For targets that require a specific provider, check-provider will catch it.
  OLS_PROVIDER_CONFIG_FILE = olsconfig-openai.yaml
  SYSTEM_CONFIG             = system/system_openai.yaml
endif

MCP_ENABLED ?= true
ifeq ($(MCP_ENABLED),false)
  OLS_PROVIDER_CONFIG_FILE = olsconfig-openai-no-mcp.yaml
  SYSTEM_CONFIG             = system/system_openai.yaml
endif

# ── Dashboard paths (relative to dashboard/) ───────────────────────────────────
# Usage: make run-dashboard              # main eval results
#        make run-dashboard OLS_ENV=true # OSSM eval results
OLS_ENV ?= false

ifeq ($(OLS_ENV),true)
  LS_EVAL_SYSTEM_CFG_PATH = ../$(SYSTEM_CONFIG)
  LS_EVAL_DATA_PATH       = ../ossm/conversations.yaml
  LS_EVAL_REPORTS_PATH    = ../ossm/results
else
  LS_EVAL_SYSTEM_CFG_PATH = ../$(SYSTEM_CONFIG)
  LS_EVAL_DATA_PATH       = ../scenarios/conversations.yaml
  LS_EVAL_REPORTS_PATH    = ../dashboard_results
endif

# ── Include evaluation targets ─────────────────────────────────────────────────
include scenarios/scenarios.mk
include ossm/ossm_scenarios.mk

EMBEDDING_MODEL ?= sentence-transformers/all-mpnet-base-v2

.PHONY: setup setup-vector-db get-embeddings-model setup-dashboard run-dashboard run-ols run-mcp \
        check-venv check-openai-key check-services check-services-ols check-bookinfo check-provider

# ── Provider info + validation ────────────────────────────────────────────────
# Validates PROVIDER at runtime (not parse-time) so "make setup PROVIDER=all" works.
check-provider:
	@case "$(PROVIDER)" in \
	  openai|google) \
	    printf 'Provider:     \033[1m%s\033[0m\n' "$(PROVIDER)"; \
	    printf 'OLS config:   olsconfig/%s\n' "$(OLS_PROVIDER_CONFIG_FILE)"; \
	    printf 'System cfg:   %s\n' "$(SYSTEM_CONFIG)"; \
	    ;; \
	  *) \
	    printf '\033[0;31mERROR:\033[0m Unknown PROVIDER "%s". Supported: openai, google\n' "$(PROVIDER)"; \
	    exit 1; \
	    ;; \
	esac

# ── Environment guards ─────────────────────────────────────────────────────────

check-bookinfo:
	@$(KUBECTL) get pods -n bookinfo --no-headers 2>/dev/null | grep -q "Running" || \
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

check-services-ols:
	@nc -z localhost 8080 2>/dev/null || \
	  (printf '\033[0;31mERROR:\033[0m Port 8080 not open. Run: make run-ols\n'; exit 1)

check-services: check-services-ols
	@nc -z localhost 8089 2>/dev/null || \
	  (printf '\033[0;31mERROR:\033[0m Port 8089 not open. Run: make run-mcp\n'; exit 1)

check-venv:
	@[ -d venv ] || \
	  (printf '\033[0;31mERROR:\033[0m venv not found. Run: make setup\n'; exit 1)

# ── Setup ──────────────────────────────────────────────────────────────────────

venv/bin/activate:
	@command -v python3 >/dev/null 2>&1 || \
	  (printf '\033[0;31mERROR:\033[0m python3 not found in PATH.\n'; exit 1)
	@# lightspeed-evaluation requires Python >=3.11,<3.14 — prefer 3.13/3.12/3.11
	$(eval PYTHON := $(shell \
	  for v in python3.13 python3.12 python3.11; do \
	    command -v $$v 2>/dev/null && break; \
	  done))
	@[ -n "$(PYTHON)" ] || \
	  (printf '\033[0;31mERROR:\033[0m Python 3.11–3.13 required (lightspeed-evaluation does not support 3.14+).\n'; \
	   printf '  Install with: sudo dnf install python3.13\n'; exit 1)
	@printf 'Using %s\n' "$(PYTHON)"
	$(PYTHON) -m venv venv
	venv/bin/pip install git+https://github.com/lightspeed-core/lightspeed-evaluation.git

setup: venv/bin/activate

# ── setup-dashboard: sparse-clone the dashboard/ folder and install npm deps ───
setup-dashboard:
	@if [ -d dashboard ] && [ -n "$$(ls -A dashboard 2>/dev/null)" ]; then \
	  printf '\033[0;33mSKIP\033[0m dashboard/ already exists. Remove it to re-download: rm -rf dashboard\n'; \
	else \
	  printf 'Cloning dashboard from lightspeed-evaluation@$(LSE_TAG)...\n'; \
	  tmpdir=$$(mktemp -d); \
	  git clone --depth 1 --branch $(LSE_TAG) --filter=blob:none --sparse \
	    $(LSE_REPO) "$$tmpdir"; \
	  git -C "$$tmpdir" sparse-checkout set dashboard; \
	  cp -r "$$tmpdir/dashboard" .; \
	  rm -rf "$$tmpdir"; \
	  printf '\033[0;32m✓\033[0m Dashboard downloaded to dashboard/\n'; \
	fi
	@printf 'Installing npm dependencies...\n'
	$(MAKE) -C dashboard install
	@printf '\033[0;32m✓\033[0m Dashboard ready. Run: make run-dashboard\n'

# ── run-dashboard: start the Vite dev server with project paths ────────────────
run-dashboard: check-venv
	@[ -d dashboard/node_modules ] || \
	  (printf '\033[0;31mERROR:\033[0m Dashboard not set up. Run: make setup-dashboard\n'; exit 1)
	@if [ "$(OLS_ENV)" = "true" ]; then \
	  printf 'Dashboard mode: \033[1mOSSM\033[0m (OLS_ENV=true)\n'; \
	  printf '  system:  $(LS_EVAL_SYSTEM_CFG_PATH)\n'; \
	  printf '  data:    $(LS_EVAL_DATA_PATH)\n'; \
	  printf '  reports: $(LS_EVAL_REPORTS_PATH)\n'; \
	else \
	  printf 'Cleaning dashboard_results/ and collecting from results/*/\n'; \
	  rm -rf dashboard_results; \
	  mkdir -p dashboard_results/graphs; \
	  for dir in results/*/; do \
	    [ -d "$$dir" ] || continue; \
	    find "$$dir" -maxdepth 1 \( -name '*.json' -o -name '*.csv' \) -exec cp -v {} dashboard_results/ \; ; \
	    [ -d "$${dir}graphs" ] && find "$${dir}graphs" -maxdepth 1 -type f -exec cp -v {} dashboard_results/graphs/ \; || true; \
	  done; \
	fi
	cd dashboard && \
	  PATH=$$(pwd)/../venv/bin:$$PATH \
	  LS_EVAL_SYSTEM_CFG_PATH=$(LS_EVAL_SYSTEM_CFG_PATH) \
	  LS_EVAL_DATA_PATH=$(LS_EVAL_DATA_PATH) \
	  LS_EVAL_REPORTS_PATH=$(LS_EVAL_REPORTS_PATH) \
	  LS_EVAL_DASHBOARD_RUN_ENABLED=true \
	  OPENAI_API_KEY=$${OPENAI_API_KEY:-$$(cat "$(OPENAI_KEY_FILE)")} \
	  GEMINI_API_KEY=$${GEMINI_API_KEY:-$$(cat "$(GEMINI_KEY_FILE)")} \
	  API_KEY=$(_KIALI_TOKEN) \
	  npx vite

## get-embeddings-model: Download the sentence-transformers embedding model to ./embeddings_model
get-embeddings-model: check-venv
	@if [ -d embeddings_model ] && [ -n "$$(ls -A embeddings_model 2>/dev/null)" ]; then \
	  printf '\033[0;33mSKIP\033[0m embeddings_model/ already exists. Remove it to re-download: rm -rf embeddings_model\n'; \
	else \
	  printf 'Installing sentence-transformers (CPU-only torch)...\n'; \
	  venv/bin/pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet; \
	  venv/bin/pip install sentence-transformers --quiet; \
	  printf 'Downloading embedding model: %s\n' "$(EMBEDDING_MODEL)"; \
	  venv/bin/python -c "\
from sentence_transformers import SentenceTransformer; \
print('Downloading $(EMBEDDING_MODEL) ...'); \
SentenceTransformer('$(EMBEDDING_MODEL)').save('./embeddings_model'); \
print('Saved to ./embeddings_model')"; \
	  printf '\033[0;32m✓\033[0m Embedding model saved to embeddings_model/\n'; \
	fi

setup-vector-db: get-embeddings-model
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

run-ols: check-provider setup-vector-db
	@openai_mount=""; gemini_mount=""; gcp_mount=""; \
	[ -f "$(HOME)/.openai/openai_api_key.txt" ] && \
	  openai_mount="-v $(HOME)/.openai/openai_api_key.txt:/app-root/openai_api_key.txt:Z"; \
	[ -f "$(HOME)/.gemini/google_api_key.txt" ] && \
	  gemini_mount="-v $(HOME)/.gemini/google_api_key.txt:/app-root/google_api_key.txt:Z"; \
	[ -f "$(HOME)/.gcp/gcp_credentials.txt" ] && \
	  gcp_mount="-v $(HOME)/.gcp/gcp_credentials.txt:/app-root/gcp_credentials.txt:Z"; \
	podman run -it --rm \
	  -v ./olsconfig:/app-root/config:Z \
	  -v ./vector_db:/app-root/vector_db:Z \
	  $$openai_mount \
	  $$gemini_mount \
	  $$gcp_mount \
	  -e OLS_CONFIG_FILE=/app-root/config/$(OLS_PROVIDER_CONFIG_FILE) \
	  -p 8080:8080 \
	  $(OLS_IMAGE)

run-mcp:
	@tmpconf=$$(mktemp /tmp/mcp-config-XXXXXX.toml); \
	trap 'rm -f "$$tmpconf"' EXIT; \
	KIALI_ENDPOINT=$(KIALI_ENDPOINT) envsubst < $(MCP_CONFIG) > "$$tmpconf"; \
	printf 'Starting MCP server (KIALI_ENDPOINT=%s)\n' "$(KIALI_ENDPOINT)"; \
	npx kubernetes-mcp-server@latest --port 8089 --disable-multi-cluster --config "$$tmpconf"
