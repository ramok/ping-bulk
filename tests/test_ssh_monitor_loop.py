"""Unit tests for SshPingMonitor.ping() select()-based loop — D4.

SshPingMonitor differs from PingMonitor in two key ways:
  1. Uses select() with a 2s stale timeout instead of a blocking for-loop.
  2. When select() times out AND we previously had live output, a synthetic
     lost ping (None) is appended to history to prevent the display freezing.

Strategy: mock subprocess.Popen and the select.select() call so we can
feed controlled sequences of "data ready" / "timeout" events without
needing actual network or subprocesses.
"""

import io
import threading
import time
from unittest.mock import patch, MagicMock, call

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FATAL_STDERR_SSH = 'ssh: Permission denied (publickey)\n'
_FATAL_STDERR_PING = 'ping: name or service not known\n'


def _ssh_monitor(pb, ping_host='10.0.0.1', ssh_dest='relay'):
    return pb.SshPingMonitor([ssh_dest], ping_host)


def _run_ping(monitor, timeout=5.0):
    t = threading.Thread(target=monitor.ping, daemon=True)
    t.start()
    t.join(timeout)
    return t


def _make_fake_proc(readline_side_effect, stderr_text=''):
    """Build a mock Popen whose stdout.readline() follows a script."""
    proc = MagicMock()
    proc.stdout.readline.side_effect = readline_side_effect
    proc.stderr.read.return_value = stderr_text
    proc.wait.return_value = None
    proc.poll.return_value = None
    return proc


# ---------------------------------------------------------------------------
# select() helpers — build the sequence of (rlist, _, _) return values
# ---------------------------------------------------------------------------

def _ready(proc_stdout):
    """select() return indicating data is ready on stdout."""
    return ([proc_stdout], [], [])


