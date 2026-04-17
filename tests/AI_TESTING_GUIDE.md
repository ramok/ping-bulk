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
If tests fail or are interrupted abruptly, orphaned `tmux` sessions might be left running in the background. This can cause subsequent test runs to fail or consume system resources.
- **Detect Orphaned Sessions**: Run `tmux ls` to list active sessions.
- **Cleanup**: To kill all `ping-bulk` test sessions, run:
  ```bash
  tmux kill-server
  ```
  *(Note: This will terminate all tmux sessions for the current user. Use `tmux kill-session -t <session_name>` to selectively kill test sessions if you have other important tmux work running.)*

## Patterns & Best Practices for AI

1. **Wait for State Changes:** Always use `sess.wait_for(text)` after sending an input that triggers a UI transition. Do not rely on hardcoded `time.sleep()`, as UI rendering speeds vary.
2. **Stable Grids for Assertions:** Use exact string matching on the output of `sess.capture_pane()`. Keep in mind that `capture_pane` preserves trailing spaces.
3. **Typing Literals vs Keys:**
   - To send a command string like "10.0.0.1", use `sess.send_literal("10.0.0.1")`.
   - To press Enter or Escape, use `sess.send_keys("Enter")` or `sess.send_keys("Escape")`.
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

