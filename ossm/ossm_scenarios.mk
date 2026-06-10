# ──────────────────────────────────────────────────────────────────────────────
# scenarios/scenarios.mk  —  evaluation targets
#
# Included by the root Makefile. Variables defined there (OPENAI_KEY_FILE,
# GEMINI_KEY_FILE, …) are available here because include merges both files
# at parse time.
#
# All conversations are defined in scenarios/conversations.yaml.
# Add a new conversation there, then optionally add an individual target below.
# ──────────────────────────────────────────────────────────────────────────────

.PHONY: test test-without-mcp check_mesh_status-test generate-ossm-results \
        check_mesh_status-test-without-mcp

OSSM_CONVERSATIONS = ossm/conversations.yaml

# Base eval command — shared by all targets
# SYSTEM_CONFIG and OLS_PROVIDER_CONFIG_FILE are set by PROVIDER in the root Makefile
SYSTEM_CONFIG = system/system_openai.yaml
RESULTS_OSSM_DIR ?= ossm/results/
RESULTS_OSSM_DIR_MCP = $(RESULTS_OSSM_DIR)/mcp
ifeq ($(MCP_ENABLED),false)
  RESULTS_OSSM_DIR_MCP = $(RESULTS_OSSM_DIR)/no-mcp
endif

OSSM_EVAL_BASE = OPENAI_API_KEY=$${OPENAI_API_KEY:-$$(cat "$(OPENAI_KEY_FILE)")} \
            WAIT_SECONDS=$(WAIT_SECONDS) \
            API_KEY=$(_KIALI_TOKEN) \
            KUBECTL=$(KUBECTL) \
            venv/bin/lightspeed-eval \
            --system-config $(SYSTEM_CONFIG) \
            --output-dir $(RESULTS_OSSM_DIR) \
            --eval-data $(OSSM_CONVERSATIONS)

# ── generate-ossm-results: build RESULTS_OSSM.md from ossm/results ────────────
generate-ossm-results: check-venv
	venv/bin/python scripts/generate_ossm_results.py

# ── all: run every conversation in conversations.yaml ─────────────────────────
test: check-venv check-openai-key check-services check-bookinfo \
	check_mesh_status-test

test-without-mcp: check-venv check-openai-key check-services-ols \
	check_mesh_status-test-without-mcp
# ── Individual conversation targets ───────────────────────────────────────────

check_mesh_status-test: check-venv check-openai-key check-services check-bookinfo
	$(OSSM_EVAL_BASE) \
	  --tag check_mesh_Status

check_mesh_status-test-without-mcp: check-venv check-openai-key check-services-ols
	$(OSSM_EVAL_BASE) \
	  --tag no_kiali 