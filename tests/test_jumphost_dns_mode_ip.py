"""Test that dns_mode='ip' shows IP of JumpHost when :resolv mapping exists."""

import pytest


class TestJumpHostDnsModeIp:
    """Test jump host display with dns_mode='ip' and :resolv mappings."""

    def test_jumphost_shows_ip_with_dns_mode_ip(self, pb):
        """Test that dns_mode='ip' shows resolved IP for jump hosts.
        
        When a jump host has a :resolv mapping and the user specifies it with
        user@alias syntax, dns_mode='ip' should display the resolved IP address,
        not the original alias.
        """
        SshPingMonitor = pb.SshPingMonitor
        
        # Set up hosts_map with a :resolv mapping for jump host
        # Format: {'alias': ('resolved_ip', 'resolved_hostname')}
        hosts_map = {
            'jump-alias': ('10.0.0.1', 'jump.example.com')
        }
        
        # Create SSH monitor with jump host using user@alias format
        # After :resolv processing, this becomes: ['-J', '10.0.0.1', 'user@destination']
        ssh_args = ['-J', '10.0.0.1', 'user@destination']
        original_ssh_args = ['-J', 'user@jump-alias', 'user@destination']
        
        monitor = SshPingMonitor(
            ssh_args,
            'localhost',
            ping_host_label='target',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        
        # Get display name with dns_mode='ip'
        display = monitor.get_display_name('ip')
        
        # Should show: 10.0.0.1 → destination → localhost (IP of ping target)
        assert '10.0.0.1' in display, f"Expected IP address in display, got: {display}"
        assert 'jump-alias' not in display, f"Alias should not appear in ip mode, got: {display}"
        assert 'destination' in display
        assert 'user@' not in display, "Usernames should be stripped from display"

    def test_jumphost_shows_alias_with_dns_mode_off(self, pb):
        """Test that dns_mode='off' shows original alias for jump hosts.
        
        When dns_mode='off', jump hosts should show their original aliases
        (as defined by user via :resolv), not IPs.
        """
        SshPingMonitor = pb.SshPingMonitor
        
        # Set up hosts_map with a :resolv mapping
        hosts_map = {
            'jump-alias': ('10.0.0.1', 'jump.example.com')
        }
        
        # Jump host with username prefix
        ssh_args = ['-J', '10.0.0.1', 'destination']
        original_ssh_args = ['-J', 'jump-alias', 'destination']
        
        monitor = SshPingMonitor(
            ssh_args,
            'localhost',
            ping_host_label='target',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        
        display = monitor.get_display_name('off')
        
        # Should show alias, not IP
        assert 'jump-alias' in display, f"Expected alias in display, got: {display}"
        assert '10.0.0.1' not in display, f"IP should not appear in off mode, got: {display}"

    def test_multiple_jumphosts_show_ips_with_dns_mode_ip(self, pb):
        """Test that dns_mode='ip' shows resolved IPs for multiple jump hosts."""
        SshPingMonitor = pb.SshPingMonitor
        
        # Multiple jump hosts with :resolv mappings
        hosts_map = {
            'jump1': ('10.0.0.1', 'jump1.example.com'),
            'jump2': ('10.0.0.2', 'jump2.example.com')
        }
        
        # Multiple jump hosts with usernames
        ssh_args = ['-J', '10.0.0.1,10.0.0.2', 'user@destination']
        original_ssh_args = ['-J', 'user@jump1,admin@jump2', 'user@destination']
        
        monitor = SshPingMonitor(
            ssh_args,
            'localhost',
            ping_host_label='target',
            original_ssh_args=original_ssh_args,
            hosts_map=hosts_map
        )
        
        display = monitor.get_display_name('ip')
        
        # Should show: 10.0.0.1 → 10.0.0.2 → destination → localhost
        assert '10.0.0.1' in display, f"Expected first jump IP in display, got: {display}"
        assert '10.0.0.2' in display, f"Expected second jump IP in display, got: {display}"
        assert 'jump1' not in display, f"Aliases should not appear in ip mode, got: {display}"
        assert 'jump2' not in display, f"Aliases should not appear in ip mode, got: {display}"
        assert 'user@' not in display, "Usernames should be stripped"
        assert 'admin@' not in display, "Usernames should be stripped"

    def test_jumphost_without_resolv_mapping_shows_original(self, pb):
        """Test that jump hosts without :resolv mappings show the original hostname."""
        SshPingMonitor = pb.SshPingMonitor
        
        # No hosts_map or empty hosts_map
        hosts_map = {}
        
        # Jump host without any :resolv mapping
        ssh_args = ['-J', 'user@jumphost', 'destination']
        
        monitor = SshPingMonitor(
            ssh_args,
            'localhost',
            ping_host_label='target',
            hosts_map=hosts_map
        )
        
        display = monitor.get_display_name('off')
        
        # Should show original hostname (without username)
        assert 'jumphost' in display, f"Expected original hostname, got: {display}"
        assert 'user@' not in display, "Username should be stripped"

