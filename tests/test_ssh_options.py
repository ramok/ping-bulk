"""Unit tests for ':set ssh-options' — flags on ping-bulk's own SSH connections.

These options exist because a 'Host *' block in the user's ssh_config applies
to ping-bulk's monitoring connections too, where it makes no sense:

  ForwardX11 yes      -> "X11 forwarding request failed on channel 0" per host
  ControlMaster auto  -> many monitors behind one relay share one ControlPath
                         and race for it; the losers log "ControlSocket ...
                         already exists, disabling multiplexing"
  LocalForward ...     -> set up once per monitored host, first to bind wins

Interactive sessions ('c', 'C', ':mux ssh') are deliberately untouched.
"""

import os
import shlex

import pytest
from unittest.mock import patch


@pytest.fixture
def app(pb, tmp_path):
    cfg = tmp_path / 'ping-bulk' / 'config'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('')
    with patch.object(pb, '_config_path', return_value=str(cfg)):
        a = pb.Application([('host', '10.0.0.1')])
    a._monitoring_started = True
    a._cfg_path = str(cfg)
    return a


@pytest.fixture(autouse=True)
def _pristine_options(pb):
    """Pin the value before and after each test.

    The live value is module-level and the pb module is imported once per
    session, so it is shared by every test in a worker.  Restoring only on the
    way out is not enough: with a randomised order a test would inherit
    whatever the previous one left, which is exactly how this leaked.
    """
    pb._ssh_monitor_options = list(pb._SSH_MONITOR_OPTIONS_DEFAULT)
    yield
    pb._ssh_monitor_options = list(pb._SSH_MONITOR_OPTIONS_DEFAULT)


def _last(app):
    return list(app.events)[-1].text.split('   ', 1)[-1]


class TestDefaults:

    def test_x11_is_off(self, pb):
        """ping has no display; a relay without xauth refuses the channel."""
        flags = pb._ssh_monitor_flags()
        assert 'ForwardX11=no' in flags
        assert 'ForwardX11Trusted=no' in flags

    def test_forwardings_are_cleared(self, pb):
        assert 'ClearAllForwardings=yes' in pb._ssh_monitor_flags()

    def test_sharing_is_not_in_the_shared_default(self, pb):
        """It differs per connection kind — see TestConnectionSharing."""
        assert not any('Control' in f for f in pb._ssh_monitor_flags())

    def test_agent_forwarding_is_left_alone(self, pb):
        """It is how the next hop authenticates in a multi-jump chain."""
        assert not any('ForwardAgent' in f for f in pb._ssh_monitor_flags())


class TestAppliedToOwnConnections:

    def test_ping_command(self, pb):
        m = pb.SshPingMonitor(['relay'], '10.1.2.3')
        assert 'ForwardX11=no' in m._build_ping_cmd()

    def test_probe_reader(self, pb):
        m = pb.SshPingMonitor(['relay'], '10.1.2.3')
        r = pb.ProbeReader(m, 'p', 60, {'t': pb.ProbeDef('t')}, retain=5)
        assert 'ForwardX11=no' in r._build_cmd()

    def test_clock_probe(self, pb):
        m = pb.SshPingMonitor(['relay'], '10.1.2.3')
        cmd = pb.Application._clock_probe_cmd(m, '10.1.2.3')
        assert 'ForwardX11=no' in cmd

    def test_options_precede_the_users_ssh_args(self, pb):
        """A -J from :remote-ping must still reach ssh."""
        m = pb.SshPingMonitor(['-J', 'bastion', 'relay'], '10.1.2.3')
        cmd = m._build_ping_cmd()
        assert cmd.index('ForwardX11=no') < cmd.index('-J')
        assert cmd[cmd.index('-J') + 1] == 'bastion'

    def test_interactive_connect_is_untouched(self, app, pb):
        """'c' is a shell: X11 and agent forwarding may be wanted there."""
        m = pb.PingMonitor('10.0.0.1')
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        assert 'ForwardX11' not in (app._connect_preview(m) or '')


