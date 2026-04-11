"""Unit tests for nested SSH jump host chaining.

Covers:
  - :remote-ping command inside :remote-ping-begin block (direct nesting)
  - :remote-ping command inside :for loop inside :remote-ping-begin block
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
    """Direct :remote-ping command inside :remote-ping-begin block (no :for loop)."""

    def test_ssh_inside_ssh_begin_chains_with_jump_option(self, pb, tmp_path):
        """:remote-ping inside :remote-ping-begin should produce -J chained command."""
        content = """\
            :remote-ping-begin komar@ps-supervisor
            :remote-ping dev@10.123.1.31 ps-jetson
            :remote-ping-end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        expected = ':remote-ping -J komar@ps-supervisor dev@10.123.1.31 ps-jetson'
        assert expected in cmd_entries, (
            f"Expected chained SSH command; got {cmd_entries!r}"
        )

    def test_multiple_ssh_inside_ssh_begin_all_chained(self, pb, tmp_path):
        """Multiple :remote-ping commands inside :remote-ping-begin all get chained."""
        content = """\
            :remote-ping-begin user@bastion
            :remote-ping admin@host1 target1
            :remote-ping admin@host2 target2
            :remote-ping-end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        assert ':remote-ping -J user@bastion admin@host1 target1' in cmd_entries
        assert ':remote-ping -J user@bastion admin@host2 target2' in cmd_entries

    def test_ssh_without_ssh_begin_not_chained(self, pb, tmp_path):
        """:remote-ping command outside :remote-ping-begin block is not modified."""
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
    """:remote-ping command inside :for loop inside :remote-ping-begin block."""

    def test_ssh_inside_for_inside_ssh_begin_chains_properly(self, pb, tmp_path):
        """The key test case from the user's example.

        :remote-ping-begin komar@ps-supervisor
            :for sensor-hub-{1-3,5}
                :remote-ping dev@10.123.$1.31 ps-jetson
            :done
        :remote-ping-end

        Should produce: :remote-ping -J komar@ps-supervisor dev@10.123.1.31 ps-jetson
        (repeated for each iteration: 1, 2, 3, 5)
        """
        content = """\
            :remote-ping-begin komar@ps-supervisor
            :for sensor-hub-{1-3,5}
            :remote-ping dev@10.123.$1.31 ps-jetson
            :done
            :remote-ping-end
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
        """:remote-ping inside :for without outer :remote-ping-begin should not chain."""
        content = """\
            :for node{1,2}
            :remote-ping user@jump$1 target$1
            :done
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
        """:remote-ping command with multiple backrefs inside :for inside :remote-ping-begin."""
        content = """\
            :remote-ping-begin admin@gateway
            :for rack{1,2}-unit{a,b}
            :remote-ping user@10.$1.$2.1 target-$1-$2
            :done
            :remote-ping-end
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
        """:for loop with both :remote-ping commands and plain host lines inside :remote-ping-begin."""
        content = """\
            :remote-ping-begin user@bastion
            :for zone{1,2}
            plain-host-$1
            :remote-ping jump@zone$1 target$1
            :done
            :remote-ping-end
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
    """:remote-ping-begin/:remote-ping-end blocks inside :for loop should produce errors."""

    def test_ssh_begin_inside_for_produces_error(self, pb, tmp_path):
        """:remote-ping-begin inside :for is not supported and should produce an error."""
        content = """\
            :for dc{1,2}
            :remote-ping-begin user@dc$1-jump
            target-$1
            :remote-ping-end
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        error_entries = [v for k, v in entries if k == 'error']

        # Should produce at least one error about :remote-ping-begin inside :for
        assert len(error_entries) >= 1
        assert any('remote-ping-begin' in v.lower() for v in error_entries)


# ===========================================================================
# TestMultipleJumpHostsWithoutUsernames
# ===========================================================================

class TestMultipleJumpHostsWithoutUsernames:
    """Multiple jump hosts without usernames in display chains."""

    def test_jump_chain_without_usernames_displays_correctly(self, pb, tmp_path):
        """Jump host chain without usernames should display all hosts."""
        content = """\
            :remote-ping-begin jumphost1
            :remote-ping jumphost2 target
            :remote-ping-end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        expected = ':remote-ping -J jumphost1 jumphost2 target'
        assert expected in cmd_entries

    def test_multiple_jump_hosts_in_for_loop(self, pb, tmp_path):
        """Multiple jump hosts without usernames expanded in :for loop."""
        content = """\
            :remote-ping-begin bastion
            :for subnet{1,2}
            :remote-ping 10.0.$1.1 final-$1
            :done
            :remote-ping-end
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
        """:remote-ping with no arguments inside :remote-ping-begin."""
        content = """\
            :remote-ping-begin user@jump
            :remote-ping
            :remote-ping-end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        # Should still chain, even if args are empty
        assert ':remote-ping -J user@jump ' in cmd_entries or ':remote-ping -J user@jump' in cmd_entries

    def test_ssh_begin_with_empty_args(self, pb, tmp_path):
        """:remote-ping-begin with no arguments."""
        content = """\
            :remote-ping-begin
            :remote-ping user@host target
            :remote-ping-end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        # Should chain with empty string
        assert ':remote-ping -J  user@host target' in cmd_entries or ':remote-ping -J user@host target' in cmd_entries

    def test_deduplication_of_chained_ssh_commands(self, pb, tmp_path):
        """Duplicate chained SSH commands should be deduplicated."""
        content = """\
            :remote-ping-begin user@jump
            :for node{1,1}
            :remote-ping admin@host target
            :done
            :remote-ping-end
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

