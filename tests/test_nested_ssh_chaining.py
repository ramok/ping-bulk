"""Unit tests for nested SSH jump host chaining.

Covers:
  - :remote-ping command inside :with remote-ping block (direct nesting)
  - :remote-ping command inside :for loop inside :with remote-ping block
  - Multiple levels of jump host chaining with -J option
  - Username stripping in jump host display chains
  - Display format verification for chained jump hosts
"""

import textwrap
import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

from utils.hosts_helper import write_hosts



# ===========================================================================
# TestDirectSshNesting
# ===========================================================================

class TestDirectSshNesting:
    """Direct :remote-ping command inside :with remote-ping block (no :for loop)."""

    def test_ssh_inside_ssh_begin_chains_with_jump_option(self, pb, tmp_path):
        """:remote-ping inside :with remote-ping should produce -J chained command."""
        content = """\
            :with remote-ping komar@ps-supervisor
            :remote-ping dev@10.123.1.31 ps-jetson
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        expected = ':remote-ping -J komar@ps-supervisor dev@10.123.1.31 ps-jetson'
        assert expected in cmd_entries, (
            f"Expected chained SSH command; got {cmd_entries!r}"
        )

    def test_multiple_ssh_inside_ssh_begin_all_chained(self, pb, tmp_path):
        """Multiple :remote-ping commands inside :with remote-ping all get chained."""
        content = """\
            :with remote-ping user@bastion
            :remote-ping admin@host1 target1
            :remote-ping admin@host2 target2
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        assert ':remote-ping -J user@bastion admin@host1 target1' in cmd_entries
        assert ':remote-ping -J user@bastion admin@host2 target2' in cmd_entries

    def test_ssh_without_ssh_begin_not_chained(self, pb, tmp_path):
        """:remote-ping command outside :with remote-ping block is not modified."""
        content = """\
            :remote-ping user@host target
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        assert ':remote-ping user@host target' in cmd_entries
        assert '-J' not in cmd_entries[0]


# ===========================================================================
# TestSshInsideForInsideSshBegin
# ===========================================================================

class TestSshInsideForInsideSshBegin:
    """:remote-ping command inside :for loop inside :with remote-ping block."""

    def test_ssh_inside_for_inside_ssh_begin_chains_properly(self, pb, tmp_path):
        """The key test case from the user's example.

        :with remote-ping komar@ps-supervisor
            :for sensor-hub-{1-3,5}
                :remote-ping dev@10.123.$1.31 ps-jetson
            :end
        :end

        Should produce: :remote-ping -J komar@ps-supervisor dev@10.123.1.31 ps-jetson
        (repeated for each iteration: 1, 2, 3, 5)
        """
        content = """\
            :with remote-ping komar@ps-supervisor
            :for sensor-hub-{1-3,5}
            :remote-ping dev@10.123.$1.31 ps-jetson
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        # Should have 4 chained SSH commands (iterations: 1, 2, 3, 5)
        expected = [
            ':remote-ping -J komar@ps-supervisor dev@10.123.1.31 ps-jetson',
            ':remote-ping -J komar@ps-supervisor dev@10.123.2.31 ps-jetson',
            ':remote-ping -J komar@ps-supervisor dev@10.123.3.31 ps-jetson',
            ':remote-ping -J komar@ps-supervisor dev@10.123.5.31 ps-jetson',
        ]

        for exp in expected:
            assert exp in cmd_entries, (
                f"Expected {exp!r} in commands; got {cmd_entries!r}"
            )

    def test_ssh_inside_for_without_outer_ssh_begin(self, pb, tmp_path):
        """:remote-ping inside :for without outer :with remote-ping should not chain."""
        content = """\
            :for node{1,2}
            :remote-ping user@jump$1 target$1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        # Should expand backrefs but not add -J
        assert ':remote-ping user@jump1 target1' in cmd_entries
        assert ':remote-ping user@jump2 target2' in cmd_entries

        # Should NOT contain -J
        for cmd in cmd_entries:
            if cmd.startswith(':remote-ping'):
                assert '-J' not in cmd, f"Unexpected -J in {cmd!r}"

    def test_ssh_inside_for_with_multiple_backrefs(self, pb, tmp_path):
        """:remote-ping command with multiple backrefs inside :for inside :with remote-ping."""
        content = """\
            :with remote-ping admin@gateway
            :for rack{1,2}-unit{a,b}
            :remote-ping user@10.$1.$2.1 target-$1-$2
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        # Should expand both backrefs and chain
        expected = [
            ':remote-ping -J admin@gateway user@10.1.a.1 target-1-a',
            ':remote-ping -J admin@gateway user@10.1.b.1 target-1-b',
            ':remote-ping -J admin@gateway user@10.2.a.1 target-2-a',
            ':remote-ping -J admin@gateway user@10.2.b.1 target-2-b',
        ]

        for exp in expected:
            assert exp in cmd_entries, (
                f"Expected {exp!r} in commands; got {cmd_entries!r}"
            )

    def test_mixed_ssh_and_host_lines_inside_for_inside_ssh_begin(self, pb, tmp_path):
        """:for loop with both :remote-ping commands and plain host lines inside :with remote-ping."""
        content = """\
            :with remote-ping user@bastion
            :for zone{1,2}
            plain-host-$1
            :remote-ping jump@zone$1 target$1
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        # Plain hosts become :remote-ping user@bastion <host>
        assert ':remote-ping user@bastion plain-host-1' in cmd_entries
        assert ':remote-ping user@bastion plain-host-2' in cmd_entries

        # :remote-ping commands become chained with -J
        assert ':remote-ping -J user@bastion jump@zone1 target1' in cmd_entries
        assert ':remote-ping -J user@bastion jump@zone2 target2' in cmd_entries


# ===========================================================================
# TestNestedSshBeginInsideFor
# ===========================================================================

class TestNestedSshBeginInsideFor:
    """:with remote-ping blocks inside :for loop — supported."""

    def test_ssh_begin_inside_for_emits_commands(self, pb, tmp_path):
        """:with remote-ping inside :for expands relay per iteration."""
        content = """\
            :for dc{1,2}
            :with remote-ping user@dc$1-jump
            target-$1
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        error_entries = [v for k, v in entries if k == 'error']
        cmd_entries = [v for k, v in entries if k == 'cmd']

        assert not error_entries, f"Expected no errors; got {error_entries!r}"
        assert ':remote-ping user@dc1-jump target-1' in cmd_entries
        assert ':remote-ping user@dc2-jump target-2' in cmd_entries


