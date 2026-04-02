"""Unit tests for ping-bulk statistics and uptime display functions.

Covers:
  _format_updown_time(seconds)
  Application._compute_updown(monitor)
  Application._compute_stat(monitor, mode)
  Application._compute_all_stats(monitor)
  Application._updown_col_width()

No ping threads are started; PingMonitor state is set directly on attributes.
The real config file (~/.config/ping-bulk/) is never touched — _config_path()
is patched to a temporary directory for every Application instance created.

Fixtures
--------
pb
    The ping-bulk module, imported once for the whole test session via
    SourceFileLoader (the script has no .py extension).
"""

import math
import os
import time
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helper: build a minimal Application without touching the real config
# ---------------------------------------------------------------------------

def make_app(pb, cfg_path, entries=None):
    """Return a non-running Application with _config_path() patched to cfg_path."""
    if entries is None:
        entries = [('host', '127.0.0.1')]
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    # Write an empty config so _load_config() finds a file but changes nothing.
    with open(cfg_path, 'w') as f:
        f.write('')
    with patch.object(pb, '_config_path', return_value=cfg_path):
        app = pb.Application(entries, log_file=None)
    return app


def make_monitor(pb, host='127.0.0.1', **attrs):
    """Return a PingMonitor with the given attributes set directly."""
    m = pb.PingMonitor(host)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ===========================================================================
# TestFormatUpdownTime
# ===========================================================================

class TestFormatUpdownTime:
    """_format_updown_time(seconds) formats durations into compact strings."""

    def test_zero_seconds(self, pb):
        assert pb._format_updown_time(0) == '0s'

    def test_one_second(self, pb):
        assert pb._format_updown_time(1) == '1s'

    def test_59_seconds(self, pb):
        assert pb._format_updown_time(59) == '59s'

    def test_60_seconds_is_one_minute(self, pb):
        assert pb._format_updown_time(60) == '1m 0s'

    def test_90_seconds(self, pb):
        assert pb._format_updown_time(90) == '1m 30s'

    def test_3599_seconds(self, pb):
        # 59 min 59 sec — still in the m/s format
        assert pb._format_updown_time(3599) == '59m 59s'

    def test_3600_seconds_is_one_hour(self, pb):
        assert pb._format_updown_time(3600) == '1h 0m'

    def test_5400_seconds(self, pb):
        # 1 h 30 m
        assert pb._format_updown_time(5400) == '1h 30m'

    def test_86399_seconds(self, pb):
        # 23 h 59 m — still in the h/m format
        assert pb._format_updown_time(86399) == '23h 59m'

    def test_86400_seconds_is_one_day(self, pb):
        assert pb._format_updown_time(86400) == '1d 0h'

    def test_90000_seconds(self, pb):
        # 1 d 1 h
        assert pb._format_updown_time(90000) == '1d 1h'

    def test_365_days(self, pb):
        seconds = 365 * 86400 + 23 * 3600
        assert pb._format_updown_time(seconds) == '365d 23h'

    def test_fractional_seconds_truncated(self, pb):
        # 59.9 rounds down to 59 s
        assert pb._format_updown_time(59.9) == '59s'

    def test_return_type_is_str(self, pb):
        assert isinstance(pb._format_updown_time(100), str)

    def test_max_width_fits_in_eight_chars(self, pb):
        """Documented max width is 8 characters."""
        for secs in (0, 59, 60, 3599, 3600, 86399, 86400, 365 * 86400 + 23 * 3600):
            result = pb._format_updown_time(secs)
            assert len(result) <= 8, (
                f"_format_updown_time({secs}) = {result!r} exceeds 8 chars"
            )


# ===========================================================================
# TestComputeUpdown
# ===========================================================================

