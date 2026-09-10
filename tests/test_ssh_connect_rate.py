"""Unit tests for ':set ssh-connect-rate' — pacing SSH connection attempts.

ping-bulk opens one connection per monitored host at once: 20 relayed hosts
were measured spawning 20 `ssh` processes within 10 ms.  sshd's MaxStartups
defaults to 10:30:100 — random early drop from the 10th concurrent
*unauthenticated* connection — so a relay carrying dozens of hosts drops a
chunk of them at every startup.  A real 54-host log showed 10-20
`kex_exchange_identification: read: Connection reset by peer` per startup.

The gate is a leaky bucket per endpoint rather than a fixed per-host offset,
because the same storm happens on every mass reconnect: a relay restart has
every monitor retry at once and the backoff carries no jitter.
"""

import threading
import time
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _pristine_rate(pb):
    """Module-level state, shared by every test in a worker."""
    pb._ssh_connect_rate = pb._SSH_CONNECT_RATE_DEFAULT
    pb._ssh_spawn_next.clear()
    yield
    pb._ssh_connect_rate = pb._SSH_CONNECT_RATE_DEFAULT
    pb._ssh_spawn_next.clear()


@pytest.fixture
def app(pb, tmp_path):
    from unittest.mock import patch
    cfg = tmp_path / 'ping-bulk' / 'config'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('')
    with patch.object(pb, '_config_path', return_value=str(cfg)):
        a = pb.Application([('host', '10.0.0.1')])
    a._monitoring_started = True
    a._cfg_path = str(cfg)
    return a


class TestFirstHop:
    """The daemon under load is the one we authenticate to, not the target."""

    def test_plain_destination(self, pb):
        assert pb._ssh_first_hop(['relay'], 'relay') == 'relay'

    def test_jump_host_is_the_endpoint(self, pb):
        """With -J the local ssh authenticates to the jump host."""
        assert pb._ssh_first_hop(['-J', 'bastion', 'relay'], 'relay') == 'bastion'

    def test_first_of_a_jump_chain(self, pb):
        assert pb._ssh_first_hop(['-J', 'a,b,c', 'relay'], 'relay') == 'a'

    def test_inline_jump_form(self, pb):
        assert pb._ssh_first_hop(['-Jbastion', 'relay'], 'relay') == 'bastion'

    def test_no_args_falls_back_to_the_destination(self, pb):
        assert pb._ssh_first_hop([], 'relay') == 'relay'


