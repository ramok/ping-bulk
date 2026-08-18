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

    def test_no_answer_alone_does_not_mark_down(self, pb):
        """'-O' means "no answer yet" — the probe is outstanding, not lost.

        Deciding at once is what made a host slower than the ping interval
        oscillate between up and down every second.
        """
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] no answer yet for icmp_seq=1\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.alive is None, "must not be marked down before the grace expires"
        assert m.xx_count == 0
        assert None not in m.history, "no timeout cell yet"
        assert 1 in m._pending

    def test_expired_probe_sets_alive_false(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] no answer yet for icmp_seq=1\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        m._expire_pending(1700000001.5, 1.0)
        assert m.alive is False
        assert m._pending == {}

    def test_no_answer_sets_latency_none(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] no answer yet for icmp_seq=1\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.latency is None

    def test_expired_probes_increment_xx_count(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] no answer yet for icmp_seq=1\n',
            '[1700000001.0] no answer yet for icmp_seq=2\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.xx_count == 0, "nothing counted while the probes are outstanding"
        m._expire_pending(1700000002.5, 1.0)
        assert m.xx_count == 2
        assert m.ping_count == 2, "each probe counted once, not twice"

    def test_expired_probe_appends_none_to_history(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        lines = [
            '[1700000000.0] no answer yet for icmp_seq=1\n',
        ]
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert None not in m.history, "no cell until the probe is written off"
        m._expire_pending(1700000001.5, 1.0)
        assert None in m.history

    def test_no_seq_falls_back_to_immediate_loss(self, pb):
        """Without a seq there is nothing to reconcile later, so fail closed."""
        m = pb.PingMonitor('10.0.0.1')
        lines = ['[1700000000.0] no answer yet\n']
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        assert m.alive is False
        assert m.xx_count == 1
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
        # seq 2 is still outstanding: its cell appears only once written off.
        assert list(m.history)[:2] == [2.0, 3.0]
        assert m.rx_count == 2
        assert m.xx_count == 0
        m._expire_pending(1700000003.5, 1.0)
        assert None in m.history
        assert m.xx_count == 1


# ---------------------------------------------------------------------------
# Late replies — a host whose RTT exceeds the ping interval
# ---------------------------------------------------------------------------

class TestLateReply:
    """`ping -O` reports "no answer yet" once the interval elapses, so a host
    slower than the interval emits BOTH lines for every probe.  Counting them
    independently made one probe register as a failure *and* a success: 50 %
    loss on a host losing nothing, doubled tx, and a 1 Hz up/down oscillation.
    """

    # One probe, answered 206 ms after the '-O' deadline.
    LATE_PAIR = [
        '[1700000001.000] no answer yet for icmp_seq=7\n',
        '[1700000001.206] 64 bytes from 10.0.0.1: icmp_seq=7 ttl=63 time=1206 ms\n',
    ]

    def _run(self, pb, lines):
        m = pb.PingMonitor('10.0.0.1')
        proc = _make_fake_proc(lines, stderr_text=_FATAL_STDERR)
        with patch('subprocess.Popen', return_value=proc):
            _run_ping(m)
        return m

    def test_late_reply_yields_one_cell(self, pb):
        m = self._run(pb, self.LATE_PAIR)
        cells = [v for v in m.history if v != 'ERR']
        assert len(cells) == 1, f"one probe must leave one cell, got {cells}"

    def test_late_cell_is_marked_late(self, pb):
        m = self._run(pb, self.LATE_PAIR)
        cell = [v for v in m.history if v != 'ERR'][0]
        assert pb._hist_is_late(cell)
        assert pb._hist_rtt(cell) == 1206.0, "the measured RTT must survive"

    def test_late_reply_counts_as_success_not_loss(self, pb):
        m = self._run(pb, self.LATE_PAIR)
        assert m.rx_count == 1
        assert m.xx_count == 0

    def test_no_double_count_of_tx(self, pb):
        """ping_count was incremented by BOTH lines for a single probe."""
        m = self._run(pb, self.LATE_PAIR)
        assert m.ping_count == 1

    def test_loss_percent_is_zero(self, pb):
        """Loss% is xx/(rx+xx) — a zero-loss host used to report 50 %."""
        m = self._run(pb, self.LATE_PAIR * 4)
        assert m.xx_count == 0
        assert m.rx_count == 4
        loss = m.xx_count / (m.rx_count + m.xx_count) * 100
        assert loss == 0.0

    def test_alive_never_goes_false(self, pb):
        """The flapping regression: `alive` must not dip between the two lines."""
        m = self._run(pb, self.LATE_PAIR * 3)
        assert m.alive is True
        assert m._pending == {}, "every probe was answered; none left outstanding"

    def test_latency_reflects_the_late_reply(self, pb):
        m = self._run(pb, self.LATE_PAIR)
        assert m.latency == 1206.0

    def test_late_rtt_feeds_the_stats(self, pb):
        m = self._run(pb, self.LATE_PAIR)
        assert m.lat_avg == 1206.0

    def test_success_mode_renders_lowercase_x(self, pb):
        m = self._run(pb, self.LATE_PAIR)
        assert pb._history_char(-1206.0, 'success') == 'x'
        assert pb._history_char(1206.0, 'success') == '.'

    def test_rtt_mode_shows_the_number_not_a_glyph(self, pb):
        """Late cells keep their RTT, so rtt/scaled still read as measurements."""
        assert pb._history_char(-1206.0, 'rtt') == pb._history_char(1206.0, 'rtt')
        assert pb._history_char(-42.0, 'scaled') == pb._history_char(42.0, 'scaled')

    def test_wide_cell_renders_magnitude(self, pb):
        """The wide-cell path formats int(round(val)); a negative would break it."""
        m = pb.PingMonitor('10.0.0.1')
        with m.lock:
            m.history.append(-1206.0)
            m.history_times.append(1700000001.0)
        out = m.get_history_string(length=1, mode='rtt', cell_width=5)
        assert '1206' in out, out
        assert '-' not in out

    def test_on_time_reply_is_not_marked_late(self, pb):
        m = self._run(pb, [
            '[1700000000.0] 64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=2.0 ms\n',
        ])
        cell = [v for v in m.history if v != 'ERR'][0]
        assert not pb._hist_is_late(cell)
        assert cell == 2.0

    def test_unrelated_seq_does_not_clear_a_pending_probe(self, pb):
        """A reply for seq 9 must not resolve an outstanding seq 7."""
        m = self._run(pb, [
            '[1700000001.0] no answer yet for icmp_seq=7\n',
            '[1700000002.0] 64 bytes from 10.0.0.1: icmp_seq=9 ttl=64 time=3.0 ms\n',
        ])
        assert 7 in m._pending
        cells = [v for v in m.history if v != 'ERR']
        assert cells == [3.0], "seq 9 lands on time; seq 7 is still outstanding"


class TestWorstHistoryCharLate:

    def test_late_ranks_between_lost_and_ok(self, pb):
        w = pb.Application._worst_history_char
        assert w(['.', 'x']) == 'x'
        assert w(['x', 'X']) == 'X'
        assert w(['x', '?']) == '?'
        assert w(['.', '.']) == '.'
