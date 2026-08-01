#!/bin/sh
# ping-bulk installer -- single-file install into ~/.local/bin.
#
# Checks that the system ping supports the flags ping-bulk needs, downloads
# the raw script from GitHub into ~/.local/bin/ping-bulk (overwriting any
# previous copy), and makes sure that directory is on PATH -- appending an
# export line to ~/.bashrc or ~/.zshrc, picked from $SHELL, when missing.
#
# Usage:
#   ./install.sh
#   curl -fsSL https://raw.githubusercontent.com/ramok/ping-bulk/master/install.sh | sh

set -eu

RAW_URL="${PING_BULK_RAW_URL:-https://raw.githubusercontent.com/ramok/ping-bulk/master/ping-bulk}"
BIN_DIR="$HOME/.local/bin"
TARGET="$BIN_DIR/ping-bulk"

info()  { printf 'install.sh: %s\n' "$1"; }
fail()  { printf 'install.sh: error: %s\n' "$1" >&2; exit 1; }

# --- prerequisites ---------------------------------------------------------
command -v python3 >/dev/null 2>&1 \
    || fail "python3 not found -- ping-bulk needs Python 3.8+"
command -v ping >/dev/null 2>&1 \
    || fail "no 'ping' binary in PATH"

# ping-bulk needs iputils' -O (report outstanding replies) and -D
# (timestamps).  Probe localhost once: first plain (catches permission
# problems), then with the flags (catches busybox/inetutils ping).
ping -c 1 -W 1 127.0.0.1 >/dev/null 2>&1 \
    || fail "'ping 127.0.0.1' failed -- fix ping permissions first"
ping -O -D -c 1 -W 1 127.0.0.1 >/dev/null 2>&1 \
    || fail "your 'ping' lacks -O/-D support -- install iputils-ping >= 20121221"
info "ping supports -O and -D -- OK"

# --- download ----------------------------------------------------------------
# Fetch into a temp file first so a failed download never clobbers an
# already-installed working copy (wget -qO truncates before failing).
mkdir -p "$BIN_DIR"
TMP="$TARGET.tmp"
if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$RAW_URL" -o "$TMP" || { rm -f "$TMP"; fail "download failed: $RAW_URL"; }
elif command -v wget >/dev/null 2>&1; then
    wget -qO "$TMP" "$RAW_URL" || { rm -f "$TMP"; fail "download failed: $RAW_URL"; }
else
    fail "need curl or wget to download $RAW_URL"
fi
chmod +x "$TMP"
mv "$TMP" "$TARGET"
info "installed $TARGET"

# --- PATH --------------------------------------------------------------------
case ":$PATH:" in
    *":$BIN_DIR:"*)
        info "$BIN_DIR is already in PATH"
        ;;
    *)
        case "${SHELL:-}" in
            */zsh) rc="$HOME/.zshrc" ;;
            *)     rc="$HOME/.bashrc" ;;
        esac
        line='export PATH="$HOME/.local/bin:$PATH"'
        if [ -f "$rc" ] && grep -qxF "$line" "$rc"; then
            info "PATH line already present in $rc -- open a new shell to use it"
        else
            printf '\n# added by ping-bulk install.sh\n%s\n' "$line" >> "$rc"
            info "added $BIN_DIR to PATH in $rc -- open a new shell or run: . $rc"
        fi
        ;;
esac

"$TARGET" --help >/dev/null 2>&1 \
    || fail "$TARGET does not run -- check your Python installation"
info "done -- try: ping-bulk 8.8.8.8 1.1.1.1  (or: ping-bulk --help-example)"
