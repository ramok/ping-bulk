"""Tests for relay OS support: ':relay-os', the '--os' flag, per-OS ping
commands, the FreeBSD and RouterOS parsers, and 'uname -s' auto-detection.

Every fixture line below is real output captured from the machines this
feature was built against (FreeBSD 14.3/OPNsense, RouterOS 7.22) — see the
shapes quoted in the parsers' docstrings in ping-bulk itself.

Monitor loop tests follow test_ssh_monitor_loop.py: a FakeProc on real OS
pipes stands in for the ssh child, and monitors are built with an explicit
relay_os so the loop never runs the detection probe (detection is tested
directly, with subprocess.run patched).
"""

import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from proc_helper import FakeProc
from utils.hosts_helper import write_hosts


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

# RouterOS 7.22, captured from `ssh admin@10.123.254.1 /ping <target>`.
_ROS_HEADER = ('  SEQ HOST                                     SIZE TTL TIME'
               '       STATUS      \n')
_ROS_REPLY = ('    0 10.0.0.1                                   56  64 349us'
              '     \n')
_ROS_REPLY_COMPOSITE = ('    2 10.0.0.1                                   56'
                        '  64 1ms433us  \n')
_ROS_TIMEOUT = ('    1 10.0.0.1                                             '
                '      timeout     \n')
# An ICMP error row names the *reporting* router in HOST and carries that
# router's own round-trip in TIME — it must not be read as a reply.
_ROS_ERROR_ROW = ('    3 10.9.9.1                                   84  64 '
                  '134ms76us  host unre...\n')
_ROS_SUMMARY = ('    sent=6 received=6 packet-loss=0% min-rtt=261us '
                'avg-rtt=355us \n')

# FreeBSD 14.3, captured from `ssh root@10.111.1.1 ping <target>`.
_FBSD_BANNER = 'PING 10.0.0.1 (10.0.0.1): 56 data bytes\n'
_FBSD_REPLY = '64 bytes from 10.0.0.1: icmp_seq=%d ttl=64 time=0.197 ms\n'


def _ssh_monitor(pb, ping_host='10.0.0.1', ssh_dest='relay', relay_os='linux'):
    return pb.SshPingMonitor([ssh_dest], ping_host, relay_os=relay_os)


