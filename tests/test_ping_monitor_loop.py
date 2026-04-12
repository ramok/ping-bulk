"""Unit tests for PingMonitor.ping() subprocess loop — D2.

Strategy: mock subprocess.Popen so that stdout yields controlled lines,
then stderr returns a fatal error to terminate the retry loop cleanly.
This lets us run ping() synchronously (in a thread we join) without
waiting for backoff delays.

Covered behaviours
------------------
- Successful reply ('time=') updates history, alive, rx_count, latency
- Timeout line ('no answer yet') updates history, alive=False, xx_count
- '-D' timestamp prefix is stripped and stored in history_times
- Fatal stderr stops the loop (error set, 'ERR' appended to history)
- Non-fatal exit is retried (second Popen is called)
- monitor.running = False stops the loop mid-iteration
- Subprocess Popen failure sets error and stops loop immediately
- Backoff doubles on each empty-output exit (capped at 30s)
"""

import io
import threading
import time
from unittest.mock import patch, MagicMock

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fake_proc(stdout_lines, stderr_text=''):
    """Return a MagicMock that mimics a Popen object."""
    proc = MagicMock()
    # stdout is iterated line-by-line in ping()
    proc.stdout = iter(stdout_lines)
    proc.stderr.read.return_value = stderr_text
    proc.wait.return_value = None
    proc.poll.return_value = None
    return proc


_FATAL_STDERR = 'ping: name or service not known\n'


