"""Shared pytest fixtures for ping-bulk integration tests.

Fixtures
--------
app_path
    Absolute path to the ``ping-bulk`` script in the repository root.

tmux_app_40
    A running ping-bulk session in a 120×40 tmux window.

tmux_app_50
    A running ping-bulk session in a 120×50 tmux window.
    At this height the help overlay fits without a scroll indicator.

tmux_app_15
    A running ping-bulk session in a 120×15 tmux window.
    Triggers a taller scroll indicator range.

Each ``tmux_app_*`` fixture yields a :class:`~tmux_helper.TmuxSession`
pre-warmed until the ping-bulk UI is visible (waits for ``'ping-bulk:'``
in the menu bar).  The session is killed automatically after the test.
"""

import os
import sys
import pytest

# Make the tests/ directory importable without installing anything.
sys.path.insert(0, os.path.dirname(__file__))

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
def tmux_app_40(app_path: str):
    """ping-bulk in a 120×40 window.  Help overlay shows a scroll indicator."""
    sess = _make_app_session('pb-test-40', app_path, width=120, height=40)
    yield sess
    sess.kill()


@pytest.fixture
def tmux_app_50(app_path: str):
    """ping-bulk in a 120×50 window.  Help overlay fits without scrolling."""
    sess = _make_app_session('pb-test-50', app_path, width=120, height=50)
    yield sess
    sess.kill()


@pytest.fixture
def tmux_app_15(app_path: str):
    """ping-bulk in a 120×15 window.  Very short; larger scroll range."""
    sess = _make_app_session('pb-test-15', app_path, width=120, height=15)
    yield sess
    sess.kill()

