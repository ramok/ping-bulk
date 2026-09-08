"""Tests for sync-history mode (wall-clock-aligned ping history bars).

In sync mode, get_history_string() maps each history entry to a 1-second
bucket relative to a shared end_time.  A host that started late (e.g. SSH
through a down jumphost) shows leading spaces for the seconds it was absent,
so all hosts share the same time axis.
"""
import time
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


class TestSyncHistoryLateCell:
    """Late cells must bucket by their own timestamp like any other reply.

    Appending a late reply (the old behaviour) put it in the same second as the
    'X' it belonged to, and sync mode is last-write-wins — so the timeout was
    silently erased there while the positional view showed both. One cell per
    probe removes that disagreement.
    """

    def _monitor(self, pb, cells):
        m = pb.PingMonitor('10.0.0.1')
        with m.lock:
            for val, ts in cells:
                m.history.append(val)
                m.history_times.append(ts)
        return m

    def test_late_cell_renders_as_x_in_its_bucket(self, pb):
        # bucket = int(end_time) - int(ts), so a cell one second back is index 1.
        m = self._monitor(pb, [(-1206.0, 1700000005.4)])
        out = m.get_history_string(length=3, mode='success', sync=True,
                                   end_time=1700000006.0)
        assert out[1] == 'x', out

    def test_late_cell_does_not_overwrite_its_neighbour(self, pb):
        """Consecutive probes occupy distinct seconds, so both survive."""
        m = self._monitor(pb, [(-1206.0, 1700000004.2),
                               (-1207.0, 1700000005.2)])
        out = m.get_history_string(length=3, mode='success', sync=True,
                                   end_time=1700000006.0)
        assert out[1] == 'x' and out[2] == 'x', out

    def test_lost_and_late_stay_distinguishable(self, pb):
        m = self._monitor(pb, [(None, 1700000004.0), (-1206.0, 1700000005.0)])
        out = m.get_history_string(length=3, mode='success', sync=True,
                                   end_time=1700000006.0)
        assert out[1] == 'x' and out[2] == 'X', out


