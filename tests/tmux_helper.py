"""Thin wrapper around the tmux CLI used by the integration tests.

Each TmuxSession owns one detached tmux session.  The session is created with
a fixed window size so every ``capture-pane`` call returns a stable grid that
the tests can assert against.

Usage::

    sess = TmuxSession('test-mytest', width=120, height=40)
    sess.send_literal('echo hello')
    sess.send_keys('Enter')
    sess.wait_for('hello')
    sess.kill()
"""

import os
import shutil
import weakref
import subprocess
import tempfile
import time

# ---------------------------------------------------------------------------
# Timeout scaling
# ---------------------------------------------------------------------------
# On a heavily loaded host the kernel scheduler may delay tmux subprocess
# execution far beyond the default 5 s poll window.  Setting the environment
# variable ``PING_BULK_TIMEOUT_SCALE`` (e.g. ``export PING_BULK_TIMEOUT_SCALE=3``)
# multiplies every ``wait_for`` / ``wait_for_absence`` timeout by that factor
# so the same test suite can be used on slow CI machines without per-call
# changes.  The interval between polls is also scaled so the poll loop does
# not spin excessively.
#
# Example:
#   PING_BULK_TIMEOUT_SCALE=3 pytest -n auto tests/
#
TIMEOUT_SCALE: float = float(os.environ.get('PING_BULK_TIMEOUT_SCALE', '1.0'))


# Every test session's name starts with this, so one pattern finds them all.
_TEST_SESSION_PREFIX = 'ping-bulk-test-'

# **The tests run on their own tmux server**, reached through a private socket
# (`tmux -L`).  Nothing here shares a server with the person running the suite,
# so a test — or a careless cleanup — cannot see, resize or kill their work.
# It also makes teardown total rather than pattern-matched: the whole server is
# killed at the end of the run, which is safe precisely because it is ours.
#
# This exists because the alternative failed in the worst way: a `tmux
# kill-server` meant for leaked test sessions destroyed 50 live sessions on a
# developer's machine, and separately 44 test sessions leaked under a name no
# cleanup pattern matched.  A private server answers both at once.
_TEST_SERVER = 'ping-bulk-test'


def tmux_cmd(*args):
    """An argv for the tests' own tmux server."""
    return ['tmux', '-L', _TEST_SERVER, *args]


# The environment the tmux server is started with — and therefore the one
# every pane inherits.
#
# **LINES and COLUMNS must not be in it.**  ncurses defaults to `use_env(TRUE)`
# and prefers those variables over the terminal's real size, so an app that
# inherits a stale `LINES=40` keeps drawing 40 rows after the window shrinks to
# 15: SIGWINCH arrives, the pty is genuinely 15 rows, and ncurses ignores both.
# The resize tests then see the *bottom* of an oversized frame and time out
# waiting for an indicator that is scrolled off the top.
#
# It only showed up once the suite moved to its own server: a long-running
# shared server was started from a context that never exported them, while this
# one inherits whatever shell ran pytest.  Measured: `env -u LINES -u COLUMNS`
# takes the indicator from '(none)' back to '1-11/161'.
_TMUX_ENV = {k: v for k, v in os.environ.items()
             if k not in ('LINES', 'COLUMNS')}

# Sessions created but not yet killed.  A WeakSet, so a forgotten object does
# not keep anything alive; conftest sweeps whatever is left at the end.
_LIVE_SESSIONS = weakref.WeakSet()


def kill_leftover_sessions():
    """Kill test sessions this run created and did not clean up.

    Only ever by name, and only names this module made.  Never
    ``tmux kill-server``: that ends every session the user has, including work
    with nothing to do with the tests.
    """
    killed = []
    for sess in list(_LIVE_SESSIONS):
        try:
            killed.append(sess.name)
            sess.kill()
        except Exception:
            pass
    return killed


