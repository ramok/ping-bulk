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

def pytest_sessionstart(session):
    """Cleanup any stale tmux sessions before the test run."""
    # Only run cleanup in the main process, not in xdist workers
    if hasattr(session.config, "workerinput"):
        return
    
    import subprocess
    import time
    
    result = subprocess.run(
        ['tmux', 'ls', '-F', '#{session_name}:#{session_created}'],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        for line in result.stdout.splitlines():
            if ':' not in line:
                continue
            name, created_str = line.split(':', 1)
            # Only clean up ping-bulk test sessions
            if name.startswith('ping-bulk-test-') and len(name) > 20:
                try:
                    created = int(created_str)
                    age_seconds = time.time() - created
                    # Only kill sessions older than 120 seconds (stale from previous runs)
                    if age_seconds > 120:
                        subprocess.run(['tmux', 'kill-session', '-t', name], check=False)
                except (ValueError, IndexError):
                    pass

def pytest_sessionfinish(session, exitstatus):
    """Cleanup is handled by individual test fixtures, not globally."""
    # We don't clean up here to avoid killing sessions from parallel pytest runs
    pass

# Make the tests/ directory importable without installing anything.
sys.path.insert(0, os.path.dirname(__file__))

# Load _FULL_HELP from the ping-bulk script (no .py extension) so fixtures
# can compute NO_SCROLL_HEIGHT dynamically instead of hardcoding the line count.
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_loader = importlib.machinery.SourceFileLoader(
    'ping_bulk', os.path.join(_repo_root, 'ping-bulk')
)
_spec = importlib.util.spec_from_loader('ping_bulk', _loader)
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

# Smallest terminal height at which all help lines fit without scrolling.
NO_SCROLL_HEIGHT = len(_mod._FULL_HELP) + 2

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
# pb fixture - ping-bulk module loader
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def pb(app_path):
    """Import ping-bulk as a module once for the whole test session."""
    loader = importlib.machinery.SourceFileLoader('ping_bulk', app_path)
    spec = importlib.util.spec_from_loader('ping_bulk', loader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Dependency check fixture
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def check_integration_deps_for_tmux_tests(request):
    """Automatically check dependencies for any test that relies on TmuxSession."""
    needs_tmux = False
    if any(f.startswith('tmux_app') for f in request.fixturenames):
        needs_tmux = True
    if hasattr(request.module, 'TmuxSession'):
        needs_tmux = True

    if needs_tmux:
        request.getfixturevalue('check_integration_deps')

@pytest.fixture(scope='function')
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


import uuid

# ---------------------------------------------------------------------------
# Per-test fixtures (function scope — each test gets a fresh session)
# ---------------------------------------------------------------------------

@pytest.fixture
def tmux_app_40(app_path: str, check_integration_deps):
    """ping-bulk in a 120×40 window.  Help overlay shows a scroll indicator."""
    sess_name = f'ping-bulk-test-40'
    sess = _make_app_session(sess_name, app_path, width=120, height=40)
    yield sess
    sess.kill()


@pytest.fixture
def tmux_app_50(app_path: str, check_integration_deps):
    """ping-bulk in a 120×50 window.  Help overlay still needs scroll (max_scroll=2)."""
    sess_name = f'ping-bulk-test-50'
    sess = _make_app_session(sess_name, app_path, width=120, height=50)
    yield sess
    sess.kill()


@pytest.fixture
def tmux_app_53(app_path: str, check_integration_deps):
    """ping-bulk in a 120×NO_SCROLL_HEIGHT window.  All help lines fit; no scroll indicator."""
    sess_name = f'ping-bulk-test-53'
    sess = _make_app_session(sess_name, app_path, width=120, height=NO_SCROLL_HEIGHT)
    yield sess
    sess.kill()


@pytest.fixture
def tmux_app_15(app_path: str, check_integration_deps):
    """ping-bulk in a 120×15 window.  Very short; larger scroll range."""
    sess_name = f'ping-bulk-test-15'
    sess = _make_app_session(sess_name, app_path, width=120, height=15)
    yield sess
    sess.kill()


@pytest.fixture
def tmux_app_with_section(app_path: str, check_integration_deps, tmp_path):
    """ping-bulk with a config file containing a section and a host."""
    import tempfile

    # Create a temporary config file with a section
    config_content = """## My Section
127.0.0.1
"""
    config_file = tmp_path / "test_config"
    config_file.write_text(config_content)

    # Start session and load the config file
    sess_name = f'ping-bulk-test-section'
    sess = TmuxSession(sess_name, width=120, height=40)
    try:
        sess.send_literal(f'python3 {app_path} -f {config_file}')
        sess.send_keys('Enter')
        sess.wait_for('ping-bulk:', timeout=10)
    except Exception:
        sess.kill()
        raise
    yield sess
    sess.kill()

