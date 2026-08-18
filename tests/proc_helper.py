"""A Popen stand-in backed by real OS pipes.

The monitor loop selects on both pipes and reads raw fds, so a MagicMock cannot
stand in for the process any more — it has no fileno().  More importantly, the
previous MagicMock harness could not express the bug this replaced: a child that
fills the stderr pipe and blocks in write(2, ...) while the parent waits on
stdout.  Real pipes make that testable (see FakeProc.flood_stderr).

Usage::

    proc = FakeProc(stdout_lines=['[1700000000.0] ... time=2.0 ms\\n'],
                    stderr_text='ping: name or service not known\\n')
    with patch('subprocess.Popen', return_value=proc):
        run_ping(monitor)

Writing happens up front by default, which is fine while the payload stays under
one pipeful (64 KiB); `feed()` and `flood_stderr()` cover the larger cases.
"""

import os
import threading


class FakeProc:
    """Mimics the parts of Popen the monitor loop touches.

    Only `.stdout` / `.stderr` (for fileno), `.poll()`, `.wait()` and
    `.terminate()` are used, so the surface stays small on purpose.
    """

    def __init__(self, stdout_lines=(), stderr_text='', close=True,
                 returncode=0):
        self._out_r, self._out_w = os.pipe()
        self._err_r, self._err_w = os.pipe()
        # Read ends are handed to the monitor; it only calls fileno() on them.
        self.stdout = os.fdopen(self._out_r, 'rb', buffering=0)
        self.stderr = os.fdopen(self._err_r, 'rb', buffering=0)
        self._returncode = returncode
        self._closed = False
        self.terminated = False

        for line in stdout_lines:
            self.feed_stdout(line)
        if stderr_text:
            self.feed_stderr(stderr_text)
        if close:
            # EOF on both pipes is what ends the read loop, standing in for the
            # child exiting.  Without it the monitor would keep waiting.
            self.close_child_side()

    # ── writing as the "child" ────────────────────────────────────────────────

    def feed_stdout(self, text):
        os.write(self._out_w, text.encode() if isinstance(text, str) else text)

    def feed_stderr(self, text):
        os.write(self._err_w, text.encode() if isinstance(text, str) else text)

    def flood_stderr(self, total_bytes, chunk=b'ping: sendmsg: Network is unreachable\n'):
        """Write more than one pipeful to stderr, from a thread.

        The write blocks once the pipe fills, exactly as the real ping does — so
        this only completes if the monitor is actually draining stderr.  Returns
        the thread so a test can assert on whether it finished.
        """
        def _writer():
            written = 0
            try:
                while written < total_bytes:
                    written += os.write(self._err_w, chunk)
            except OSError:
                pass          # pipe closed under us — fine, the test is over
        t = threading.Thread(target=_writer, daemon=True)
        t.start()
        return t

    def close_child_side(self):
        """Signal EOF on both pipes (i.e. the child exited)."""
        if self._closed:
            return
        self._closed = True
        for fd in (self._out_w, self._err_w):
            try:
                os.close(fd)
            except OSError:
                pass

    # ── the Popen surface the monitor uses ───────────────────────────────────

    def poll(self):
        # "Exited" once the write ends are closed, which is how tests end a run.
        return self._returncode if self._closed else None

    def wait(self, timeout=None):
        return self._returncode

    def terminate(self):
        self.terminated = True
        self.close_child_side()

    kill = terminate

    def cleanup(self):
        self.close_child_side()
        for f in (self.stdout, self.stderr):
            try:
                f.close()
            except OSError:
                pass