class TmuxSession:
    """Manage a single detached tmux session for integration testing."""

    def __init__(self, name: str, width: int = 120, height: int = 40):
        import uuid
        # Always use a unique session ID by appending a uuid
        self.name = f"{name}-{uuid.uuid4().hex[:8]}"
        # **One prefix, always.**  A session named anything else is invisible
        # to every cleanup that looks for test sessions, and
        # `test_recursive_fold.py` did exactly that (`pytest-rfold-…`): 44
        # sessions leaked onto a developer's tmux server where nothing would
        # find them again.  Enforced here rather than asked for in a guide.
        if not self.name.startswith(_TEST_SESSION_PREFIX):
            self.name = _TEST_SESSION_PREFIX + self.name
        self.width = width
        self.height = height
        # Registered so the run can clean up after a test that raised before
        # reaching its own kill() — several do, and a timeout is when it
        # happens.
        _LIVE_SESSIONS.add(self)

        # Kill any stale session with this name left over from a previous
        # test run that crashed without cleanup.
        stale = subprocess.run(
            tmux_cmd('has-session', '-t', self.name),
            check=False, env=_TMUX_ENV,
        )
        if stale.returncode == 0:
            subprocess.run(tmux_cmd('kill-session', '-t', self.name), check=False,
                           env=_TMUX_ENV)

        # A private config directory for this session, so the suite does not
        # read — or depend on — whoever is running it.
        #
        # The tests drive the real ./ping-bulk, which loads
        # $XDG_CONFIG_HOME/ping-bulk/config (falling back to ~/.config).  A
        # pane inherits the tmux *server's* environment, not this process's,
        # so exporting the variable here or in pytest does not reach it: it has
        # to be set on the session.  Without this, a developer's own settings
        # decide what the tests see — ':layout log' alone fails twenty of them,
        # with an error that looks like a bug in the code under test.
        self._cfgdir = tempfile.mkdtemp(prefix='pb-test-xdg-')

        # The pane runs the developer's **interactive login shell**, and the
        # tests type the command under test into it — so every session the
        # suite starts appends a line to that developer's real shell history.
        # Measured on 2026-09-14: 4559 of the 5008 lines in a developer's
        # ~/.zsh_history were this suite, and with SAVEHIST=5000 each run
        # evicted nearly all of their own.  Shell history does not come back.
        #
        # `ZDOTDIR` is the layer that works: zsh reads its rc files from there,
        # so it never sees the developer's own `.zshrc` — only the empty one
        # written below — and therefore never assigns `HISTFILE`, which it has
        # no default for.  Nothing is written at all.  Setting `HISTFILE` alone
        # is **not** enough, because an rc file that does get read assigns it
        # unconditionally and beats the environment.
        #
        # `HISTFILE` is set anyway for bash, which does default it — but note
        # that bash is only *partly* covered: `~/.bashrc` can reassign
        # `HISTFILE` exactly as `~/.zshrc` does, and the leading space needs
        # `HISTCONTROL=ignorespace`, which bash does not set by default.  A
        # pane whose shell is bash is a known gap, not a covered case.
        #
        # **That empty `.zshrc` is not optional.**  A `ZDOTDIR` with no `.zshrc`
        # in it makes Debian's zsh run `zsh-newuser-install`, an *interactive*
        # first-run wizard that owns the terminal and swallows what is typed
        # next — measured: the first command sent to the pane was consumed by
        # its menu, so `start_app` would wait for a UI that never started.  An
        # empty file is the wizard's own documented way out, and it assigns no
        # `HISTFILE`, so the history still goes nowhere.
        self._histfile = os.path.join(self._cfgdir, 'shell_history')
        open(os.path.join(self._cfgdir, '.zshrc'), 'w').close()

        # Create a new detached session with the requested dimensions.
        subprocess.run(
            tmux_cmd(
                'new-session',
                '-d',            # detached
                '-s', self.name,
                '-x', str(width),
                '-y', str(height),
                '-e', f'XDG_CONFIG_HOME={self._cfgdir}',
                '-e', f'ZDOTDIR={self._cfgdir}',
                '-e', f'HISTFILE={self._histfile}',
            ),
            check=True, env=_TMUX_ENV,
        )

        # Explicitly resize the window after creation to handle older tmux
        # versions that may ignore the -x/-y flags on new-session.
        subprocess.run(
            tmux_cmd(
                'resize-window',
                '-t', self.name,
                '-x', str(width),
                '-y', str(height),
            ),
            check=False, env=_TMUX_ENV,  # not fatal — old tmux may not support resize-window
        )

    # ------------------------------------------------------------------
    # Input helpers
    # ------------------------------------------------------------------

    def send_keys(self, *keys: str) -> None:
        """Send one or more named key tokens to the session.

        Each element in *keys* is passed as a separate argument to
        ``tmux send-keys``.  Use this for special keys such as ``'Enter'``,
        ``'Escape'``, ``'Up'``, ``'Down'``, ``'NPage'``, ``'PPage'``, etc.,
        and for **single** printable characters (``'q'``, ``':'``, …).

        Do **not** use this for multi-character strings — tmux interprets the
        whole argument as a key *name* and will silently drop anything it does
        not recognise.  Use :meth:`send_literal` for that.
        """
        subprocess.run(
            tmux_cmd('send-keys', '-t', self.name) + list(keys),
            check=True, env=_TMUX_ENV,
        )

    def send_literal(self, text: str) -> None:
        """Send *text* character-by-character without any key-name interpretation.

        Uses ``tmux send-keys -l`` so every character in *text* is inserted
        into the pty buffer literally.  Always follow with
        ``send_keys('Enter')`` if a newline is required.
        """
        subprocess.run(
            tmux_cmd('send-keys', '-t', self.name, '-l', text),
            check=True, env=_TMUX_ENV,
        )

    # ------------------------------------------------------------------
    # Output helpers
    # ------------------------------------------------------------------

    def capture_pane(self) -> str:
        """Return the current visible content of the pane as a single string.

        Lines are joined with newlines; trailing whitespace on each line is
        preserved so column-position assertions remain meaningful.
        """
        result = subprocess.run(
            tmux_cmd('capture-pane', '-t', self.name, '-p'),
            check=True, env=_TMUX_ENV,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def wait_for(self, text: str, timeout: float = 5.0, interval: float = 0.1) -> None:
        """Poll ``capture_pane`` until *text* appears or *timeout* seconds pass.

        Both *timeout* and *interval* are multiplied by :data:`TIMEOUT_SCALE`
        so the whole suite can be slowed down on loaded hosts by exporting
        ``PING_BULK_TIMEOUT_SCALE`` without touching individual call sites.

        Raises :exc:`TimeoutError` if *text* is not found within the scaled timeout.
        """
        deadline = time.monotonic() + timeout * TIMEOUT_SCALE
        scaled_interval = interval * TIMEOUT_SCALE
        while time.monotonic() < deadline:
            if text in self.capture_pane():
                return
            time.sleep(scaled_interval)
        raise TimeoutError(
            f"Timed out after {timeout * TIMEOUT_SCALE:.1f}s waiting for {text!r} in pane {self.name!r}.\n"
            f"Last pane content:\n{self.capture_pane()}"
        )

    def wait_for_absence(self, text: str, timeout: float = 5.0, interval: float = 0.1) -> None:
        """Poll until *text* is **absent** from the pane or *timeout* passes.

        Both *timeout* and *interval* are multiplied by :data:`TIMEOUT_SCALE`.

        Raises :exc:`TimeoutError` if *text* is still present after the scaled timeout.
        """
        deadline = time.monotonic() + timeout * TIMEOUT_SCALE
        scaled_interval = interval * TIMEOUT_SCALE
        while time.monotonic() < deadline:
            if text not in self.capture_pane():
                return
            time.sleep(scaled_interval)
        raise TimeoutError(
            f"Timed out after {timeout * TIMEOUT_SCALE:.1f}s waiting for absence of {text!r} in pane {self.name!r}.\n"
            f"Last pane content:\n{self.capture_pane()}"
        )

    # ------------------------------------------------------------------
    # Window management
    # ------------------------------------------------------------------

    def resize(self, width: int, height: int) -> None:
        """Resize the tmux window to *width* × *height* characters.

        Updates ``self.width`` and ``self.height`` to reflect the new size.
        """
        self.width = width
        self.height = height
        subprocess.run(
            tmux_cmd(
                'resize-window',
                '-t', self.name,
                '-x', str(width),
                '-y', str(height),
            ),
            check=True, env=_TMUX_ENV,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def run_shell(self, cmd: str) -> None:
        """Type *cmd* at the pane's shell prompt and press Enter.

        **Every shell command typed into a pane goes through here**, and it is
        prefixed with a space so `hist_ignore_space` keeps it out of the
        developer's shell history.  That is the second of two layers — the
        session already runs with `ZDOTDIR` pointed at a directory holding
        nothing but an empty `.zshrc`, so no `HISTFILE` is assigned in the
        first place — because the space depends on a shell option a developer
        may not have set, and the `ZDOTDIR` trick is zsh-specific.  Neither one
        failing on its own leaks.

        Do **not** reach for :meth:`send_literal` to run a command: it is also
        how app keystrokes are typed (``send_literal('zC')``), so it cannot
        prepend anything of its own.
        """
        self.send_literal(' ' + cmd)
        self.send_keys('Enter')

    def start_app(self, args: list[str]) -> None:
        """Start the ping-bulk application with the given arguments."""
        self.run_shell(f"python3 {os.path.abspath('ping-bulk')} {' '.join(args)}")
        # Wait for the app to initialize
        self.wait_for('DNS:', timeout=10)

    def kill(self) -> None:
        """Kill the tmux session.  Safe to call even if already dead.

        Kills this session by name and nothing else.  Never ``tmux
        kill-server``: that ends *every* session the user has, including work
        that has nothing to do with the tests.
        """
        subprocess.run(
            tmux_cmd('kill-session', '-t', self.name),
            check=False, env=_TMUX_ENV,
        )
        cfgdir = getattr(self, '_cfgdir', None)
        if cfgdir:
            shutil.rmtree(cfgdir, ignore_errors=True)
            self._cfgdir = None
        _LIVE_SESSIONS.discard(self)

    def stop(self) -> None:
        self.kill()

