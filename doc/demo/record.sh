#!/usr/bin/env bash
# record.sh — orchestrate a ping-bulk demo recording
#
# Usage:
#   ./record.sh <scenario> [--gif] [--webp] [--width W] [--height H]
#
# Examples:
#   ./record.sh basic --gif --webp
#   ./record.sh standard --gif
#   ./record.sh advanced --webp --width 140 --height 40
#
# Requirements:
#   asciinema  (apt install asciinema)
#   agg        (cargo install agg  OR  download from github.com/asciinema/agg)
#   tmux       (apt install tmux)
#   python3    (for mock-ping and keypress-overlay)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Prefer binaries from the demo venv (agg lives here)
export PATH="$SCRIPT_DIR/venv/bin:$PATH"

# Use our own tmux config — completely ignore the user's ~/.tmux.conf
TMUX_CONF="$SCRIPT_DIR/tmux.conf"
TMUXCMD="tmux -f $TMUX_CONF"

# ── Parse arguments ──────────────────────────────────────────────────────────
SCENARIO=""
DO_GIF=0
DO_WEBP=0
WIDTH=120
HEIGHT=36

while [[ $# -gt 0 ]]; do
    case "$1" in
        basic|standard|advanced) SCENARIO="$1" ;;
        --gif)    DO_GIF=1 ;;
        --webp)   DO_WEBP=1 ;;
        --width)  WIDTH="$2";  shift ;;
        --height) HEIGHT="$2"; shift ;;
        *) echo "Unknown argument: $1" >&2; exit 1 ;;
    esac
    shift
done

if [[ -z "$SCENARIO" ]]; then
    echo "Usage: $0 <basic|standard|advanced> [--gif] [--webp]" >&2
    exit 1
fi

if [[ $DO_GIF -eq 0 && $DO_WEBP -eq 0 ]]; then
    # Default: produce both
    DO_GIF=1
    DO_WEBP=1
fi

# ── Paths ────────────────────────────────────────────────────────────────────
MOCK_PING="$SCRIPT_DIR/mock-ping"
OVERLAY="$SCRIPT_DIR/keypress-overlay.py"
HOSTS_FILE="$SCRIPT_DIR/hosts/${SCENARIO}.hosts"
SCENARIO_SCRIPT="$SCRIPT_DIR/scenarios/${SCENARIO}.sh"
OUTPUT_DIR="$SCRIPT_DIR/output"
CAST_FILE="$OUTPUT_DIR/${SCENARIO}.cast"
GIF_FILE="$OUTPUT_DIR/${SCENARIO}.gif"
WEBP_FILE="$OUTPUT_DIR/${SCENARIO}.webp"

FIFO="/tmp/ping-bulk-demo-keys-$$.fifo"
SESSION="pb-demo-$$"

# Per-scenario mock-ping settings
case "$SCENARIO" in
    basic)
        FAIL_AFTER=22       # ~5s into the "watch down" phase; recording offset ~1.5s
        FAIL_DURATION=7
        FAIL_HOST=8.8.8.8   # only gw-canary goes down; other hosts stay up
        ;;
    standard)
        FAIL_AFTER=35
        FAIL_DURATION=6
        FAIL_HOST=
        ;;
    advanced)
        FAIL_AFTER=55
        FAIL_DURATION=7
        FAIL_HOST=
        ;;
esac

mkdir -p "$OUTPUT_DIR"

# ── Dependency checks ────────────────────────────────────────────────────────
check_dep() {
    if ! command -v "$1" &>/dev/null; then
        echo "ERROR: '$1' not found. $2" >&2
        exit 1
    fi
}
check_dep asciinema "Install: apt install asciinema"
check_dep tmux      "Install: apt install tmux"
check_dep python3   "Install: apt install python3"
if [[ $DO_GIF -eq 1 || $DO_WEBP -eq 1 ]]; then
    check_dep agg "Install: cargo install agg  OR  download from github.com/asciinema/agg/releases"
fi

# ── Inject mock binaries on PATH ─────────────────────────────────────────────
# Prepend a fake bin/ dir so demo-aware mocks shadow real system binaries.
#   ping → mock-ping   (PingMonitor subprocess)
#   mtr  → mock-mtr    (:mux mtr — fake traceroute TUI for demo)
#   ssh  → mock-ssh    (:mux ssh demo-mode + SshPingMonitor ping-relay mode)
FAKE_BIN="/tmp/pb-demo-fakebin-$$"
mkdir -p "$FAKE_BIN"
# Use wrapper scripts (not symlinks) so the absolute path is embedded and
# the mocks are always found even when PATH propagation to new tmux panes
# is unreliable.
printf '#!/bin/sh\nexec "%s" "$@"\n' "$SCRIPT_DIR/mock-ping" > "$FAKE_BIN/ping"
printf '#!/bin/sh\nexec "%s" "$@"\n' "$SCRIPT_DIR/mock-mtr"  > "$FAKE_BIN/mtr"
printf '#!/bin/sh\nexec "%s" "$@"\n' "$SCRIPT_DIR/mock-ssh"  > "$FAKE_BIN/ssh"
chmod +x "$FAKE_BIN/ping" "$FAKE_BIN/mtr" "$FAKE_BIN/ssh"

