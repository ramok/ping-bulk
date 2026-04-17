.PHONY: help test test-q venv clean-venv

VENV     := tests/venv
PYTEST   := $(VENV)/bin/pytest
REQS     := requirements-dev.txt

# Timeout multiplier for slow / loaded hosts.
# Override on the command line: make test SCALE=3
SCALE    ?= 1

# ── Default target ────────────────────────────────────────────────────────────
help:
	@echo "Usage: make [target] [SCALE=N]"
	@echo ""
	@echo "Targets:"
	@echo "  test        Run full test suite (verbose). Creates venv if missing."
	@echo "  test-q      Run tests in quiet mode (summary only)."
	@echo "  venv        Create / refresh the test virtual environment."
	@echo "  clean-venv  Delete the venv (forces full reinstall on next run)."
	@echo "  help        Show this help message (default)."
	@echo ""
	@echo "Options:"
	@echo "  SCALE=N     Multiply all tmux wait_for timeouts by N (default: 1)."
	@echo "              Useful on heavily loaded hosts, e.g.: make test SCALE=3"

# ── Test targets ──────────────────────────────────────────────────────────────

test: $(VENV)
	PING_BULK_TIMEOUT_SCALE=$(SCALE) $(PYTEST) -n auto tests/

test-q: $(VENV)
	PING_BULK_TIMEOUT_SCALE=$(SCALE) $(PYTEST) -n auto -q tests/

# ── Venv management ───────────────────────────────────────────────────────────

venv: $(VENV)

$(VENV): $(REQS)
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r $(REQS)
	@touch $(VENV)

clean-venv:
	rm -rf $(VENV)
