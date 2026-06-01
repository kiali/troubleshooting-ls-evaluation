# Usage:
#   make setup                # Create venv and install the evaluation framework
#   make all                  # Run all evals
#   make namespace_pod_count  # Run a single eval by tag
#   make run-ols              # Run the LightSpeed service container
#   make run-mcp              # Start the Kiali MCP server
#   make run-mcp KIALI_ENDPOINT=https://my-kiali.example.com/

KIALI_ENDPOINT ?= https://kiali-istio-system.apps-crc.testing/
MCP_CONFIG     ?= mcp_config.toml
OLS_IMAGE      ?= quay.io/openshift-lightspeed/lightspeed-service-api:latest
KIALI_RAG_VERSION ?= latest
KIALI_RAG_DB   ?= quay.io/kiali/kiali-byok:$(KIALI_RAG_VERSION)

OPENAI_KEY_FILE ?= $(HOME)/.openai/openai_api_key.txt
GEMINI_KEY_FILE ?= $(HOME)/.gemini/google_api_key.txt

.PHONY: all namespace_pod_count run-mcp run-ols setup check-venv check-services check-openai-key check-bookinfo generate-results

# EVAL_CMD: runs inside the venv; OPENAI_API_KEY is sourced from the key file
# when not already set in the environment.
EVAL_CMD = OPENAI_API_KEY=$${OPENAI_API_KEY:-$$(cat "$(GEMINI_KEY_FILE)")} \
		   GEMINI_API_KEY=$${GEMINI_API_KEY:-$$(cat "$(GEMINI_KEY_FILE)")} \
           API_KEY=$$(oc whoami -t) \
           venv/bin/lightspeed-eval \
           --system-config system.yaml \
           --eval-data scenario_evals.yaml \
           --output-dir results

# ── check-bookinfo: verify the Bookinfo app is running in the cluster ─────────
check-bookinfo:
	@oc get pods -n bookinfo --no-headers 2>/dev/null | grep -q "Running" || \
	  (printf '\033[0;31mERROR:\033[0m Bookinfo application is not running in namespace "bookinfo".\n'; \
	   printf '  Deploy it with the traffic generator:\n'; \
	   printf '    curl -L https://raw.githubusercontent.com/kiali/kiali/master/hack/istio/install-bookinfo-demo.sh \\\n'; \
	   printf '         -o install-bookinfo-demo.sh\n'; \
	   printf '    chmod +x install-bookinfo-demo.sh\n'; \
	   printf '    ./install-bookinfo-demo.sh -tg true\n'; exit 1)

# ── check-openai-key: resolve OPENAI_API_KEY from env or key file ─────────────
check-openai-key:
	@if [ -n "$$OPENAI_API_KEY" ]; then \
	  printf 'OPENAI_API_KEY already set, skipping key file.\n'; \
	else \
	  printf 'OPENAI_API_KEY not set. Loading from %s\n' "$(OPENAI_KEY_FILE)"; \
	  [ -f "$(OPENAI_KEY_FILE)" ] || \
	    (printf '\033[0;31mERROR:\033[0m Key file not found: $(OPENAI_KEY_FILE)\n  Either export OPENAI_API_KEY or create the file.\n'; exit 1); \
	  export OPENAI_API_KEY=$$(cat "$(OPENAI_KEY_FILE)"); \
	fi

# ── check-services: verify OLS (8080) and MCP (8089) are reachable ───────────
check-services:
	@nc -z localhost 8080 2>/dev/null || \
	  (printf '\033[0;31mERROR:\033[0m Nothing is listening on port 8080.\n  Start the OLS service first: make run-ols\n'; exit 1)
	@nc -z localhost 8089 2>/dev/null || \
	  (printf '\033[0;31mERROR:\033[0m Nothing is listening on port 8089.\n  Start the MCP server first: make run-mcp\n'; exit 1)

# ── check-venv: fail with a helpful message if setup has not been run ─────────
check-venv:
	@[ -d venv ] || \
	  (printf '\033[0;31mERROR:\033[0m venv not found. Run \033[1mmake setup\033[0m first.\n'; exit 1)

# ── setup: create venv and install the evaluation framework ───────────────────
generate-results: check-venv
	venv/bin/python scripts/generate_results.py

venv/bin/activate:
	@command -v python3 >/dev/null 2>&1 || \
	  (printf '\033[0;31mERROR:\033[0m python3 is not installed or not in PATH.\n'; exit 1)
	@python3 -c "import sys; sys.exit(0) if sys.version_info >= (3,11) else sys.exit(1)" || \
	  (printf '\033[0;31mERROR:\033[0m python3 >= 3.11 is required (found %s).\n' \
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

all: fix_bookinfo_fault_injection

fix_bookinfo_fault_injection: check-venv check-openai-key check-services check-bookinfo
	$(EVAL_CMD) --tags fix_bookinfo_fault_injection