class TestSyncConnectGaps:
    """Seconds with no ping process render '_' rather than a blank.

    A blank in sync mode is ambiguous — not monitored yet, no sample this
    second, or a relayed host still establishing its SSH connection.  The last
    is knowable, and for a jump host it can be several seconds, so the bar was
    simply shorter with nothing to say why.
    """

    END = 1000.0

    def _monitor(self, pb, samples=(), windows=(), open_since=None):
        m = pb.PingMonitor('127.0.0.1')
        m.history = deque(maxlen=200)
        m.history_times = deque(maxlen=200)
        for offset, val in samples:
            m.history.append(val)
            m.history_times.append(self.END - offset)
        for t0_off, t1_off in windows:
            m._connect_windows.append((self.END - t0_off, self.END - t1_off))
        if open_since is not None:
            m._connect_since = self.END - open_since
        m.stop()
        return m

    def _bar(self, m, length=10, cell_width=1):
        return m.get_history_string(length=length, sync=True, end_time=self.END,
                                    cell_width=cell_width)

    # ── the reported case: a slow connect before the first sample ───────────

    def test_connect_before_first_sample_is_marked(self, pb):
        """Bucket 0 is the newest second, so the gap sits at the old end.

        A span from 6 s ago to 3 s ago covers four whole seconds — both ends
        are inclusive, since each names a second that had no ping running.
        """
        m = self._monitor(pb, samples=[(0, 1.0), (1, 1.0), (2, 1.0)],
                          windows=[(6, 3)])
        assert self._bar(m) == '...____   '

    def test_still_connecting_marks_up_to_now(self, pb):
        """An open span reaches bucket 0: nothing has arrived yet."""
        m = self._monitor(pb, open_since=4)
        assert self._bar(m) == '_____     '

    def test_a_gap_between_runs_is_marked(self, pb):
        m = self._monitor(pb, samples=[(0, 1.0), (1, 1.0), (4, 1.0), (5, 1.0)],
                          windows=[(3, 2)])
        assert self._bar(m) == '..__..    '

    # ── samples always outrank the marker ───────────────────────────────────

    def test_a_sample_is_not_overwritten(self, pb):
        """A recorded probe outweighs 'the process was starting'."""
        m = self._monitor(pb, samples=[(1, 5.0)], windows=[(2, 0)])
        assert self._bar(m)[1] == '.'

    def test_a_loss_is_not_overwritten(self, pb):
        m = self._monitor(pb, samples=[(1, None)], windows=[(2, 0)])
        assert self._bar(m)[1] == 'X'

    def test_an_error_cell_is_not_overwritten(self, pb):
        m = self._monitor(pb, samples=[(1, 'ERR')], windows=[(2, 0)])
        assert self._bar(m)[1] == '?'

    # ── boundaries ─────────────────────────────────────────────────────────

    def test_no_windows_leaves_blanks(self, pb):
        m = self._monitor(pb, samples=[(0, 1.0)])
        assert self._bar(m) == '.         '

    def test_a_window_older_than_the_bar_is_ignored(self, pb):
        m = self._monitor(pb, samples=[(0, 1.0)], windows=[(40, 30)])
        assert self._bar(m) == '.         '

    def test_a_window_is_clipped_to_the_bar(self, pb):
        """An old span is trimmed at the bar's edge, not wrapped.

        It ends 2 s ago, so the two newest buckets are after it and stay blank.
        """
        m = self._monitor(pb, windows=[(40, 2)])
        assert self._bar(m) == '  ________'

    def test_marker_does_not_appear_in_non_sync_mode(self, pb):
        """The dense strip is one cell per probe; it has no empty seconds."""
        m = self._monitor(pb, samples=[(0, 1.0)], windows=[(5, 1)])
        assert '_' not in m.get_history_string(length=10, sync=False)

    # ── multi-character cells (rtt mode) ───────────────────────────────────

    def test_rtt_mode_fills_the_whole_cell(self, pb):
        """A 3-char cell becomes '__ ', not a bare '_' in a blank cell."""
        m = self._monitor(pb, windows=[(3, 1)])
        bar = self._bar(m, length=4, cell_width=3)
        assert bar == '   __ __ __ ', repr(bar)

    def test_rtt_mode_keeps_a_sample_cell(self, pb):
        m = self._monitor(pb, samples=[(0, 7.0)], windows=[(3, 0)])
        bar = self._bar(m, length=4, cell_width=3)
        assert bar.startswith(' 7 '), repr(bar)
        assert bar[3:] == '__ __ __ ', repr(bar)

    # ── statistics are untouched ───────────────────────────────────────────

    def test_no_effect_on_counters(self, pb):
        """These seconds had no probe, which is the whole point."""
        m = self._monitor(pb, samples=[(0, 1.0)], windows=[(5, 1)])
        before = (m.rx_count, m.xx_count, m.ping_count)
        self._bar(m)
        assert (m.rx_count, m.xx_count, m.ping_count) == before


class TestConnectWindowTracking:
    """The spans are opened and closed by the subprocess loop itself."""

    def test_a_fresh_monitor_has_no_spans(self, pb):
        m = pb.PingMonitor('127.0.0.1')
        assert m._connect_since is None
        assert list(m._connect_windows) == []

    def test_first_result_closes_the_span(self, pb):
        m = pb.PingMonitor('127.0.0.1')
        m._connect_since = time.time() - 5
        m._handle_stdout_line(
            '[1700000000.0] 64 bytes from 127.0.0.1: icmp_seq=1 ttl=64 time=1.0 ms')
        assert m._connect_since is None
        assert len(m._connect_windows) == 1

    def test_a_non_result_line_leaves_the_span_open(self, pb):
        """Banner and statistics lines are not results."""
        m = pb.PingMonitor('127.0.0.1')
        m._connect_since = time.time() - 5
        m._handle_stdout_line('PING 127.0.0.1 (127.0.0.1) 56(84) bytes of data.')
        assert m._connect_since is not None

    def test_spans_are_bounded(self, pb):
        """A host that reconnects for days must not grow memory."""
        m = pb.PingMonitor('127.0.0.1')
        assert m._connect_windows.maxlen is not None

    def test_port_monitor_has_no_spans(self, pb):
        """A TCP connect is immediate; there is no setup to report."""
        m = pb.PortMonitor('127.0.0.1', '443')
        assert m._connect_since is None