class TestConnectionSharing:
    """The right answer differs by connection kind, so it is not in the default.

    ping and clock probes reach the *relay*, and many hosts share one relay —
    sharing them onto one master trips sshd's MaxSessions (default 10) and the
    hosts past the tenth are refused outright.  A probe reader reaches the
    *host itself*, one endpoint each, and reconnects whenever its remote loop
    restarts, so a master saves a handshake and an authentication each time.
    """

    def test_default_carries_no_sharing_option(self, pb):
        assert not any('Control' in f for f in pb._SSH_MONITOR_OPTIONS_DEFAULT)

    def test_ping_declines_sharing(self, pb):
        m = pb.SshPingMonitor(['relay'], '10.1.2.3')
        assert 'ControlMaster=no' in m._build_ping_cmd()

    def test_clock_probe_declines_sharing(self, pb):
        m = pb.SshPingMonitor(['relay'], '10.1.2.3')
        assert 'ControlMaster=no' in pb.Application._clock_probe_cmd(m, '10.1.2.3')

    def test_probe_reader_shares(self, pb):
        m = pb.SshPingMonitor(['relay'], '10.1.2.3')
        r = pb.ProbeReader(m, 'p', 60, {'t': pb.ProbeDef('t')}, retain=5)
        cmd = r._build_cmd()
        assert 'ControlMaster=auto' in cmd
        assert any(f.startswith('ControlPath=') for f in cmd)
        assert any(f.startswith('ControlPersist=') for f in cmd)

    def test_socket_lives_in_a_private_directory(self, pb):
        """SSH options are set by the master, so a shared socket would impose
        this connection's ForwardX11=no on any later session reusing it."""
        d = pb._ssh_control_dir()
        assert d is not None
        assert os.stat(d).st_mode & 0o077 == 0, oct(os.stat(d).st_mode)

    def test_socket_path_stays_short(self, pb):
        """A Unix socket path is limited to about 107 bytes."""
        d = pb._ssh_control_dir()
        assert len(os.path.join(d, '%C')) < 80, d

    def test_control_path_uses_the_ssh_hash(self, pb):
        m = pb.SshPingMonitor(['relay'], '10.1.2.3')
        r = pb.ProbeReader(m, 'p', 60, {'t': pb.ProbeDef('t')}, retain=5)
        path = [f for f in r._build_cmd() if f.startswith('ControlPath=')][0]
        assert path.endswith('/%C'), path

    def test_runtime_dir_is_preferred(self, pb, tmp_path, monkeypatch):
        """tmpfs, already 0700, and cleared at logout — so no stale sockets."""
        monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
        assert pb._ssh_control_dir() == str(tmp_path / 'ping-bulk')

    def test_cache_dir_is_the_fallback(self, pb, tmp_path, monkeypatch):
        """No runtime dir under cron, a systemd unit, or kiosk."""
        monkeypatch.delenv('XDG_RUNTIME_DIR', raising=False)
        monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
        assert pb._ssh_control_dir() == str(tmp_path / 'ping-bulk')

    def test_an_existing_loose_directory_is_tightened(self, pb, tmp_path, monkeypatch):
        """~/.cache is commonly 0755, where a socket would be visible."""
        monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
        loose = tmp_path / 'ping-bulk'
        loose.mkdir(mode=0o755)
        pb._ssh_control_dir()
        assert os.stat(loose).st_mode & 0o077 == 0

    def test_directory_name_is_fixed_not_the_script_name(self, pb, tmp_path, monkeypatch):
        """Two invocations under different names should reuse one master."""
        monkeypatch.setenv('XDG_RUNTIME_DIR', str(tmp_path))
        assert pb._ssh_control_dir().endswith('/ping-bulk')

    # ── an explicit user choice wins ────────────────────────────────────────

    def test_user_sharing_choice_is_respected_for_probes(self, app, pb):
        app._cmd_ssh_options('-o ControlMaster=auto -o ControlPath=/tmp/mine-%C')
        m = pb.SshPingMonitor(['relay'], '10.1.2.3')
        r = pb.ProbeReader(m, 'p', 60, {'t': pb.ProbeDef('t')}, retain=5)
        cmd = r._build_cmd()
        assert 'ControlPath=/tmp/mine-%C' in cmd
        assert not any(f.startswith('ControlPath=/run') for f in cmd)

    def test_user_sharing_choice_is_respected_for_ping(self, app, pb):
        """ssh takes the first value, so ours must not be prepended over theirs."""
        app._cmd_ssh_options('-o ControlMaster=auto')
        m = pb.SshPingMonitor(['relay'], '10.1.2.3')
        assert 'ControlMaster=no' not in m._build_ping_cmd()

    def test_no_sharing_when_no_directory_is_usable(self, pb, monkeypatch):
        monkeypatch.setattr(pb, '_ssh_control_dir', lambda: None)
        m = pb.SshPingMonitor(['relay'], '10.1.2.3')
        r = pb.ProbeReader(m, 'p', 60, {'t': pb.ProbeDef('t')}, retain=5)
        assert not any('Control' in f for f in r._build_cmd())


