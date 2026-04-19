.PHONY: all basic standard advanced play clean venv help

RECORD  := $(CURDIR)/record.sh
OUTDIR  := $(CURDIR)/output
VENV    := $(CURDIR)/venv
PYTHON  := python3

# agg v1.7.0 binary for linux-x86_64
AGG_URL := https://github.com/asciinema/agg/releases/download/v1.7.0/agg-x86_64-unknown-linux-musl
AGG_BIN := $(VENV)/bin/agg

help:
	@echo "Usage: make [target] [ARGS='--gif --webp']"
	@echo ""
	@echo "Targets:"
	@echo "  all       Record all three demos (basic, standard, advanced)"
	@echo "  basic     ~30s: startup, TCP port, details overlay, failure/recovery"
	@echo "  standard  ~60s: + DNS/stats/history, folding, help, search, command line"
	@echo "  advanced  ~90s: + autofold, :edit, :mux mtr, SSH connect, :remote-ping"
	@echo "  venv      Create venv and install agg (run once before recording)"
	@echo "  play      Play a .cast recording in the terminal (DEMO=basic|standard|advanced)"
	@echo "  clean     Remove generated .cast / .gif / .webp files"
	@echo ""
	@echo "Options:"
	@echo "  ARGS      Extra flags passed to record.sh (default: --gif --webp)"
	@echo ""
	@echo "Examples:"
	@echo "  make venv                         # one-time setup"
	@echo "  make basic                        # basic demo, both .gif and .webp"
	@echo "  make standard ARGS='--gif'        # standard demo, .gif only"
	@echo "  make all ARGS='--webp'            # all demos, .webp only"
	@echo "  make play                         # play basic demo in terminal"
	@echo "  make play DEMO=standard           # play standard demo"

ARGS ?= --gif --webp

venv: $(AGG_BIN)

$(AGG_BIN):
	$(PYTHON) -m venv $(VENV)
	curl -fL --retry 3 -o $(AGG_BIN) $(AGG_URL)
	chmod +x $(AGG_BIN)
	@echo "agg installed: $$($(AGG_BIN) --version)"

all: basic standard advanced

basic: $(AGG_BIN) $(OUTDIR)/basic.cast
$(OUTDIR)/basic.cast:
	bash $(RECORD) basic $(ARGS)

standard: $(AGG_BIN) $(OUTDIR)/standard.cast
$(OUTDIR)/standard.cast:
	bash $(RECORD) standard $(ARGS)

advanced: $(AGG_BIN) $(OUTDIR)/advanced.cast
$(OUTDIR)/advanced.cast:
	bash $(RECORD) advanced $(ARGS)

clean:
	rm -f $(OUTDIR)/*.cast $(OUTDIR)/*.gif $(OUTDIR)/*.webp

DEMO ?= basic

play:
	@test -f $(OUTDIR)/$(DEMO).cast || { echo "ERROR: $(OUTDIR)/$(DEMO).cast not found. Run: make $(DEMO)"; exit 1; }
	asciinema play $(OUTDIR)/$(DEMO).cast
	reset
