"""Unit tests for the remote-clock (Drift) feature.

Covers the pure helpers and the stat integration without touching the network:
  - _format_offset        — signed compact offset formatting + ±12h fold semantics
  - _format_utc_hms       — ms-since-UTC-midnight → HH:MM:SS
  - _parse_tsandaddr      — tsandaddr block parsing (abs + delta hops, junk)
  - _select_target_ts     — last-forward-hop-before-repeat selection, NAT, guards
  - _clock_probe_cmd      — local vs SSH (remote-ping) command construction
  - offset computation     — remote vs local, midnight wrap folded to ±12h
  - _compute_stat(Drift/RTime) — no-rt / not-probed / value / error states
  - _display_stale         — down/error hosts gray out frozen stats; RTime
                             freezes at the last probe instead of ticking
  - :set stats drift/rtime — alias parsing
  - :set clock-interval    — value parsing + validation
  - _run_clock_probe       — no-rt verdict needs consecutive failed probes

The probe subprocess itself (_clock_probe_once) is exercised against real
hosts in the e2e/tmux tests, not here.
"""

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_monitor(pb, host='127.0.0.1', **attrs):
    m = pb.PingMonitor(host)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


def make_app(pb, tmp_path, entries=None):
    import os
    from unittest.mock import patch
    if entries is None:
        entries = [('host', '127.0.0.1')]
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    with patch.object(pb, '_config_path', return_value=cfg):
        return pb.Application(entries, log_file=None)


# ===========================================================================
# _format_offset
# ===========================================================================

class TestFormatOffset:
    @pytest.mark.parametrize('ms,expected', [
        (0,            '0.0s'),   # rounds to zero → unsigned (no '-0.0s')
        (40,           '0.0s'),
        (-40,          '0.0s'),
        (60,           '+0.1s'),
        (-60,          '-0.1s'),
        (300,          '+0.3s'),
        (-300,         '-0.3s'),
        (12500,        '+12.5s'),
        (-12500,       '-12.5s'),
        (59900,        '+59.9s'),
        (65000,        '+1m05s'),
        (-65000,       '-1m05s'),
        (4020000,      '+1h07m'),          # 1h07m
        (-(11*3600+7*60)*1000, '-11h07m'),  # the known wrong-clock relay
        (2*86400*1000 + 3*3600*1000, '+2d03h'),
    ])
    def test_values(self, pb, ms, expected):
        assert pb._format_offset(ms) == expected

    def test_signed_above_display_precision(self, pb):
        assert pb._format_offset(100).startswith('+')
        assert pb._format_offset(-100).startswith('-')

    def test_unsigned_below_display_precision(self, pb):
        # ±49 ms rounds to 0.0s — direction is noise, so no sign at all.
        assert pb._format_offset(-1) == '0.0s'
        assert pb._format_offset(49) == '0.0s'


# ===========================================================================
# _format_utc_hms
# ===========================================================================

class TestFormatUtcHms:
    @pytest.mark.parametrize('ms,expected', [
        (0,        '00:00:00'),
        (37957706, '10:32:37'),
        (77999687, '21:39:59'),
        (86399000, '23:59:59'),
    ])
    def test_values(self, pb, ms, expected):
        assert pb._format_utc_hms(ms) == expected

    def test_wraps_past_midnight(self, pb):
        # 24h + 5s worth of ms folds back to 00:00:05
        assert pb._format_utc_hms(86400000 + 5000) == '00:00:05'


# ===========================================================================
# _parse_tsprespec_ts
# ===========================================================================

# Real 'ping -T tsandaddr 10.123.2.2' output captured from a NAT'd host whose
# real inside address is 10.0.0.2 with a wrong clock (~22:27 UTC vs ~11:21 local).
TSANDADDR_NAT = """\
PING 10.123.2.2 (10.123.2.2) 56(124) bytes of data.
64 bytes from 10.123.2.2: icmp_seq=1 ttl=62 time=47.3 ms
TS: \t10.122.0.129\t40867797 absolute
\t10.122.0.62\t39984470
\t10.123.2.1\t-39985112
\t10.0.0.2\t39985018
Unrecorded hops: 3
"""

