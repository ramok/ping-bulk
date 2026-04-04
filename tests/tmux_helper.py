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

import subprocess
import time


class TmuxSession:
    """Manage a single detached tmux session for integration testing."""

    def __init__(self, name: str, width: int = 120, height: int = 40):
        import uuid
        # Always use a unique session ID by appending a uuid
        self.name = f"{name}-{uuid.uuid4().hex[:8]}"
        self.width = width
        self.height = height

        # Kill any stale session with this name left over from a previous
        # test run that crashed without cleanup.
        stale = subprocess.run(
            ['tmux', 'has-session', '-t', self.name],
            check=False,
        )
        if stale.returncode == 0:
            subprocess.run(['tmux', 'kill-session', '-t', self.name], check=False)

        # Create a new detached session with the requested dimensions.
        subprocess.run(
            [
                'tmux', 'new-session',
                '-d',            # detached
                '-s', self.name,
                '-x', str(width),
                '-y', str(height),
            ],
            check=True,
        )

        # Explicitly resize the window after creation to handle older tmux
        # versions that may ignore the -x/-y flags on new-session.
        subprocess.run(
            [
                'tmux', 'resize-window',
                '-t', self.name,
                '-x', str(width),
                '-y', str(height),
            ],
            check=False,  # not fatal — old tmux may not support resize-window
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
            ['tmux', 'send-keys', '-t', self.name] + list(keys),
            check=True,
        )

    def send_literal(self, text: str) -> None:
        """Send *text* character-by-character without any key-name interpretation.

        Uses ``tmux send-keys -l`` so every character in *text* is inserted
        into the pty buffer literally.  Always follow with
        ``send_keys('Enter')`` if a newline is required.
        """
        subprocess.run(
            ['tmux', 'send-keys', '-t', self.name, '-l', text],
            check=True,
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
            ['tmux', 'capture-pane', '-t', self.name, '-p'],
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout

    def wait_for(self, text: str, timeout: float = 5.0, interval: float = 0.1) -> None:
        """Poll ``capture_pane`` until *text* appears or *timeout* seconds pass.

        Raises :exc:`TimeoutError` if *text* is not found within *timeout*.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if text in self.capture_pane():
                return
            time.sleep(interval)
        raise TimeoutError(
            f"Timed out after {timeout}s waiting for {text!r} in pane {self.name!r}.\n"
            f"Last pane content:\n{self.capture_pane()}"
        )

    def wait_for_absence(self, text: str, timeout: float = 5.0, interval: float = 0.1) -> None:
        """Poll until *text* is **absent** from the pane or *timeout* passes.

        Raises :exc:`TimeoutError` if *text* is still present after *timeout*.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if text not in self.capture_pane():
                return
            time.sleep(interval)
        raise TimeoutError(
            f"Timed out after {timeout}s waiting for absence of {text!r} in pane {self.name!r}.\n"
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
            [
                'tmux', 'resize-window',
                '-t', self.name,
                '-x', str(width),
                '-y', str(height),
            ],
            check=True,
        )

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()

    def start_app(self, args: list[str]) -> None:
        """Start the ping-bulk application with the given arguments."""
        import os
        self.send_keys(f"python3 {os.path.abspath('ping-bulk')} {' '.join(args)}")
        self.send_keys("Enter")
        # Give the app a moment to start
        time.sleep(0.5)

    def kill(self) -> None:
        """Kill the tmux session.  Safe to call even if already dead."""
        subprocess.run(
            ['tmux', 'kill-session', '-t', self.name],
            check=False,
        )

    def stop(self) -> None:
        self.kill()