def _run_ping(monitor, timeout=3.0):
    """Run monitor.ping() in a background thread; join within *timeout* s."""
    t = threading.Thread(target=monitor.ping, daemon=True)
    t.start()
    t.join(timeout)
    return t


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPingMonitorSuccessLine:

    def test_time_line_sets_alive_true(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=3.7 ms\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.alive is True

    def test_time_line_sets_latency(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=12.3 ms\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.latency == pytest.approx(12.3)

    def test_time_line_increments_rx_count(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.0 ms\n',
            '[1700000001.0] 64 bytes from 10.0.0.1: icmp_seq=2 ttl=64 time=2.0 ms\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.rx_count == 2

    def test_time_line_appends_latency_to_history(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=5.5 ms\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert 5.5 in m.history

    def test_timestamp_prefix_stored_in_history_times(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000042.5] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.0 ms\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert any(abs(t - 1700000042.5) < 0.01 for t in m.history_times)

    def test_increments_ping_count(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.0 ms\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.ping_count == 1

    def test_records_latency_in_welford(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=10.0 ms\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m._lat_count == 1
        assert m._lat_mean == pytest.approx(10.0)


class TestPingMonitorTimeoutLine:

    def test_no_answer_sets_alive_false(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] no answer yet for icmp_seq=1\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.alive is False

    def test_no_answer_sets_latency_none(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] no answer yet for icmp_seq=1\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.latency is None

    def test_no_answer_increments_xx_count(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] no answer yet for icmp_seq=1\n',
            '[1700000001.0] no answer yet for icmp_seq=2\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.xx_count == 2

    def test_no_answer_appends_none_to_history(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] no answer yet for icmp_seq=1\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert None in m.history


class TestPingMonitorFatalError:

    def test_fatal_stderr_sets_error(self, pb):
        m = pb.PingMonitor('badhost')
        proc = _make_fake_proc([], stderr_text='ping: badhost: Name or service not known\n')
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.error is not None
        assert 'not known' in m.error.lower()

    def test_fatal_stderr_appends_err_to_history(self, pb):
        m = pb.PingMonitor('badhost')
        proc = _make_fake_proc([], stderr_text='ping: badhost: Name or service not known\n')
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert 'ERR' in m.history

    def test_fatal_stderr_stops_loop(self, pb):
        """After a fatal error the monitor should not call Popen again."""
        m = pb.PingMonitor('badhost')
        proc = _make_fake_proc([], stderr_text='ping: badhost: Name or service not known\n')
        call_count = []
        def fake_popen(*a, **kw):
            call_count.append(1)
            return proc
        with patch('subprocess.Popen', side_effect=fake_popen):
            _run_ping(m)
        assert len(call_count) == 1

    def test_popen_exception_sets_error(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        with patch('subprocess.Popen', side_effect=FileNotFoundError('ping not found')):
            _run_ping(m)
        assert m.error is not None
        assert 'ping not found' in m.error


class TestPingMonitorNonFatalRetry:

    def test_non_fatal_exit_retries_popen(self, pb):
        """Empty stdout + empty stderr → not fatal; expect a second Popen call."""
        m = pb.PingMonitor('10.0.0.1')
        procs = [
            _make_fake_proc([], stderr_text=''),
            _make_fake_proc([], stderr_text='ping: 10.0.0.1: Network is unreachable\n'),
        ]
        idx = [0]
        def fake_popen(*a, **kw):
            p = procs[idx[0]]
            idx[0] += 1
            return p
        with patch('subprocess.Popen', side_effect=fake_popen):
            with patch('time.sleep'):  # skip backoff delay
                _run_ping(m)
        assert idx[0] == 2  # Popen called twice

    def test_backoff_doubles_on_empty_output(self, pb):
        """Each empty-stdout exit should double the sleep duration."""
        m = pb.PingMonitor('10.0.0.1')
        sleep_calls = []
        # 3 empty exits then fatal
        procs = [
            _make_fake_proc([], stderr_text=''),
            _make_fake_proc([], stderr_text=''),
            _make_fake_proc([], stderr_text=''),
            _make_fake_proc([], stderr_text='ping: name or service not known\n'),
        ]
        idx = [0]
        def fake_popen(*a, **kw):
            p = procs[idx[0]]
            idx[0] += 1
            return p
        with patch('subprocess.Popen', side_effect=fake_popen):
            with patch('time.sleep', side_effect=lambda s: sleep_calls.append(s)):
                _run_ping(m)
        # backoff sequence: 1 → 2 → 4
        assert sleep_calls == [1, 2, 4]

    def test_backoff_resets_after_output(self, pb):
        """Receiving output resets the backoff back to 1s."""
        m = pb.PingMonitor('10.0.0.1')
        sleep_calls = []
        procs = [
            # First run: produces output → backoff resets to 1
            _make_fake_proc(
                ['[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.0 ms\n'],
                stderr_text='',
            ),
            # Second run: empty → backoff penalty
            _make_fake_proc([], stderr_text=''),
            # Third run: fatal → stop
            _make_fake_proc([], stderr_text='ping: name or service not known\n'),
        ]
        idx = [0]
        def fake_popen(*a, **kw):
            p = procs[idx[0]]
            idx[0] += 1
            return p
        with patch('subprocess.Popen', side_effect=fake_popen):
            with patch('time.sleep', side_effect=lambda s: sleep_calls.append(s)):
                _run_ping(m)
        # After first run (got output), backoff was reset to 1.
        # After second run (no output), sleep(1) then next retry → fatal → sleep(2).
        assert sleep_calls[0] == 1  # reset after output → first sleep is 1

    def test_backoff_capped_at_30(self, pb):
        """Backoff never exceeds 30 seconds."""
        m = pb.PingMonitor('10.0.0.1')
        sleep_calls = []
        # 8 empty exits: 1, 2, 4, 8, 16, 30, 30, 30  then fatal
        procs = [_make_fake_proc([], stderr_text='') for _ in range(8)]
        procs.append(_make_fake_proc([], stderr_text='ping: name or service not known\n'))
        idx = [0]
        def fake_popen(*a, **kw):
            p = procs[idx[0]]
            idx[0] = min(idx[0] + 1, len(procs) - 1)
            return p
        with patch('subprocess.Popen', side_effect=fake_popen):
            with patch('time.sleep', side_effect=lambda s: sleep_calls.append(s)):
                _run_ping(m)
        assert max(sleep_calls) == 30


class TestPingMonitorStopWhileRunning:

    def test_stop_flag_exits_loop(self, pb):
        """Setting running=False mid-loop causes ping() to exit cleanly."""
        m = pb.PingMonitor('10.0.0.1')

        def slow_stdout():
            yield '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.0 ms\n'
            m.running = False
            yield '[1700000001.0] 64 bytes from 10.0.0.1: icmp_seq=2 ttl=64 time=2.0 ms\n'

        proc = MagicMock()
        proc.stdout = slow_stdout()
        proc.stderr.read.return_value = ''
        proc.wait.return_value = None

        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m, timeout=5.0)

        # Should only have one history entry (second line not processed)
        assert len(m.history) == 1

    def test_mixed_success_then_timeout(self, pb):
        """History tracks both success and timeout lines correctly."""
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=2.0 ms\n',
            '[1700000001.0] no answer yet for icmp_seq=2\n',
            '[1700000002.0] 64 bytes from 10.0.0.1: icmp_seq=3 ttl=64 time=3.0 ms\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        hist = list(m.history)
        assert hist[:3] == [2.0, None, 3.0]
        assert m.rx_count == 2
        assert m.xx_count == 1
