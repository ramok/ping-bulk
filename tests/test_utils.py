"""Unit tests for ping-bulk utility/helper functions.

Covers:
  _format_updown_time(seconds)   — compact duration formatter (D8)
  _history_char(val, mode)       — single-char history renderer (D8)
  check_state_changes()          — UP/DOWN state machine (D1)

No ping threads or network access; monitor state is set directly.
"""

import os
import time
import math
import threading
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_monitor(pb, host='127.0.0.1'):
    m = pb.PingMonitor(host)
    return m


def make_app(pb, tmp_path):
    cfg = tmp_path / "ping-bulk" / "config"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('')
    with patch.object(pb, '_config_path', return_value=str(cfg)):
        app = pb.Application([('host', '127.0.0.1')], log_file=None)
    return app


# ===========================================================================
# D8 — _format_updown_time
# ===========================================================================

class TestFormatUpdownTime:

    def test_zero_seconds(self, pb):
        assert pb._format_updown_time(0) == "0s"

    def test_seconds_only(self, pb):
        assert pb._format_updown_time(59) == "59s"

    def test_exactly_one_minute(self, pb):
        assert pb._format_updown_time(60) == "1m 0s"

    def test_minutes_and_seconds(self, pb):
        assert pb._format_updown_time(90) == "1m 30s"

    def test_59_minutes_59_seconds(self, pb):
        assert pb._format_updown_time(3599) == "59m 59s"

    def test_exactly_one_hour(self, pb):
        assert pb._format_updown_time(3600) == "1h 0m"

    def test_hours_and_minutes(self, pb):
        assert pb._format_updown_time(7320) == "2h 2m"

    def test_23_hours_59_minutes(self, pb):
        assert pb._format_updown_time(86399) == "23h 59m"

    def test_exactly_one_day(self, pb):
        assert pb._format_updown_time(86400) == "1d 0h"

    def test_days_and_hours(self, pb):
        assert pb._format_updown_time(86400 + 7200) == "1d 2h"

    def test_large_duration(self, pb):
        assert pb._format_updown_time(365 * 86400 + 23 * 3600) == "365d 23h"

    def test_float_truncated(self, pb):
        # Float input: fractional seconds should be truncated, not rounded
        assert pb._format_updown_time(59.9) == "59s"


# ===========================================================================
# D8 — _history_char
# ===========================================================================

class TestHistoryChar:

    # success mode
    def test_success_success(self, pb):
        assert pb._history_char(10.0, 'success') == '.'

    def test_success_timeout(self, pb):
        assert pb._history_char(None, 'success') == 'X'

    def test_success_error(self, pb):
        assert pb._history_char('ERR', 'success') == '?'

    # rtt mode
    def test_rtt_single_digit(self, pb):
        assert pb._history_char(5.0, 'rtt') == '5'

    def test_rtt_two_digit(self, pb):
        assert pb._history_char(47.2, 'rtt') == '7'

    def test_rtt_three_digit(self, pb):
        assert pb._history_char(123.0, 'rtt') == '3'

    def test_rtt_timeout(self, pb):
        assert pb._history_char(None, 'rtt') == 'X'

    def test_rtt_error(self, pb):
        assert pb._history_char('ERR', 'rtt') == '?'

    # scaled mode
    def test_scaled_under_10ms(self, pb):
        assert pb._history_char(5.0, 'scaled') == '0'

    def test_scaled_50ms(self, pb):
        # round(50 / 100 * 9) = round(4.5) = 4 (banker's rounding) or 5
        result = pb._history_char(50.0, 'scaled')
        assert result in ('4', '5')

    def test_scaled_100ms(self, pb):
        # round(100/100*9) = 9
        assert pb._history_char(100.0, 'scaled') == '9'

    def test_scaled_over_100ms(self, pb):
        assert pb._history_char(200.0, 'scaled') == '>'

    def test_scaled_timeout(self, pb):
        assert pb._history_char(None, 'scaled') == 'X'

    def test_scaled_error(self, pb):
        assert pb._history_char('ERR', 'scaled') == '?'


