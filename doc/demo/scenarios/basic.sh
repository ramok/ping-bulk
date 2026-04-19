#!/usr/bin/env bash
# basic.sh — ~30s demo scenario
# Called by record.sh with:
#   PANE  = tmux target pane for ping-bulk
#   FIFO  = path to keypress overlay FIFO
# Demonstrates: startup, TCP port target, details overlay, host failure+recovery

set -euo pipefail

# Helper: send a key to ping-bulk pane and announce it on the overlay
key() {
    local label="$1"; shift
    echo "$label" > "$FIFO"
    $TMUXCMD send-keys -t "$PANE" "$@"
}

pause() { sleep "$1"; }

# ── Wait for ping-bulk to initialise ────────────────────────────────────────
pause 4

# ── Show the initial state — let a few pings arrive ─────────────────────────
pause 3

# ── Navigate down to the TCP port entry ─────────────────────────────────────
key "↓" Down
pause 0.4
key "↓" Down
pause 0.4
key "↓" Down
pause 0.4
key "↓" Down
pause 0.6

# ── Open details overlay ────────────────────────────────────────────────────
key "Enter" Enter
pause 3

# ── Close overlay ───────────────────────────────────────────────────────────
key "q" q
pause 1

# ── Navigate back to gw-canary (the one that will fail) ─────────────────────
key "↑" Up
pause 0.4
key "↑" Up
pause 0.4

# ── Watch gw-canary go down (FAIL_AFTER=22 → ~5s after this point) ──────────
# (failure happens automatically via MOCK_PING_FAIL_AFTER env)
pause 6
key "Esc" Escape
pause 4

# ── Watch the recovery ──────────────────────────────────────────────────────
pause 7

# ── Done: quit ──────────────────────────────────────────────────────────────
echo "QUIT" > "$FIFO"
