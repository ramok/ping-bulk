# ping-bulk Testing Infrastructure Guide for AI

This document provides a technical overview of the testing infrastructure for `ping-bulk`, designed for AI assistants and future developers working on the repository.

## Framework Overview
- **Test Runner:** `pytest`
- **UI Testing Tool:** `tmux` (headless pty session)
- **Core Strategy:** Since `ping-bulk` is a curses-based terminal application, standard stdout capture is insufficient for integration tests. The test suite spins up an actual instance of `ping-bulk` inside a detached `tmux` session. The tests interact with it by sending keystrokes via `tmux send-keys` and verifying the UI state by reading the terminal screen buffer via `tmux capture-pane`.

## Key Components

### 1. `tmux_helper.py` (`TmuxSession`)
A thin wrapper class around the `tmux` CLI used to orchestrate the test sessions.
- **`__init__(name, width, height)`:** Creates a detached tmux session of a fixed window size. Ensuring a stable grid size is critical so that pane captures yield consistent UI layouts for assertion.
- **Input Helpers:**
  - `send_keys(*keys)`: Used for special keys (e.g., `'Enter'`, `'Escape'`, `'Up'`, `'Down'`) or single printable characters.
  - `send_literal(text)`: Used to type multi-character strings cleanly, without tmux misinterpreting them as key names.
  - `run_shell(cmd)`: Types a **shell** command at the pane's prompt and presses Enter. Use this for anything the shell runs — never `send_literal` — because it prefixes the command with a space so `hist_ignore_space` keeps it out of the developer's shell history. `start_app()` goes through it.
- **Output Helpers:**
  - `capture_pane()`: Returns the visible terminal screen as a single string. Trailing whitespaces are preserved, keeping column assertions reliable.
  - `wait_for(text, timeout=5.0)`: Polls `capture_pane` until the `text` appears. This is heavily used to wait for UI state transitions (e.g., waiting for the menu bar to appear or a dialog to open).
  - `wait_for_absence(text, timeout=5.0)`: Polls until `text` disappears.
- **Window Management:** `resize(width, height)`, `kill()`.

### 2. `conftest.py` (Fixtures)
Provides function-scoped `tmux` session fixtures so that each test gets a fresh, isolated `ping-bulk` UI instance. The sessions are pre-warmed (waiting for `'ping-bulk:'` to appear in the menu bar) and automatically killed after the test.

**Common Fixtures:**
- `app_path`: Absolute path to the main `ping-bulk` script.
- `check_integration_deps`: Automatically skips integration tests if `tmux` or `ping` are not available on the `PATH`.
- `tmux_app_40`: 120x40 tmux window. Useful for testing UI elements that require a scrollbar (e.g., help overlay).
- `tmux_app_50`: 120x50 tmux window. Large enough that UI overlays generally fit without scrolling.
- `tmux_app_15`: 120x15 tmux window. Very short window to aggressively test scroll boundaries.
- `tmux_app_with_section`: Starts `ping-bulk` using a temporary config file to test configuration parsing and UI rendering of sections.

### 3. CLI Tests
- **`test_cli.py`**: Tests command-line arguments (like `--help` and no arguments) directly without spinning up curses. This ensures that the CLI logic operates cleanly without requiring a `tmux` environment.

## Parallel Testing

Since the test suite interacts with an actual `tmux` session, running tests in parallel previously caused collisions due to shared session names. The fixtures in `conftest.py` have been updated to generate isolated session names using a unique 8-character UUID for each test, resolving these collisions.

### How to Execute Tests in Parallel
1. Create the venv (one-time): `make venv`  — or manually:
   ```bash
   python3 -m venv tests/venv
   tests/venv/bin/pip install -r requirements-dev.txt
   ```
2. Run the test suite: `make test`  — or directly:
   ```bash
   tests/venv/bin/pytest -n auto tests/
   ```
   Specify worker count explicitly with `-n 4` if needed.

### Handling Hanging Tests
If tests fail or are interrupted abruptly, orphaned `tmux` sessions might be
left behind.  They cannot reach your own sessions, and the next run clears
them, but here is where they live:

- **The suite runs on its own tmux server.** Every session is created on a
  private socket, `tmux -L ping-bulk-test`, so the tests cannot see, resize or
  kill the sessions you are working in — and you cannot accidentally sweep
  theirs away with yours. To look at what the tests are doing, name the socket:

  ```bash
  tmux -L ping-bulk-test ls
  tmux -L ping-bulk-test attach -t <session>
  ```

- **Cleanup is automatic and checked.** `pytest_sessionstart` kills anything
  left on that socket by an earlier run, and `pytest_sessionfinish` kills what
  this run leaked and *reports the count*, so a leak is visible instead of
  silent. The server exits by itself once its last session is gone.

- **To clean up by hand**, kill sessions on that socket individually:

  ```bash
  tmux -L ping-bulk-test ls -F '#{session_name}' | xargs -r -n1 tmux -L ping-bulk-test kill-session -t
  ```

