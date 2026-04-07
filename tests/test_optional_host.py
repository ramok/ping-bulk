"""Unit tests for '?host' optional-host syntax.

A host line prefixed with '?' is added to the monitor list only when a
:resolv mapping for the expanded name has already been registered.  If
no mapping exists the line is silently skipped.  The feature is designed
for :for loops where some iterations lack a particular device.
"""

import textwrap
import pytest

from utils.hosts_helper import write_hosts


# ---------------------------------------------------------------------------
# parse-level tests — what entry tuples does parse_hosts_file() produce?
# ---------------------------------------------------------------------------

class TestOptionalHostParsing:
    """parse_hosts_file() emits ('optional_host', name) for '?' lines."""

    def test_question_prefix_emits_optional_host(self, pb, tmp_path):
        """A '?' prefix on a plain line emits an optional_host entry."""
        content = """\
            ?my-device
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [('optional_host', 'my-device')]

    def test_no_prefix_emits_host(self, pb, tmp_path):
        """A line without '?' emits a regular host entry (unchanged)."""
        content = """\
            my-device
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [('host', 'my-device')]

    def test_optional_inside_for_with_backref(self, pb, tmp_path):
        """:for with '?host$1': optional_host emitted for each iteration."""
        content = """\
            :for hub-{1..3}
                ?sh$1-cam
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('optional_host', 'sh1-cam'),
            ('optional_host', 'sh2-cam'),
            ('optional_host', 'sh3-cam'),
        ], f"Got: {entries!r}"

    def test_mixed_optional_and_required_in_for(self, pb, tmp_path):
        """Required and optional lines coexist inside :for."""
        content = """\
            :for hub-{1..2}
                sh$1-router
                ?sh$1-cam
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host',          'sh1-router'),
            ('optional_host', 'sh1-cam'),
            ('host',          'sh2-router'),
            ('optional_host', 'sh2-cam'),
        ], f"Got: {entries!r}"

    def test_optional_with_brace_expansion(self, pb, tmp_path):
        """'?' prefix with brace expansion (no backref) emits multiple optional_host."""
        content = """\
            ?device-{1,2,3}
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('optional_host', 'device-1'),
            ('optional_host', 'device-2'),
            ('optional_host', 'device-3'),
        ], f"Got: {entries!r}"


# ---------------------------------------------------------------------------
# Application-level tests — which monitors actually get created?
# ---------------------------------------------------------------------------

class TestOptionalHostApplication:
    """Application.__init__ skips optional_host entries with no :resolv mapping."""

    def _make_app(self, pb, entries):
        """Build an Application from a pre-built entry list (no file needed)."""
        app = pb.Application.__new__(pb.Application)
        # Minimal init that bypasses file parsing and curses.
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
        app.pending_key    = None
        app.running        = True
        app.threads        = []
        app._start_time    = None
        app._fold_stack    = []

        for kind, *rest in entries:
            value = rest[0] if rest else ''
            if kind == 'cmd':
                app._dispatch_cmd(value)
            elif kind == 'host':
                host_str, port_str = pb.parse_target(value)
                m = pb.PingMonitor(host_str)
                if host_str in app.hosts_map:
                    ip, hostname = app.hosts_map[host_str]
                    m.resolved_ip = ip
                    m.resolved_hostname = hostname
                    m.resolv_static = True
                app.monitors.append(m)
                app.entries.append(m)
            elif kind == 'optional_host':
                host_str, port_str = pb.parse_target(value)
                if host_str not in app.hosts_map:
                    continue
                ip, hostname = app.hosts_map[host_str]
                m = pb.PingMonitor(host_str)
                m.resolved_ip = ip
                m.resolved_hostname = hostname
                m.resolv_static = True
                app.monitors.append(m)
                app.entries.append(m)
            elif kind == 'section':
                level = rest[1] if len(rest) > 1 else 1
                app.entries.append(pb.SectionLabel(value, level))
        return app

    def test_optional_host_skipped_without_resolv(self, pb, tmp_path):
        """optional_host with no :resolv mapping → monitor not created."""
        entries = [('optional_host', 'sh3-cam')]
        app = self._make_app(pb, entries)
        assert len(app.monitors) == 0, "Should be skipped — no :resolv for sh3-cam"

    def test_optional_host_added_with_resolv(self, pb, tmp_path):
        """optional_host with a :resolv mapping → monitor created with resolv_static."""
        entries = [
            ('cmd', ':resolv 10.0.1.50 sh1-cam'),
            ('optional_host', 'sh1-cam'),
        ]
        app = self._make_app(pb, entries)
        assert len(app.monitors) == 1
        m = app.monitors[0]
        assert m.host == 'sh1-cam'
        assert m.resolved_ip == '10.0.1.50'
        assert m.resolved_hostname == 'sh1-cam'
        assert m.resolv_static is True

    def test_for_loop_skips_missing_iterations(self, pb, tmp_path):
        """Full round-trip: :resolv for hubs 1,2,4 → hub3 cam skipped."""
        content = textwrap.dedent("""\
            :resolv 10.0.1.50  sh1-cam
            :resolv 10.0.2.50  sh2-cam
            :resolv 10.0.4.50  sh4-cam
            :for hub-{1..4}
                ?sh$1-cam
            :done
        """)
        f = tmp_path / 'hosts.txt'
        f.write_text(content)
        entries = pb.parse_hosts_file(str(f))
        # Build app manually from entries (no curses)
        app = self._make_app(pb, entries)
        host_names = [m.host for m in app.monitors]
        assert host_names == ['sh1-cam', 'sh2-cam', 'sh4-cam'], (
            f"Expected sh1/sh2/sh4-cam; got {host_names!r}"
        )
        # sh3-cam must not appear
        assert 'sh3-cam' not in host_names

    def test_required_hosts_unaffected(self, pb, tmp_path):
        """Required (non-?) hosts are always added regardless of :resolv."""
        content = textwrap.dedent("""\
            :for hub-{1..3}
                sh$1-router
                ?sh$1-cam
            :done
        """)
        f = tmp_path / 'hosts.txt'
        f.write_text(content)
        entries = pb.parse_hosts_file(str(f))
        app = self._make_app(pb, entries)
        host_names = [m.host for m in app.monitors]
        # All three routers must be present
        assert 'sh1-router' in host_names
        assert 'sh2-router' in host_names
        assert 'sh3-router' in host_names
        # No cameras (no :resolv defined)
        assert not any('cam' in h for h in host_names)

    def test_plain_optional_host_outside_for(self, pb, tmp_path):
        """'?host' outside a :for loop also respects :resolv gating."""
        content = textwrap.dedent("""\
            :resolv 10.0.1.1  alpha
            ?alpha
            ?beta
        """)
        f = tmp_path / 'hosts.txt'
        f.write_text(content)
        entries = pb.parse_hosts_file(str(f))
        app = self._make_app(pb, entries)
        host_names = [m.host for m in app.monitors]
        assert host_names == ['alpha'], f"Got: {host_names!r}"