# Real output for a direct 1-hop host: destination stamps twice, then return.
TSANDADDR_GATEWAY = """\
64 bytes from 10.122.0.62: icmp_seq=1 ttl=64 time=40.3 ms
TS: \t10.122.0.129\t40868853 absolute
\t10.122.0.62\t39984467
\t10.122.0.62\t0
\t10.122.0.129\t-39984427
"""


class TestParseTsandaddr:
    def test_parses_nat_hops(self, pb):
        hops = pb._parse_tsandaddr(TSANDADDR_NAT)
        assert [h[0] for h in hops] == [
            '10.122.0.129', '10.122.0.62', '10.123.2.1', '10.0.0.2']
        # cumulative absolute values (first absolute, rest deltas)
        assert hops[0][1] == 40867797
        assert hops[1][1] == 40867797 + 39984470          # 80852267 (~22:27)
        assert hops[3][1] == hops[2][1] + 39985018         # host's real clock

    def test_stops_at_unrecorded(self, pb):
        hops = pb._parse_tsandaddr(TSANDADDR_NAT)
        assert len(hops) == 4  # 'Unrecorded hops: 3' ends the block

    def test_no_ts_block_returns_empty(self, pb):
        assert pb._parse_tsandaddr(
            "64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=0.5 ms\n") == []

    def test_busybox_error_returns_empty(self, pb):
        assert pb._parse_tsandaddr("ping: invalid option -- 'T'\n") == []


class TestSelectTargetTs:
    def test_nat_picks_deepest_forward_hop(self, pb):
        hops = pb._parse_tsandaddr(TSANDADDR_NAT)
        ts = pb._select_target_ts(hops)
        # 10.0.0.2's clock ≈ 22:27 UTC, definitely not local ~11:21
        assert ts is not None
        assert pb._format_utc_hms(ts).startswith('22:')

    def test_gateway_picks_hop_before_repeat(self, pb):
        hops = pb._parse_tsandaddr(TSANDADDR_GATEWAY)
        ts = pb._select_target_ts(hops)
        # destination 10.122.0.62 (its wrong ~22:27 clock), not our return hop
        assert ts == 40868853 + 39984467

    def test_single_hop_only_us_returns_none(self, pb):
        # Only our own egress stamped → host did not answer → no reading.
        assert pb._select_target_ts([('10.0.0.9', 40000000)]) is None

    def test_empty_returns_none(self, pb):
        assert pb._select_target_ts([]) is None

    def test_out_of_range_timestamp_rejected(self, pb):
        # A non-standard high-bit value (≥ 24h in ms) is not a valid clock.
        hops = [('10.0.0.1', 100), ('10.0.0.2', 90_000_000)]
        assert pb._select_target_ts(hops) is None


# ===========================================================================
# Offset computation (fold to ±12h)
# ===========================================================================

class TestOffsetFold:
    @staticmethod
    def offset(remote_ms, local_ms):
        remote = remote_ms % 86_400_000
        return ((remote - local_ms + 43_200_000) % 86_400_000) - 43_200_000

    def test_small_positive(self):
        assert self.offset(37_958_000, 37_957_000) == 1000

    def test_small_negative(self):
        assert self.offset(37_957_000, 37_958_000) == -1000

    def test_wrong_relay_eleven_hours(self, pb):
        off = self.offset(77_999_687, 37_957_199)
        assert pb._format_offset(off) == '+11h07m'

    def test_near_midnight_does_not_read_as_24h(self):
        # remote just after midnight, local just before: should be small +, not ~-24h
        off = self.offset(1000, 86_399_000)
        assert off == 2000


# ===========================================================================
# _compute_stat('Drift')
# ===========================================================================

class TestComputeStatDrift:
    def test_not_probed_shows_dash(self, pb):
        m = make_monitor(pb)  # clock_state defaults to 'idle', offset None
        assert pb.Application._compute_stat(m, 'Drift').strip() == '-'

    def test_no_remote_time(self, pb):
        m = make_monitor(pb, clock_state='no-remote-time')
        assert pb.Application._compute_stat(m, 'Drift').strip() == 'no-rt'

    def test_ok_value(self, pb):
        m = make_monitor(pb, clock_state='ok', clock_offset_ms=-700)
        assert pb.Application._compute_stat(m, 'Drift').strip() == '-0.7s'

    def test_error_takes_precedence(self, pb):
        m = make_monitor(pb, clock_state='ok', clock_offset_ms=1000, error='boom')
        assert pb.Application._compute_stat(m, 'Drift').strip() == '??'


