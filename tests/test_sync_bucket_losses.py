"""Unit tests for the sync view's placement of a lost probe.

Sync mode buckets history by wall-clock second so every host shares one time
axis.  Two things conspired to hide losses there:

  1. A loss was stamped when the *verdict* was reached, not when the probe was
     sent.  'ping -O' prints "no answer yet for icmp_seq=N" one interval after
     probe N goes out, and _expire_pending then waits 'late-grace' on top — so
     the 'X' landed one to two seconds late, in a second belonging to a later
     probe.
  2. A second holds one cell, and the bucket was filled last-writer-wins.  So
     the displaced 'X' was usually overwritten by the reply of the probe whose
     second it had landed in, and vanished.

Together, a monitoring tool silently dropped failures from the very view meant
for comparing hosts against each other.  The dense (non-sync) strip was never
affected: its cells are one per sample, in append order.
"""

import pytest


T0 = 1_000_000.0


def _direct(pb):
    return pb.PingMonitor('10.0.0.1')


def _relayed(pb):
    return pb.SshPingMonitor(['relay'], '10.0.0.1')


def _sync(m, length=4, end=None, mode='success', **kw):
    return m.get_history_string(length=length, offset=0, mode=mode, sync=True,
                                end_time=T0 + length - 0.1 if end is None else end,
                                **kw)


def _dense(m, length=4, mode='success', **kw):
    return m.get_history_string(length=length, offset=0, mode=mode, **kw)


def _stamp(m, samples):
    """Put (timestamp, value) pairs straight into the deques, in order."""
    for ts, val in samples:
        m.history.append(val)
        m.history_times.append(ts)


# ---------------------------------------------------------------------------
# A lost probe is dated when it was sent
# ---------------------------------------------------------------------------

class TestLossIsDatedAtSendTime:

    def test_the_expired_loss_lands_in_the_probe_second(self, pb):
        """The whole timeline, through the real code paths.

        Probe 2 goes out at T0+1 and is never answered.  ping reports it at
        T0+2 (one interval later) and the 0.5 s state loop writes it off at
        T0+3.5, a grace period after that.  The 'X' belongs to T0+1.
        """
        m = _direct(pb)
        m._record_reply(25.0, T0 + 0.03, seq=1)     # probe 1, sent T0+0
        m._record_no_answer(T0 + 2.00, seq=2)       # '-O' for probe 2
        m._record_reply(25.0, T0 + 2.03, seq=3)     # probe 3, sent T0+2
        m._record_reply(25.0, T0 + 3.03, seq=4)     # probe 4, sent T0+3
        m._expire_pending(T0 + 3.50, 1.0)           # verdict reached here
        # newest second leftmost: T0+3, T0+2, T0+1, T0+0
        assert _sync(m) == '..X.'

    def test_the_reply_of_the_next_probe_survives(self, pb):
        """The displaced X used to eat it.

        A short grace puts the write-off inside the very second the next
        probe answered in, which is the collision the old stamp produced.
        """
        m = _direct(pb)
        m._record_no_answer(T0 + 2.00, seq=2)     # probe 2, sent T0+1
        m._record_reply(25.0, T0 + 2.03, seq=3)   # probe 3, answered T0+2
        m._expire_pending(T0 + 2.20, 0.1)         # verdict inside T0+2
        assert _sync(m)[1] == '.', 'T0+2 answered and must still say so'
        assert _sync(m)[2] == 'X', 'and T0+1 is where the loss belongs'

    def test_the_stamp_is_one_interval_before_the_report(self, pb):
        m = _direct(pb)
        m._record_no_answer(T0 + 5.0, seq=9)
        m._expire_pending(T0 + 9.0, 1.0)
        assert list(m.history) == [None]
        assert list(m.history_times) == [T0 + 4.0]

    def test_a_later_write_off_does_not_move_the_stamp(self, pb):
        """The verdict may be slow; the probe is still when it was."""
        m = _direct(pb)
        m._record_no_answer(T0 + 5.0, seq=9)
        m._expire_pending(T0 + 30.0, 1.0)       # state loop was busy
        assert list(m.history_times) == [T0 + 4.0]

    def test_a_seqless_report_is_dated_the_same_way(self, pb):
        """No icmp_seq to pair with: written off at once, but same arithmetic."""
        m = _direct(pb)
        m._record_no_answer(T0 + 5.0, seq=None)
        assert list(m.history) == [None]
        assert list(m.history_times) == [T0 + 4.0]

    def test_a_late_reply_is_dated_at_its_probe_too(self, pb):
        """It answers the probe '-O' flagged, so it belongs in that second."""
        m = _direct(pb)
        m._record_no_answer(T0 + 2.0, seq=2)        # probe 2 sent T0+1
        m._record_reply(1500.0, T0 + 2.6, seq=2)    # answered 1.6 s later
        assert list(m.history_times) == [T0 + 1.0]
        assert list(m.history)[0] < 0, 'negative encoding marks it late'
        assert _sync(m)[2] == 'x', _sync(m)     # the T0+1 second

    def test_an_on_time_reply_keeps_its_own_stamp(self, pb):
        """Nothing flagged it, so there is nothing to correct."""
        m = _direct(pb)
        m._record_reply(25.0, T0 + 2.03, seq=3)
        assert list(m.history_times) == [T0 + 2.03]

    def test_a_stale_window_loss_is_dated_now(self, pb):
        """No probe was ever reported, so there is no send time to recover."""
        m = _direct(pb)
        m._record_stale_loss(T0 + 7.0)
        assert list(m.history_times) == [T0 + 7.0]

    def test_a_stale_window_that_eats_a_probe_dates_it_as_that_probe(self, pb):
        """Same event, whichever path notices it, so the same second."""
        m = _direct(pb)
        m._record_no_answer(T0 + 2.0, seq=2)     # probe 2, sent T0+1
        m._record_stale_loss(T0 + 9.0)           # the child went quiet
        assert list(m.history_times) == [T0 + 1.0]
        assert not m._pending, 'the probe must be consumed, not counted twice'

    def test_a_port_monitor_is_untouched(self, pb):
        """No '-O' line exists for a TCP check, so nothing to re-date."""
        m = pb.PortMonitor('10.0.0.1', 22)
        m.history.append(5.0); m.history_times.append(T0 + 2.0)
        m._expire_pending(T0 + 9.0, 1.0)         # no-op: nothing pending
        assert list(m.history_times) == [T0 + 2.0]
        assert list(m.history) == [5.0]

    def test_the_dense_view_is_unchanged(self, pb):
        """Dense cells are one per sample in append order, whatever the stamps."""
        m = _direct(pb)
        m._record_reply(25.0, T0 + 0.03, seq=1)
        m._record_no_answer(T0 + 2.00, seq=2)
        m._record_reply(25.0, T0 + 2.03, seq=3)
        m._expire_pending(T0 + 3.50, 1.0)
        assert _dense(m, length=3) == 'X..'


