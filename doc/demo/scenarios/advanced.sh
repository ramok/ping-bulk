#!/usr/bin/env bash
# advanced.sh — ~90s demo scenario
# Called by record.sh with:
#   PANE  = tmux target pane for ping-bulk
#   FIFO  = path to keypress overlay FIFO
# Demonstrates: vim navigation, autofold, details overlay, :edit, :mux mtr,
#               SSH connect, :remote-ping, failure+recovery

set -euo pipefail

key() {
    local label="$1"; shift
    echo "$label" > "$FIFO"
    $TMUXCMD send-keys -t "$PANE" "$@"
}

pause() { sleep "$1"; }

# ── Wait for initialisation + autofold to kick in ───────────────────────────
pause 5

# ── Vim-style navigation ─────────────────────────────────────────────────────
key "j" j; pause 0.3
key "j" j; pause 0.3
key "j" j; pause 0.3
key "k" k; pause 0.3
key "k" k; pause 0.3
key "G" G; pause 0.5   # jump to bottom
key "gg" g; pause 0.1; $TMUXCMD send-keys -t "$PANE" g; pause 0.5   # jump to top

# ── Autofold: show LAN section auto-collapsing (healthy section folds) ───────
# Already visible after startup — add comment overlay
echo "autofold: healthy sections fold automatically" > "$FIFO"
pause 2
echo "" > "$FIFO"

# ── Details overlay ─────────────────────────────────────────────────────────
key "↓" Down; pause 0.3
key "↓" Down; pause 0.3
key "Enter" Enter; pause 3
key "q" q; pause 0.8

# ── :edit — rename "LAN" → "Office LAN" section, then live reload ────────────
key ":edit" :
$TMUXCMD send-keys -t "$PANE" -l "edit"
echo ":edit↵" > "$FIFO"
pause 0.5
key "" Enter
pause 2      # wait for vim to open
# In vim: substitute "## LAN" → "## Office LAN", then save+quit
$TMUXCMD send-keys -t "$PANE" -l ":%s/## LAN/## Office LAN/"
echo ":%s/## LAN → ## Office LAN/↵" > "$FIFO"
pause 0.5
$TMUXCMD send-keys -t "$PANE" Enter
pause 0.3
$TMUXCMD send-keys -t "$PANE" -l ":wq"
echo ":wq↵" > "$FIFO"
$TMUXCMD send-keys -t "$PANE" Enter
pause 1.5
# ping-bulk prompts: "[1] re-exec  [2] reload  [3] ignore" — choose live reload
key "2 (reload)" 2
pause 3      # allow reload + host re-start to settle before next action

# ── :mux mtr — open mock-mtr in split (bound to 't' by hosts file) ──────────
# After reload highlighted_index is None.  Navigate to gw-canary (8.8.8.8):
#   index 0=## LAN  1=router  2=switch-core  3=switch-floor2  4=nas-backup
#         5=gw-isp  6=## Internet  7=gw-canary
key "↓" Down; pause 0.2
key "↓" Down; pause 0.2
key "↓" Down; pause 0.2
key "↓" Down; pause 0.2
key "↓" Down; pause 0.2
key "↓" Down; pause 0.2
key "↓" Down; pause 0.2
key "↓" Down; pause 0.3   # now on gw-canary (8.8.8.8)
key "t" t
echo "t → :mux mtr (traceroute)" > "$FIFO"
pause 8      # mock-mtr runs for ~6s then exits on its own (pane auto-closes)

# ── SSH connect (c key → :mux ssh %r) ───────────────────────────────────────
# mock-ssh shows "Connecting… Connection refused" then exits after ~4s
key "c" c
echo "c → SSH connect" > "$FIFO"
pause 6

# ── remote-ping section visible ─────────────────────────────────────────────
key "G" G; pause 0.5
echo "remote-ping via SSH" > "$FIFO"
pause 2

# ── Watch failure+recovery ───────────────────────────────────────────────────
# Scroll back to gw-canary area
key "gg" g; $TMUXCMD send-keys -t "$PANE" g; pause 0.3
key "↓" Down; pause 0.3
key "↓" Down; pause 0.3
echo "" > "$FIFO"
pause 20

echo "QUIT" > "$FIFO"