class TestComputeStatRTime:
    """RTime shows the remote clock time-of-day (UTC), not the offset."""

    def test_not_probed_shows_dash(self, pb):
        m = make_monitor(pb)
        assert pb.Application._compute_stat(m, 'RTime').strip() == '-'

    def test_no_remote_time(self, pb):
        m = make_monitor(pb, clock_state='no-remote-time')
        assert pb.Application._compute_stat(m, 'RTime').strip() == 'no-rt'

    def test_ok_shows_hms(self, pb):
        # A live-estimated HH:MM:SS clock string (local + offset).
        m = make_monitor(pb, clock_state='ok', clock_offset_ms=0)
        val = pb.Application._compute_stat(m, 'RTime').strip()
        assert len(val) == 8 and val.count(':') == 2, val

    def test_offset_shifts_displayed_time(self, pb):
        # A +1h offset must move the shown hour one ahead of the local hour.
        import time
        m0 = make_monitor(pb, clock_state='ok', clock_offset_ms=0)
        m1 = make_monitor(pb, clock_state='ok', clock_offset_ms=3600_000)
        h0 = int(pb.Application._compute_stat(m0, 'RTime').strip()[:2])
        h1 = int(pb.Application._compute_stat(m1, 'RTime').strip()[:2])
        assert (h0 + 1) % 24 == h1


# ===========================================================================
# _display_stale — gray frozen stats while the host is down
# ===========================================================================

class TestDisplayStale:
    """Down/error hosts render frozen stats (Drift/RTime, Avg/Min/Max/StDev)
    in gray.  The values keep displaying, but RTime stops ticking — it
    freezes at the remote time of the last probe."""

    def test_alive_host_not_stale(self, pb):
        m = make_monitor(pb, alive=True)
        assert not pb.Application._display_stale(m)

    def test_down_host_stale(self, pb):
        m = make_monitor(pb, alive=False)
        assert pb.Application._display_stale(m)

    def test_never_replied_stale(self, pb):
        m = make_monitor(pb)  # alive defaults to None (still connecting)
        assert pb.Application._display_stale(m)

    def test_error_host_stale(self, pb):
        m = make_monitor(pb, alive=True, error='boom')
        assert pb.Application._display_stale(m)

    def test_down_host_keeps_showing_values(self, pb):
        # The value is not blanked when the host goes down — only grayed.
        m = make_monitor(pb, alive=False, clock_state='ok',
                         clock_offset_ms=-1000)
        assert pb.Application._compute_stat(m, 'Drift').strip() == '-1.0s'
        val = pb.Application._compute_stat(m, 'RTime').strip()
        assert len(val) == 8 and val.count(':') == 2, val

    def test_down_host_rtime_frozen_at_last_probe(self, pb):
        # RTime stops ticking when down: it shows the remote clock as of
        # the last successful probe, not a live extrapolation.
        import time
        age = 3600.0
        m = make_monitor(pb, alive=False, clock_state='ok', clock_offset_ms=0,
                         _clock_ts=time.monotonic() - age)
        val = pb.Application._compute_stat(m, 'RTime').strip()
        h, mn, s = (int(x) for x in val.split(':'))
        shown = h * 3600 + mn * 60 + s
        expect = int(time.time() - age) % 86400
        diff = abs(shown - expect)
        assert min(diff, 86400 - diff) <= 2, (val, expect)

    def test_alive_host_rtime_ticks_live(self, pb):
        # An alive host ignores the probe age — the clock stays live.
        import time
        m = make_monitor(pb, alive=True, clock_state='ok', clock_offset_ms=0,
                         _clock_ts=time.monotonic() - 3600.0)
        val = pb.Application._compute_stat(m, 'RTime').strip()
        h, mn, s = (int(x) for x in val.split(':'))
        shown = h * 3600 + mn * 60 + s
        expect = int(time.time()) % 86400
        diff = abs(shown - expect)
        assert min(diff, 86400 - diff) <= 2, (val, expect)


# ===========================================================================
# :set stats drift / rtime  and  :set clock-interval
# ===========================================================================

