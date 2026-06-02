# ──────────────────────────────────────────────────────────────────────────────
# scenarios/scenarios.mk  —  evaluation targets
#
# Included by the root Makefile. Variables defined there (OPENAI_KEY_FILE,
# GEMINI_KEY_FILE, …) are available here because include merges both files
# at parse time.
#
# Adding a new scenario:
#   1. Create scenarios/<name>/eval_data.yaml
#   2. Add a dedicated target below (optional — make all picks it up anyway)
# ──────────────────────────────────────────────────────────────────────────────

.PHONY: all clean-results generate-results \
        fix_bookinfo_fault_injection check_mesh_status

# Base eval command — each target appends --eval-data and --output-dir
EVAL_BASE = OPENAI_API_KEY=$${OPENAI_API_KEY:-$$(cat "$(OPENAI_KEY_FILE)")} \
            GEMINI_API_KEY=$${GEMINI_API_KEY:-$$(cat "$(GEMINI_KEY_FILE)")} \
            API_KEY=$$(oc whoami -t) \
            venv/bin/lightspeed-eval \
            --system-config system.yaml

# ── clean-results: wipe all evaluation output ─────────────────────────────────
clean-results:
	rm -rf results/

# ── generate-results: build RESULTS.md from the latest run ────────────────────
generate-results: check-venv
	venv/bin/python scripts/generate_results.py

# ── all: run every scenario that has an eval_data.yaml ────────────────────────
all: clean-results check-venv check-openai-key check-services check-bookinfo
	@failed=0; total=0; \
	for scenario_dir in scenarios/*/; do \
	  [ -f "$$scenario_dir/eval_data.yaml" ] || \
	    { printf '\033[0;33mSKIP\033[0m  %s (no eval_data.yaml)\n' "$$scenario_dir"; continue; }; \
	  name=$$(basename "$$scenario_dir"); \
	  total=$$((total + 1)); \
	  printf '\n\033[0;34m── Scenario: %s\033[0m\n' "$$name"; \
	  if $(EVAL_BASE) \
	       --eval-data "$$scenario_dir/eval_data.yaml" \
	       --output-dir "results/$$name"; then \
	    printf '\033[0;32m✓\033[0m  %s passed\n' "$$name"; \
	  else \
	    printf '\033[0;31m✗\033[0m  %s FAILED\n' "$$name"; \
	    failed=$$((failed + 1)); \
	  fi; \
	done; \
	[ "$$total" -eq 0 ] && { printf 'No scenarios found in scenarios/\n'; exit 0; }; \
	printf '\n── Summary: %d/%d scenarios passed' "$$((total - failed))" "$$total"; \
	[ "$$failed" -eq 0 ] && printf ' \033[0;32m✓\033[0m\n' || \
	  { printf ' \033[0;31m(%d failed)\033[0m\n' "$$failed"; exit 1; }

# ── Individual scenario targets ────────────────────────────────────────────────

fix_bookinfo_fault_injection: check-venv check-openai-key check-services check-bookinfo
	$(EVAL_BASE) \
	  --eval-data scenarios/fix_bookinfo_fault_injection/eval_data.yaml \
	  --output-dir results/fix_bookinfo_fault_injection

check_mesh_status: check-venv check-openai-key check-services check-bookinfo
	$(EVAL_BASE) \
	  --eval-data scenarios/check_mesh_status/eval_data.yaml \
	  --output-dir results/check_mesh_status
