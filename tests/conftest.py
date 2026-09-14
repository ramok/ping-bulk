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
import time
import sys
import pytest

def pytest_sessionstart(session):
    """Private config directory, private tmux server, and a clean slate.

    **The config directory.** The tests build a real ``Application``, which
    loads ``$XDG_CONFIG_HOME/ping-bulk/config`` — so without this the suite
    reads, and can *write*, whoever is running it.  A developer's own
    ``:layout log`` fails twenty tests with errors that look exactly like a
    regression in the code under test, and a test that reaches ``:save-config``
    unpatched overwrites a real config.  Both happened.

    **The tmux server.** Every session lives on ``tmux -L ping-bulk-test``
    (see ``tmux_helper``), so the suite cannot see or touch the user's own
    sessions at all.  Leftovers from an earlier run are killed here, by name,
    on that private server — a run must not inherit a session another run
    abandoned.

    Note what is *not* done: ``tmux kill-server``.  Not even on the private
    socket.  The rule is absolute because the failure it prevents is
    unrecoverable, and a habit that has an exception is not a habit.  The
    private server exits on its own once its last session is gone.
    """
    import tempfile
    cfg = os.environ.get('PB_TEST_XDG')
    if not cfg:
        cfg = tempfile.mkdtemp(prefix='pb-test-xdg-')
        os.environ['PB_TEST_XDG'] = cfg
    os.environ['XDG_CONFIG_HOME'] = cfg

    # Refuse to run at all if anything can reach the user's tmux server.
    # Not a comment, not a convention — the suite stops.  A previous version
    # relied on `tmux_cmd` naming a private socket and on nothing ever editing
    # that; one temporary edit later, the start-up sweep destroyed 11 of a
    # developer's live sessions.
    _assert_private_tmux()

    # Only sweep in the controller, not in every xdist worker.
    if hasattr(session.config, "workerinput"):
        return
    _kill_test_sessions('left over from an earlier run', older_than=120)


def _assert_private_tmux():
    """Every tmux command must name the suite's own socket."""
    from tmux_helper import tmux_cmd, _TEST_SERVER
    argv = tmux_cmd('ls')
    if argv[:3] != ['tmux', '-L', _TEST_SERVER]:
        raise pytest.UsageError(
            'refusing to run: tmux commands would reach the default server '
            '(%r).  The suite must use its own socket, tmux -L %s.'
            % (' '.join(argv), _TEST_SERVER))


def _kill_test_sessions(why, older_than=None):
    """Kill *test* sessions on the tests' own tmux server, one by one.

    *older_than* seconds, when given, spares anything younger — because the
    socket is shared by every pytest invocation, not just this one.  Two
    terminals running the suite at once would otherwise destroy each other's
    live sessions mid-test.  The original harness had exactly this check, with
    the comment "to avoid killing sessions from parallel pytest runs", and an
    earlier pass through this file dropped it.

    Two independent guards, because relying on one of them failed
    catastrophically.  The socket is private (``tmux -L``), **and** every name
    must carry ``_TEST_SESSION_PREFIX``.

    The first version had only the socket guard and killed everything the
    socket listed — "safe by construction", because the socket belongs to the
    suite.  Then a one-line experiment pointed ``tmux_cmd`` at the default
    server for a single test run, and this function destroyed 11 of a
    developer's live sessions.  It never ran ``kill-server``; it did not need
    to.  A function that kills every session it is shown *is* a kill-server
    wearing a loop, and its safety lived entirely in a constant somebody was
    always going to edit.

    So the prefix check is not redundant.  Pointed at the wrong server, the
    worst this can now do is kill sessions that the suite itself named.
    """
    import subprocess
    try:
        from tmux_helper import tmux_cmd, _TEST_SESSION_PREFIX
    except Exception:
        return []
    try:
        listed = subprocess.run(
            tmux_cmd('ls', '-F', '#{session_name}:#{session_created}'),
            capture_output=True, text=True, check=False)
    except Exception:
        return []
    names = []
    for row in listed.stdout.split():
        name, _, created = row.rpartition(':')
        if not name.startswith(_TEST_SESSION_PREFIX):
            continue
        if older_than is not None:
            try:
                if time.time() - float(created) < older_than:
                    continue        # another run's, and still alive
            except ValueError:
                continue            # unparseable: leave it alone
        names.append(name)
    for name in names:
        subprocess.run(tmux_cmd('kill-session', '-t', name), check=False)
    if names:
        print(f'\ntmux: killed {len(names)} test session(s) {why}')
    return names


def pytest_sessionfinish(session, exitstatus):
    """Leave the private tmux server empty, and say so if it was not.

    Several tests build a session and then call ``wait_for`` with no
    try/except, so a timeout leaves one behind; 44 accumulated before anybody
    noticed.  Killing them here keeps the next run clean, and reporting the
    count is what makes the leak visible instead of silent.
    """
    if hasattr(session.config, "workerinput"):
        return
    # Only this run's own sessions, from its registry — never a sweep of the
    # socket, which another pytest invocation may be using right now.
    try:
        from tmux_helper import kill_leftover_sessions
        leaked = kill_leftover_sessions()
    except Exception:
        leaked = []
    if leaked:
        print('\ntmux: %d session(s) were not cleaned up by their own test: %s'
              % (len(leaked), ', '.join(sorted(leaked)[:5])))


# Make the tests/ directory importable without installing anything.
sys.path.insert(0, os.path.dirname(__file__))

# Load module from the ping-bulk script (no .py extension) so fixtures
# can compute NO_SCROLL_HEIGHT dynamically instead of hardcoding the line count.
_repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_loader = importlib.machinery.SourceFileLoader(
    'ping_bulk', os.path.join(_repo_root, 'ping-bulk')
)
_spec = importlib.util.spec_from_loader('ping_bulk', _loader)
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

# Smallest terminal height at which all tab-0 help lines fit without scrolling.
_tab0_fragments = _mod._join_help_fragments(
    _mod._HELP_LEGEND, _mod._HELP_HOTKEYS, _mod._HELP_SEARCH, _mod._HELP_FOLDING,
    _mod._HELP_CMDS_INTERACTIVE, _mod._HELP_SSH,
)
_tab0_N = _mod.Application._HELP_PINNED + len(_tab0_fragments)  # pinned header rows + content
NO_SCROLL_HEIGHT = _tab0_N + 2

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
def isolated_config_dir(tmp_path_factory, monkeypatch):
    """A fresh config directory per test.

    ``pytest_sessionstart`` keeps the suite out of the developer's real config,
    but one directory shared by every test is not enough: anything that runs
    ':save-config' — or, now, autosave — writes a config that later tests then
    *read*, so a run could pass alone and fail in the suite depending on the
    order xdist happened to pick.  Measured: ten failures under ``-n auto``
    against a file that passed 48/48 on its own.

    The tmux sessions get their own directory the same way; a pane cannot see
    this one, because it inherits the tmux server's environment.
    """
    monkeypatch.setenv('XDG_CONFIG_HOME', str(tmp_path_factory.mktemp('xdg')))


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
        sess.wait_for('DNS:', timeout=10)
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
        sess.wait_for('DNS:', timeout=10)
    except Exception:
        sess.kill()
        raise
    yield sess
    sess.kill()

