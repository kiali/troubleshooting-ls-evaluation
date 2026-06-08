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

.PHONY: all clean-results generate-results \
        fix_bookinfo_fault_injection fix_bookinfo_routing check_mesh_status

CONVERSATIONS = scenarios/conversations.yaml
WAIT_SECONDS ?= 200   # seconds to wait after setup/cleanup for metrics to propagate

# Base eval command — shared by all targets
# SYSTEM_CONFIG and OLS_PROVIDER_CONFIG_FILE are set by PROVIDER in the root Makefile

EVAL_BASE = OPENAI_API_KEY=$${OPENAI_API_KEY:-$$(cat "$(OPENAI_KEY_FILE)")} \
            GEMINI_API_KEY=$${GEMINI_API_KEY:-$$(cat "$(GEMINI_KEY_FILE)")} \
            GOOGLE_APPLICATION_CREDENTIALS=$(HOME)/.gcp/gcp_credentials.txt \
            WAIT_SECONDS=$(WAIT_SECONDS) \
            API_KEY=$(_KIALI_TOKEN) \
            KUBECTL=$(KUBECTL) \
            venv/bin/lightspeed-eval \
            --system-config $(SYSTEM_CONFIG) \
            --output-dir results/ \
            --eval-data $(CONVERSATIONS)

# ── clean-results: wipe provider-specific evaluation output ───────────────────
clean-results:
	rm -rf results/

# ── generate-results: build RESULTS.md from the latest run ────────────────────
generate-results: check-venv
	venv/bin/python scripts/generate_results.py --results-dir results/

# ── all: run every conversation in conversations.yaml ─────────────────────────
all: check-venv check-openai-key check-services check-bookinfo \
	fix_bookinfo_routing check_mesh_status fix_bookinfo_fault_injection

# ── Individual conversation targets ───────────────────────────────────────────

fix_bookinfo_fault_injection: check-venv check-openai-key check-services check-bookinfo
	$(EVAL_BASE) \
	  --tag fault_injection_bookinfo

fix_bookinfo_routing: check-venv check-openai-key check-services check-bookinfo
	$(EVAL_BASE) \
	  --tag fix_bookinfo_routing

check_mesh_status: check-venv check-openai-key check-services check-bookinfo
	$(EVAL_BASE) \
	  --tag healthy_env