def _timeout():
    """select() return indicating nothing is ready (stale timeout)."""
    return ([], [], [])


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSshPingMonitorSuccessLine:

    def test_time_line_sets_alive_true(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc(
            [
                '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=5.0 ms\n',
                '',  # EOF
            ],
            stderr_text=_FATAL_STDERR_SSH,
        )
        sel_returns = [_ready(proc.stdout), _ready(proc.stdout)]
        with patch('subprocess.Popen', return_value=proc):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        assert m.alive is True

    def test_time_line_sets_latency(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc(
            ['[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=8.8 ms\n', ''],
            stderr_text=_FATAL_STDERR_SSH,
        )
        sel_returns = [_ready(proc.stdout), _ready(proc.stdout)]
        with patch('subprocess.Popen', return_value=proc):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        assert m.latency == pytest.approx(8.8)

    def test_time_line_increments_rx_count(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc(
            [
                '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.0 ms\n',
                '[1700000001.0] 64 bytes from 10.0.0.1: icmp_seq=2 ttl=64 time=2.0 ms\n',
                '',
            ],
            stderr_text=_FATAL_STDERR_SSH,
        )
        sel_returns = [_ready(proc.stdout)] * 3
        with patch('subprocess.Popen', return_value=proc):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        assert m.rx_count == 2

    def test_no_answer_line_increments_xx_count(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc(
            [
                '[1700000000.0] no answer yet for icmp_seq=1\n',
                '',
            ],
            stderr_text=_FATAL_STDERR_SSH,
        )
        sel_returns = [_ready(proc.stdout), _ready(proc.stdout)]
        with patch('subprocess.Popen', return_value=proc):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        assert m.xx_count == 1

    def test_records_latency_in_welford(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc(
            ['[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=10.0 ms\n', ''],
            stderr_text=_FATAL_STDERR_SSH,
        )
        sel_returns = [_ready(proc.stdout), _ready(proc.stdout)]
        with patch('subprocess.Popen', return_value=proc):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        assert m._lat_count == 1
        assert m._lat_mean == pytest.approx(10.0)


class TestSshPingMonitorStaleTimeout:

    def test_stale_timeout_without_prior_output_no_synthetic_ping(self, pb):
        """select() timeout BEFORE any output → no synthetic ping appended."""
        m = _ssh_monitor(pb)
        proc = _make_fake_proc([''], stderr_text=_FATAL_STDERR_SSH)
        proc.poll.side_effect = [None, 0]  # first poll=running, second poll=exited
        sel_returns = [_timeout(), _ready(proc.stdout)]
        with patch('subprocess.Popen', return_value=proc):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        # No output before timeout, so no synthetic None should be in history
        assert None not in m.history

    def test_stale_timeout_after_output_appends_synthetic_lost_ping(self, pb):
        """select() timeout AFTER real output → synthetic None appended."""
        m = _ssh_monitor(pb)
        # Sequence: success line, then timeout, then EOF
        proc = _make_fake_proc(
            ['[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.0 ms\n', ''],
            stderr_text=_FATAL_STDERR_SSH,
        )
        proc.poll.side_effect = [None, None, 0]  # running, running, exited
        sel_returns = [
            _ready(proc.stdout),   # data: success line
            _timeout(),            # stale — should synthesise lost ping
            _ready(proc.stdout),   # EOF line
        ]
        with patch('subprocess.Popen', return_value=proc):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        hist = list(m.history)
        # success (1.0), synthetic lost (None), plus possibly ERR from fatal stderr
        assert 1.0 in hist
        assert None in hist
        assert m.xx_count >= 1

    def test_stale_timeout_sets_alive_false(self, pb):
        """After a synthetic lost ping, alive should be False."""
        m = _ssh_monitor(pb)
        proc = _make_fake_proc(
            ['[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.0 ms\n', ''],
            stderr_text=_FATAL_STDERR_SSH,
        )
        proc.poll.side_effect = [None, None, 0]
        sel_returns = [_ready(proc.stdout), _timeout(), _ready(proc.stdout)]
        with patch('subprocess.Popen', return_value=proc):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        # After the stale timeout the monitor should have marked alive=False
        # (it may later be overwritten if more output came, but here there's none)
        assert m.alive is False


class TestSshPingMonitorFatalError:

    def test_ssh_fatal_stderr_stops_loop(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc([''], stderr_text=_FATAL_STDERR_SSH)
        sel_returns = [_ready(proc.stdout)]
        call_count = [0]
        def fake_popen(*a, **kw):
            call_count[0] += 1
            return proc
        with patch('subprocess.Popen', side_effect=fake_popen):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        assert call_count[0] == 1
        assert m.error is not None

    def test_ping_fatal_stderr_stops_loop(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc([''], stderr_text=_FATAL_STDERR_PING)
        sel_returns = [_ready(proc.stdout)]
        with patch('subprocess.Popen', return_value=proc):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        assert m.error is not None
        assert 'ERR' in m.history

    def test_popen_exception_stops_loop(self, pb):
        m = _ssh_monitor(pb)
        with patch('subprocess.Popen', side_effect=FileNotFoundError('ssh not found')):
            _run_ping(m)
        assert m.error is not None
        assert 'ssh not found' in m.error

    def test_fatal_err_appended_to_history(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc([''], stderr_text=_FATAL_STDERR_SSH)
        sel_returns = [_ready(proc.stdout)]
        with patch('subprocess.Popen', return_value=proc):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        assert 'ERR' in m.history


class TestSshPingMonitorNonFatalRetry:

    def test_non_fatal_exit_retries(self, pb):
        m = _ssh_monitor(pb)
        procs = [
            _make_fake_proc([''], stderr_text=''),
            _make_fake_proc([''], stderr_text=_FATAL_STDERR_SSH),
        ]
        idx = [0]
        def fake_popen(*a, **kw):
            p = procs[idx[0]]
            idx[0] += 1
            return p
        sel_returns = [_ready(procs[0].stdout), _ready(procs[1].stdout)]
        with patch('subprocess.Popen', side_effect=fake_popen):
            with patch('select.select', side_effect=sel_returns):
                with patch('time.sleep'):
                    _run_ping(m)
        assert idx[0] == 2

    def test_stop_flag_respected_before_next_iteration(self, pb):
        m = _ssh_monitor(pb)

        def slow_readline():
            yield '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.0 ms\n'
            m.running = False
            yield ''  # EOF

        proc = MagicMock()
        proc.stdout.readline.side_effect = slow_readline()
        proc.stderr.read.return_value = ''
        proc.wait.return_value = None
        proc.poll.return_value = None

        sel_returns = [_ready(proc.stdout), _ready(proc.stdout)]
        with patch('subprocess.Popen', return_value=proc):
            with patch('select.select', side_effect=sel_returns):
                _run_ping(m)
        # Only one history entry (the success line before running=False)
        assert m.rx_count == 1