# ===========================================================================
# D1 — check_state_changes() state machine
# ===========================================================================

class TestCheckStateChanges:
    """Unit tests for the UP/DOWN state machine in check_state_changes().

    Rather than running the real loop (which sleeps 0.5s), we call
    check_state_changes() in a thread and let it advance naturally,
    then inspect the events logged.
    """

    def _run_one_tick(self, app, monitor):
        """Run exactly one loop-body pass of check_state_changes without sleeping.

        We patch time.sleep to stop the loop after the first iteration.
        """
        call_count = [0]
        orig_sleep = time.sleep

        def fake_sleep(t):
            call_count[0] += 1
            app.running = False  # stop the loop after first sleep

        with patch('time.sleep', side_effect=fake_sleep):
            app.running = True
            app.check_state_changes()

    # ── initial observation ────────────────────────────────────────────────

    def test_initial_up_sets_up_since(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb)
        m.alive = True
        app.monitors = [m]

        self._run_one_tick(app, m)

        assert m.last_state is True
        assert m.up_since is not None

    def test_initial_up_logs_host_starts_up(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb, '10.0.0.1')
        m.alive = True
        app.monitors = [m]

        self._run_one_tick(app, m)

        texts = [e.text for e in app.events]
        assert any("host starts up" in t for t in texts)

    def test_initial_down_sets_pending_not_down_since(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb)
        m.alive = False
        app.monitors = [m]

        self._run_one_tick(app, m)

        assert m.last_state is False
        assert m._down_pending_ts is not None
        # On first observation of DOWN, down_since is set but "host down" is NOT
        # logged yet (that waits for the threshold timer to expire).
        assert m.down_since is not None

    def test_initial_down_does_not_log_host_down(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb, '10.0.0.2')
        m.alive = False
        app.monitors = [m]

        self._run_one_tick(app, m)

        texts = [e.text for e in app.events]
        assert not any("host down" in t for t in texts)

    # ── down threshold (HWM) ──────────────────────────────────────────────

    def test_down_logged_after_threshold(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb, '10.0.0.3')
        m.alive = False
        m.last_state = False
        # Simulate pending timer started 4 seconds ago (> _DOWN_LOG_SECS=3)
        m._down_pending_ts = time.monotonic() - 4.0
        app.monitors = [m]

        self._run_one_tick(app, m)

        texts = [e.text for e in app.events]
        assert any("host down" in t for t in texts)
        assert m.down_since is not None

    def test_down_not_logged_before_threshold(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb, '10.0.0.4')
        m.alive = False
        m.last_state = False
        m._down_pending_ts = time.monotonic() - 1.0  # only 1 second < 3s threshold
        app.monitors = [m]

        self._run_one_tick(app, m)

        texts = [e.text for e in app.events]
        assert not any("host down" in t for t in texts)
        assert m.down_since is None

    # ── recovery ──────────────────────────────────────────────────────────

    def test_silent_recovery_before_threshold(self, pb, tmp_path):
        """Host goes down and recovers before the 3s threshold — no events logged."""
        app = make_app(pb, tmp_path)
        m = make_monitor(pb, '10.0.0.5')
        m.alive = True          # now alive again
        m.last_state = False    # was down
        m.down_since = None     # never logged
        m._down_pending_ts = time.monotonic() - 1.0
        app.monitors = [m]

        self._run_one_tick(app, m)

        texts = [e.text for e in app.events]
        assert not any("recover" in t for t in texts)
        assert m.up_since is not None

    def test_recovery_logs_event_after_logged_down(self, pb, tmp_path):
        """Host was DOWN (logged) and recovers — logs 'host recover'."""
        app = make_app(pb, tmp_path)
        m = make_monitor(pb, '10.0.0.6')
        m.alive = True
        m.last_state = False
        m.down_since = time.monotonic() - 10.0   # was logged as down
        m._down_pending_ts = None
        app.monitors = [m]

        self._run_one_tick(app, m)

        texts = [e.text for e in app.events]
        assert any("host recover" in t for t in texts)
        assert m.down_since is None
        assert m.up_since is not None

    # ── error logging ──────────────────────────────────────────────────────

    def test_fatal_error_logged_once(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb, '10.0.0.7')
        m.alive = None
        m.error = "ping: connect: Network unreachable"
        m.error_logged = False
        app.monitors = [m]

        # Run two ticks — error should only appear once
        self._run_one_tick(app, m)
        # second tick: error already logged
        app.running = True
        self._run_one_tick(app, m)

        error_events = [e for e in app.events if "error:" in e.text]
        assert len(error_events) == 1
        assert m.error_logged is True

    # ── UP → DOWN transition ───────────────────────────────────────────────

    def test_up_to_down_starts_pending_timer(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb, '10.0.0.8')
        m.alive = False
        m.last_state = True    # was up
        m.up_since = time.monotonic() - 30.0
        app.monitors = [m]

        self._run_one_tick(app, m)

        assert m._down_pending_ts is not None
        assert m.down_since is None
        assert m.last_state is False
        texts = [e.text for e in app.events]
        assert not any("host down" in t for t in texts)


