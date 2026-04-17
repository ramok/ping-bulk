.PHONY: test venv clean-venv

VENV     := tests/venv
PYTEST   := $(VENV)/bin/pytest
REQS     := requirements-dev.txt

# Run the full test suite (creates venv automatically if missing).
test: $(VENV)
	$(PYTEST) -n auto tests/

# Quiet run — no per-test output, just summary.
test-q: $(VENV)
	$(PYTEST) -n auto -q tests/

# Create / refresh the test virtual environment.
venv: $(VENV)

$(VENV): $(REQS)
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r $(REQS)
	@touch $(VENV)   # update mtime so make sees it as up-to-date

# Remove the venv (e.g. to force a full reinstall).
clean-venv:
	rm -rf $(VENV)