class TestComputeUpdown:
    """Application._compute_updown(monitor) returns (display_str, is_down)."""

    def test_error_returns_question_marks(self, pb):
        m = make_monitor(pb, error='some error')
        s, is_down = pb.Application._compute_updown(m)
        assert s == '??'
        assert is_down is False

    def test_alive_with_up_since(self, pb):
        now = time.monotonic()
        m = make_monitor(pb, alive=True, up_since=now - 65)
        s, is_down = pb.Application._compute_updown(m)
        # 65 seconds → "1m 5s"
        assert s == '1m 5s'
        assert is_down is False

    def test_down_with_down_since(self, pb):
        now = time.monotonic()
        m = make_monitor(pb, alive=False, down_since=now - 70)
        s, is_down = pb.Application._compute_updown(m)
        # 70 seconds → "1m 10s"
        assert s == '1m 10s'
        assert is_down is True

    def test_alive_none_returns_dash(self, pb):
        """alive=None (not yet determined) → '-', not down."""
        m = make_monitor(pb, alive=None)
        s, is_down = pb.Application._compute_updown(m)
        assert s == '-'
        assert is_down is False

    def test_alive_true_but_no_up_since(self, pb):
        """alive=True but up_since not set → '-', not down."""
        m = make_monitor(pb, alive=True, up_since=None)
        s, is_down = pb.Application._compute_updown(m)
        assert s == '-'
        assert is_down is False

    def test_alive_false_but_no_down_since(self, pb):
        """alive=False but down_since not set → '-', not down."""
        m = make_monitor(pb, alive=False, down_since=None)
        s, is_down = pb.Application._compute_updown(m)
        assert s == '-'
        assert is_down is False

    def test_monotonic_time_is_used(self, pb):
        """The elapsed time is computed from time.monotonic(), not wall clock."""
        fixed_now = 1_000_000.0
        m = make_monitor(pb, alive=True, up_since=fixed_now - 3600)
        with patch('time.monotonic', return_value=fixed_now):
            s, _ = pb.Application._compute_updown(m)
        assert s == '1h 0m'

    def test_down_color_flag_true_when_down(self, pb):
        now = time.monotonic()
        m = make_monitor(pb, alive=False, down_since=now - 5)
        _, is_down = pb.Application._compute_updown(m)
        assert is_down is True

    def test_up_color_flag_false_when_up(self, pb):
        now = time.monotonic()
        m = make_monitor(pb, alive=True, up_since=now - 5)
        _, is_down = pb.Application._compute_updown(m)
        assert is_down is False


# ===========================================================================
# TestComputeStat
# ===========================================================================