class TestSetCommands:
    def test_drift_alias(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._dispatch_cmd(':set stats drift')
        assert app.stats_custom == ['Drift']
        assert app._clock_enabled()

    def test_rtime_is_distinct_column(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._dispatch_cmd(':set stats rtime')
        assert app.stats_custom == ['RTime']   # not the same as Drift
        assert app._clock_enabled()

    def test_rtime_and_drift_together(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._dispatch_cmd(':set stats rtime,drift')
        assert app.stats_custom == ['RTime', 'Drift']

    def test_drift_in_comma_list(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._dispatch_cmd(':set stats last,drift,avg')
        assert app.stats_custom == ['Last', 'Drift', 'Avg']
        assert app._clock_enabled()

    def test_clock_disabled_by_default(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        assert not app._clock_enabled()

    def test_clock_interval_default(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        assert app.clock_interval == 30.0

    def test_clock_interval_set(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._dispatch_cmd(':set clock-interval 60')
        assert app.clock_interval == 60.0

    def test_clock_interval_rejects_nonpositive(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._dispatch_cmd(':set clock-interval 0')
        assert app.clock_interval == 30.0  # unchanged


# ===========================================================================
# Probe target IP resolution
# ===========================================================================

class TestProbeTargetIp:
    def test_prefers_resolved_ip(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb, host='example.test', resolved_ip='10.9.8.7')
        assert app._clock_probe_target_ip(m) == '10.9.8.7'

    def test_literal_ip_host(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb, host='10.1.2.3')
        assert app._clock_probe_target_ip(m) == '10.1.2.3'


class TestProbeCmd:
    """Command construction — local ping vs SSH (remote-ping) branch."""

    def test_local_ping_cmd(self, pb):
        m = pb.PingMonitor('10.1.2.3')
        assert pb.Application._clock_probe_cmd(m, '10.1.2.3') == [
            'ping', '-n', '-c', '1', '-W', '2', '-T', 'tsandaddr', '10.1.2.3']

    def test_remote_ping_cmd_uses_ssh_args(self, pb):
        # SshPingMonitor runs the probe on the relay, reusing its SSH args.
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@relay'], ping_host='10.0.0.5')
        cmd = pb.Application._clock_probe_cmd(m, '10.0.0.5')
        assert cmd == [
            'ssh', '-o', 'BatchMode=yes', '-J', 'bastion', 'user@relay',
            'ping', '-n', '-c', '1', '-W', '2', '-T', 'tsandaddr', '10.0.0.5']


# ===========================================================================
# _run_clock_probe — the no-rt verdict state machine
# ===========================================================================

class TestNoRtVerdict:
    """'no-remote-time' needs _CLOCK_NO_RT_PROBES consecutive failures: each
    probe is a single packet, so one lost packet must not permanently brand
    a timestamp-capable host as unsupported."""

    @staticmethod
    def probe(pb, app, m, result):
        from unittest.mock import patch
        with patch.object(app, '_clock_probe_once', return_value=result):
            app._run_clock_probe(m)

    def test_verdict_needs_consecutive_failures(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb)
        for i in range(pb._CLOCK_NO_RT_PROBES - 1):
            self.probe(pb, app, m, None)
            assert m.clock_state == 'idle', f"probe {i + 1} must not decide"
        self.probe(pb, app, m, None)
        assert m.clock_state == 'no-remote-time'

    def test_success_resets_failure_count(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = make_monitor(pb)
        self.probe(pb, app, m, None)
        self.probe(pb, app, m, None)
        self.probe(pb, app, m, 1500)          # answers on the third try
        assert m.clock_state == 'ok'
        assert m.clock_offset_ms == 1500
        assert m._clock_fails == 0
        # A later transient failure keeps 'ok' and never re-counts to no-rt.
        for _ in range(pb._CLOCK_NO_RT_PROBES + 1):
            self.probe(pb, app, m, None)
        assert m.clock_state == 'ok'
        assert m.clock_offset_ms == 1500

    def test_failed_probes_schedule_retry(self, pb, tmp_path):
        import time
        app = make_app(pb, tmp_path)
        m = make_monitor(pb)
        self.probe(pb, app, m, None)
        assert m.clock_state == 'idle'
        assert m._clock_next_ts > time.monotonic(), \
            "a non-final failure must schedule the next attempt"