> **Never run `tmux kill-server`** — not on your own server, and not on the
> test socket either. This guide used to suggest it with a parenthetical
> warning, and the warning did not work: it destroyed 50 live sessions on a
> developer's machine, most of them unrelated long-running work, and tmux
> sessions cannot be recovered. A rule with an exception is not a rule, so
> there is no exception. Separately, 44 test sessions once leaked under the
> name `pytest-rfold-*`, which no cleanup pattern matched — which is why
> `TmuxSession` now forces the `ping-bulk-test-` prefix and registers every
> session it creates for sweeping.

## The pane runs *your* shell, and it must not keep what the tests type

A tmux pane starts the developer's own interactive login shell, and the tests
type the command under test into it — so every session the suite starts
appends a line to the real `~/.zsh_history`. Measured on 2026-09-14: **4559 of
the 5008 lines** in a developer's history were this suite, one per session, and
with `SAVEHIST=5000` each run evicted nearly all of their own commands. Their
history reached back three days. Shell history does not come back.

Two layers, because either alone has a way to fail:

- **`ZDOTDIR` points at the session's private temp directory**, so zsh never
  reads the developer's own `.zshrc` — only the empty one written there — and
  therefore never assigns `HISTFILE`, which it has no default for. Nothing is
  written at all. Setting `HISTFILE` *alone* is not enough: an rc file that
  does get read assigns it unconditionally and beats the environment.
- **`run_shell(cmd)` prefixes a space**, which `hist_ignore_space` drops. This
  covers a shell whose rc files the first layer does not govern.

**That empty `.zshrc` is not tidiness.** A `ZDOTDIR` with no `.zshrc` makes
Debian's zsh run `zsh-newuser-install`, an *interactive* first-run wizard that
takes over the terminal: measured, it swallowed the first command sent to the
pane, so `start_app` waited for a UI that never started. An empty file is the
wizard's own documented way out and assigns no `HISTFILE`.

**A bash pane is a known gap, not a covered case.** `HISTFILE` is set on the
session for bash, which does default it — but `~/.bashrc` can reassign it
exactly as `~/.zshrc` does, and the leading space needs
`HISTCONTROL=ignorespace`, which bash does not set by default.

So: **run shell commands with `run_shell`, never `send_literal` plus `Enter`.**
`send_literal` cannot prepend anything of its own — it is also how app
keystrokes are typed (`send_literal('zC')`). `tests/test_shell_history_clean.py`
fails if a new test bypasses `run_shell`.

## Patterns & Best Practices for AI

1. **Wait for State Changes:** Always use `sess.wait_for(text)` after sending an input that triggers a UI transition. Do not rely on hardcoded `time.sleep()`, as UI rendering speeds vary.
2. **Stable Grids for Assertions:** Use exact string matching on the output of `sess.capture_pane()`. Keep in mind that `capture_pane` preserves trailing spaces.
3. **Typing Literals vs Keys:**
   - To send a command string like "10.0.0.1", use `sess.send_literal("10.0.0.1")`.
   - To press Enter or Escape, use `sess.send_keys("Enter")` or `sess.send_keys("Escape")`.
   - **To run a shell command, use `sess.run_shell(cmd)`** — not `send_literal` plus an `Enter`. The pane runs the developer's own interactive shell, so a command typed into it lands in their real history; `run_shell` prefixes a space and `test_shell_history_clean.py` fails if a new test bypasses it.
4. **Scoping:** Remember that UI tests are inherently slower. Use them strategically. For testing internal data parsing or isolated logic, consider unit tests that mock or invoke functions directly rather than driving the full UI.
5. **No Network Dependency:** To prevent flaky tests, ensure network-dependent features (like `ping` or `ssh`) are mocked or directed to `127.0.0.1` (localhost is reliably reachable).

## Test Template

When creating a new test file, use the following template to maintain consistency with the existing suite:

```python
import pytest
from utils.hosts_helper import write_hosts

# Example 1: UI integration test using tmux
class TestFeatureNameUI:
    @pytest.fixture(autouse=True)
    def setup(self, tmux_app_50):
        # Or tmux_app_40, depending on viewport needs
        self.sess = tmux_app_50

    def test_basic_behavior(self):
        # Trigger an action
        self.sess.send_literal(":mycommand")
        self.sess.send_keys("Enter")

        # Wait for the expected state transition
        self.sess.wait_for("expected output text")

        # Capture pane and assert UI looks correct
        screen = self.sess.capture_pane()
        assert "expected output text" in screen

# Example 2: Unit test using pb directly and write_hosts for config parsing
class TestFeatureNameUnit:
    def test_parsing_behavior(self, pb, tmp_path):
        content = """
        :section My Section
        10.0.0.1
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'My Section'),
            ('host', '10.0.0.1')
        ]
```