# ===========================================================================
# TestMultipleJumpHostsWithoutUsernames
# ===========================================================================

class TestMultipleJumpHostsWithoutUsernames:
    """Multiple jump hosts without usernames in display chains."""

    def test_jump_chain_without_usernames_displays_correctly(self, pb, tmp_path):
        """Jump host chain without usernames should display all hosts."""
        content = """\
            :with remote-ping jumphost1
            :remote-ping jumphost2 target
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        expected = ':remote-ping -J jumphost1 jumphost2 target'
        assert expected in cmd_entries

    def test_multiple_jump_hosts_in_for_loop(self, pb, tmp_path):
        """Multiple jump hosts without usernames expanded in :for loop."""
        content = """\
            :with remote-ping bastion
            :for subnet{1,2}
            :remote-ping 10.0.$1.1 final-$1
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        assert ':remote-ping -J bastion 10.0.1.1 final-1' in cmd_entries
        assert ':remote-ping -J bastion 10.0.2.1 final-2' in cmd_entries


# ===========================================================================
# TestEdgeCases
# ===========================================================================

class TestEdgeCases:
    """Edge cases and error conditions."""

    def test_ssh_with_empty_args_inside_ssh_begin(self, pb, tmp_path):
        """:remote-ping with no arguments inside :with remote-ping."""
        content = """\
            :with remote-ping user@jump
            :remote-ping
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        # Should still chain, even if args are empty
        assert ':remote-ping -J user@jump ' in cmd_entries or ':remote-ping -J user@jump' in cmd_entries

    def test_ssh_begin_with_empty_args(self, pb, tmp_path):
        """:with remote-ping with no arguments."""
        content = """\
            :with remote-ping
            :remote-ping user@host target
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        # Should chain with empty string
        assert ':remote-ping -J  user@host target' in cmd_entries or ':remote-ping -J user@host target' in cmd_entries

    def test_deduplication_of_chained_ssh_commands(self, pb, tmp_path):
        """Duplicate chained SSH commands should be deduplicated."""
        content = """\
            :with remote-ping user@jump
            :for node{1,1}
            :remote-ping admin@host target
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']
        warn_entries = [v for k, v in entries if k == 'warn']

        # Should have the command only once
        chained_cmd = ':remote-ping -J user@jump admin@host target'
        assert cmd_entries.count(chained_cmd) == 1

        # Should have a duplicate warning
        assert len(warn_entries) >= 1


# ===========================================================================
# TestDisplayNameFormatting
# ===========================================================================

class TestDisplayNameFormatting:
    """Verify that SshPingMonitor displays chained jump hosts correctly."""

    def test_chained_jump_host_display_format(self, pb):
        """Chained jump hosts should display as: jump1 → jump2 → ssh_dest → target."""
        SshPingMonitor = pb.SshPingMonitor

        # -J takes comma-separated jump hosts, then SSH destination is the last arg
        ssh_args = ['-J', 'user@jump1,admin@jump2', 'user@sshhost']
        monitor = SshPingMonitor(ssh_args, 'localhost', ping_host_label='target')

        display = monitor.get_display_name('off')

        # Should strip usernames and show complete chain
        assert 'user@' not in display, f"Username should be stripped: {display}"
        assert 'admin@' not in display, f"Username should be stripped: {display}"
        assert 'jump1' in display
        assert 'jump2' in display
        assert 'sshhost' in display
        assert 'target' in display
        assert '→' in display

    def test_single_jump_host_display(self, pb):
        """Single jump host should display as: jump → target."""
        SshPingMonitor = pb.SshPingMonitor

        ssh_args = ['-J', 'admin@jumphost', 'localhost']
        monitor = SshPingMonitor(ssh_args, 'localhost', ping_host_label='target')

        display = monitor.get_display_name('off')

        assert 'admin@' not in display
        assert 'jumphost' in display
        assert 'target' in display

    def test_no_jump_host_display(self, pb):
        """SSH without jump host should display as: ssh_dest → target."""
        SshPingMonitor = pb.SshPingMonitor

        # SSH destination is the last (and only) argument in ssh_args
        ssh_args = ['user@sshhost']
        monitor = SshPingMonitor(ssh_args, 'localhost', ping_host_label='target')

        display = monitor.get_display_name('off')

        assert 'user@' not in display
        assert 'sshhost' in display
        assert 'target' in display



# ===========================================================================
# TestWithRelayLabel  — ## label on :with remote-ping line and inside block
# ===========================================================================

class TestWithRelayLabel:
    """## label on :with remote-ping line and on host lines inside the block."""

    def test_with_relay_ip_label_emits_resolv(self, pb, tmp_path):
        """:with remote-ping user@IP ## label  →  :resolv IP label emitted."""
        content = """\
            :with remote-ping komar@10.10.6.117 ## ps-supervisor
            10.10.6.1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']
        assert ':resolv 10.10.6.117 ps-supervisor' in cmd_entries, (
            f":resolv not emitted for relay; cmds={cmd_entries!r}"
        )

    def test_with_relay_hostname_label_not_emitted(self, pb, tmp_path):
        """## label on :with line is only processed if the relay is an IP."""
        content = """\
            :with remote-ping komar@ps-supervisor ## relay
            10.10.6.1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']
        assert not any(':resolv' in c for c in cmd_entries), (
            f"Unexpected :resolv for hostname relay; cmds={cmd_entries!r}"
        )

    def test_host_label_inside_with_block_emits_resolv(self, pb, tmp_path):
        """IP ## label on a host line inside :with remote-ping block emits :resolv."""
        content = """\
            :with remote-ping komar@relay
            10.10.6.10 ## myserver
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']
        assert ':resolv 10.10.6.10 myserver' in cmd_entries, (
            f":resolv not emitted for host inside block; cmds={cmd_entries!r}"
        )
        assert any(':remote-ping' in c and '10.10.6.10' in c for c in cmd_entries), (
            f":remote-ping not emitted; cmds={cmd_entries!r}"
        )


# ===========================================================================
# TestRelayTargetHostnameDisplay
# — dns_mode='hostname' for a host with ## label inside :with remote-ping
# ===========================================================================

def _make_app(pb, entries):
    """Build a minimal Application from pre-parsed entry tuples."""
    app = pb.Application.__new__(pb.Application)
    app.monitors  = []
    app.entries   = []
    app.hosts_map = {}
    app.port_map  = {}
    app.events    = pb.deque(maxlen=1000)
    app.history_size   = 100
    app.sync_history   = True
    app.log_size       = 1000
    app.dns_mode       = 0
    app.stats_mode     = 0
    app.sort_by        = 'none'
    app.history_mode   = 0
    app.history_offset = 0
    app._visible_ping_length = 50
    app.log_offset     = 0
    app.highlighted_index = None
    app.log_file       = None
    app._monitoring_started = False
    app.prompt         = None
    app.cmd            = None
    app.cmd_history    = []
    app.help_open      = False
    app.help_scroll    = 0
    app.details_open   = False
    app.details_monitor = None
    app.details_scroll = 0
    app.running        = True
    app.threads        = []
    app._start_time    = None
    app._fold_stack    = []
    app.kiosk_mode     = False
    app.variables      = {}

    for kind, *rest in entries:
        value = rest[0] if rest else ''
        if kind == 'cmd':
            app._dispatch_cmd(value)
        elif kind in ('host', 'optional_host'):
            host_str, _ = pb.parse_target(value)
            m = pb.PingMonitor(host_str)
            if host_str in app.hosts_map:
                ip, hostname = app.hosts_map[host_str]
                m.resolved_ip = ip
                m.resolved_hostname = hostname
                m.resolv_static = True
            app.monitors.append(m)
            app.entries.append(m)
        elif kind == 'section':
            level = rest[1] if len(rest) > 1 else 1
            folded_default = rest[2] if len(rest) > 2 else False
            app.entries.append(pb.SectionEntry(value, level=level,
                                               folded=folded_default))
    return app


class TestRelayTargetHostnameDisplay:
    """dns_mode='hostname' shows ## label for target inside :with remote-ping."""

    def test_hostname_mode_shows_label_not_ip(self, pb, tmp_path):
        """Target IP with ## label inside :with block → label shown in hostname mode."""
        content = """\
            :with remote-ping komar@10.10.6.117 ## ps-supervisor
            1.1.1.1 ## internet
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        app = _make_app(pb, entries)

        ssh_monitors = [m for m in app.monitors
                        if isinstance(m, pb.SshPingMonitor)]
        assert ssh_monitors, "expected at least one SshPingMonitor"

        m = ssh_monitors[0]
        display = m.get_display_name('hostname')
        assert 'internet' in display, (
            f"Expected 'internet' in hostname display, got: {display!r}\n"
            f"  resolved_hostname={m.resolved_hostname!r}, "
            f"  _ping_host_label={m._ping_host_label!r}, "
            f"  hosts_map={app.hosts_map!r}"
        )
        assert '1.1.1.1' not in display, (
            f"Raw IP should not appear in hostname display, got: {display!r}"
        )

    def test_hostname_mode_relay_label_shown(self, pb, tmp_path):
        """Relay IP with ## label → relay label shown in hostname mode."""
        content = """\
            :with remote-ping komar@10.10.6.117 ## ps-supervisor
            1.1.1.1 ## internet
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        app = _make_app(pb, entries)

        m = [m for m in app.monitors if isinstance(m, pb.SshPingMonitor)][0]
        display = m.get_display_name('hostname')
        assert 'ps-supervisor' in display, (
            f"Expected relay label 'ps-supervisor' in display, got: {display!r}"
        )

    def test_ordering_remote_ping_before_resolv(self, pb, tmp_path):
        """:remote-ping entry must appear before :resolv in parsed output."""
        content = """\
            :with remote-ping komar@relay
            10.0.0.1 ## myhost
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']
        remote_ping_idx = next(
            (i for i, v in enumerate(cmd_entries) if ':remote-ping' in v and '10.0.0.1' in v),
            None)
        resolv_idx = next(
            (i for i, v in enumerate(cmd_entries) if ':resolv 10.0.0.1' in v),
            None)
        assert remote_ping_idx is not None, f":remote-ping not in cmds: {cmd_entries!r}"
        assert resolv_idx is not None,      f":resolv not in cmds: {cmd_entries!r}"
        assert remote_ping_idx < resolv_idx, (
            f":remote-ping (idx {remote_ping_idx}) must come before "
            f":resolv (idx {resolv_idx}) so the monitor exists when "
            f"_apply_hosts_entry runs"
        )