# ---------------------------------------------------------------------------
# Two samples in one second
# ---------------------------------------------------------------------------

class TestBucketCollisionKeepsTheWorse:
    """A relayed host is stamped when its line reaches us, and ssh delivers in
    bursts — so two samples in one second is normal, not exotic.
    """

    def _both_orders(self, pb, a, b, no_alarm=False, **kw):
        """Render the same two samples in one second, each way round.

        Both orders, always: last-writer-wins gave the right answer for
        whichever order happened to put the winner second, so a one-order
        test passes with the fix reverted.
        """
        out = []
        for first, last in ((a, b), (b, a)):
            m = _relayed(pb)
            m.no_alarm = no_alarm
            _stamp(m, [(T0 + 2.1, first), (T0 + 2.6, last)])
            out.append(_sync(m, **kw))
        assert out[0] == out[1], f'order changed the outcome: {out}'
        return out[0]

    def test_a_loss_survives_a_reply_in_the_same_second(self, pb):
        assert self._both_orders(pb, None, 25.0)[1] == 'X'

    def test_a_process_error_outranks_a_loss(self, pb):
        assert self._both_orders(pb, None, 'ERR')[1] == '?'

    def test_a_loss_outranks_a_late_reply(self, pb):
        assert self._both_orders(pb, -1500.0, None)[1] == 'X'

    def test_a_late_reply_outranks_a_clean_one(self, pb):
        assert self._both_orders(pb, -1500.0, 25.0)[1] == 'x'

    def test_two_replies_leave_a_reply(self, pb):
        assert self._both_orders(pb, 25.0, 30.0)[1] == '.'

    def test_the_slower_of_two_replies_is_the_one_kept(self, pb):
        """They rank equal as '.', so the reading shown must still be decided
        on the same principle — and 88 ms is the worse news than 11 ms.

        Resolving on the rendered cell instead got this wrong twice over: it
        kept whichever arrived last, and comparing cell text compares digits
        ('19' against '20' would make '9' the winner).
        """
        assert self._both_orders(pb, 11.0, 88.0, mode='rtt',
                                 cell_width=3)[3:6] == '88 '
        assert self._both_orders(pb, 11.0, 88.0, mode='scaled')[1] == '8'

    def test_an_expected_loss_does_not_mask_a_reply(self, pb):
        """':no-alarm' says a miss here is not news, and that holds here too."""
        assert self._both_orders(pb, None, 25.0, no_alarm=True)[1] == '.'

    def test_an_expected_loss_still_beats_an_empty_second(self, pb):
        m = _relayed(pb)
        m.no_alarm = True
        _stamp(m, [(T0 + 2.1, None)])
        assert _sync(m)[1] == 'o'

    def test_rtt_cells_collide_the_same_way(self, pb):
        """A wide cell holds a number, so the rank must come from the value."""
        assert self._both_orders(pb, None, 25.0, cell_width=3)[3:6] == 'XX '

    def test_a_scaled_overflow_still_counts_as_a_reply(self, pb):
        """'>' is drawn for an RTT past the top of the scale."""
        m = _relayed(pb)
        m.history.append(2000.0); m.history_times.append(T0 + 2.6)
        assert _sync(m, mode='scaled')[1] == '>'
        assert self._both_orders(pb, 2000.0, None, mode='scaled')[1] == 'X'

    def test_a_number_beats_an_empty_rtt_cell(self, pb):
        m = _relayed(pb)
        _stamp(m, [(T0 + 2.6, 25.0)])
        assert _sync(m, cell_width=3)[3:6] == '25 ', _sync(m, cell_width=3)


class TestOneRankingEverywhere:
    """The section header and the rows under it must not disagree."""

    @pytest.mark.parametrize('pair,expected', [
        (('?', 'X'), '?'),
        (('X', 'x'), 'X'),
        (('x', '.'), 'x'),
        (('.', 'o'), '.'),
        (('o', '_'), 'o'),
        (('_', ' '), '_'),
    ])
    def test_each_step_of_the_ranking(self, pb, pair, expected):
        assert pb.Application._worst_history_char(list(pair)) == expected
        assert pb.Application._worst_history_char(list(reversed(pair))) == expected

    def test_an_empty_list_is_blank(self, pb):
        assert pb.Application._worst_history_char([]) == ' '