def _wait_for(predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if predicate():
            return True
        time.sleep(0.01)
    return False


def _run_until(monitor, proc, predicate, timeout=5.0):
    """Run monitor.ping() against *proc* until *predicate* holds, then stop."""
    with patch('subprocess.Popen', return_value=proc):
        t = threading.Thread(target=monitor.ping, daemon=True)
        t.start()
        ok = _wait_for(predicate, timeout)
        monitor.running = False
        proc.cleanup()
        t.join(5.0)
    return ok


def make_app(pb, tmp_path, entries=None):
    cfg_path = str(tmp_path / 'ping-bulk' / 'config')
    with patch.object(pb, '_config_path', return_value=cfg_path):
        app = pb.Application(entries or [])
    return app


@pytest.fixture
def fresh_detection(pb, monkeypatch):
    """Give each test its own detection cache: pb is session-scoped."""
    monkeypatch.setattr(pb, '_relay_os_cache', {})
    monkeypatch.setattr(pb, '_relay_os_locks', {})


def _uname_result(stdout='', stderr='', returncode=0):
    return SimpleNamespace(stdout=stdout, stderr=stderr,
                           returncode=returncode)


# ---------------------------------------------------------------------------
# RouterOS time parser
# ---------------------------------------------------------------------------

class TestRouterosTimeParser:
    def test_microseconds(self, pb):
        assert pb._parse_routeros_time('349us') == pytest.approx(0.349)

    def test_composite_ms_us(self, pb):
        assert pb._parse_routeros_time('1ms433us') == pytest.approx(1.433)

    def test_milliseconds(self, pb):
        assert pb._parse_routeros_time('12ms') == pytest.approx(12.0)

    def test_seconds(self, pb):
        assert pb._parse_routeros_time('2s') == pytest.approx(2000.0)

    def test_bare_integer_is_ms(self, pb):
        """RouterOS v6 prints TIME as a bare integer of milliseconds."""
        assert pb._parse_routeros_time('12') == pytest.approx(12.0)

    def test_rejects_non_time_tokens(self, pb):
        for token in ('timeout', '10.0.0.1', 'SEQ', 'host', 'ms', '1x2'):
            assert pb._parse_routeros_time(token) is None, token


# ---------------------------------------------------------------------------
# Per-OS ping command
# ---------------------------------------------------------------------------

class TestOsPingCommands:
    def _prepared(self, pb, relay_os, ssh_args=None):
        m = pb.SshPingMonitor(ssh_args or ['user@remote'], 'target.host',
                              relay_os=relay_os)
        m._prepare_spawn()
        return m

    def test_linux_cmd_unchanged(self, pb):
        m = self._prepared(pb, 'linux')
        assert m._build_ping_cmd() == (
            ['ssh', '-o', 'BatchMode=yes']
            + pb._ssh_sharing_flags(False) + pb._ssh_quiet_flags()
            + pb._ssh_monitor_flags()
            + ['user@remote', 'ping', '-O', '-D', 'target.host'])

    def test_mikrotik_cmd(self, pb):
        m = self._prepared(pb, 'mikrotik')
        assert m._build_ping_cmd() == (
            ['ssh', '-o', 'BatchMode=yes']
            + pb._ssh_sharing_flags(False) + pb._ssh_quiet_flags()
            + pb._ssh_monitor_flags()
            + ['user@remote', '/ping', 'target.host'])

    def test_freebsd_cmd_has_ready_marker_and_keepalive(self, pb):
        m = self._prepared(pb, 'freebsd')
        cmd = m._build_ping_cmd()
        assert cmd == (
            ['ssh', '-o', 'BatchMode=yes']
            + pb._ssh_sharing_flags(False) + pb._ssh_quiet_flags()
            + pb._ssh_monitor_flags()
            + ['-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=3',
               'user@remote',
               f'echo {pb._FBSD_READY_MARKER}; exec ping target.host'])
        assert cmd.count('ServerAliveInterval=5') == 1

    def test_freebsd_keepalive_yields_to_user_choice(self, pb):
        m = self._prepared(pb, 'freebsd',
                           ssh_args=['-o', 'ServerAliveInterval=30',
                                     'user@remote'])
        cmd = m._build_ping_cmd()
        assert 'ServerAliveInterval=5' not in cmd
        assert 'ServerAliveInterval=30' in cmd

    def test_profile_applies_watchdog_tuning(self, pb):
        m = self._prepared(pb, 'freebsd')
        assert m._STALE_MAX_WINDOWS > 1000, \
            "freebsd must never kill the child for silence"
        linux = self._prepared(pb, 'linux')
        assert linux._STALE_MAX_WINDOWS == pb.SubprocessMonitor._STALE_MAX_WINDOWS

    def test_fatal_wordings_are_per_os(self, pb):
        ros = self._prepared(pb, 'mikrotik')
        assert ros._is_fatal_error('failure: resolve failed (:ping; line 1)')
        assert ros._is_fatal_error('bad command name uname (line 1 column 1)')
        fbsd = self._prepared(pb, 'freebsd')
        assert fbsd._is_fatal_error(
            'ping: cannot resolve nosuchhost.invalid: Name does not resolve')
        linux = self._prepared(pb, 'linux')
        assert not linux._is_fatal_error('failure: resolve failed (:ping; line 1)')
        assert not linux._is_fatal_error('ping: cannot resolve x: …')


# ---------------------------------------------------------------------------
# RouterOS read loop
# ---------------------------------------------------------------------------

class TestMikrotikLoop:
    def test_reply_row_sets_alive_and_latency(self, pb):
        m = _ssh_monitor(pb, relay_os='mikrotik')
        proc = FakeProc(stdout_lines=[_ROS_HEADER, _ROS_REPLY], close=False)
        assert _run_until(m, proc, lambda: m.rx_count == 1)
        assert m.alive is True
        assert m.latency == pytest.approx(0.349)

    def test_composite_time_parsed(self, pb):
        m = _ssh_monitor(pb, relay_os='mikrotik')
        proc = FakeProc(stdout_lines=[_ROS_REPLY_COMPOSITE], close=False)
        assert _run_until(m, proc, lambda: m.rx_count == 1)
        assert m.latency == pytest.approx(1.433)

    def test_header_and_summary_are_ignored(self, pb):
        m = _ssh_monitor(pb, relay_os='mikrotik')
        proc = FakeProc(stdout_lines=[_ROS_HEADER, _ROS_SUMMARY, _ROS_REPLY],
                        close=False)
        assert _run_until(m, proc, lambda: m.rx_count == 1)
        assert m.ping_count == 1, "only the reply row is a probe result"
        assert m.xx_count == 0

    def test_timeout_row_becomes_backdated_loss(self, pb):
        """A 'timeout' row goes through the same _pending machinery as '-O'."""
        m = _ssh_monitor(pb, relay_os='mikrotik')
        proc = FakeProc(stdout_lines=[_ROS_TIMEOUT], close=False)
        assert _run_until(m, proc, lambda: bool(m._pending))
        assert m.xx_count == 0, "outstanding, not yet lost"
        heard = m._pending[1]
        m._expire_pending(time.time() + 2.0, 1.0)
        assert m.xx_count == 1
        # Dated at the probe's send time, one interval before the row.
        assert m.history_times[-1] == pytest.approx(
            heard - m._PING_PROBE_INTERVAL)

    def test_error_row_with_time_is_a_loss_not_a_reply(self, pb):
        """'3 10.9.9.1 84 64 134ms76us host unre...' — the TIME belongs to the
        reporting router, so reading it as a reply would fake a 134 ms echo."""
        m = _ssh_monitor(pb, relay_os='mikrotik')
        proc = FakeProc(stdout_lines=[_ROS_ERROR_ROW], close=False)
        assert _run_until(m, proc, lambda: bool(m._pending))
        assert m.rx_count == 0
        assert m.latency is None
        m._expire_pending(time.time() + 2.0, 1.0)
        assert m.xx_count == 1


# ---------------------------------------------------------------------------
# FreeBSD read loop
# ---------------------------------------------------------------------------

class TestFreebsdLoop:
    def test_replies_parse_with_seq_zero_base(self, pb):
        m = _ssh_monitor(pb, relay_os='freebsd')
        proc = FakeProc(stdout_lines=[f'{pb._FBSD_READY_MARKER}\n',
                                      _FBSD_BANNER,
                                      _FBSD_REPLY % 0, _FBSD_REPLY % 1],
                        close=False)
        assert _run_until(m, proc, lambda: m.rx_count == 2)
        assert m.alive is True
        assert m.latency == pytest.approx(0.197)
        assert m.xx_count == 0

    def test_seq_gap_backfills_losses(self, pb):
        """seq 0 then seq 4 → probes 1-3 were lost, back-dated 1 s apart."""
        m = _ssh_monitor(pb, relay_os='freebsd')
        m._prepare_spawn()
        t0 = 1700000000.0
        assert pb._fbsd_parse_line(m, (_FBSD_REPLY % 0).strip(), t0)
        assert pb._fbsd_parse_line(m, (_FBSD_REPLY % 4).strip(), t0 + 4.0)
        assert m.rx_count == 2
        assert m.xx_count == 3
        # Oldest first, ending one interval before the recovering reply.
        assert list(m.history_times)[-4:-1] == [
            pytest.approx(t0 + 1.0), pytest.approx(t0 + 2.0),
            pytest.approx(t0 + 3.0)]

    def test_silence_synthesis_is_reconciled_by_seq_gap(self, pb):
        """Losses already synthesised from silence are not billed again."""
        m = _ssh_monitor(pb, relay_os='freebsd')
        m._prepare_spawn()
        t0 = 1700000000.0
        assert pb._fbsd_parse_line(m, (_FBSD_REPLY % 0).strip(), t0)
        m._record_silence_losses(t0 + 4.2)     # 4.2 s minus 1 s margin → 3
        assert m.xx_count == 3
        pb._fbsd_parse_line(m, (_FBSD_REPLY % 4).strip(), t0 + 4.3)
        assert m.xx_count == 3, "the seq gap was already covered by silence"
        assert m.rx_count == 2

    def test_reply_jitter_is_not_a_loss(self, pb):
        """Measured: replies arrive 0.94-1.10 s apart through a real relay.
        A gap a little over one interval must not book a loss — that read as
        25 % loss on a host that was answering every probe."""
        m = _ssh_monitor(pb, relay_os='freebsd')
        m._prepare_spawn()
        t0 = 1700000000.0
        pb._fbsd_parse_line(m, (_FBSD_REPLY % 0).strip(), t0)
        m._record_silence_losses(t0 + 1.10)
        m._record_silence_losses(t0 + 1.97)
        assert m.xx_count == 0

    def test_out_of_order_reply_records_no_loss(self, pb):
        m = _ssh_monitor(pb, relay_os='freebsd')
        m._prepare_spawn()
        t0 = 1700000000.0
        pb._fbsd_parse_line(m, (_FBSD_REPLY % 5).strip(), t0)
        pb._fbsd_parse_line(m, (_FBSD_REPLY % 4).strip(), t0 + 0.2)
        assert m.rx_count == 2
        assert m.xx_count == 0

    def test_reorder_does_not_drag_the_anchor_backwards(self, pb):
        """5, 4, 6 is one reordered reply and no loss.  Moving the anchor to
        4 makes the 6 look like a two-probe gap and books a phantom loss."""
        m = _ssh_monitor(pb, relay_os='freebsd')
        m._prepare_spawn()
        t0 = 1700000000.0
        for seq, dt in ((5, 0.0), (4, 0.2), (6, 1.0)):
            pb._fbsd_parse_line(m, (_FBSD_REPLY % seq).strip(), t0 + dt)
        assert m.rx_count == 3
        assert m.xx_count == 0

    def test_duplicate_reply_is_not_a_gap(self, pb):
        m = _ssh_monitor(pb, relay_os='freebsd')
        m._prepare_spawn()
        t0 = 1700000000.0
        pb._fbsd_parse_line(m, (_FBSD_REPLY % 7).strip(), t0)
        pb._fbsd_parse_line(m, (_FBSD_REPLY % 7).strip(), t0 + 0.1)
        assert m.xx_count == 0

    def test_renumbered_child_reanchors_without_synthesising(self, pb):
        """A restarted ping numbers from 0 again.  The anchor has to follow
        it — otherwise every later reply reads as a backwards jump and
        nothing is ever reconciled again."""
        m = _ssh_monitor(pb, relay_os='freebsd')
        m._prepare_spawn()
        t0 = 1700000000.0
        pb._fbsd_parse_line(m, (_FBSD_REPLY % 2000).strip(), t0)
        pb._fbsd_parse_line(m, (_FBSD_REPLY % 0).strip(), t0 + 1.0)
        assert m.xx_count == 0
        # …and the new numbering is reconciled from there on.
        pb._fbsd_parse_line(m, (_FBSD_REPLY % 2).strip(), t0 + 3.0)
        assert m.xx_count == 1

    def test_seq_wrap_is_not_a_flood_of_losses(self, pb):
        m = _ssh_monitor(pb, relay_os='freebsd')
        m._prepare_spawn()
        t0 = 1700000000.0
        pb._fbsd_parse_line(m, (_FBSD_REPLY % 65535).strip(), t0)
        pb._fbsd_parse_line(m, (_FBSD_REPLY % 0).strip(), t0 + 1.0)
        assert m.xx_count == 0

    def test_marker_is_not_a_result_line(self, pb):
        """A run that produced only the marker must classify like one that
        never got a reply — its stderr still decides fatal, and its backoff
        keeps growing."""
        m = _ssh_monitor(pb, relay_os='freebsd')
        m._prepare_spawn()
        assert pb._fbsd_parse_line(m, pb._FBSD_READY_MARKER,
                                   1700000000.0) is False
        assert m._stale_without_output is True

    def test_down_target_synthesises_losses_without_killing(self, pb):
        """Measured: a down target through a FreeBSD relay is silent from the
        first byte.  After the ready marker, silence must become ~1/s losses
        and the ssh child must NOT be killed by the stale watchdog."""
        m = _ssh_monitor(pb, relay_os='freebsd')
        proc = FakeProc(stdout_lines=[f'{pb._FBSD_READY_MARKER}\n'],
                        close=False)
        with patch.object(pb._RelayOsFreebsd, 'stale_secs', 0.05):
            assert _run_until(m, proc, lambda: m.xx_count >= 1, timeout=5.0)
        assert proc.terminated is False, \
            "silence means the target is down, not that the child is wedged"
        assert m.alive is False

    def test_silence_before_marker_is_not_loss(self, pb):
        """A slow ssh connect (no marker yet) must not be reported as loss."""
        m = _ssh_monitor(pb, relay_os='freebsd')
        proc = FakeProc(close=False)           # silent: still connecting
        with patch.object(pb._RelayOsFreebsd, 'stale_secs', 0.05):
            with patch('subprocess.Popen', return_value=proc):
                t = threading.Thread(target=m.ping, daemon=True)
                t.start()
                time.sleep(0.5)                # several stale windows
                m.running = False
                proc.cleanup()
                t.join(5.0)
        assert m.xx_count == 0
        assert None not in m.history


# ---------------------------------------------------------------------------
# Auto-detection
# ---------------------------------------------------------------------------

class TestDetection:
    def test_linux_uname(self, pb, fresh_detection):
        with patch('subprocess.run',
                   return_value=_uname_result('Linux\n')) as run:
            assert pb._detect_relay_os(['user@r1'], 'user@r1') == 'linux'
        assert run.call_count == 1
        cmd = run.call_args[0][0]
        assert cmd[-2:] == ['uname', '-s']
        assert 'user@r1' in cmd

    def test_freebsd_uname(self, pb, fresh_detection):
        with patch('subprocess.run', return_value=_uname_result('FreeBSD\n')):
            assert pb._detect_relay_os(['root@r2'], 'root@r2') == 'freebsd'

    def test_routeros_bad_command(self, pb, fresh_detection):
        """RouterOS has no uname; measured on 7.22, exit code 1."""
        err = 'bad command name uname (line 1 column 1)\n'
        with patch('subprocess.run',
                   return_value=_uname_result('', err, returncode=1)):
            assert pb._detect_relay_os(['admin@r3'], 'admin@r3') == 'mikrotik'

    def test_result_is_cached_per_ssh_args(self, pb, fresh_detection):
        with patch('subprocess.run',
                   return_value=_uname_result('Linux\n')) as run:
            pb._detect_relay_os(['user@r4'], 'user@r4')
            pb._detect_relay_os(['user@r4'], 'user@r4')
        assert run.call_count == 1, "one probe per relay, cached afterwards"

    def test_connection_failure_falls_back_without_caching(self, pb,
                                                           fresh_detection,
                                                           monkeypatch):
        """A relay that is down at startup must not be branded linux forever."""
        monkeypatch.setattr(pb, '_relay_os_retry_after', {})
        monkeypatch.setattr(pb, '_RELAY_OS_RETRY_PAUSE', 0.0)
        kex = 'kex_exchange_identification: read: Connection reset by peer\n'
        with patch('subprocess.run',
                   return_value=_uname_result('', kex, returncode=255)) as run:
            assert pb._detect_relay_os(['user@r5'], 'user@r5') == 'linux'
            assert pb._detect_relay_os(['user@r5'], 'user@r5') == 'linux'
        assert run.call_count == 2, "an unanswered probe must not be cached"

    def test_failed_probe_is_not_retried_by_every_host(self, pb,
                                                       fresh_detection,
                                                       monkeypatch):
        """All hosts behind one relay share the key, so without a pause they
        queue on its lock and each pays the probe's timeout before it may
        even try its own ping — 47 waits for one unreachable relay."""
        monkeypatch.setattr(pb, '_relay_os_retry_after', {})
        kex = 'kex_exchange_identification: read: Connection reset by peer\n'
        with patch('subprocess.run',
                   return_value=_uname_result('', kex, returncode=255)) as run:
            for _ in range(10):
                assert pb._detect_relay_os(['user@r9'], 'user@r9') == 'linux'
        assert run.call_count == 1, "one probe per relay per pause"

    def test_probe_bounds_its_own_connect(self, pb, fresh_detection,
                                          monkeypatch):
        monkeypatch.setattr(pb, '_relay_os_retry_after', {})
        with patch('subprocess.run',
                   return_value=_uname_result('Linux\n')) as run:
            pb._detect_relay_os(['user@r10'], 'user@r10')
        assert 'ConnectTimeout=10' in run.call_args[0][0], \
            "a black-holed relay would otherwise sit in the TCP handshake"

    def test_probe_is_paced_through_the_spawn_gate(self, pb, fresh_detection):
        gates = []
        with patch.object(pb, '_ssh_spawn_gate', side_effect=gates.append):
            with patch('subprocess.run',
                       return_value=_uname_result('Linux\n')):
                pb._detect_relay_os(['-J', 'hop1,hop2', 'user@r6'], 'user@r6')
        assert gates == ['hop1'], \
            "the probe authenticates to the first jump hop, like any monitor"

    def test_auto_monitor_detects_before_spawn(self, pb, fresh_detection):
        """An 'auto' monitor resolves its profile in _prepare_spawn."""
        m = pb.SshPingMonitor(['admin@r7'], '10.0.0.1')   # default: auto
        err = 'bad command name uname (line 1 column 1)\n'
        with patch('subprocess.run',
                   return_value=_uname_result('', err, returncode=1)):
            m._prepare_spawn()
        assert m._relay_os_resolved == 'mikrotik'
        assert m._build_ping_cmd()[-2:] == ['/ping', '10.0.0.1']


# ---------------------------------------------------------------------------
# :relay-os command and precedence
# ---------------------------------------------------------------------------

class TestRelayOsCommand:
    def test_flag_beats_rule(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_relay_os('relay* linux')
        app._cmd_remote_ping('--os mikrotik user@relay1 10.0.0.1')
        m = app.monitors[0]
        assert m._relay_os_declared == 'mikrotik'

    def test_rule_applies_to_existing_monitor(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('user@relay2 10.0.0.2')
        m = app.monitors[0]
        assert m._relay_os_declared == 'auto'
        app._cmd_relay_os('relay2 freebsd')
        assert m._relay_os_declared == 'freebsd'

    def test_rule_matches_with_and_without_username(self, pb, tmp_path):
        """Same name resolution as :no-alarm: a plain name matches exactly,
        with or without the user@ prefix."""
        app = make_app(pb, tmp_path)
        app._cmd_relay_os('relay3 mikrotik')
        app._cmd_remote_ping('admin@relay3 10.0.0.3')
        assert app.monitors[0]._relay_os_declared == 'mikrotik'

    def test_rule_matches_resolv_alias(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.5.5.5 myrelay')
        app._cmd_relay_os('myrelay freebsd')
        app._cmd_remote_ping('admin@myrelay 10.0.0.9')
        assert app.monitors[0]._relay_os_declared == 'freebsd'

    def test_last_matching_rule_wins(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_relay_os('r* linux')
        app._cmd_relay_os('relay4 mikrotik')
        app._cmd_remote_ping('user@relay4 10.0.0.4')
        assert app.monitors[0]._relay_os_declared == 'mikrotik'

    def test_same_pattern_is_replaced_not_stacked(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_relay_os('relay5 linux')
        app._cmd_relay_os('relay5 freebsd')
        assert app.relay_os_rules == [('relay5', 'freebsd')]

    def test_routeros_alias_normalised(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_relay_os('relay6 routeros')
        assert app.relay_os_rules == [('relay6', 'mikrotik')]

    def test_unknown_os_rejected(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_relay_os('relay7 windows')
        assert app.relay_os_rules == []

    def test_remove_rule(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_relay_os('relay8 freebsd')
        app._cmd_relay_os('--remove relay8')
        assert app.relay_os_rules == []

    def test_changed_declaration_requests_respawn(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('user@relay9 10.0.0.9')
        m = app.monitors[0]
        m._relay_os_resolved = 'linux'          # as if a spawn resolved auto
        app._cmd_relay_os('relay9 mikrotik')
        assert m._relay_os_resolved is None, \
            "a changed OS must be re-resolved on the next spawn"

    def test_unknown_os_flag_warns_and_detects(self, pb, tmp_path):
        """A typo must not cost the host: dropping it would take out every
        host in a ':with remote-ping --os …' block."""
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('--os windows user@relay 10.0.0.1')
        assert len(app.monitors) == 1
        assert app.monitors[0]._relay_os_declared == 'auto'
        assert any('unknown --os' in e.text for e in app.events)

    def test_explicit_auto_beats_a_rule(self, pb, tmp_path):
        """'--os auto' is how one relay is excused from a glob that claims
        it; the flag is documented as beating any rule."""
        app = make_app(pb, tmp_path)
        app._cmd_relay_os('relay* mikrotik')
        app._cmd_remote_ping('--os auto user@relay1 10.0.0.1')
        assert app.monitors[0]._relay_os_declared == 'auto'

    def test_repeated_os_flag_leaves_nothing_for_ssh(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('--os freebsd --os mikrotik user@relay 10.0.0.1')
        m = app.monitors[0]
        assert '--os' not in m._ssh_args
        assert 'mikrotik' not in m._ssh_args
        assert m._relay_os_declared == 'freebsd'

    def test_remove_without_a_pattern_is_a_usage_error(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_relay_os('relay8 freebsd')
        app._cmd_relay_os('--remove')
        assert app.relay_os_rules == [('relay8', 'mikrotik')] or \
            app.relay_os_rules == [('relay8', 'freebsd')]
        assert any('missing host or glob' in e.text for e in app.events)

    def test_rule_written_after_the_hosts_still_applies(self, pb, tmp_path):
        """The safety net ':no-alarm' has: rules may follow the host lines."""
        content = """\
            :with remote-ping admin@late-relay
            10.0.0.1
            :end
            :relay-os late-relay mikrotik
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        app = make_app(pb, tmp_path, entries)
        relayed = [m for m in app.monitors
                   if isinstance(m, pb.SshPingMonitor)]
        assert relayed and relayed[0]._relay_os_declared == 'mikrotik'

    def test_os_flag_never_reaches_ssh_args(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('--os freebsd -J bastion user@relay 10.0.0.1')
        m = app.monitors[0]
        assert '--os' not in m._ssh_args
        assert 'freebsd' not in m._ssh_args
        assert m._relay_os_declared == 'freebsd'

    def test_save_config_persists_rules(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_relay_os('*-router mikrotik')
        cfg_path = str(tmp_path / 'ping-bulk' / 'config')
        with patch.object(pb, '_config_path', return_value=cfg_path):
            app._save_config()
        with open(cfg_path) as f:
            assert ':relay-os *-router mikrotik\n' in f.read()


# ---------------------------------------------------------------------------
# Hosts-file parsing round-trips
# ---------------------------------------------------------------------------

class TestOsFlagParsing:
    def test_with_block_carries_os_flag(self, pb, tmp_path):
        content = """\
            :with remote-ping --os freebsd root@relay
            10.0.0.1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [v for k, v in entries if k == 'cmd']
        assert ':remote-ping --os freebsd root@relay 10.0.0.1' in cmds

    def test_nested_remote_ping_drops_outer_os_flag(self, pb, tmp_path):
        """The outer relay becomes a mere -J hop; its --os must not leak into
        the chained command where it would name the wrong machine."""
        content = """\
            :with remote-ping --os freebsd root@relay
            :remote-ping ops@inner 10.1.1.1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [v for k, v in entries if k == 'cmd']
        assert ':remote-ping -J root@relay ops@inner 10.1.1.1' in cmds

    def test_for_loop_chain_drops_outer_os_flag(self, pb, tmp_path):
        content = """\
            :with remote-ping --os mikrotik admin@gw
            :for node{1,2}
            :remote-ping user@jump$1 10.0.$1.1
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [v for k, v in entries if k == 'cmd']
        assert ':remote-ping -J admin@gw user@jump1 10.0.1.1' in cmds
        assert not any('--os' in c and '-J' in c for c in cmds)

    def test_bad_os_in_a_with_block_is_reported_once(self, pb, tmp_path):
        """Once, where the block is opened — not once per host it wraps —
        and the hosts are still monitored through the relay."""
        content = """\
            :with remote-ping --os bogus root@relay
            10.0.0.1
            10.0.0.2
            10.0.0.3
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        warns = [v for k, v in entries if k == 'warn']
        cmds = [v for k, v in entries if k == 'cmd']
        assert len(warns) == 1 and 'unknown --os' in warns[0]
        assert len([c for c in cmds if c.startswith(':remote-ping')]) == 3

    def test_with_block_label_resolv_survives_os_flag(self, pb, tmp_path):
        """'## label' on the :with line maps the relay IP even with --os."""
        content = """\
            :with remote-ping --os mikrotik admin@10.9.9.9 ## harbour-router
            10.0.0.1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [v for k, v in entries if k == 'cmd']
        assert ':resolv 10.9.9.9 harbour-router' in cmds


# ---------------------------------------------------------------------------
# MikroTik jump-host forwarding tip
# ---------------------------------------------------------------------------

class TestWatchdogCountsAnyOutput:
    """Regression: the kill counter must be reset by *any* output.

    A host that answers with an ICMP error makes iputils print a line per
    probe that this parser does not recognise ('From … Destination Host
    Unreachable' — no 'time=' and no 'no answer yet').  Counting staleness
    from the last *parsed result* killed the child every _STALE_MAX_WINDOWS
    windows, and a 52-host production run turned into a restart storm: 50
    'restarting ping' events and 13 'client_loop: send disconnect: Broken
    pipe' inside a minute, where the previous build had one restart in
    fourteen hours.
    """

    _UNREACH = 'From 10.123.254.2 icmp_seq=%d Destination Host Unreachable\n'

    def test_unparsed_stdout_does_not_kill_the_child(self, pb):
        # Patch the profile, not the instance: _prepare_spawn re-arms
        # _STALE_SECS from it on every spawn.  0.05 s windows mean the buggy
        # build would have reached its 3-window kill within ~0.15 s.
        m = _ssh_monitor(pb, relay_os='linux')
        proc = FakeProc(close=False)
        with patch.object(pb._RelayOsLinux, 'stale_secs', 0.05):
            with patch('subprocess.Popen', return_value=proc):
                t = threading.Thread(target=m.ping, daemon=True)
                t.start()
                deadline = time.time() + 1.0
                seq = 0
                while time.time() < deadline:
                    proc.feed_stdout(self._UNREACH % seq)
                    seq += 1
                    time.sleep(0.02)
                m.running = False
                proc.cleanup()
                t.join(5.0)
        assert proc.terminated is False, \
            "a child that is still talking must not be restarted"

    def test_unparsed_stderr_reports_loss_but_spares_the_child(self, pb):
        """FreeBSD's 'sendto: Host is down' keeps select busy every second.
        The loss must still be reported (it is this transport's only loss
        signal), and the child must still be left alone."""
        m = _ssh_monitor(pb, relay_os='freebsd')
        proc = FakeProc(stdout_lines=[f'{pb._FBSD_READY_MARKER}\n'],
                        close=False)
        with patch.object(pb._RelayOsFreebsd, 'stale_secs', 0.05):
            with patch('subprocess.Popen', return_value=proc):
                t = threading.Thread(target=m.ping, daemon=True)
                t.start()
                # Losses are counted in probe intervals with one interval of
                # jitter margin, so the first one lands after ~2 s of silence.
                deadline = time.time() + 3.0
                while time.time() < deadline and m.xx_count == 0:
                    proc.feed_stderr('ping: sendto: Host is down\n')
                    time.sleep(0.05)
                ok = m.xx_count >= 1
                m.running = False
                proc.cleanup()
                t.join(5.0)
        assert ok, "silence of *results* is still this transport's loss signal"
        assert proc.terminated is False


class TestTransportErrorPhrasing:
    """A ping/ssh complaint is rephrased around the host.

    'ping: sendmsg: No route to host' names the system call that failed; on
    its own in a log whose other lines are host states it reads as plumbing,
    and it says nothing about whether the host ever worked.  Which heading it
    gets depends on the host's history, not on the message.
    """

    _RAW = 'ping: sendmsg: No route to host'

    def _monitor(self, pb, rx=0, alive=None, up=None):
        m = _ssh_monitor(pb, relay_os='linux')
        m.rx_count, m.alive, m.up_since = rx, alive, up
        return m

    def test_never_up_is_a_startup_failure(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = self._monitor(pb)
        text = app._phrase_transport_error(m, self._RAW)
        assert text.startswith('host startup fail: no route to host')
        assert self._RAW in text, "the exact text stays greppable"

    def test_was_up_and_is_down_now(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = self._monitor(pb, rx=10, alive=False)
        assert app._phrase_transport_error(m, self._RAW).startswith(
            'host unreachable: no route to host')

    def test_answering_host_gets_probe_error(self, pb, tmp_path):
        """One failed probe on a live host is worth a line, not an alarm."""
        app = make_app(pb, tmp_path)
        m = self._monitor(pb, rx=10, alive=True, up=1.0)
        assert app._phrase_transport_error(m, self._RAW).startswith(
            'probe error: no route to host')

    def test_unrecognised_line_is_untouched(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        m = self._monitor(pb)
        raw = 'ping: local error: Message too long'
        assert app._phrase_transport_error(m, raw) == raw

    def test_jump_channel_close_is_diagnosed(self, pb):
        """'Connection closed by UNKNOWN port 65535' — with -J the relay
        connection rides a channel that has no peer address of its own, so
        ssh cannot name who closed it."""
        assert pb._host_diagnosis(
            'Connection closed by UNKNOWN port 65535').startswith(
                'ssh closed during handshake')

    def test_ssh_notices_are_suppressed(self, pb):
        """LogLevel=ERROR: ping-bulk opens one connection per host, and the
        host-key notice arrived once per host on every startup."""
        m = _ssh_monitor(pb, relay_os='linux')
        m._prepare_spawn()
        assert 'LogLevel=ERROR' in m._build_ping_cmd()

    def test_quiet_flag_applies_despite_a_user_ssh_options_value(self, pb):
        """It sits outside ':set ssh-options' on purpose: a value set once —
        or written by ':save-config' — would otherwise freeze that user on
        the defaults of whichever release wrote it."""
        m = _ssh_monitor(pb, relay_os='linux')
        m._prepare_spawn()
        with patch.object(pb, '_ssh_monitor_options', ['-o', 'ForwardX11=no']):
            assert 'LogLevel=ERROR' in m._build_ping_cmd()

    def test_user_log_level_wins(self, pb):
        m = pb.SshPingMonitor(['-o', 'LogLevel=DEBUG', 'user@r'], '10.0.0.1',
                              relay_os='linux')
        m._prepare_spawn()
        cmd = m._build_ping_cmd()
        assert 'LogLevel=ERROR' not in cmd
        assert 'LogLevel=DEBUG' in cmd

    def test_user_log_level_in_ssh_options_wins(self, pb):
        m = _ssh_monitor(pb, relay_os='linux')
        m._prepare_spawn()
        with patch.object(pb, '_ssh_monitor_options',
                          ['-o', 'LogLevel=INFO']):
            assert 'LogLevel=ERROR' not in m._build_ping_cmd()


class TestForwardingTip:
    def test_refused_channel_queues_the_tip_once(self, pb):
        m = _ssh_monitor(pb, relay_os='linux')
        refusal = 'channel 0: open failed: administratively prohibited: open failed'
        m._note_stderr(refusal)
        m._note_stderr(refusal)
        fresh = m.take_new_stderr()
        tips = [l for l in fresh if 'forwarding-enabled=both' in l]
        assert len(tips) == 1
        assert refusal in fresh

    def test_unrelated_stderr_gets_no_tip(self, pb):
        m = _ssh_monitor(pb, relay_os='linux')
        m._note_stderr('ssh: connect to host relay port 22: Connection refused')
        assert not any('forwarding-enabled' in l for l in m.take_new_stderr())
