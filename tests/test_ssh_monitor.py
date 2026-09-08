"""Unit tests for SshPingMonitor.

Covers:
  - __init__ attribute initialisation
  - get_display_name() for all three dns_mode values
  - resolve_dns() targeting the ping host (not the SSH destination)
  - _build_ping_cmd() output
  - creation via Application._cmd_remote_ping() (the ':ssh' command)
"""

import pytest
from unittest.mock import patch


# ── fixtures ──────────────────────────────────────────────────────────────────

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
        assert m.get_display_name('off') == 'remote → target.host'

    def test_dns_off_default(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        assert m.get_display_name() == 'remote → target.host'

    def test_dns_off_uses_ping_host_label_not_ping_host(self, pb):
        m = pb.SshPingMonitor(['user@remote'], '10.0.0.5', ping_host_label='web01')
        assert m.get_display_name('off') == 'remote → web01'

    def test_dns_ip_uses_resolved_ip(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        m.resolved_ip = '10.0.0.1'
        assert m.get_display_name('ip') == 'remote → 10.0.0.1'

    def test_dns_ip_falls_back_to_ping_host_when_no_resolved_ip(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        assert m.resolved_ip is None
        assert m.get_display_name('ip') == 'remote → target.host'

    def test_dns_hostname_uses_resolved_hostname(self, pb):
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        m.resolved_hostname = 'pretty.name'
        assert m.get_display_name('hostname') == 'remote → pretty.name'

    def test_dns_hostname_falls_back_to_ping_host_label(self, pb):
        m = pb.SshPingMonitor(['user@remote'], '10.0.0.5', ping_host_label='web01')
        assert m.resolved_hostname is None
        assert m.get_display_name('hostname') == 'remote → web01'

    def test_dns_ip_pre_populated_ip(self, pb):
        m = pb.SshPingMonitor(['user@remote'], '10.0.0.5')
        assert m.get_display_name('ip') == 'remote → 10.0.0.5'

    def test_jump_host_dest_in_display_name(self, pb):
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], 'target.host')
        assert m.get_display_name('off') == 'bastion → remote → target.host'


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
        """The monitoring options sit between BatchMode and the user's args."""
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        cmd = m._build_ping_cmd()
        assert cmd == (['ssh', '-o', 'BatchMode=yes']
                       + pb._ssh_sharing_flags(False) + pb._ssh_monitor_flags()
                       + ['user@remote', 'ping', '-O', '-D', 'target.host'])

    def test_jump_host_cmd(self, pb):
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], 'target.host')
        cmd = m._build_ping_cmd()
        assert cmd == (['ssh', '-o', 'BatchMode=yes']
                       + pb._ssh_sharing_flags(False) + pb._ssh_monitor_flags()
                       + ['-J', 'bastion', 'user@remote',
                          'ping', '-O', '-D', 'target.host'])

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
        app._cmd_remote_ping('user@remote target.host')
        assert len(app.monitors) == 1
        assert isinstance(app.monitors[0], pb.SshPingMonitor)

    def test_cmd_ssh_ping_host_label(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('user@remote target.host')
        assert app.monitors[0]._ping_host_label == 'target.host'

    def test_cmd_ssh_ssh_args(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('user@remote target.host')
        assert app.monitors[0]._ssh_args == ['user@remote']

    def test_cmd_ssh_jump_host(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('-J bastion user@remote target.host')
        m = app.monitors[0]
        assert m._ssh_args == ['-J', 'bastion', 'user@remote']
        assert m._ping_host == 'target.host'

    def test_cmd_ssh_too_few_args_logs_error(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('user@remote')
        assert len(app.monitors) == 0
        assert any('usage' in e for e in app.events)

    def test_cmd_ssh_no_args_logs_error(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('')
        assert len(app.monitors) == 0
        assert any('usage' in e for e in app.events)

    def test_cmd_ssh_brace_expansion(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('user@remote target.{1,2}')
        assert len(app.monitors) == 2
        hosts = [m._ping_host for m in app.monitors]
        assert 'target.1' in hosts
        assert 'target.2' in hosts

    def test_cmd_ssh_resolv_mapping_applied(self, pb, tmp_path):
        """When a :resolv mapping exists, :ssh uses the resolved IP as ping_host."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.0.0.5 web01')
        app._cmd_remote_ping('user@remote web01')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ping_host == '10.0.0.5'
        assert m._ping_host_label == 'web01'

    def test_cmd_ssh_resolv_mapping_with_username(self, pb, tmp_path):
        """When :resolv mapping exists, :ssh user@hostname resolves hostname to IP."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('192.168.1.10 ps-supervisor')
        app._cmd_remote_ping('komar@ps-supervisor localhost')
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
        app._cmd_remote_ping('ps-supervisor localhost')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        # SSH destination should be resolved to IP (bare hostname)
        assert m._ssh_args == ['192.168.1.10']
        assert m._ping_host == 'localhost'

    def test_cmd_ssh_monitor_added_to_entries(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('user@remote target.host')
        assert app.monitors[0] in app.entries


# ── TestSshProxyJumpResolution ────────────────────────────────────────────────

class TestSshProxyJumpResolution:
    """Test automatic :resolv mapping resolution for ProxyJump/jump hosts."""

    def test_cmd_ssh_resolv_J_option_simple(self, pb, tmp_path):
        """Jump host specified with -J should be resolved via :resolv mapping."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion')
        app._cmd_remote_ping('-J bastion user@remote target.host')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-J', '10.10.1.100', 'user@remote']

    def test_cmd_ssh_resolv_J_option_with_username(self, pb, tmp_path):
        """Jump host with user@host format should preserve username."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion')
        app._cmd_remote_ping('-J admin@bastion user@remote target.host')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-J', 'admin@10.10.1.100', 'user@remote']

    def test_cmd_ssh_resolv_J_option_multihop(self, pb, tmp_path):
        """Comma-separated multi-hop jump hosts should all be resolved."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion1')
        app._cmd_resolv('10.10.1.101 bastion2')
        app._cmd_remote_ping('-J bastion1,bastion2 user@remote target.host')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-J', '10.10.1.100,10.10.1.101', 'user@remote']

    def test_cmd_ssh_resolv_J_option_multihop_mixed(self, pb, tmp_path):
        """Multi-hop with mixed user@host and bare hostname."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion1')
        app._cmd_resolv('10.10.1.101 bastion2')
        app._cmd_remote_ping('-J user@bastion1,bastion2 user@remote target.host')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-J', 'user@10.10.1.100,10.10.1.101', 'user@remote']

    def test_cmd_ssh_resolv_J_option_unmapped_passthrough(self, pb, tmp_path):
        """Unmapped jump host should pass through unchanged."""
        app = make_app(pb, tmp_path)
        app._cmd_remote_ping('-J unmapped-bastion user@remote target.host')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-J', 'unmapped-bastion', 'user@remote']

    def test_cmd_ssh_resolv_o_ProxyJump_no_space(self, pb, tmp_path):
        """-oProxyJump=host (no space) should be resolved."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion')
        app._cmd_remote_ping('-oProxyJump=bastion user@remote target.host')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-oProxyJump=10.10.1.100', 'user@remote']

    def test_cmd_ssh_resolv_o_ProxyJump_with_space(self, pb, tmp_path):
        """-o ProxyJump=host (with space) should be resolved."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion')
        app._cmd_remote_ping('-o ProxyJump=bastion user@remote target.host')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-o', 'ProxyJump=10.10.1.100', 'user@remote']

    def test_cmd_ssh_resolv_o_ProxyJump_multihop(self, pb, tmp_path):
        """-o ProxyJump=host1,host2 multi-hop should be resolved."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion1')
        app._cmd_resolv('10.10.1.101 bastion2')
        app._cmd_remote_ping('-o ProxyJump=bastion1,bastion2 user@remote target.host')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-o', 'ProxyJump=10.10.1.100,10.10.1.101', 'user@remote']

    def test_cmd_ssh_resolv_o_ProxyJump_with_username(self, pb, tmp_path):
        """-o ProxyJump=user@host should preserve username."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion')
        app._cmd_remote_ping('-o ProxyJump=admin@bastion user@remote target.host')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-o', 'ProxyJump=admin@10.10.1.100', 'user@remote']

    def test_cmd_ssh_resolv_combined_J_and_dest(self, pb, tmp_path):
        """Both -J jump host AND SSH destination should be resolved."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion')
        app._cmd_resolv('192.168.1.10 ps-supervisor')
        app._cmd_remote_ping('-J bastion ps-supervisor localhost')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-J', '10.10.1.100', '192.168.1.10']
        assert m._ping_host == 'localhost'

    def test_cmd_ssh_resolv_J_and_dest_with_usernames(self, pb, tmp_path):
        """Both -J user@jump and user@dest should preserve usernames."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion')
        app._cmd_resolv('192.168.1.10 ps-supervisor')
        app._cmd_remote_ping('-J admin@bastion komar@ps-supervisor localhost')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-J', 'admin@10.10.1.100', 'komar@192.168.1.10']

    def test_cmd_ssh_resolv_whitespace_in_multihop(self, pb, tmp_path):
        """Whitespace around commas in multi-hop should be stripped."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion1')
        app._cmd_resolv('10.10.1.101 bastion2')
        app._cmd_remote_ping('-J bastion1, bastion2 user@remote target.host')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-J', '10.10.1.100,10.10.1.101', 'user@remote']

    def test_cmd_ssh_resolv_multiple_J_options(self, pb, tmp_path):
        """Multiple -J options should each be resolved independently."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion1')
        app._cmd_resolv('10.10.1.101 bastion2')
        # Note: SSH doesn't actually support multiple -J but we handle it anyway
        app._cmd_remote_ping('-J bastion1 -J bastion2 user@remote target.host')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-J', '10.10.1.100', '-J', '10.10.1.101', 'user@remote']

    def test_cmd_ssh_resolv_J_at_end_of_args_ignored(self, pb, tmp_path):
        """-J at end of args (no value) should be handled safely without crash."""
        app = make_app(pb, tmp_path)
        # This is malformed but shouldn't crash
        app._cmd_remote_ping('user@remote target.host -J')
        # The parsing treats last token '-J' as ping_host_pattern, 'target.host' as ssh_dest
        # This creates a monitor that will ping '-J' (weird but safe - no crash)
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ping_host == '-J'  # Confirms it's treated as ping target
        assert m._ssh_args == ['user@remote', 'target.host']

    def test_cmd_ssh_resolv_o_without_ProxyJump_unchanged(self, pb, tmp_path):
        """-o with non-ProxyJump option should pass through unchanged."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('192.168.1.10 ps-supervisor')
        app._cmd_remote_ping('-o StrictHostKeyChecking=no ps-supervisor localhost')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == ['-o', 'StrictHostKeyChecking=no', '192.168.1.10']

    def test_cmd_ssh_resolv_mixed_options(self, pb, tmp_path):
        """Mix of -J, -o ProxyJump=, and other SSH options."""
        app = make_app(pb, tmp_path)
        app._cmd_resolv('10.10.1.100 bastion')
        app._cmd_resolv('192.168.1.10 ps-supervisor')
        app._cmd_remote_ping('-o ConnectTimeout=10 -J bastion -p 2222 ps-supervisor localhost')
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m._ssh_args == [
            '-o', 'ConnectTimeout=10',
            '-J', '10.10.1.100',
            '-p', '2222',
            '192.168.1.10'
        ]


# ── TestSshExtractJumpHosts ───────────────────────────────────────────────────

class TestSshExtractJumpHosts:
    """Test _extract_jump_hosts() method for parsing jump host arguments."""

    def test_extract_J_simple(self, pb):
        """Single -J jump host."""
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['bastion']

    def test_extract_J_with_username(self, pb):
        """Single -J with user@host format."""
        m = pb.SshPingMonitor(['-J', 'admin@bastion', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['admin@bastion']

    def test_extract_J_multihop_comma_separated(self, pb):
        """Multiple jump hosts in single -J flag (comma-separated)."""
        m = pb.SshPingMonitor(['-J', 'bastion1,bastion2', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['bastion1', 'bastion2']

    def test_extract_J_multihop_with_usernames(self, pb):
        """Multi-hop with user@host format in comma-separated list."""
        m = pb.SshPingMonitor(['-J', 'admin@bastion1,root@bastion2', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['admin@bastion1', 'root@bastion2']

    def test_extract_J_multihop_mixed(self, pb):
        """Multi-hop with mixed bare hostname and user@host."""
        m = pb.SshPingMonitor(['-J', 'user@bastion1,bastion2,admin@bastion3', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['user@bastion1', 'bastion2', 'admin@bastion3']

    def test_extract_J_whitespace_trimmed(self, pb):
        """Whitespace around commas should be stripped."""
        m = pb.SshPingMonitor(['-J', 'bastion1, bastion2 , bastion3', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['bastion1', 'bastion2', 'bastion3']

    def test_extract_J_empty_string(self, pb):
        """-J with empty value (shouldn't happen but handled safely)."""
        m = pb.SshPingMonitor(['-J', '', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == []

    def test_extract_J_at_end_no_value(self, pb):
        """-J at end of args with no value."""
        m = pb.SshPingMonitor(['-J'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == []

    def test_extract_o_ProxyJump_no_space(self, pb):
        """-oProxyJump=host (no space between -o and ProxyJump)."""
        m = pb.SshPingMonitor(['-oProxyJump=bastion', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['bastion']

    def test_extract_o_ProxyJump_with_space(self, pb):
        """-o ProxyJump=host (with space)."""
        m = pb.SshPingMonitor(['-o', 'ProxyJump=bastion', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['bastion']

    def test_extract_o_ProxyJump_multihop(self, pb):
        """-o ProxyJump=host1,host2 comma-separated."""
        m = pb.SshPingMonitor(['-o', 'ProxyJump=bastion1,bastion2', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['bastion1', 'bastion2']

    def test_extract_o_ProxyJump_with_username(self, pb):
        """-o ProxyJump=user@host format."""
        m = pb.SshPingMonitor(['-o', 'ProxyJump=admin@bastion', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['admin@bastion']

    def test_extract_multiple_J_options(self, pb):
        """Multiple separate -J options."""
        m = pb.SshPingMonitor(['-J', 'bastion1', '-J', 'bastion2', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['bastion1', 'bastion2']

    def test_extract_mixed_J_and_o_ProxyJump(self, pb):
        """Mix of -J and -o ProxyJump= in same command."""
        m = pb.SshPingMonitor(['-J', 'bastion1', '-o', 'ProxyJump=bastion2', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['bastion1', 'bastion2']

    def test_extract_no_jump_hosts(self, pb):
        """No jump host options present."""
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == []

    def test_extract_o_other_option_ignored(self, pb):
        """-o with non-ProxyJump option should not be extracted."""
        m = pb.SshPingMonitor(['-o', 'StrictHostKeyChecking=no', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == []

    def test_extract_mixed_options_with_other_flags(self, pb):
        """Jump hosts extracted correctly even with other SSH options."""
        m = pb.SshPingMonitor([
            '-o', 'ConnectTimeout=10',
            '-J', 'bastion1,bastion2',
            '-p', '2222',
            '-o', 'ProxyJump=bastion3',
            'user@remote'
        ], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['bastion1', 'bastion2', 'bastion3']

    def test_extract_trailing_comma_ignored(self, pb):
        """Trailing comma in jump host list should be handled."""
        m = pb.SshPingMonitor(['-J', 'bastion1,bastion2,', 'user@remote'], 'target.host')
        jumps = m._extract_jump_hosts(m._ssh_args)
        assert jumps == ['bastion1', 'bastion2']


# ── TestSshReverseLookupAlias ─────────────────────────────────────────────────

class TestSshReverseLookupAlias:
    """Test _reverse_lookup_alias() for finding original aliases from resolved IPs."""

    def test_reverse_lookup_exact_ip_match(self, pb):
        """IP matches resolved IP in hosts_map."""
        hosts_map = {'web01': ('10.0.0.5', 'web01.example.com')}
        m = pb.SshPingMonitor(['user@remote'], 'target.host', hosts_map=hosts_map)
        alias = m._reverse_lookup_alias('10.0.0.5')
        assert alias == 'web01'

    def test_reverse_lookup_no_match(self, pb):
        """IP not in hosts_map returns unchanged."""
        hosts_map = {'web01': ('10.0.0.5', 'web01.example.com')}
        m = pb.SshPingMonitor(['user@remote'], 'target.host', hosts_map=hosts_map)
        alias = m._reverse_lookup_alias('10.0.0.99')
        assert alias == '10.0.0.99'

    def test_reverse_lookup_hostname_match(self, pb):
        """Hostname that matches resolved IP returns alias."""
        hosts_map = {'web01': ('10.0.0.5', 'web01.example.com')}
        m = pb.SshPingMonitor(['user@remote'], 'target.host', hosts_map=hosts_map)
        # If 'web01.example.com' is the resolved IP (shouldn't be, but test the logic)
        alias = m._reverse_lookup_alias('web01.example.com')
        assert alias == 'web01.example.com'  # Not found as IP, returns unchanged

    def test_reverse_lookup_empty_hosts_map(self, pb):
        """Empty hosts_map returns input unchanged."""
        m = pb.SshPingMonitor(['user@remote'], 'target.host', hosts_map={})
        alias = m._reverse_lookup_alias('10.0.0.5')
        assert alias == '10.0.0.5'

    def test_reverse_lookup_no_hosts_map(self, pb):
        """No hosts_map (None) returns input unchanged."""
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        alias = m._reverse_lookup_alias('10.0.0.5')
        assert alias == '10.0.0.5'

    def test_reverse_lookup_multiple_entries(self, pb):
        """Multiple entries in hosts_map, correct match returned."""
        hosts_map = {
            'web01': ('10.0.0.5', 'web01.example.com'),
            'web02': ('10.0.0.6', 'web02.example.com'),
            'bastion': ('10.10.1.100', 'bastion.example.com')
        }
        m = pb.SshPingMonitor(['user@remote'], 'target.host', hosts_map=hosts_map)
        assert m._reverse_lookup_alias('10.0.0.5') == 'web01'
        assert m._reverse_lookup_alias('10.0.0.6') == 'web02'
        assert m._reverse_lookup_alias('10.10.1.100') == 'bastion'

    def test_reverse_lookup_with_username(self, pb):
        """user@host format should strip username and perform lookup."""
        hosts_map = {'bastion': ('10.10.1.100', 'bastion.example.com')}
        m = pb.SshPingMonitor(['user@remote'], 'target.host', hosts_map=hosts_map)
        # The method strips username and looks up the host part
        alias = m._reverse_lookup_alias('user@10.10.1.100')
        # Should return 'bastion' (alias found for 10.10.1.100 after stripping user@)
        assert alias == 'bastion'


# ── TestSshJumpChainDisplay ───────────────────────────────────────────────────

class TestSshJumpChainDisplay:
    """Test get_display_name() with jump host chains in various DNS modes."""

    def test_jump_chain_display_single_jump_dns_off(self, pb):
        """Single jump host with dns_mode='off' shows original names."""
        hosts_map = {'bastion': ('10.10.1.100', 'bastion.example.com')}
        original_ssh_args = ['-J', 'bastion', 'user@remote']
        resolved_ssh_args = ['-J', '10.10.1.100', 'user@remote']
        m = pb.SshPingMonitor(
            resolved_ssh_args,
            'target.host',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        display = m.get_display_name('off')
        assert display == 'bastion → remote → target.host'

    def test_jump_chain_display_single_jump_dns_ip(self, pb):
        """Single jump host with dns_mode='ip' shows resolved IPs for all hosts."""
        hosts_map = {'bastion': ('10.10.1.100', 'bastion.example.com')}
        original_ssh_args = ['-J', 'bastion', 'user@remote']
        resolved_ssh_args = ['-J', '10.10.1.100', 'user@remote']
        m = pb.SshPingMonitor(
            resolved_ssh_args,
            '10.0.0.5',
            ping_host_label='target.host',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        m.resolved_ip = '10.0.0.5'
        display = m.get_display_name('ip')
        assert display == '10.10.1.100 → remote → 10.0.0.5'

    def test_jump_chain_display_single_jump_dns_hostname(self, pb):
        """Single jump host with dns_mode='hostname' shows hostnames."""
        hosts_map = {'bastion': ('10.10.1.100', 'bastion.example.com')}
        original_ssh_args = ['-J', 'bastion', 'user@remote']
        resolved_ssh_args = ['-J', '10.10.1.100', 'user@remote']
        m = pb.SshPingMonitor(
            resolved_ssh_args,
            '10.0.0.5',
            ping_host_label='target.host',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        m.resolved_hostname = 'target.example.com'
        display = m.get_display_name('hostname')
        assert display == 'bastion → remote → target.example.com'

    def test_jump_chain_display_multihop_dns_off(self, pb):
        """Multiple jump hosts with dns_mode='off' shows all in chain."""
        hosts_map = {
            'bastion1': ('10.10.1.100', 'bastion1.example.com'),
            'bastion2': ('10.10.1.101', 'bastion2.example.com')
        }
        original_ssh_args = ['-J', 'bastion1,bastion2', 'user@remote']
        resolved_ssh_args = ['-J', '10.10.1.100,10.10.1.101', 'user@remote']
        m = pb.SshPingMonitor(
            resolved_ssh_args,
            'target.host',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        display = m.get_display_name('off')
        assert display == 'bastion1 → bastion2 → remote → target.host'

    def test_jump_chain_display_multihop_with_usernames(self, pb):
        """Multiple jump hosts with user@ prefixes."""
        hosts_map = {
            'bastion1': ('10.10.1.100', 'bastion1.example.com'),
            'bastion2': ('10.10.1.101', 'bastion2.example.com')
        }
        original_ssh_args = ['-J', 'admin@bastion1,root@bastion2', 'user@remote']
        resolved_ssh_args = ['-J', 'admin@10.10.1.100,root@10.10.1.101', 'user@remote']
        m = pb.SshPingMonitor(
            resolved_ssh_args,
            'target.host',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        display = m.get_display_name('off')
        assert display == 'bastion1 → bastion2 → remote → target.host'

    def test_jump_chain_display_no_jump_hosts(self, pb):
        """No jump hosts, only SSH destination."""
        m = pb.SshPingMonitor(['user@remote'], 'target.host')
        display = m.get_display_name('off')
        assert display == 'remote → target.host'

    def test_jump_chain_display_mixed_mapped_unmapped(self, pb):
        """Mix of mapped and unmapped jump hosts."""
        hosts_map = {'bastion1': ('10.10.1.100', 'bastion1.example.com')}
        original_ssh_args = ['-J', 'bastion1,unmapped-host', 'user@remote']
        resolved_ssh_args = ['-J', '10.10.1.100,unmapped-host', 'user@remote']
        m = pb.SshPingMonitor(
            resolved_ssh_args,
            'target.host',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        display = m.get_display_name('off')
        # bastion1 should be looked up and found, unmapped-host stays as-is
        assert display == 'bastion1 → unmapped-host → remote → target.host'

    def test_jump_chain_display_ProxyJump_format(self, pb):
        """-o ProxyJump= format should also extract jump hosts."""
        hosts_map = {'bastion': ('10.10.1.100', 'bastion.example.com')}
        original_ssh_args = ['-o', 'ProxyJump=bastion', 'user@remote']
        resolved_ssh_args = ['-o', 'ProxyJump=10.10.1.100', 'user@remote']
        m = pb.SshPingMonitor(
            resolved_ssh_args,
            'target.host',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        display = m.get_display_name('off')
        assert display == 'bastion → remote → target.host'

    def test_jump_chain_display_ping_host_dns_ip(self, pb):
        """Ping host shows resolved IP in dns_mode='ip'."""
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], 'target.host')
        m.resolved_ip = '10.0.0.5'
        display = m.get_display_name('ip')
        assert display == 'bastion → remote → 10.0.0.5'

    def test_jump_chain_display_ping_host_dns_hostname(self, pb):
        """Ping host shows resolved hostname in dns_mode='hostname'."""
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], '10.0.0.5', ping_host_label='web01')
        m.resolved_hostname = 'web01.example.com'
        display = m.get_display_name('hostname')
        assert display == 'bastion → remote → web01.example.com'

    def test_jump_chain_display_fallback_no_resolved_ip(self, pb):
        """dns_mode='ip' falls back to ping_host when resolution fails."""
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], 'target.host')
        # No resolved_ip set
        display = m.get_display_name('ip')
        assert display == 'bastion → remote → target.host'

    def test_jump_chain_display_fallback_no_resolved_hostname(self, pb):
        """dns_mode='hostname' falls back to ping_host_label when resolution fails."""
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], '10.0.0.5', ping_host_label='web01')
        # No resolved_hostname set
        display = m.get_display_name('hostname')
        assert display == 'bastion → remote → web01'

    def test_jump_chain_display_empty_original_ssh_args(self, pb):
        """No original_ssh_args provided, falls back to resolved args."""
        m = pb.SshPingMonitor(['-J', '10.10.1.100', 'user@remote'], 'target.host')
        display = m.get_display_name('off')
        # Without original_ssh_args, it uses the resolved args
        assert display == '10.10.1.100 → remote → target.host'

    def test_jump_chain_display_three_jump_hops(self, pb):
        """Three jump hosts in chain."""
        hosts_map = {
            'bastion1': ('10.10.1.100', 'bastion1.example.com'),
            'bastion2': ('10.10.1.101', 'bastion2.example.com'),
            'bastion3': ('10.10.1.102', 'bastion3.example.com')
        }
        original_ssh_args = ['-J', 'bastion1,bastion2,bastion3', 'user@remote']
        resolved_ssh_args = ['-J', '10.10.1.100,10.10.1.101,10.10.1.102', 'user@remote']
        m = pb.SshPingMonitor(
            resolved_ssh_args,
            'target.host',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        display = m.get_display_name('off')
        assert display == 'bastion1 → bastion2 → bastion3 → remote → target.host'

    def test_jump_chain_display_ssh_dest_also_mapped(self, pb):
        """SSH destination is also mapped via :resolv."""
        hosts_map = {
            'bastion': ('10.10.1.100', 'bastion.example.com'),
            'ps-supervisor': ('192.168.1.10', 'ps-supervisor.example.com')
        }
        original_ssh_args = ['-J', 'bastion', 'ps-supervisor']
        resolved_ssh_args = ['-J', '10.10.1.100', '192.168.1.10']
        m = pb.SshPingMonitor(
            resolved_ssh_args,
            'localhost',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        m._ssh_dest_label = 'ps-supervisor'  # This is set by the implementation
        display = m.get_display_name('off')
        # The display should show original aliases for jump host, dest shows label
        assert display == 'bastion → ps-supervisor → localhost'