class TestComputeStat:
    """Application._compute_stat(monitor, mode) returns a 6-character string."""

    # ── error sentinel ────────────────────────────────────────────────────

    def test_error_returns_six_char_placeholder_for_all_modes(self, pb):
        m = make_monitor(pb, error='oops')
        for mode in pb.STATS_MODES:
            if mode == 'off':
                continue
            result = pb.Application._compute_stat(m, mode)
            assert result == '    ??', (
                f"mode={mode!r}: expected '    ??' for errored monitor, got {result!r}"
            )

    # ── no data (fresh monitor) ───────────────────────────────────────────

    def _fresh(self, pb):
        """A monitor that has never recorded any pings."""
        return make_monitor(pb, alive=None, latency=None,
                            latencies=[], rx_count=0, xx_count=0, ping_count=0)

    def test_avg_no_data(self, pb):
        assert pb.Application._compute_stat(self._fresh(pb), 'Avg') == '     -'

    def test_min_no_data(self, pb):
        assert pb.Application._compute_stat(self._fresh(pb), 'Min') == '     -'

    def test_max_no_data(self, pb):
        assert pb.Application._compute_stat(self._fresh(pb), 'Max') == '     -'

    def test_stdev_no_data(self, pb):
        assert pb.Application._compute_stat(self._fresh(pb), 'StDev') == '     -'

    def test_loss_no_data(self, pb):
        assert pb.Application._compute_stat(self._fresh(pb), 'Loss%') == '     -'

    def test_rx_no_data(self, pb):
        assert pb.Application._compute_stat(self._fresh(pb), 'RX') == '     0'

    def test_tx_no_data(self, pb):
        assert pb.Application._compute_stat(self._fresh(pb), 'TX') == '     0'

    def test_xx_no_data(self, pb):
        assert pb.Application._compute_stat(self._fresh(pb), 'XX') == '     0'

    # ── Last (ms) ─────────────────────────────────────────────────────────

    def test_last_with_latency(self, pb):
        m = make_monitor(pb, latency=12.5)
        assert pb.Application._compute_stat(m, 'Last') == '  12.5'

    def test_last_no_latency(self, pb):
        m = make_monitor(pb, latency=None)
        assert pb.Application._compute_stat(m, 'Last') == '     -'

    def test_last_is_six_chars(self, pb):
        m = make_monitor(pb, latency=999.9)
        result = pb.Application._compute_stat(m, 'Last')
        assert len(result) == 6

    # ── Avg ───────────────────────────────────────────────────────────────

    def test_avg_single_value(self, pb):
        m = make_monitor(pb, latencies=[42.0])
        assert pb.Application._compute_stat(m, 'Avg') == '  42.0'

    def test_avg_multiple_values(self, pb):
        m = make_monitor(pb, latencies=[10.0, 20.0, 30.0])
        assert pb.Application._compute_stat(m, 'Avg') == '  20.0'

    def test_avg_is_six_chars(self, pb):
        m = make_monitor(pb, latencies=[100.0])
        assert len(pb.Application._compute_stat(m, 'Avg')) == 6

    # ── Min / Max ─────────────────────────────────────────────────────────

    def test_min_value(self, pb):
        m = make_monitor(pb, latencies=[30.0, 10.0, 20.0])
        assert pb.Application._compute_stat(m, 'Min') == '  10.0'

    def test_max_value(self, pb):
        m = make_monitor(pb, latencies=[30.0, 10.0, 20.0])
        assert pb.Application._compute_stat(m, 'Max') == '  30.0'

    # ── Loss% ────────────────────────────────────────────────────────────

    def test_loss_25_percent(self, pb):
        # 3 RX, 1 XX → 25.0%
        m = make_monitor(pb, rx_count=3, xx_count=1, ping_count=4)
        assert pb.Application._compute_stat(m, 'Loss%') == ' 25.0%'

    def test_loss_0_percent(self, pb):
        m = make_monitor(pb, rx_count=10, xx_count=0, ping_count=10)
        assert pb.Application._compute_stat(m, 'Loss%') == '  0.0%'

    def test_loss_100_percent(self, pb):
        m = make_monitor(pb, rx_count=0, xx_count=5, ping_count=5)
        assert pb.Application._compute_stat(m, 'Loss%') == '100.0%'

    def test_loss_is_six_chars(self, pb):
        m = make_monitor(pb, rx_count=1, xx_count=1, ping_count=2)
        assert len(pb.Application._compute_stat(m, 'Loss%')) == 6

    # ── StDev ─────────────────────────────────────────────────────────────

    def test_stdev_one_value_returns_dash(self, pb):
        # Need at least 2 values
        m = make_monitor(pb, latencies=[10.0])
        assert pb.Application._compute_stat(m, 'StDev') == '     -'

    def test_stdev_three_values(self, pb):
        # Population stdev of [10, 20, 30]: mean=20, variance=(100+0+100)/3≈66.67, stdev≈8.165
        m = make_monitor(pb, latencies=[10.0, 20.0, 30.0])
        result = pb.Application._compute_stat(m, 'StDev')
        expected_val = math.sqrt(sum((x - 20.0)**2 for x in [10, 20, 30]) / 3)
        assert result == f"{expected_val:6.1f}", (
            f"Expected '{expected_val:6.1f}', got {result!r}"
        )

    def test_stdev_identical_values(self, pb):
        m = make_monitor(pb, latencies=[15.0, 15.0, 15.0])
        assert pb.Application._compute_stat(m, 'StDev') == '   0.0'

    def test_stdev_is_six_chars(self, pb):
        m = make_monitor(pb, latencies=[1.0, 100.0])
        assert len(pb.Application._compute_stat(m, 'StDev')) == 6

    # ── RX / TX / XX counts ───────────────────────────────────────────────

    def test_rx_count(self, pb):
        m = make_monitor(pb, rx_count=42, ping_count=42)
        assert pb.Application._compute_stat(m, 'RX') == '    42'

    def test_tx_count(self, pb):
        m = make_monitor(pb, rx_count=8, xx_count=2, ping_count=10)
        assert pb.Application._compute_stat(m, 'TX') == '    10'

    def test_xx_count(self, pb):
        m = make_monitor(pb, rx_count=8, xx_count=2, ping_count=10)
        assert pb.Application._compute_stat(m, 'XX') == '     2'

    def test_count_fields_are_six_chars(self, pb):
        m = make_monitor(pb, rx_count=1000, xx_count=500, ping_count=1500)
        for mode in ('RX', 'TX', 'XX'):
            result = pb.Application._compute_stat(m, mode)
            assert len(result) == 6, f"mode={mode!r}: len={len(result)!r}"

    # ── Down (Up/Down time compact) ───────────────────────────────────────

    def test_down_mode_up_host(self, pb):
        now = time.monotonic()
        m = make_monitor(pb, alive=True, up_since=now - 65)
        result = pb.Application._compute_stat(m, 'Down')
        # "1m 5s" → stripped → "1m5s" → right-justified to 6 → "  1m5s"
        assert result == '  1m5s'

    def test_down_mode_down_host(self, pb):
        now = time.monotonic()
        m = make_monitor(pb, alive=False, down_since=now - 65)
        result = pb.Application._compute_stat(m, 'Down')
        assert result == '  1m5s'

    def test_down_mode_six_chars(self, pb):
        now = time.monotonic()
        m = make_monitor(pb, alive=True, up_since=now - 5)
        result = pb.Application._compute_stat(m, 'Down')
        assert len(result) == 6

    def test_down_mode_no_timing_info(self, pb):
        m = make_monitor(pb, alive=None)
        result = pb.Application._compute_stat(m, 'Down')
        # _compute_updown returns '-'; stripped is '-'; right-justified to 6 is '     -'
        assert result == '     -'

    def test_down_mode_error(self, pb):
        m = make_monitor(pb, error='fail')
        result = pb.Application._compute_stat(m, 'Down')
        assert result == '    ??'

    # ── return value is always 6 chars for all modes ──────────────────────

    def test_all_modes_return_six_chars_with_data(self, pb):
        now = time.monotonic()
        m = make_monitor(pb,
                         alive=True, up_since=now - 10,
                         latency=15.0,
                         latencies=[10.0, 15.0, 20.0],
                         rx_count=3, xx_count=1, ping_count=4)
        for mode in pb.STATS_MODES:
            if mode in ('off', 'All'):
                continue
            result = pb.Application._compute_stat(m, mode)
            assert len(result) == 6, (
                f"mode={mode!r}: expected 6 chars, got {len(result)} ({result!r})"
            )


