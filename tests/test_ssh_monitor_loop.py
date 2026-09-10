"""Unit tests for SshPingMonitor's read loop — D4.

The loop itself now lives in SubprocessMonitor and is shared with PingMonitor;
SshPingMonitor differs only in the command it builds, the fatal-error patterns it
recognises, and the fact that it does not trust ping's '-D' timestamp (that stamp
is written on the remote side, so only local receipt time is meaningful).

Strategy: back the subprocess with real OS pipes (`proc_helper.FakeProc`) so the
loop's select()/os.read() path is exercised for real.  The previous harness mocked
select() with scripted return values, which pinned the tests to one exact call
sequence and — more importantly — could not represent a child blocked writing to
a full stderr pipe, the bug this loop was rewritten to prevent.

`_STALE_SECS` is a class attribute, so stale-timeout tests lower it instead of
waiting the production 2 s.
"""

import threading
import time
from unittest.mock import patch

import pytest

from proc_helper import FakeProc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FATAL_STDERR_SSH = 'ssh: Permission denied (publickey)\n'
_FATAL_STDERR_PING = 'ping: name or service not known\n'

_REPLY = '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=%s ms\n'


def _ssh_monitor(pb, ping_host='10.0.0.1', ssh_dest='relay', relay_os='linux'):
    # relay_os is pinned: 'auto' (the production default) would probe the
    # relay with `uname -s` through subprocess.run, which these tests patch
    # at the Popen level — the detection probe would consume the FakeProc
    # meant for the monitor's own ping.  Detection has its own tests in
    # test_relay_os.py.
    return pb.SshPingMonitor([ssh_dest], ping_host, relay_os=relay_os)


def _run_ping(monitor, timeout=5.0):
    t = threading.Thread(target=monitor.ping, daemon=True)
    t.start()
    t.join(timeout)
    return t