# ── Inject mock-ping path into hosts file ────────────────────────────────────
EFFECTIVE_HOSTS="/tmp/pb-demo-hosts-$$.hosts"
cp "$HOSTS_FILE" "$EFFECTIVE_HOSTS"

# ── Cleanup handler ──────────────────────────────────────────────────────────
cleanup() {
    $TMUXCMD kill-session -t "$SESSION" 2>/dev/null || true
    rm -f "$FIFO" "$EFFECTIVE_HOSTS"
    rm -rf "$FAKE_BIN"
}
trap cleanup EXIT

# ── Create FIFO ──────────────────────────────────────────────────────────────
mkfifo "$FIFO"

# ── Create tmux session (main pane = ping-bulk, bottom split = overlay) ──────
OVERLAY_HEIGHT=2
MAIN_HEIGHT=$(( HEIGHT - OVERLAY_HEIGHT - 1 ))

# Launch ping-bulk directly via env+python3 — no user shell, no echo of command.
# Multiple args to new-session → tmux does execvp (no shell involved).
PANE_MAIN=$($TMUXCMD new-session -d -s "$SESSION" -x "$WIDTH" -y "$HEIGHT" -P -F '#{pane_id}' \
    env \
        PATH="$FAKE_BIN:$PATH" \
        MOCK_PING_FAIL_AFTER="$FAIL_AFTER" \
        MOCK_PING_FAIL_DURATION="$FAIL_DURATION" \
        MOCK_PING_FAIL_HOST="$FAIL_HOST" \
        MOCK_PING_LATENCY_BASE=1.2 \
        MOCK_PING_LATENCY_JITTER=0.3 \
        MOCK_PING_SEED=42 \
    python3 "$REPO_ROOT/ping-bulk" -f "$EFFECTIVE_HOSTS")

# Disable status bar so all HEIGHT rows are available to panes (no gap fill)
$TMUXCMD set-option -t "$SESSION" status off
# Re-assert window size now that status bar is gone
$TMUXCMD resize-window -t "$SESSION" -x "$WIDTH" -y "$HEIGHT" 2>/dev/null || true

# Propagate FAKE_BIN PATH to all future panes in this session.
# When ping-bulk calls "tmux split-window mtr TARGET" (:mux mtr), the new pane
# is started by the tmux server with the session env — not with ping-bulk's env.
# Setting PATH here ensures mock-mtr and mock-ssh are found in :mux-opened panes.
$TMUXCMD set-environment -t "$SESSION" PATH "$FAKE_BIN:$PATH"

# Bottom split: overlay runs python3 directly — no shell, no echo of command
PANE_OVERLAY=$($TMUXCMD split-window -t "$PANE_MAIN" -v -l $OVERLAY_HEIGHT -P -F '#{pane_id}' \
    python3 "$OVERLAY" "$FIFO")

# Resize main pane explicitly
$TMUXCMD resize-pane -t "$PANE_MAIN" -y $MAIN_HEIGHT

# Re-focus main pane: the overlay was the last created, so it's the active pane.
# When ping-bulk calls "tmux split-window" (no -t), tmux splits the ACTIVE pane.
# We must make MAIN active so :mux commands split the correct (large) pane.
$TMUXCMD select-pane -t "$PANE_MAIN"

# ── Start asciinema recording ────────────────────────────────────────────────
# Record the whole tmux session by attaching to it from within asciinema
ASCIINEMA_PID=""

asciinema rec --overwrite \
    --cols "$WIDTH" \
    --rows "$HEIGHT" \
    -c "$TMUXCMD attach-session -t $SESSION -r" \
    "$CAST_FILE" &
ASCIINEMA_PID=$!

# Give asciinema a moment to attach
sleep 1.5

# ── Run scenario ─────────────────────────────────────────────────────────────
export PANE="$PANE_MAIN"
export FIFO
export TMUXCMD
bash "$SCENARIO_SCRIPT"

# ── Graceful exit ─────────────────────────────────────────────────────────────
# Let the last few frames render
sleep 1.5

# Quit ping-bulk (session may close on its own when ping-bulk exits)
$TMUXCMD send-keys -t "$PANE_MAIN" q 2>/dev/null || true

# Wait a moment; send second q in case first opened an overlay
sleep 1
$TMUXCMD send-keys -t "$PANE_MAIN" q 2>/dev/null || true
sleep 0.5

# Kill the tmux session — this causes asciinema to stop recording (if still alive)
$TMUXCMD kill-session -t "$SESSION" 2>/dev/null || true

wait "$ASCIINEMA_PID" 2>/dev/null || true

echo "Recorded: $CAST_FILE"

# ── Convert to GIF / WebP ────────────────────────────────────────────────────
if [[ $DO_GIF -eq 1 ]]; then
    agg --speed 1.0 "$CAST_FILE" "$GIF_FILE"
    echo "Generated: $GIF_FILE"
fi

if [[ $DO_WEBP -eq 1 ]]; then
    agg --speed 1.0 "$CAST_FILE" "$WEBP_FILE"
    echo "Generated: $WEBP_FILE"
fi

echo "Done."