# ===========================================================================
# TestComputeAllStats
# ===========================================================================

def _parse_all_stats_fields(result):
    """Extract 8 fixed-width 6-char fields from _compute_all_stats output."""
    return [result[i:i+6] for i in range(0, 62, 8)]


class TestComputeAllStats:
    """Application._compute_all_stats(monitor) returns exactly 62 characters."""

    _EXPECTED_LEN = 62

    def test_error_returns_62_chars(self, pb):
        m = make_monitor(pb, error='fail')
        result = pb.Application._compute_all_stats(m)
        assert len(result) == self._EXPECTED_LEN, (
            f"error case: expected {self._EXPECTED_LEN} chars, got {len(result)}: {result!r}"
        )

    def test_error_all_question_marks(self, pb):
        m = make_monitor(pb, error='fail')
        result = pb.Application._compute_all_stats(m)
        # 8 fields of '    ??' joined by '  '
        expected = '  '.join(['    ??'] * 8)
        assert result == expected

    def test_no_data_returns_62_chars(self, pb):
        m = make_monitor(pb, latencies=[], rx_count=0, xx_count=0, ping_count=0)
        result = pb.Application._compute_all_stats(m)
        assert len(result) == self._EXPECTED_LEN, (
            f"no-data case: expected {self._EXPECTED_LEN} chars, got {len(result)}: {result!r}"
        )

    def test_no_data_loss_field_is_dash(self, pb):
        """When no pings have been sent the Loss% field is '    - ' (dash with space)."""
        m = make_monitor(pb, latencies=[], rx_count=0, xx_count=0, ping_count=0)
        result = pb.Application._compute_all_stats(m)
        fields = _parse_all_stats_fields(result)
        loss_field = fields[3]
        assert loss_field == '    - ', (
            f"Expected '    - ' for no-data loss, got {loss_field!r}"
        )

    def test_normal_values_returns_62_chars(self, pb):
        m = make_monitor(pb,
                         latencies=[10.0, 20.0, 30.0],
                         rx_count=3, xx_count=1, ping_count=4)
        result = pb.Application._compute_all_stats(m)
        assert len(result) == self._EXPECTED_LEN, (
            f"normal case: expected {self._EXPECTED_LEN} chars, got {len(result)}: {result!r}"
        )

    def test_avg_field(self, pb):
        m = make_monitor(pb, latencies=[10.0, 20.0, 30.0],
                         rx_count=3, xx_count=0, ping_count=3)
        result = pb.Application._compute_all_stats(m)
        fields = _parse_all_stats_fields(result)
        assert fields[0] == '  20.0', f"Avg field: {fields[0]!r}"

    def test_min_field(self, pb):
        m = make_monitor(pb, latencies=[10.0, 20.0, 30.0],
                         rx_count=3, xx_count=0, ping_count=3)
        result = pb.Application._compute_all_stats(m)
        fields = _parse_all_stats_fields(result)
        assert fields[1] == '  10.0', f"Min field: {fields[1]!r}"

    def test_max_field(self, pb):
        m = make_monitor(pb, latencies=[10.0, 20.0, 30.0],
                         rx_count=3, xx_count=0, ping_count=3)
        result = pb.Application._compute_all_stats(m)
        fields = _parse_all_stats_fields(result)
        assert fields[2] == '  30.0', f"Max field: {fields[2]!r}"

    def test_loss_field_with_data(self, pb):
        # 1 loss out of 4 → 25.0%
        m = make_monitor(pb, latencies=[10.0, 20.0, 30.0],
                         rx_count=3, xx_count=1, ping_count=4)
        result = pb.Application._compute_all_stats(m)
        fields = _parse_all_stats_fields(result)
        assert fields[3] == ' 25.0%', f"Loss% field: {fields[3]!r}"

    def test_stdev_field(self, pb):
        lats = [10.0, 20.0, 30.0]
        m = make_monitor(pb, latencies=lats, rx_count=3, xx_count=0, ping_count=3)
        result = pb.Application._compute_all_stats(m)
        fields = _parse_all_stats_fields(result)
        avg = sum(lats) / len(lats)
        expected_stdev = math.sqrt(sum((x - avg)**2 for x in lats) / len(lats))
        assert fields[4] == f"{expected_stdev:6.1f}", f"StDev field: {fields[4]!r}"

    def test_rx_tx_xx_fields(self, pb):
        m = make_monitor(pb, latencies=[10.0],
                         rx_count=7, xx_count=3, ping_count=10)
        result = pb.Application._compute_all_stats(m)
        fields = _parse_all_stats_fields(result)
        assert fields[5] == '     7', f"RX field: {fields[5]!r}"
        assert fields[6] == '    10', f"TX field: {fields[6]!r}"
        assert fields[7] == '     3', f"XX field: {fields[7]!r}"

    def test_eight_fields_total(self, pb):
        """The result must split into exactly 8 fixed-position 6-char fields."""
        m = make_monitor(pb, latencies=[10.0],
                         rx_count=1, xx_count=0, ping_count=1)
        result = pb.Application._compute_all_stats(m)
        fields = _parse_all_stats_fields(result)
        assert len(fields) == 8, (
            f"Expected 8 fields, got {len(fields)}: {fields!r}"
        )

    def test_each_field_is_six_chars(self, pb):
        m = make_monitor(pb, latencies=[10.0, 20.0, 30.0],
                         rx_count=3, xx_count=1, ping_count=4)
        result = pb.Application._compute_all_stats(m)
        fields = _parse_all_stats_fields(result)
        for i, f in enumerate(fields):
            assert len(f) == 6, (
                f"Field {i} has {len(f)} chars, expected 6: {f!r}"
            )