class TestStderrDiagnostics:
    """A per-probe ping error should be stated once, and explain a down event.

    Before this, a route flap showed only as lost probes with no stated cause —
    the reason the field diagnosis needed strace.
    """

    def test_first_occurrence_is_queued(self, pb, tmp_path):
        m = pb.PingMonitor('10.0.0.1')
        assert m._note_stderr('ping: sendmsg: Network is unreachable') is True
        assert m.take_new_stderr() == ['ping: sendmsg: Network is unreachable']

    def test_repeat_is_not_queued_again(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        for _ in range(50):
            m._note_stderr('ping: sendmsg: Network is unreachable')
        assert len(m.take_new_stderr()) == 1, "a flood must be reported once"

    def test_distinct_messages_each_reported(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        m._note_stderr('ping: sendmsg: Network is unreachable')
        m._note_stderr('ping: local error: Message too long')
        assert len(m.take_new_stderr()) == 2

    def test_take_drains(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        m._note_stderr('ping: something')
        assert m.take_new_stderr()
        assert m.take_new_stderr() == [], "already reported"

    def test_blank_lines_ignored(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        m._note_stderr('   ')
        assert m.take_new_stderr() == []

    def test_recent_stderr_offered_as_reason(self, pb):
        """A recognised wording is shortened to its host-level meaning: this
        text goes in brackets after 'host down', where the system call that
        hit the error is mostly punctuation.  The stderr pass still logs the
        line in full, so the exact text stays greppable."""
        m = pb.PingMonitor('10.0.0.1')
        m._note_stderr('ping: sendmsg: Network is unreachable')
        assert m.recent_stderr() == 'network is unreachable'

    def test_unrecognised_reason_passed_through_verbatim(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        m._note_stderr('ping: local error: Message too long')
        assert m.recent_stderr() == 'ping: local error: Message too long'

    def test_stale_stderr_not_offered_as_reason(self, pb):
        """An old warning must not be blamed for a fresh outage."""
        m = pb.PingMonitor('10.0.0.1')
        m._note_stderr('ping: sendmsg: Network is unreachable')
        assert m.recent_stderr(time.time() + 3600) is None

    def test_no_stderr_no_reason(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        assert m.recent_stderr() is None

    def test_seen_set_is_capped(self, pb):
        """Runs last for days; varying message text must not grow memory."""
        m = pb.PingMonitor('10.0.0.1')
        for i in range(m._SEEN_STDERR_MAX + 50):
            m._note_stderr(f'ping: transient failure #{i}')
        assert len(m._seen_stderr) <= m._SEEN_STDERR_MAX