class TestGate:

    def _elapsed(self, pb, endpoint, n):
        t0 = time.monotonic()
        for _ in range(n):
            pb._ssh_spawn_gate(endpoint)
        return time.monotonic() - t0

    def test_first_attempt_is_immediate(self, pb):
        assert self._elapsed(pb, 'relay', 1) < 0.05

    def test_attempts_are_paced(self, pb):
        pb._ssh_connect_rate = 20.0        # 50 ms apart
        elapsed = self._elapsed(pb, 'relay', 4)
        assert 0.12 < elapsed < 0.5, elapsed

    def test_rate_zero_disables_the_gate(self, pb):
        pb._ssh_connect_rate = 0
        assert self._elapsed(pb, 'relay', 20) < 0.05

    def test_endpoints_have_separate_budgets(self, pb):
        """Hosts on different relays must not wait for each other."""
        pb._ssh_connect_rate = 10.0
        t0 = time.monotonic()
        pb._ssh_spawn_gate('relayA')
        pb._ssh_spawn_gate('relayB')
        assert time.monotonic() - t0 < 0.05

    def test_the_budget_recovers_over_time(self, pb):
        """A leaky bucket, so a later reconnect is not charged for the past."""
        pb._ssh_connect_rate = 100.0
        pb._ssh_spawn_gate('relay')
        time.sleep(0.05)
        assert self._elapsed(pb, 'relay', 1) < 0.02

    def test_concurrent_threads_are_serialised(self, pb):
        """The storm is concurrent, so the gate has to hold across threads."""
        pb._ssh_connect_rate = 20.0
        stamps = []
        lock = threading.Lock()

        def go():
            pb._ssh_spawn_gate('relay')
            with lock:
                stamps.append(time.monotonic())

        threads = [threading.Thread(target=go) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(5)
        stamps.sort()
        assert stamps[-1] - stamps[0] > 0.15, stamps


class TestSpawnEndpoint:
    """Which monitors are paced, and against what."""

    def test_local_ping_is_not_paced(self, pb):
        """It contacts no daemon."""
        assert pb.PingMonitor('10.0.0.1')._spawn_endpoint() is None

    def test_relayed_host_is_paced_against_its_relay(self, pb):
        m = pb.SshPingMonitor(['relay'], '10.1.2.3')
        assert m._spawn_endpoint() == 'relay'

    def test_relayed_host_with_a_jump_uses_the_jump(self, pb):
        m = pb.SshPingMonitor(['-J', 'bastion', 'relay'], '10.1.2.3')
        assert m._spawn_endpoint() == 'bastion'

    def test_hosts_behind_one_relay_share_a_budget(self, pb):
        """The point of keying on the endpoint: MaxStartups is per-sshd."""
        a = pb.SshPingMonitor(['relay'], '10.1.2.3')
        b = pb.SshPingMonitor(['relay'], '10.1.2.4')
        assert a._spawn_endpoint() == b._spawn_endpoint()


class TestEveryConnectionKindIsPaced:
    """All three connections ping-bulk opens itself go through the gate.

    The clock probe was missed, and it is the worst offender: each host
    schedules the next probe one interval after the last, so they never
    drift apart and every host's probe comes due on the same tick.  A relay
    carrying 47 hosts therefore saw 47 simultaneous handshakes every
    clock-interval, far past sshd's MaxStartups — measured in a production
    log as a 6 s stall that restarted all 47 monitors at once.
    """

    def test_clock_probe_is_paced_against_the_jump_host(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        with patch.object(pb, '_config_path', return_value=cfg):
            app = pb.Application([])
        m = pb.SshPingMonitor(['-J', 'bastion', 'admin@relay'], '10.1.2.3')
        m.resolved_ip = '10.1.2.3'
        gates = []
        with patch.object(pb, '_ssh_spawn_gate', side_effect=gates.append):
            with patch('subprocess.run',
                       side_effect=OSError('not actually run')):
                app._clock_probe_once(m)
        assert gates == ['bastion'], \
            "the probe authenticates to the first hop, like any connection"

    def test_local_clock_probe_is_not_paced(self, pb, tmp_path):
        """A local 'ping -T' contacts no daemon."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        with patch.object(pb, '_config_path', return_value=cfg):
            app = pb.Application([])
        m = pb.PingMonitor('10.1.2.3')
        m.resolved_ip = '10.1.2.3'
        gates = []
        with patch.object(pb, '_ssh_spawn_gate', side_effect=gates.append):
            with patch('subprocess.run',
                       side_effect=OSError('not actually run')):
                app._clock_probe_once(m)
        assert gates == []


class TestSetCommand:

    def _last(self, app):
        return list(app.events)[-1].text.split('   ', 1)[-1]

    def test_sets_the_rate(self, app, pb):
        app._cmd_ssh_connect_rate('10')
        assert pb._ssh_connect_rate == 10.0

    def test_zero_is_accepted_as_no_limit(self, app, pb):
        app._cmd_ssh_connect_rate('0')
        assert pb._ssh_connect_rate == 0
        assert 'no limit' in self._last(app)

    def test_query_reports_the_rate(self, app):
        app._cmd_ssh_connect_rate('')
        assert '5/s' in self._last(app)

    @pytest.mark.parametrize('bad', ['-1', 'fast', ''])
    def test_invalid_values_are_refused(self, app, pb, bad):
        if bad == '':
            pytest.skip('empty is the query form')
        before = pb._ssh_connect_rate
        app._cmd_ssh_connect_rate(bad)
        assert pb._ssh_connect_rate == before
        assert 'invalid value' in self._last(app)

    def test_a_custom_rate_is_saved(self, app, pb):
        from unittest.mock import patch
        app._cmd_ssh_connect_rate('2')
        with patch.object(pb, '_config_path', return_value=app._cfg_path):
            app._save_config()
        assert any('ssh-connect-rate 2' in l for l in open(app._cfg_path))

    def test_the_default_is_not_saved(self, app, pb):
        from unittest.mock import patch
        with patch.object(pb, '_config_path', return_value=app._cfg_path):
            app._save_config()
        assert not any('ssh-connect-rate' in l for l in open(app._cfg_path))

    def test_round_trip(self, app, pb):
        from unittest.mock import patch
        app._cmd_ssh_connect_rate('2')
        with patch.object(pb, '_config_path', return_value=app._cfg_path):
            app._save_config()
            pb._ssh_connect_rate = 99.0
            pb.Application([('host', '10.0.0.1')])
        assert pb._ssh_connect_rate == 2.0