# ===========================================================================
# TestUpdownColWidth
# ===========================================================================

class TestUpdownColWidth:
    """Application._updown_col_width() returns the max width needed across monitors."""

    _HEADER = 'Up/Down'
    _MIN_WIDTH = len(_HEADER)  # 7

    def test_minimum_width_with_no_monitors(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, entries=[('host', '127.0.0.1')])
        # Remove the auto-added monitor so the list is empty.
        app.monitors.clear()
        assert app._updown_col_width() == self._MIN_WIDTH

    def test_minimum_width_when_all_dash(self, pb, tmp_path):
        """Monitors with '-' return (len 1) must not reduce the minimum."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, entries=[('host', '127.0.0.1')])
        app.monitors[0].alive = None  # _compute_updown returns ('-', False)
        assert app._updown_col_width() == self._MIN_WIDTH

    def test_expands_for_longer_duration(self, pb, tmp_path):
        """A long duration string must cause the column to widen beyond 7."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, entries=[('host', '127.0.0.1')])
        now = time.monotonic()
        # 365 days + 23 hours → "365d 23h" (8 chars)
        app.monitors[0].alive    = True
        app.monitors[0].up_since = now - (365 * 86400 + 23 * 3600)
        width = app._updown_col_width()
        assert width == 8, (
            f"Expected width=8 for '365d 23h', got {width}"
        )

    def test_takes_maximum_across_multiple_monitors(self, pb, tmp_path):
        """With several monitors the column width is the longest display string."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, entries=[
            ('host', '10.0.0.1'),
            ('host', '10.0.0.2'),
            ('host', '10.0.0.3'),
        ])
        now = time.monotonic()
        # monitor 0: alive=None → '-' (1 char)
        app.monitors[0].alive = None
        # monitor 1: up 65 s → "1m 5s" (5 chars)
        app.monitors[1].alive    = True
        app.monitors[1].up_since = now - 65
        # monitor 2: up 365d 23h → "365d 23h" (8 chars)
        app.monitors[2].alive    = True
        app.monitors[2].up_since = now - (365 * 86400 + 23 * 3600)
        assert app._updown_col_width() == 8

    def test_never_less_than_header_width(self, pb, tmp_path):
        """Even with a very short uptime the returned width is at least 7."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, entries=[('host', '127.0.0.1')])
        now = time.monotonic()
        app.monitors[0].alive    = True
        app.monitors[0].up_since = now - 1   # "1s" — only 2 chars
        assert app._updown_col_width() >= self._MIN_WIDTH

    def test_error_monitor_returns_question_marks(self, pb, tmp_path):
        """A monitor with error='…' contributes '??' (2 chars), not expanding beyond min."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, entries=[('host', '127.0.0.1')])
        app.monitors[0].error = 'fail'
        # '??' is 2 chars < 7, so result is still the minimum
        assert app._updown_col_width() == self._MIN_WIDTH