def _make_fake_proc(stdout_lines, stderr_text=''):
    """Popen stand-in on real pipes; closing the write ends stands in for exit."""
    return FakeProc(stdout_lines=stdout_lines, stderr_text=stderr_text)


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestSshPingMonitorSuccessLine:

    def test_time_line_sets_alive_true(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc([_REPLY % '5.0'], stderr_text=_FATAL_STDERR_SSH)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.alive is True

    def test_time_line_sets_latency(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc([_REPLY % '8.8'], stderr_text=_FATAL_STDERR_SSH)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.latency == pytest.approx(8.8)

    def test_time_line_increments_rx_count(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc(
            ['[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=1.0 ms\n',
             '[1700000001.0] 64 bytes from 10.0.0.1: icmp_seq=2 ttl=64 time=2.0 ms\n'],
            stderr_text=_FATAL_STDERR_SSH,
        )
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.rx_count == 2

    def test_no_answer_line_defers_until_expiry(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc(['[1700000000.0] no answer yet for icmp_seq=1\n'],
                               stderr_text=_FATAL_STDERR_SSH)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.xx_count == 0, "outstanding, not yet lost"
        # This monitor stamps local receipt time rather than trusting ping's '-D',
        # so expiry is measured against the real clock, not the fixture's epoch.
        m._expire_pending(time.time() + 2.0, 1.0)
        assert m.xx_count == 1

    def test_records_latency_in_welford(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc([_REPLY % '10.0'], stderr_text=_FATAL_STDERR_SSH)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m._lat_count == 1
        assert m._lat_mean == pytest.approx(10.0)

    def test_remote_timestamp_is_not_trusted(self, pb):
        """The '-D' stamp comes from the remote clock; local receipt time is used."""
        m = _ssh_monitor(pb)
        proc = _make_fake_proc([_REPLY % '1.0'], stderr_text=_FATAL_STDERR_SSH)
        before = time.time()
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        stamps = [t for t in m.history_times]
        assert stamps and stamps[0] >= before, (
            "expected local receipt time, not the fixture's 1700000000.0")


class TestSshPingMonitorStaleTimeout:
    """No output for _STALE_SECS means the link is stuck, not that it is idle."""

    def test_stale_timeout_without_prior_output_no_synthetic_ping(self, pb):
        m = _ssh_monitor(pb)
        m._STALE_SECS = 0.1
        proc = FakeProc(close=False)          # silent, pipes stay open
        with patch('subprocess.Popen', return_value=proc):
            t = threading.Thread(target=m.ping, daemon=True)
            t.start()
            time.sleep(0.5)                   # several stale windows
            m.running = False
            proc.cleanup()
            t.join(5.0)
        assert None not in m.history, "a slow start must not be counted as loss"

    def test_stale_timeout_after_output_appends_synthetic_lost_ping(self, pb):
        m = _ssh_monitor(pb)
        m._STALE_SECS = 0.1
        proc = FakeProc(close=False)
        with patch('subprocess.Popen', return_value=proc):
            t = threading.Thread(target=m.ping, daemon=True)
            t.start()
            proc.feed_stdout(_REPLY % '1.0')
            assert _wait_for(lambda: m.rx_count == 1)
            assert _wait_for(lambda: None in m.history), "stale window should record a loss"
            m.running = False
            proc.cleanup()
            t.join(5.0)
        assert 1.0 in list(m.history)
        assert m.xx_count >= 1

    def test_stale_timeout_sets_alive_false(self, pb):
        m = _ssh_monitor(pb)
        m._STALE_SECS = 0.1
        proc = FakeProc(close=False)
        with patch('subprocess.Popen', return_value=proc):
            t = threading.Thread(target=m.ping, daemon=True)
            t.start()
            proc.feed_stdout(_REPLY % '1.0')
            assert _wait_for(lambda: m.rx_count == 1)
            assert _wait_for(lambda: m.alive is False)
            m.running = False
            proc.cleanup()
            t.join(5.0)


class TestSshPingMonitorFatalError:

    def test_ssh_fatal_stderr_stops_loop(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc([], stderr_text=_FATAL_STDERR_SSH)
        call_count = [0]

        def fake_popen(*a, **kw):
            call_count[0] += 1
            return proc

        with patch('subprocess.Popen', side_effect=fake_popen):
            _run_ping(m)
        assert call_count[0] == 1, "a fatal error must not be retried"
        assert m.error is not None

    def test_ping_fatal_stderr_stops_loop(self, pb):
        m = _ssh_monitor(pb)
        proc = _make_fake_proc([], stderr_text=_FATAL_STDERR_PING)
        with patch('subprocess.Popen', return_value=proc):
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
        proc = _make_fake_proc([], stderr_text=_FATAL_STDERR_SSH)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert 'ERR' in m.history


class TestSshPingMonitorNonFatalRetry:

    def test_non_fatal_exit_retries(self, pb):
        m = _ssh_monitor(pb)
        procs = [_make_fake_proc([], stderr_text=''),
                 _make_fake_proc([], stderr_text=_FATAL_STDERR_SSH)]
        idx = [0]

        def fake_popen(*a, **kw):
            p = procs[idx[0]]
            idx[0] += 1
            return p

        with patch('subprocess.Popen', side_effect=fake_popen):
            with patch('time.sleep'):
                _run_ping(m)
        assert idx[0] == 2, "a non-fatal exit should respawn the child"

    def test_stop_flag_respected_before_next_iteration(self, pb):
        m = _ssh_monitor(pb)
        proc = FakeProc(close=False)
        with patch('subprocess.Popen', return_value=proc):
            t = threading.Thread(target=m.ping, daemon=True)
            t.start()
            proc.feed_stdout(_REPLY % '1.0')
            assert _wait_for(lambda: m.rx_count == 1)
            m.running = False
            proc.feed_stdout('[1700000001.0] 64 bytes from 10.0.0.1: '
                             'icmp_seq=2 ttl=64 time=2.0 ms\n')
            t.join(5.0)
        assert not t.is_alive()
        assert m.rx_count == 1, "output after running=False must be ignored"
        proc.cleanup()
