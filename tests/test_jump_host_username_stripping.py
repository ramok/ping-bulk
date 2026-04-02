"""Test username stripping in SSH jump host display chains."""

import pytest


# ---------------------------------------------------------------------------
# Tests for username stripping in SSH jump host display chains
# ---------------------------------------------------------------------------

def test_strip_username_basic(pb):
    """Test _strip_username() removes user@ prefix."""
    SshPingMonitor = pb.SshPingMonitor

    # Test the static method directly
    assert SshPingMonitor._strip_username("user@host") == "host"
    assert SshPingMonitor._strip_username("host") == "host"
    assert SshPingMonitor._strip_username("user@10.0.0.1") == "10.0.0.1"
    assert SshPingMonitor._strip_username("10.0.0.1") == "10.0.0.1"


def test_jump_host_display_strips_username(pb):
    """Test that jump hosts with user@ prefix show only hostname in display chain."""
    SshPingMonitor = pb.SshPingMonitor

    # Create SSH monitor with jump host containing username
    ssh_args = ['-J', 'user@jumphost', 'user@destination']
    monitor = SshPingMonitor(ssh_args, 'localhost', ping_host_label='target')

    # Display should strip usernames from all hosts in the chain
    display = monitor.get_display_name('off')

    # Should be: jumphost → destination → target (all without user@ prefix)
    assert 'user@' not in display, f"Username not stripped from display: {display}"
    assert 'jumphost' in display
    assert 'destination' in display
    assert 'target' in display


def test_multiple_jump_hosts_strip_usernames(pb):
    """Test multiple jump hosts all have usernames stripped."""
    SshPingMonitor = pb.SshPingMonitor

    # Multiple jump hosts with usernames
    ssh_args = ['-J', 'admin@jump1,root@jump2', 'user@destination']
    monitor = SshPingMonitor(ssh_args, 'localhost', ping_host_label='target')

    display = monitor.get_display_name('off')

    # No usernames should appear
    assert 'admin@' not in display
    assert 'root@' not in display
    assert 'user@' not in display

    # Hostnames should appear
    assert 'jump1' in display
    assert 'jump2' in display
    assert 'destination' in display

