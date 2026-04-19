#!/usr/bin/env bash
# standard.sh — ~60s demo scenario
# Called by record.sh with:
#   PANE  = tmux target pane for ping-bulk
#   FIFO  = path to keypress overlay FIFO
# Demonstrates: navigation, DNS/stats/history cycling, folding, help overlay,
#               search, filter, command line, failure+recovery

set -euo pipefail

key() {
    local label="$1"; shift
    echo "$label" > "$FIFO"
    $TMUXCMD send-keys -t "$PANE" "$@"
}

pause() { sleep "$1"; }

# ── Wait for initialisation ─────────────────────────────────────────────────
pause 4

# ── Navigate hosts with arrow keys ──────────────────────────────────────────
pause 1
key "↓" Down; pause 0.4
key "↓" Down; pause 0.4
key "↓" Down; pause 0.4
key "↑" Up;   pause 0.4
key "↑" Up;   pause 0.8

# ── Cycle DNS mode ──────────────────────────────────────────────────────────
key "D" D; pause 1.2
key "D" D; pause 1.2
key "D" D; pause 1.0

# ── Cycle stats column ──────────────────────────────────────────────────────
key "s" s; pause 0.1
key "s" s; pause 0.1
key "s" s; pause 0.1
key "s" s; pause 0.1
key "s" s; pause 0.1
key "s" s; pause 0.1
key "s" s; pause 0.1
key "s" s; pause 0.1
key "s" s; pause 0.2
key "s" s; pause 0.1

# ── Cycle history mode ──────────────────────────────────────────────────────
key "H" H; pause 1.2
key "H" H; pause 1.2
key "H" H; pause 1.0

# ── Fold the Office LAN section ─────────────────────────────────────────────
# Navigate to section header first (press Esc to deselect, then use [/] )
key "Esc" Escape; pause 0.4
key "[" "["; pause 1.5   # fold-all
pause 0.5
key "]" "]"; pause 1.5   # unfold-all
pause 0.5

# Select a host and fold its section with Space
key "↓" Down; pause 0.3
key "Space" Space; pause 1.0
key "Space" Space; pause 0.8
# Set "seen" mark to Event log
key "Esc" Escape; pause 0.4
key "Space" Space; pause 0.8

# ── Open help overlay ───────────────────────────────────────────────────────
key "?" ?; pause 1.5
key "↓" Down; pause 0.5
key "↓" Down; pause 0.5
key "PgDn" NPage; pause 1.0
key "q" q; pause 0.8

# ── Search ──────────────────────────────────────────────────────────────────
key "/" /
$TMUXCMD send-keys -t "$PANE" -l "canary"
echo "/canary↵" > "$FIFO"
key "" Enter
pause 0.8
key "n" n; pause 0.6
key "N" N; pause 0.6
key "Esc" Escape; pause 0.6

# ── Command line ────────────────────────────────────────────────────────────
key ":" :
$TMUXCMD send-keys -t "$PANE" -l "set dns ip"
echo ":set dns ip↵" > "$FIFO"
key "" Enter
pause 1.5
key ":" :
$TMUXCMD send-keys -t "$PANE" -l "set dns off"
echo ":set dns off↵" > "$FIFO"
key "" Enter
pause 1.0

# ── Watch failure+recovery (mock-ping triggers ~8s after total start) ───────
# By now we're ~25s in; gw-canary failure happens at MOCK_PING_FAIL_AFTER
pause 15

echo "QUIT" > "$FIFO"
