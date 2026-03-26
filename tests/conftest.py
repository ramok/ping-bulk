"""Shared pytest fixtures for ping-bulk integration tests.

Fixtures
--------
app_path
    Absolute path to the ``ping-bulk`` script in the repository root.

tmux_app_40
    A running ping-bulk session in a 120×40 tmux window.

tmux_app_50
    A running ping-bulk session in a 120×50 tmux window.
    At this height the overlay still needs a small scroll range (max_scroll=3).

tmux_app_53
    A running ping-bulk session in a 120×NO_SCROLL_HEIGHT tmux window.
    At this height all help lines fit (max_scroll=0)
    so the scroll indicator is absent.

tmux_app_15
    A running ping-bulk session in a 120×15 tmux window.
    Triggers a taller scroll indicator range.

Each ``tmux_app_*`` fixture yields a :class:`~tmux_helper.TmuxSession`
pre-warmed until the ping-bulk UI is visible (waits for ``'ping-bulk:'``
in the menu bar).  The session is killed automatically after the test.
"""

import importlib.machinery
import importlib.util
import os
import shutil
import sys
import pytest

# Make the tests/ directory importable without installing anything.
sys.path.insert(0, os.path.dirname(__file__))

# Load _HELP_LINES from the ping-bulk script (no .py extension) so fixtures
# can compute NO_SCROLL_HEIGHT dynamically instead of hardcoding the line count.
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_loader = importlib.machinery.SourceFileLoader(
    'ping_bulk', os.path.join(_repo_root, 'ping-bulk')
)
_spec = importlib.util.spec_from_loader('ping_bulk', _loader)
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

# Smallest terminal height at which all help lines fit without scrolling.
NO_SCROLL_HEIGHT = len(_mod._HELP_LINES) + 2

from tmux_helper import TmuxSession  # noqa: E402


# ---------------------------------------------------------------------------
# app_path fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def app_path() -> str:
    """Absolute path to the ping-bulk script."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, 'ping-bulk')
    assert os.path.isfile(path), f"ping-bulk not found at {path}"
    return path


# ---------------------------------------------------------------------------
# Dependency check fixture
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def check_integration_deps():
    """Skip integration tests when required system tools are not on PATH.

    Checks for ``tmux`` (drives the curses UI) and ``ping`` (used by the app
    itself).  Both must be present for the tmux-based tests to work.

    Install hints:
      tmux  — apt install tmux  /  brew install tmux
      ping  — usually pre-installed; on Debian: apt install iputils-ping
    """
    missing = [tool for tool in ('tmux', 'ping') if shutil.which(tool) is None]
    if missing:
        tools = ', '.join(missing)
        hints = {
            'tmux': 'apt install tmux  /  brew install tmux',
            'ping': 'apt install iputils-ping',
        }
        hint_lines = '; '.join(hints[t] for t in missing)
        pytest.skip(
            f"Integration tests require {tools} on PATH — {hint_lines}"
        )


# ---------------------------------------------------------------------------
# Internal factory
# ---------------------------------------------------------------------------

def _make_app_session(name: str, app_path: str, width: int, height: int) -> TmuxSession:
    """Start ping-bulk inside a new tmux session and wait for the UI to appear.

    Uses ``127.0.0.1`` as the single ping target — it is always reachable
    on localhost so the app renders a real host row immediately.
    """
    sess = TmuxSession(name, width=width, height=height)
    try:
        # Send the command as a literal string so tmux does not interpret
        # spaces or special characters as key names.
        sess.send_literal(f'python3 {app_path} 127.0.0.1')
        sess.send_keys('Enter')
        # Wait until the menu bar appears — confirms curses has initialised.
        sess.wait_for('ping-bulk:', timeout=10)
    except Exception:
        sess.kill()
        raise
    return sess


# ---------------------------------------------------------------------------
# Per-test fixtures (function scope — each test gets a fresh session)
# ---------------------------------------------------------------------------

@pytest.fixture
def tmux_app_40(app_path: str, check_integration_deps):
    """ping-bulk in a 120×40 window.  Help overlay shows a scroll indicator."""
    sess = _make_app_session('ping-bulk-test-40', app_path, width=120, height=40)
    yield sess
    sess.kill()


@pytest.fixture
def tmux_app_50(app_path: str, check_integration_deps):
    """ping-bulk in a 120×50 window.  Help overlay still needs scroll (max_scroll=2)."""
    sess = _make_app_session('ping-bulk-test-50', app_path, width=120, height=50)
    yield sess
    sess.kill()


@pytest.fixture
def tmux_app_53(app_path: str, check_integration_deps):
    """ping-bulk in a 120×NO_SCROLL_HEIGHT window.  All help lines fit; no scroll indicator."""
    sess = _make_app_session('ping-bulk-test-53', app_path, width=120, height=NO_SCROLL_HEIGHT)
    yield sess
    sess.kill()


@pytest.fixture
def tmux_app_15(app_path: str, check_integration_deps):
    """ping-bulk in a 120×15 window.  Very short; larger scroll range."""
    sess = _make_app_session('ping-bulk-test-15', app_path, width=120, height=15)
    yield sess
    sess.kill()

