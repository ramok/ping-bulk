# tmux with GNU screen key bindings

`tmux.screen-keys.conf` configures tmux to use the same key bindings as GNU
screen so you can switch between the two multiplexers without relearning.

## Usage

```sh
# Start a new tmux server with this config
tmux -f examples/tmux.screen-keys.conf

# Reload inside a running session
tmux source-file examples/tmux.screen-keys.conf

# Use permanently — add to ~/.tmux.conf:
source-file /path/to/ping-bulk/examples/tmux.screen-keys.conf
```

## Key binding reference

| Screen key | Action | tmux command |
|------------|--------|--------------|
| `C-a` | Prefix (same as screen) | `set prefix C-a` |
| `C-a a` | Send literal `C-a` to shell | `send-prefix` |
| `C-a C-a` | Toggle to previously active window | `last-window` |
| `C-a c` / `C-a C-c` | New window (preserves current path) | `new-window` |
| `C-a n` / `Space` / `C-a C-n` | Next window | `next-window` |
| `C-a p` / `BSpace` / `C-a C-p` | Previous window | `previous-window` |
| `C-a 0`–`9` | Switch to window by number | `select-window -t :N` |
| `C-a '` | Go to window by name or number | `command-prompt` |
| `C-a "` | Interactive window chooser | `choose-window` |
| `C-a A` | Rename current window | `command-prompt rename-window` |
| `C-a w` / `C-a C-w` | List windows (brief) | `list-windows` |
| `C-a *` | List attached clients | `list-clients` |
| `C-a d` / `C-a C-d` | Detach from session | `detach-client` |
| `C-a K` / `C-a C-k` | Kill window / kill session | `kill-window` / `kill-session` |
| `C-a S` | Horizontal split (new pane below) | `split-window -v` |
| `C-a \|` | Vertical split (new pane to the right) | `split-window -h` |
| `C-a Tab` | Focus next region/pane | `select-pane -t :.+` |
| `Shift-Tab` | Focus previous region/pane | `select-pane -t :.-` |
| `C-a X` | Remove (kill) current pane | `kill-pane` |
| `C-a Q` | Keep only current pane | `kill-pane -a` |
| `C-a [` / `C-a Esc` | Enter copy/scrollback mode | `copy-mode` |
| `C-a ]` | Paste copied text | `paste-buffer` |
| `C-a l` / `C-a C-l` | Redisplay / refresh | `refresh-client` |
| `C-a t` | Show time / clock | `clock-mode` |
| `C-a i` | Show window info | `display-message` |
| `C-a :` | Command mode | `command-prompt` |
| `C-a ?` | List key bindings | `list-keys` |
| `C-a z` | Zoom (toggle full-screen pane) | `resize-pane -Z` |
| `C-a H` | Toggle logging to `~/tmux.S-I.P.log` | `pipe-pane` |
| `C-a O` | Move pane to its own window | `break-pane` |
| `C-a =` | Broadcast input to all panes | `setw synchronize-panes` |

## Notes

- **Split direction**: screen `C-a S` = horizontal boundary (pane below);
  screen `C-a |` = vertical boundary (pane right). tmux `-v`/`-h` flags
  match this convention in this config.
- **Copy mode**: in copy mode `v` begins selection and `y` copies (vi style).
- **No status bar in screen**: the config adds a minimal blue status bar
  showing session name, window list, and time. Remove or customize the
  `status-*` lines if you prefer a clean screen.
- **Mouse**: disabled by default; uncomment `set-option -g mouse on` to enable.
