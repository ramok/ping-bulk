"""Unit tests for SshPingMonitor.

Covers:
  - __init__ attribute initialisation
  - get_display_name() for all three dns_mode values
  - resolve_dns() targeting the ping host (not the SSH destination)
  - _build_ping_cmd() output
  - creation via Application._cmd_ssh() (the ':ssh' command)
"""

import importlib.machinery
import importlib.util
import pytest
from unittest.mock import patch


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope='session')
def pb(app_path):
    loader = importlib.machinery.SourceFileLoader('ping_bulk', app_path)
    spec = importlib.util.spec_from_loader('ping_bulk', loader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def make_app(pb, tmp_path, entries=None):
    if entries is None:
        entries = []
    cfg_path = str(tmp_path / 'ping-bulk' / 'config')
    with patch.object(pb, '_config_path', return_value=cfg_path):
        app = pb.Application(entries)
    return app


# ── TestSshPingMonitorInit ────────────────────────────────────────────────────

class TestSshPingMonitorInit:
    def test_host_label_is_dest_arrow_ping_host(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        assert m.host == 'user@remote→target.host'

    def test_ssh_dest_is_last_ssh_arg(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        assert m._ssh_dest == 'user@remote'

    def test_ssh_args_stored(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        assert m._ssh_args == ['user@remote']

    def test_ping_host_stored(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        assert m._ping_host == 'target.host'

    def test_ping_host_label_defaults_to_ping_host(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        assert m._ping_host_label == 'target.host'

    def test_explicit_ping_host_label(self, pb):
        m = pb.SshPingMonitor(['user@remote'], '10.0.0.5', ping_host_label='web01')
        assert m._ping_host_label == 'web01'

    def test_host_label_uses_ping_host_label(self, pb):
        m = pb.SshPingMonitor(['user@remote'], '10.0.0.5', ping_host_label='web01')
        assert m.host == 'user@remote→web01'

    def test_ip_ping_host_pre_populates_resolved_ip(self, pb):
        m = pb.SshPingMonitor(['user@remote'], '10.0.0.5')
        assert m.resolved_ip == '10.0.0.5'

    def test_hostname_ping_host_does_not_pre_populate_resolved_ip(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        assert m.resolved_ip is None

    def test_empty_ssh_args_gives_empty_dest(self, pb):
        m = pb.SshPingMonitor([], 'target.host')
        assert m._ssh_dest == ''
        assert m.host == '→target.host'

    def test_jump_host_dest_is_last_arg(self, pb):
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], 'target.host')
        assert m._ssh_dest == 'user@remote'
        assert m.host == 'user@remote→target.host'


# ── TestSshPingMonitorGetDisplayName ─────────────────────────────────────────

class TestSshPingMonitorGetDisplayName:
    def test_dns_off_returns_label(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        assert m.get_display_name('off') == 'user@remote→target.host'

    def test_dns_off_default(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        assert m.get_display_name() == 'user@remote→target.host'

    def test_dns_off_uses_ping_host_label_not_ping_host(self, pb):
        m = pb.SshPingMonitor(['user@remote'], '10.0.0.5', ping_host_label='web01')
        assert m.get_display_name('off') == 'user@remote→web01'

    def test_dns_ip_uses_resolved_ip(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        m.resolved_ip = '10.0.0.1'
        assert m.get_display_name('ip') == 'user@remote→10.0.0.1'

    def test_dns_ip_falls_back_to_ping_host_when_no_resolved_ip(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        assert m.resolved_ip is None
        assert m.get_display_name('ip') == 'user@remote→target.host'

    def test_dns_hostname_uses_resolved_hostname(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        m.resolved_hostname = 'pretty.name'
        assert m.get_display_name('hostname') == 'user@remote→pretty.name'

    def test_dns_hostname_falls_back_to_ping_host_label(self, pb):
        m = pb.SshPingMonitor(['user@remote'], '10.0.0.5', ping_host_label='web01')
        assert m.resolved_hostname is None
        assert m.get_display_name('hostname') == 'user@remote→web01'

    def test_dns_ip_pre_populated_ip(self, pb):
        m = pb.SshPingMonitor(['user@remote'], '10.0.0.5')
        assert m.get_display_name('ip') == 'user@remote→10.0.0.5'

    def test_jump_host_dest_in_display_name(self, pb):
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], 'target.host')
        assert m.get_display_name('off') == 'user@remote→target.host'


# ── TestSshPingMonitorResolveDns ──────────────────────────────────────────────

class TestSshPingMonitorResolveDns:
    def test_resolve_dns_sets_resolved_ip(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        with patch('socket.gethostbyname', return_value='10.0.0.1'), \
             patch('socket.gethostbyaddr', return_value=('host.name', [], ['10.0.0.1'])):
            m.resolve_dns()
        assert m.resolved_ip == '10.0.0.1'

    def test_resolve_dns_sets_resolved_hostname(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        with patch('socket.gethostbyname', return_value='10.0.0.1'), \
             patch('socket.gethostbyaddr', return_value=('host.name', [], ['10.0.0.1'])):
            m.resolve_dns()
        assert m.resolved_hostname == 'host.name'

    def test_resolve_dns_forward_failure_sets_none(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        with patch('socket.gethostbyname', side_effect=OSError), \
             patch('socket.gethostbyaddr', side_effect=OSError):
            m.resolve_dns()
        assert m.resolved_ip is None

    def test_resolve_dns_reverse_failure_sets_none(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        with patch('socket.gethostbyname', return_value='10.0.0.1'), \
             patch('socket.gethostbyaddr', side_effect=OSError):
            m.resolve_dns()
        assert m.resolved_ip == '10.0.0.1'
        assert m.resolved_hostname is None

    def test_resolve_dns_targets_ping_host_not_ssh_dest(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'ping-target.host')
        resolved = []
        def fake_gethostbyname(host):
            resolved.append(host)
            return '10.0.0.2'
        with patch('socket.gethostbyname', side_effect=fake_gethostbyname), \
             patch('socket.gethostbyaddr', return_value=('h', [], [])):
            m.resolve_dns()
        assert resolved == ['ping-target.host']

    def test_resolve_dns_does_not_target_ssh_dest(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'ping-target.host')
        resolved = []
        def fake_gethostbyname(host):
            resolved.append(host)
            return '10.0.0.2'
        with patch('socket.gethostbyname', side_effect=fake_gethostbyname), \
             patch('socket.gethostbyaddr', return_value=('h', [], [])):
            m.resolve_dns()
        assert 'user@remote' not in resolved


# ── TestSshPingMonitorBuildPingCmd ────────────────────────────────────────────

class TestSshPingMonitorBuildPingCmd:
    def test_basic_cmd(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        cmd = m._build_ping_cmd()
        assert cmd == ['ssh', '-o', 'BatchMode=yes', 'user@remote',
                       'ping', '-O', '-D', 'target.host']

    def test_jump_host_cmd(self, pb):
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], 'target.host')
        cmd = m._build_ping_cmd()
        assert cmd == ['ssh', '-o', 'BatchMode=yes', '-J', 'bastion', 'user@remote',
                       'ping', '-O', '-D', 'target.host']

    def test_batchmode_flag_present(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        cmd = m._build_ping_cmd()
        assert '-o' in cmd
        assert 'BatchMode=yes' in cmd

    def test_ping_flags_present(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        cmd = m._build_ping_cmd()
        assert '-O' in cmd
        assert '-D' in cmd

    def test_ping_host_is_last_arg(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        cmd = m._build_ping_cmd()
        assert cmd[-1] == 'target.host'


# ── TestSshPingMonitorViaCmd ──────────────────────────────────────────────────

class TestSshPingMonitorViaCmd:
    def test_cmd_ssh_creates_monitor(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_ssh('user@remote target.host')
        assert len(app.monitors) == 1
        assert isinstance(app.monitors[0], pb.SshPingMonitor)

    def test_cmd_ssh_ping_host_label(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_ssh('user@remote target.host')
        assert app.monitors[0]._ping_host_label == 'target.host'

    def test_cmd_ssh_ssh_args(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_ssh('user@remote target.host')
        assert app.monitors[0]._ssh_args == ['user@remote']

    def test_cmd_ssh_jump_host(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_ssh('-J bastion user@remote target.host')
        m = app.monitors[0]
        assert m._ssh_args == ['-J', 'bastion', 'user@remote']
        assert m._ping_host == 'target.host'

    def test_cmd_ssh_too_few_args_logs_error(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_ssh('user@remote')
        assert len(app.monitors) == 0
        assert any('usage' in e for e in app.events)

    def test_cmd_ssh_no_args_logs_error(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_ssh('')
        assert len(app.monitors) == 0
        assert any('usage' in e for e in app.events)

    def test_cmd_ssh_brace_expansion(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_ssh('user@remote target.{1,2}')
        assert len(app.monitors) == 2
        hosts = [m._ping_host for m in app.monitors]
        assert 'target.1' in hosts
        assert 'target.2' in hosts

    def test_cmd_ssh_resolv_mapping_applied(self, pb, tmp_path):
        """When a :resolv mapping exists, :ssh uses the resolved IP as ping_host."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.0.0.5 web01')
        app._cmd_ssh('user@remote web01')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ping_host == '10.0.0.5'
        assert m._ping_host_label == 'web01'

    def test_cmd_ssh_resolv_mapping_with_username(self, pb, tmp_path):
        """When :resolv mapping exists, :ssh user@hostname resolves hostname to IP."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('192.168.1.10 ps-supervisor')
        app._cmd_ssh('komar@ps-supervisor localhost')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        # SSH destination should be resolved to user@IP
        assert m._ssh_args == ['komar@192.168.1.10']
        # Ping host remains as given
        assert m._ping_host == 'localhost'

    def test_cmd_ssh_resolv_mapping_preserves_bare_hostname(self, pb, tmp_path):
        """When :resolv mapping exists for bare hostname (no @), it should be resolved."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('192.168.1.10 ps-supervisor')
        app._cmd_ssh('ps-supervisor localhost')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        # SSH destination should be resolved to IP (bare hostname)
        assert m._ssh_args == ['192.168.1.10']
        assert m._ping_host == 'localhost'

    def test_cmd_ssh_monitor_added_to_entries(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_ssh('user@remote target.host')
        assert app.monitors[0] in app.entries

