# ping-bulk tests

Integration tests for the `ping-bulk` terminal application.

## Requirements

| Dependency | Purpose |
|---|---|
| `pytest` | test runner |
| `tmux` | drive the curses UI in a headless pty |
| Python 3.8+ | required by ping-bulk itself |

Install Python dependencies:

```sh
pip install pytest
```

`tmux` must be on `PATH` (e.g. `apt install tmux` / `brew install tmux`).

## Running

```sh
# All tests
pytest tests/

# Verbose output
pytest tests/ -v

# One file
pytest tests/test_cli.py
pytest tests/test_help_overlay.py

# One test class
pytest tests/test_help_overlay.py::TestScrollIndicatorAt40Rows

# One test
pytest tests/test_help_overlay.py::TestOpenClose::test_close_with_escape
```

## Structure

```
tests/
  tmux_helper.py         — TmuxSession: thin wrapper around the tmux CLI
  conftest.py            — shared fixtures (app_path, tmux_app_40/50/15)
  test_cli.py            — CLI tests (no curses; subprocess only)
  test_help_overlay.py   — help overlay open/close, scroll indicator, resize
  README.md              — this file
```

## Fixtures

| Fixture | Window size | Notes |
|---|---|---|
| `tmux_app_40` | 120 × 40 | Overlay scroll indicator visible (38/47 lines fit) |
| `tmux_app_50` | 120 × 50 | All 47 overlay lines fit; no scroll indicator |
| `tmux_app_15` | 120 × 15 | Only 13 lines fit; large scroll range (max=34) |

All `tmux_app_*` fixtures are **function-scoped**: each test gets a fresh
ping-bulk session and the session is killed automatically after the test.

All `tmux_app_*` fixtures also depend on `check_integration_deps` (session-scoped):
if `tmux` or `ping` are not on `PATH` the integration tests are skipped automatically
and `test_cli.py` continues to run unaffected.

## Test files

### `test_cli.py`

Tests the command-line interface without starting curses:

- **`TestNoArgs`** — no arguments → exit 0, usage printed to stdout
- **`TestHelpFlag`** — `--help` → exit 0, stdout includes examples/flags

### `test_help_overlay.py`

Tests the `?` / `:help` overlay rendered inside a live curses session:

| Class | Fixture | What it tests |
|---|---|---|
| `TestOpenClose` | `tmux_app_40` | Open with `?` and `:help`; close with `q`, `Q`, `Esc`; menu bar restored |
| `TestScrollIndicatorAt40Rows` | `tmux_app_40` | Indicator present; `↓`/`↑`/`NPage`/`PPage` update the line range |
| `TestNoIndicatorAt50Rows` | `tmux_app_50` | No indicator; all content visible |
| `TestScrollIndicatorAt15Rows` | `tmux_app_15` | Indicator `1-13/46`; `NPage` not clamped at shallow scroll |
| `TestResize` | `tmux_app_40` | Shrink → indicator changes; grow → indicator disappears |

## Help overlay geometry

```
_HELP_LINES count : 46
_HELP_INNER_W     : 70
box_w             : 72  (inner + 2 border chars)

height | visible_count | max_scroll | indicator at scroll=0
-------+---------------+------------+-----------------------
  40   |      38       |     8      |  ↑↓ 1-38/46
  50   |      46       |     0      |  (none)
  15   |      13       |    33      |  ↑↓ 1-13/46
```

