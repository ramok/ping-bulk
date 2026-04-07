"""Tests for sync-history mode (wall-clock-aligned ping history bars).

In sync mode, get_history_string() maps each history entry to a 1-second
bucket relative to a shared end_time.  A host that started late (e.g. SSH
through a down jumphost) shows leading spaces for the seconds it was absent,
so all hosts share the same time axis.
"""
from collections import deque


class TestSyncHistoryGetHistoryString:
    """Unit tests for Monitor.get_history_string in sync mode."""

    def _make_monitor(self, pb, entries):
        """Create a PingMonitor with pre-populated history and history_times.

        entries — list of (timestamp_offset, value) where timestamp_offset is
                  seconds before end_time.  value is a float (latency), None, or 'ERR'.
        end_time is 1000.0 by convention.
        """
        m = pb.PingMonitor("127.0.0.1")
        m.history       = deque(maxlen=200)
        m.history_times = deque(maxlen=200)
        end_time = 1000.0
        for offset, val in entries:
            m.history.append(val)
            m.history_times.append(end_time - offset)
        m.stop()
        return m

    def test_sync_fills_full_length(self, pb):
        """Result always has exactly `length` characters."""
        m = self._make_monitor(pb, [(2, 1.0), (1, 2.0), (0, 3.0)])
        s = m.get_history_string(length=10, offset=0, mode='success',
                                 cell_width=1, sync=True, end_time=1000)
        assert len(s) == 10

    def test_sync_latest_ping_at_bucket_zero(self, pb):
        """A ping at end_time lands in bucket 0 (leftmost char = newest)."""
        m = self._make_monitor(pb, [(0, 5.0)])  # exactly at end_time
        s = m.get_history_string(length=5, offset=0, mode='success',
                                 cell_width=1, sync=True, end_time=1000)
        # bucket 0 = position 0, rest are spaces
        assert s[0] == '.', f"Expected '.' at pos 0, got: {s!r}"
        assert s[1:] == '    ', f"Expected spaces after, got: {s!r}"

    def test_sync_late_start_shows_leading_spaces(self, pb):
        """A monitor that started late has spaces at the oldest (right) positions."""
        # 3 pings at offsets 2, 1, 0 — positions 0..4 to the right should be spaces
        entries = [(2, 1.0), (1, 2.0), (0, 3.0)]
        m = self._make_monitor(pb, entries)
        s = m.get_history_string(length=8, offset=0, mode='success',
                                 cell_width=1, sync=True, end_time=1000)
        # First 3 chars filled, last 5 should be spaces
        assert s[:3] == '...', f"Expected '...' at start, got: {s!r}"
        assert s[3:] == '     ', f"Expected spaces at end, got: {s!r}"

    def test_sync_gap_in_middle_preserved(self, pb):
        """A gap in the middle (missed second) shows as a space."""
        # pings at offsets 3, 1, 0 — bucket 2 is empty
        entries = [(3, 1.0), (1, 2.0), (0, 3.0)]
        m = self._make_monitor(pb, entries)
        s = m.get_history_string(length=5, offset=0, mode='success',
                                 cell_width=1, sync=True, end_time=1000)
        # buckets: 0='.', 1='.', 2=' ', 3='.', 4=' '
        assert s[0] == '.', f"bucket 0: {s!r}"
        assert s[1] == '.', f"bucket 1: {s!r}"
        assert s[2] == ' ', f"bucket 2 (gap): {s!r}"
        assert s[3] == '.', f"bucket 3: {s!r}"

    def test_sync_timeout_shows_X(self, pb):
        """A timeout (None value) shows as 'X' in sync mode."""
        m = self._make_monitor(pb, [(0, None)])
        s = m.get_history_string(length=3, offset=0, mode='success',
                                 cell_width=1, sync=True, end_time=1000)
        assert s[0] == 'X', f"Expected 'X' for timeout, got: {s!r}"

    def test_sync_error_shows_question_mark(self, pb):
        """An ERR value shows as '?' in sync mode."""
        m = self._make_monitor(pb, [(0, 'ERR')])
        s = m.get_history_string(length=3, offset=0, mode='success',
                                 cell_width=1, sync=True, end_time=1000)
        assert s[0] == '?', f"Expected '?' for ERR, got: {s!r}"

    def test_sync_out_of_range_entries_ignored(self, pb):
        """Entries outside the requested window do not appear."""
        # ping at offset 100 — outside length=5 window
        m = self._make_monitor(pb, [(100, 1.0), (0, 2.0)])
        s = m.get_history_string(length=5, offset=0, mode='success',
                                 cell_width=1, sync=True, end_time=1000)
        assert s[0] == '.', f"bucket 0: {s!r}"
        # bucket 100 is out of range — only 1 dot, rest spaces
        assert s[1:] == '    ', f"Expected spaces: {s!r}"

    def test_sync_stable_across_renders(self, pb):
        """Same end_time always produces identical output (no drift)."""
        entries = [(2, 1.0), (1, 2.0), (0, 3.0)]
        m = self._make_monitor(pb, entries)
        kwargs = dict(length=6, offset=0, mode='success',
                      cell_width=1, sync=True, end_time=1000)
        s1 = m.get_history_string(**kwargs)
        s2 = m.get_history_string(**kwargs)
        assert s1 == s2, "Output changed between renders with same end_time"

    def test_sync_two_monitors_same_end_time_aligned(self, pb):
        """Two monitors rendered with the same end_time are perfectly aligned.

        fast_monitor started 50s ago; slow_monitor (e.g. SSH) started 30s ago.
        The slow monitor's history should start with 20 spaces then 30 dots,
        exactly aligned with fast_monitor's last 30 positions.
        """
        end_time = 1000
        # fast: 50 pings, one per second
        fast = pb.PingMonitor("10.0.0.1")
        fast.history       = deque(maxlen=200)
        fast.history_times = deque(maxlen=200)
        for i in range(50):
            fast.history.append(1.0)
            fast.history_times.append(end_time - 49 + i)
        fast.stop()

        # slow: 30 pings, one per second, started 20s after fast
        slow = pb.PingMonitor("10.0.0.2")
        slow.history       = deque(maxlen=200)
        slow.history_times = deque(maxlen=200)
        for i in range(30):
            slow.history.append(1.0)
            slow.history_times.append(end_time - 29 + i)
        slow.stop()

        length = 50
        fast_s = fast.get_history_string(length=length, offset=0, mode='success',
                                         cell_width=1, sync=True, end_time=end_time)
        slow_s = slow.get_history_string(length=length, offset=0, mode='success',
                                         cell_width=1, sync=True, end_time=end_time)

        # fast: all 50 positions filled
        assert fast_s == '.' * 50, f"fast: {fast_s!r}"
        # slow: 20 spaces then 30 dots
        assert slow_s == '.' * 30 + ' ' * 20, f"slow: {slow_s!r}"

    def test_non_sync_mode_unaffected(self, pb):
        """Without sync=True, get_history_string behaves as before."""
        m = pb.PingMonitor("127.0.0.1")
        m.history = deque([1.0, 2.0, None], maxlen=200)
        m.history_times = deque([997.0, 998.0, 999.0], maxlen=200)
        m.stop()
        # Non-sync: no end_time needed, result reversed from deque order
        s = m.get_history_string(length=3, offset=0, mode='success', cell_width=1)
        assert len(s) == 3
        assert s[0] == 'X'   # newest = None → 'X'
        assert s[1] == '.'   # 2.0
        assert s[2] == '.'   # 1.0

    def test_sync_subsecond_jitter_eliminated(self, pb):
        """Two hosts whose pings arrive in the same second at different sub-second
        offsets must land in the same bucket — no per-host positional jitter."""
        end_time = 1000  # integer render_time

        # Host A: ping at 999.1 (same second as 999)
        a = pb.PingMonitor("10.0.0.1")
        a.history       = deque([1.0], maxlen=200)
        a.history_times = deque([999.1], maxlen=200)
        a.stop()

        # Host B: ping at 999.9 (same second, different sub-second)
        b = pb.PingMonitor("10.0.0.2")
        b.history       = deque([1.0], maxlen=200)
        b.history_times = deque([999.9], maxlen=200)
        b.stop()

        sa = a.get_history_string(length=5, offset=0, mode='success',
                                  cell_width=1, sync=True, end_time=end_time)
        sb = b.get_history_string(length=5, offset=0, mode='success',
                                  cell_width=1, sync=True, end_time=end_time)
        assert sa == sb, (
            f"Sub-second jitter: hosts in the same second show different positions.\n"
            f"  A (ts=999.1): {sa!r}\n"
            f"  B (ts=999.9): {sb!r}"
        )
