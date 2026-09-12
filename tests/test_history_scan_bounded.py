"""The history bar must cost a screen width, not a history size.

':set history-size' defaults to 86400 — 24 h at one ping a second — while the
bar shows a screen width of it.  Copying and walking the whole deque per host
per draw made a redraw grow with uptime, and the section headers repeat the
work for every host they cover.  Measured at 100 columns over 54 hosts: 17 ms
per redraw after ten minutes, 402 ms after five and a half hours, 1.8 s once
the deque filled.  The draw loop runs on a 100 ms key timeout, so that is what
turns each keypress into a one-second wait after half a day.
"""

import time
from collections import deque

import pytest


class CountingDeque(deque):
    """A deque that records how many items were read out of it.

    Both directions are counted: the regression was a full ``list(self.history)``
    copy, which is forward iteration, and a fix that merely reversed the walk
    without bounding it would be just as slow.
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.reverse_reads = 0

    def __reversed__(self):
        for item in super().__reversed__():
            self.reverse_reads += 1
            yield item

    def __iter__(self):
        for item in super().__iter__():
            self.reverse_reads += 1
            yield item


def _monitor(pb, samples, now):
    m = pb.PingMonitor('10.0.0.1')
    vals = [12.5] * samples
    times = [now - (samples - i) for i in range(samples)]
    m.history = CountingDeque(vals, maxlen=86400)
    m.history_times = CountingDeque(times, maxlen=86400)
    return m


class TestScanIsBounded:

    @pytest.mark.parametrize('samples', [3600, 20340, 86400])
    def test_sync_scan_does_not_grow_with_history(self, pb, samples):
        now = time.time()
        m = _monitor(pb, samples, now)
        m.get_history_string(length=100, offset=0, mode='success',
                             cell_width=1, sync=True, end_time=now)
        # A screen width plus the back-dating grace, not the whole deque.
        budget = 100 + pb._SYNC_SCAN_GRACE + 2
        assert m.history_times.reverse_reads <= budget, (
            f"{samples} samples -> read {m.history_times.reverse_reads}")

    @pytest.mark.parametrize('samples', [3600, 86400])
    def test_dense_scan_does_not_grow_with_history(self, pb, samples):
        now = time.time()
        m = _monitor(pb, samples, now)
        m.get_history_string(length=100, offset=20, mode='success',
                             cell_width=1, sync=False)
        assert m.history.reverse_reads <= 120 + 2

    # No wall-clock assertion here on purpose: at 0.07 ms a ratio test measures
    # timer noise, and under 'pytest -n auto' it would flake and send someone
    # hunting a regression that is not there.  The read budgets above pin the
    # same invariant deterministically, and fail on the unfixed code.


class TestBoundedScanKeepsTheSameCells:
    """The scan reads less; it must still draw the same thing.

    Nothing here asserts the ordering of the rebuilt tail: _worse_hist_sample
    is symmetric over every value these deques hold, so a test claiming to
    guard that would pass with the ordering removed.  What is worth pinning is
    that a bounded scan still reaches a back-dated sample and still resolves
    two samples that share a second.
    """

    def test_a_sample_behind_the_window_edge_is_not_lost(self, pb):
        now = time.time()
        m = pb.PingMonitor('10.0.0.1')
        m.history = deque(maxlen=86400)
        m.history_times = deque(maxlen=86400)
        # A long healthy run, then a loss appended late but dated 3 s back.
        for i in range(500):
            m.history.append(12.5)
            m.history_times.append(now - (500 - i))
        m.history.append(None)
        m.history_times.append(now - 3)
        out = m.get_history_string(length=10, offset=0, mode='success',
                                   cell_width=1, sync=True, end_time=now)
        assert out[3] == 'X', out

    def test_two_samples_in_one_second_keep_the_worse(self, pb):
        """A relayed host is stamped when its line arrives and ssh delivers in
        bursts, so one second can hold two samples."""
        now = time.time()
        m = pb.PingMonitor('10.0.0.1')
        m.history = deque([12.5, None], maxlen=86400)
        m.history_times = deque([now - 5, now - 5], maxlen=86400)
        out = m.get_history_string(length=10, offset=0, mode='success',
                                   cell_width=1, sync=True, end_time=now)
        assert out[5] == 'X', out

    def test_the_slower_of_two_replies_survives(self, pb):
        now = time.time()
        m = pb.PingMonitor('10.0.0.1')
        m.history = deque([5.0, 200.0], maxlen=86400)
        m.history_times = deque([now - 5, now - 5], maxlen=86400)
        out = m.get_history_string(length=10, offset=0, mode='rtt',
                                   cell_width=4, sync=True, end_time=now)
        assert '200' in out, out
