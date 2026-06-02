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
        fix_bookinfo_fault_injection check_mesh_status

CONVERSATIONS = scenarios/conversations.yaml

# Base eval command — shared by all targets
EVAL_BASE = OPENAI_API_KEY=$${OPENAI_API_KEY:-$$(cat "$(OPENAI_KEY_FILE)")} \
            GEMINI_API_KEY=$${GEMINI_API_KEY:-$$(cat "$(GEMINI_KEY_FILE)")} \
            API_KEY=$$(oc whoami -t) \
            venv/bin/lightspeed-eval \
            --system-config system.yaml \
			--output-dir results \
            --eval-data $(CONVERSATIONS)

# ── clean-results: wipe all evaluation output ─────────────────────────────────
clean-results:
	rm -rf results/

# ── generate-results: build RESULTS.md from the latest run ────────────────────
generate-results: check-venv
	venv/bin/python scripts/generate_results.py

# ── all: run every conversation in conversations.yaml ─────────────────────────
all: clean-results check-venv check-openai-key check-services check-bookinfo
	$(EVAL_BASE) --output-dir results

# ── Individual conversation targets ───────────────────────────────────────────

fix_bookinfo_fault_injection: check-venv check-openai-key check-services check-bookinfo
	$(EVAL_BASE) \
	  --conv-ids fix_bookinfo_fault_injection

check_mesh_status: check-venv check-openai-key check-services check-bookinfo
	$(EVAL_BASE) \
	  --conv-ids check_mesh_status
