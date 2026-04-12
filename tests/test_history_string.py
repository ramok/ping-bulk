"""Unit tests for Monitor.get_history_string() — D3.

Covers:
  - Non-sync mode: success / rtt / scaled char encoding, cell_width > 1,
    offset, sparse history, fatal-error suppression
  - Sync mode: wall-clock bucket alignment, gaps between pings, offset
"""

import time
import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def make_monitor_with_history(pb, values, wall_times=None):
    """Return a PingMonitor with history pre-populated.

    values     — list of history values (float ms, None, or 'ERR'),
                 in chronological order (oldest first).
    wall_times — parallel list of wall-clock timestamps; defaults to
                 [now - len(values) + i + 1 for i in range(len(values))]
    """
    m = pb.PingMonitor('127.0.0.1')
    if wall_times is None:
        now = time.time()
        wall_times = [now - len(values) + i + 1 for i in range(len(values))]
    for v, t in zip(values, wall_times):
        m.history.append(v)
        m.history_times.append(t)
    return m


# ===========================================================================
# Non-sync mode
# ===========================================================================

class TestGetHistoryStringNonSync:

    def test_empty_history_returns_spaces(self, pb):
        m = pb.PingMonitor('h')
        result = m.get_history_string(length=5)
        assert result == '     '

    def test_length_respected(self, pb):
        m = make_monitor_with_history(pb, [10.0, 20.0, 30.0])
        result = m.get_history_string(length=5)
        assert len(result) == 5

    def test_success_mode_dots(self, pb):
        m = make_monitor_with_history(pb, [10.0, 20.0])
        result = m.get_history_string(length=2, mode='success')
        assert result == '..'

    def test_success_mode_timeout(self, pb):
        m = make_monitor_with_history(pb, [None])
        result = m.get_history_string(length=1, mode='success')
        assert result == 'X'

    def test_success_mode_error(self, pb):
        m = make_monitor_with_history(pb, ['ERR'])
        result = m.get_history_string(length=1, mode='success')
        assert result == '?'

    def test_rtt_mode_digit(self, pb):
        m = make_monitor_with_history(pb, [47.0])
        result = m.get_history_string(length=1, mode='rtt')
        assert result == '7'

    def test_scaled_mode(self, pb):
        m = make_monitor_with_history(pb, [5.0])    # < 10ms → '0'
        result = m.get_history_string(length=1, mode='scaled')
        assert result == '0'

    def test_newest_entry_at_leftmost_position(self, pb):
        # get_history_string returns newest-first (left edge = newest).
        m = make_monitor_with_history(pb, [10.0, 20.0, None])
        # Last appended (None) is newest; with length=3 → "X.." from left
        result = m.get_history_string(length=3, mode='success')
        assert result[0] == 'X'   # newest
        assert result[1] == '.'
        assert result[2] == '.'

    def test_offset_skips_newest(self, pb):
        # offset=1 skips the newest entry; next-newest appears at left
        m = make_monitor_with_history(pb, [10.0, None])
        result_0 = m.get_history_string(length=1, offset=0)
        result_1 = m.get_history_string(length=1, offset=1)
        assert result_0 == 'X'   # newest is None → 'X'
        assert result_1 == '.'   # older is 10.0 → '.'

    def test_sparse_history_pads_with_spaces(self, pb):
        m = make_monitor_with_history(pb, [5.0])
        result = m.get_history_string(length=5, mode='success')
        # Only 1 sample; rest should be spaces
        assert result.count('.') == 1
        assert result.count(' ') == 4

    def test_fatal_error_returns_spaces(self, pb):
        m = make_monitor_with_history(pb, [10.0, 20.0])
        m.error = "fatal error"
        result = m.get_history_string(length=5)
        assert result == '     '

    # ── cell_width > 1 ────────────────────────────────────────────────────

    def test_cell_width_2_success(self, pb):
        m = make_monitor_with_history(pb, [10.0])
        result = m.get_history_string(length=1, cell_width=2)
        # cell_width=2 → num_w = cell_width-1 = 1; capped = min(10, 10^1-1) = 9; cell = "9 "
        assert len(result) == 2
        assert result == '9 '

    def test_cell_width_2_small_value(self, pb):
        m = make_monitor_with_history(pb, [5.0])
        result = m.get_history_string(length=1, cell_width=2)
        assert result == '5 '

    def test_cell_width_2_timeout(self, pb):
        m = make_monitor_with_history(pb, [None])
        result = m.get_history_string(length=1, cell_width=2)
        assert result == 'X '

    def test_cell_width_2_error(self, pb):
        m = make_monitor_with_history(pb, ['ERR'])
        result = m.get_history_string(length=1, cell_width=2)
        assert result == '? '

    def test_cell_width_3_value(self, pb):
        m = make_monitor_with_history(pb, [42.0])
        result = m.get_history_string(length=1, cell_width=3)
        assert result == '42 '  # num_w=2; capped=min(42,99)=42 → f"{42:>2} "

    def test_cell_width_total_length(self, pb):
        m = make_monitor_with_history(pb, [1.0, 2.0, 3.0])
        result = m.get_history_string(length=3, cell_width=2)
        assert len(result) == 6   # 3 cells × 2 chars each


# ===========================================================================
# Sync mode
# ===========================================================================

class TestGetHistoryStringSync:

    def test_sync_correct_bucket_placement(self, pb):
        """A ping that arrived exactly at second T should land in the right bucket."""
        now = 1000.0
        # Two pings: one at second 999 (1 sec ago) and one at second 998 (2 sec ago).
        m = make_monitor_with_history(pb, [10.0, 20.0], wall_times=[999.0, 998.0])
        result = m.get_history_string(length=3, sync=True, end_time=now, mode='success')
        # Bucket 0 = second 999 (t_end=1000 → bucket = 1000 - int(999) = 1)
        # Bucket 1 = second 998 (bucket = 1000 - int(998) = 2)
        # result[0]=oldest of last 1 second, result[1]=second 998
        assert result[1] == '.'
        assert result[2] == '.'

    def test_sync_gap_filled_with_space(self, pb):
        """Seconds with no ping should be a space character."""
        now = 1000.0
        # Only ping at second 995 (5 sec ago), nothing at 996-999.
        m = make_monitor_with_history(pb, [10.0], wall_times=[995.0])
        result = m.get_history_string(length=6, sync=True, end_time=now, mode='success')
        # bucket = 1000 - 995 = 5
        assert result[5] == '.'
        for i in range(5):
            assert result[i] == ' '

    def test_sync_offset_shifts_window(self, pb):
        """offset moves the right edge of the window."""
        now = 1000.0
        # Ping at second 999.
        m = make_monitor_with_history(pb, [10.0], wall_times=[999.0])
        # With offset=2, t_end = int(1000) - 2 = 998; bucket = 998 - int(999) = -1 → out of range
        result = m.get_history_string(length=3, sync=True, end_time=now, offset=2,
                                       mode='success')
        assert '.' not in result   # ping is outside the shifted window

    def test_sync_length_respected(self, pb):
        m = make_monitor_with_history(pb, [1.0, 2.0])
        result = m.get_history_string(length=10, sync=True,
                                       end_time=time.time(), mode='success')
        assert len(result) == 10

    def test_sync_fatal_error_returns_spaces(self, pb):
        m = make_monitor_with_history(pb, [10.0])
        m.error = "dead"
        result = m.get_history_string(length=5, sync=True, end_time=time.time())
        assert result == '     '