class TestSetCommand:

    def test_replaces_the_defaults(self, app, pb):
        app._cmd_ssh_options('-o ForwardX11=no -o ServerAliveInterval=15')
        assert pb._ssh_monitor_flags() == [
            '-o', 'ForwardX11=no', '-o', 'ServerAliveInterval=15']

    def test_none_clears(self, app, pb):
        app._cmd_ssh_options('none')
        assert pb._ssh_monitor_flags() == []

    def test_default_restores(self, app, pb):
        app._cmd_ssh_options('none')
        app._cmd_ssh_options('default')
        assert pb._ssh_monitor_flags() == pb._SSH_MONITOR_OPTIONS_DEFAULT

    def test_query_reports_the_current_value(self, app):
        app._cmd_ssh_options('')
        assert 'ForwardX11=no' in _last(app)

    def test_query_reports_none_when_cleared(self, app):
        app._cmd_ssh_options('none')
        app._cmd_ssh_options('')
        assert 'none' in _last(app)

    def test_quoted_value_is_split_as_a_shell_would(self, app, pb):
        app._cmd_ssh_options("-o 'ProxyJump=a b'")
        assert pb._ssh_monitor_flags() == ['-o', 'ProxyJump=a b']

    def test_unbalanced_quote_is_reported(self, app, pb):
        before = list(pb._ssh_monitor_flags())
        app._cmd_ssh_options("-o 'oops")
        assert pb._ssh_monitor_flags() == before

    def test_change_is_announced_as_taking_effect_later(self, app):
        """Existing children keep the options they were started with."""
        app._cmd_ssh_options('-o ForwardX11=no')
        assert 'from now on' in _last(app)


class TestKiosk:
    """An option here reaches every monitoring connection."""

    def _kiosk_app(self, pb, tmp_path):
        cfg = tmp_path / 'ping-bulk' / 'config'
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            a = pb.Application([('host', '10.0.0.1')], kiosk_mode=True)
        a._monitoring_started = True
        return a

    def test_proxycommand_is_refused(self, pb, tmp_path):
        """Otherwise it is a shell escape by another route."""
        app = self._kiosk_app(pb, tmp_path)
        before = list(pb._ssh_monitor_flags())
        app._cmd_ssh_options('-o ProxyCommand=/bin/sh')
        assert pb._ssh_monitor_flags() == before
        assert 'not allowed' in _last(app)

    def test_localcommand_is_refused(self, pb, tmp_path):
        app = self._kiosk_app(pb, tmp_path)
        app._cmd_ssh_options('-o LocalCommand=/bin/sh')
        assert 'not allowed' in _last(app)

    def test_a_harmless_option_is_accepted(self, pb, tmp_path):
        app = self._kiosk_app(pb, tmp_path)
        app._cmd_ssh_options('-o ForwardX11=no')
        assert pb._ssh_monitor_flags() == ['-o', 'ForwardX11=no']

    def test_not_restricted_outside_kiosk(self, app, pb):
        app._cmd_ssh_options('-o ProxyCommand=/bin/true')
        assert pb._ssh_monitor_flags() == ['-o', 'ProxyCommand=/bin/true']


class TestPersistence:

    def test_a_custom_value_is_saved(self, app, pb):
        app._cmd_ssh_options('-o ForwardX11=no')
        with patch.object(pb, '_config_path', return_value=app._cfg_path):
            app._save_config()
        assert any('ssh-options' in l for l in open(app._cfg_path))

    def test_the_default_is_not_saved(self, app, pb):
        with patch.object(pb, '_config_path', return_value=app._cfg_path):
            app._save_config()
        assert not any('ssh-options' in l for l in open(app._cfg_path))

    def test_round_trip(self, app, pb):
        app._cmd_ssh_options('-o ForwardX11=no -o Compression=yes')
        with patch.object(pb, '_config_path', return_value=app._cfg_path):
            app._save_config()
            pb._ssh_monitor_options = []
            pb.Application([('host', '10.0.0.1')])
        assert pb._ssh_monitor_flags() == [
            '-o', 'ForwardX11=no', '-o', 'Compression=yes']

    def test_cleared_value_round_trips(self, app, pb):
        app._cmd_ssh_options('none')
        with patch.object(pb, '_config_path', return_value=app._cfg_path):
            app._save_config()
            pb._ssh_monitor_options = list(pb._SSH_MONITOR_OPTIONS_DEFAULT)
            pb.Application([('host', '10.0.0.1')])
        assert pb._ssh_monitor_flags() == []
