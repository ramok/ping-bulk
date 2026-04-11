"""Unit tests for :let variable system in parse_hosts_file().

Covers:
  - scalar variable substitution in host lines
  - scalar variable in directive arguments (:resolv, :title, etc.)
  - :let with brace-expanded name (indexed variables)
  - $name bare substitution in host lines
  - ${name} brace-delimited substitution
  - ${expr_$N} two-level expansion inside :for body
  - :let inside :for body → loop-local, not visible after :end
  - :let before :for → available in loop body
  - undefined variable → empty string, no error
  - :title${fold$1} pattern (the motivating use case)
  - interactive _cmd_let sets self.variables
  - :let missing name → error entry
"""

import os
import textwrap
import pytest
from unittest.mock import patch

from utils.hosts_helper import write_hosts


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def parse(pb, content, tmp_path):
    """Write *content* to a temp hosts file and return parse_hosts_file entries."""
    p = tmp_path / 'hosts.txt'
    p.write_text(textwrap.dedent(content))
    return pb.parse_hosts_file(str(p))


def hosts(entries):
    return [v for k, v in entries if k == 'host']


def cmds(entries):
    return [v for k, v in entries if k == 'cmd']


def sections(entries):
    return [(v, lv, fd) for k, v, lv, fd in entries if k == 'section']


def errors(entries):
    return [v for k, v in entries if k == 'error']


def warns(entries):
    return [v for k, v in entries if k == 'warn']


def make_app(pb, tmp_path):
    cfg = str(tmp_path / 'cfg' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    with patch.object(pb, '_config_path', return_value=cfg):
        return pb.Application([('host', '127.0.0.1')], log_file=None)


# ===========================================================================
# Scalar substitution
# ===========================================================================

class TestLetScalar:
    """Basic :let scalar substitution."""

    def test_simple_host_substitution(self, pb, tmp_path):
        """:let prefix val  → $prefix expanded in host lines."""
        entries = parse(pb, """\
            :let prefix 10.0.0
            $prefix.1
            $prefix.2
        """, tmp_path)
        assert hosts(entries) == ['10.0.0.1', '10.0.0.2']

    def test_undefined_bare_variable_expands_to_empty(self, pb, tmp_path):
        """An undefined $name expands to empty string."""
        entries = parse(pb, """\
            prefix$notdefined.host
            10.0.0.1
        """, tmp_path)
        # $notdefined → "" → "prefix.host"
        assert 'prefix.host' in hosts(entries)
        assert '10.0.0.1' in hosts(entries)

    def test_undefined_braced_variable_expands_to_empty(self, pb, tmp_path):
        """${undefined} expands to empty string, same as $undefined."""
        entries = parse(pb, """\
            host${undef}name
            10.0.0.1
        """, tmp_path)
        # ${undef} → "" → "hostname"
        assert 'hostname' in hosts(entries)
        assert '10.0.0.1' in hosts(entries)

    def test_undefined_partial_variable_empty(self, pb, tmp_path):
        """$unknown in middle of host name → expands to empty."""
        entries = parse(pb, """\
            host-$unknown.example.com
        """, tmp_path)
        # $unknown → "" → "host-.example.com"
        assert hosts(entries) == ['host-.example.com']

    def test_redefine_variable(self, pb, tmp_path):
        """:let can redefine a variable; later value takes effect."""
        entries = parse(pb, """\
            :let x first
            $x.host
            :let x second
            $x.host
        """, tmp_path)
        assert hosts(entries) == ['first.host', 'second.host']

    def test_let_clears_variable(self, pb, tmp_path):
        """:let name (no value) sets variable to empty string."""
        entries = parse(pb, """\
            :let x hello
            $x.host
            :let x
            $x.host
        """, tmp_path)
        # After :let x (no value), $x = "" → ".host" → host named ".host"
        assert hosts(entries) == ['hello.host', '.host']

    def test_let_in_directive_argument(self, pb, tmp_path):
        """:let variable substituted in directive arguments."""
        entries = parse(pb, """\
            :let ip 10.0.0.5
            :resolv $ip myhost
        """, tmp_path)
        assert any(':resolv 10.0.0.5 myhost' in c for c in cmds(entries))

    def test_let_in_title(self, pb, tmp_path):
        """:let variable substituted in :title directive."""
        entries = parse(pb, """\
            :let zone prod
            :title $zone servers
        """, tmp_path)
        secs = sections(entries)
        assert secs == [('prod servers', 1, False)]


# ===========================================================================
# Brace expansion on variable names
# ===========================================================================

class TestLetBraceNames:
    """:let name{expansion} value — indexed variables."""

    def test_brace_range_creates_indexed_vars(self, pb, tmp_path):
        """:let sh{1..3} val$1 creates sh1, sh2, sh3 with eager $1 substitution."""
        entries = parse(pb, """\
            :let sh{1..3} hub-$1
            $sh1
            $sh2
            $sh3
        """, tmp_path)
        assert hosts(entries) == ['hub-1', 'hub-2', 'hub-3']

    def test_brace_list_creates_indexed_vars(self, pb, tmp_path):
        """:let name{a,b,c} val creates namea, nameb, namec."""
        entries = parse(pb, """\
            :let pfx{a,b} 10.$1.0.1
            $pfxa
            $pfxb
        """, tmp_path)
        assert hosts(entries) == ['10.a.0.1', '10.b.0.1']

    def test_let_missing_name_produces_error(self, pb, tmp_path):
        """:let with no name produces an error entry."""
        entries = parse(pb, """\
            :let
            10.0.0.1
        """, tmp_path)
        assert errors(entries), "Expected error for :let with no name"
        assert hosts(entries) == ['10.0.0.1']


# ===========================================================================
# ${expr} brace-delimited substitution
# ===========================================================================

class TestBraceDelimitedVar:
    """${name} and ${expr_$N} substitution."""

    def test_braced_var_simple(self, pb, tmp_path):
        """${name} expands just like $name."""
        entries = parse(pb, """\
            :let prefix 192.168
            ${prefix}.1.1
        """, tmp_path)
        assert hosts(entries) == ['192.168.1.1']

    def test_braced_var_adjacent_text(self, pb, tmp_path):
        """${name} allows adjacent characters without ambiguity."""
        entries = parse(pb, """\
            :let net 10
            ${net}abc
        """, tmp_path)
        assert hosts(entries) == ['10abc']

    def test_braced_undefined(self, pb, tmp_path):
        """${undefined} expands to empty string, same as $undefined."""
        entries = parse(pb, """\
            host${undef}name
        """, tmp_path)
        # ${undef} → "" → "hostname"
        assert hosts(entries) == ['hostname']


# ===========================================================================
# Two-level expansion: ${name_$N} inside :for body
# ===========================================================================

class TestTwoLevelExpansion:
    """${expr_$N} two-level expansion: expand $N first, then look up variable."""

    def test_title_fold_pattern(self, pb, tmp_path):
        """:title${fold$1} $0 — the motivating use case.

        Only the fold variables that should be folded need to be defined.
        Undefined ${fold$N} expands to "" so the directive becomes :title.
        """
        entries = parse(pb, """\
            :let fold4 -
            :for sensor-hub-{1..5}
                :title${fold$1} hub-$1
            :end
        """, tmp_path)
        secs = sections(entries)
        # iterations 1,2,3,5 → fold_default=False; iteration 4 → fold_default=True
        assert len(secs) == 5
        by_name = {name: fd for name, _lv, fd in secs}
        assert by_name['hub-1'] is False
        assert by_name['hub-2'] is False
        assert by_name['hub-3'] is False
        assert by_name['hub-4'] is True,  "hub-4 should be folded"
        assert by_name['hub-5'] is False

    def test_two_level_with_undefined_inner(self, pb, tmp_path):
        """${name_$1} where variable not found → empty string → no fold."""
        entries = parse(pb, """\
            :for host-{1..3}
                :title${fold$1} section-$1
            :end
        """, tmp_path)
        secs = sections(entries)
        # No fold* variables defined → ${fold$N} → "" → :title (not folded)
        assert all(not fd for _n, _l, fd in secs)

    def test_two_level_host_line(self, pb, tmp_path):
        """${prefix$1} in a host line resolves to the indexed variable."""
        entries = parse(pb, """\
            :let ip1 10.0.1
            :let ip2 10.0.2
            :for {1..2}
                ${ip$1}.100
            :end
        """, tmp_path)
        assert hosts(entries) == ['10.0.1.100', '10.0.2.100']


# ===========================================================================
# :let inside :for body (loop-local)
# ===========================================================================

class TestLetInsideFor:
    """:let inside :for body is loop-local."""

    def test_let_in_body_updates_local_vars(self, pb, tmp_path):
        """:let inside :for body takes effect for subsequent lines in same iteration."""
        entries = parse(pb, """\
            :for {1..2}
                :let sfx -$1
                host$sfx
            :end
        """, tmp_path)
        assert hosts(entries) == ['host-1', 'host-2']

    def test_let_in_body_does_not_leak(self, pb, tmp_path):
        """:let inside :for body does not change the outer variable store."""
        entries = parse(pb, """\
            :let sfx original
            :for {1..2}
                :let sfx loop-$1
                host$sfx
            :end
            outer$sfx
        """, tmp_path)
        # Inside loop: host$sfx = host + loop-1 = hostloop-1 (no separator)
        # Outside loop: sfx should still be 'original'
        assert 'hostloop-1' in hosts(entries)
        assert 'hostloop-2' in hosts(entries)
        assert 'outeroriginal' in hosts(entries), \
            f"Expected 'outeroriginal' after loop, got {hosts(entries)}"

    def test_let_before_for_available_in_body(self, pb, tmp_path):
        """:let defined before :for is visible inside the loop body."""
        entries = parse(pb, """\
            :let suffix .example.com
            :for host{1..3}
                $0$suffix
            :end
        """, tmp_path)
        assert hosts(entries) == [
            'host1.example.com',
            'host2.example.com',
            'host3.example.com',
        ]


# ===========================================================================
# Interactive :let via _cmd_let
# ===========================================================================

class TestCmdLet:
    """Application._cmd_let sets self.variables."""

    def test_cmd_let_sets_variable(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._dispatch_cmd(':let myvar hello')
        assert app.variables.get('myvar') == 'hello'

    def test_cmd_let_no_value_clears(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._dispatch_cmd(':let myvar hello')
        app._dispatch_cmd(':let myvar')
        assert app.variables.get('myvar') == ''

    def test_cmd_let_no_name_logs_event(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._monitoring_started = True
        app._dispatch_cmd(':let')
        assert any('let' in e for e in app.events)

    def test_cmd_let_brace_name(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        app._dispatch_cmd(':let node{1..3} server-$1')
        assert app.variables['node1'] == 'server-1'
        assert app.variables['node2'] == 'server-2'
        assert app.variables['node3'] == 'server-3'

    def test_cmd_let_variables_passed_to_source(self, pb, tmp_path):
        """Variables set via :let are available in subsequently :source'd files."""
        app = make_app(pb, tmp_path)
        app._dispatch_cmd(':let net 10.0.0')

        hosts_file = tmp_path / 'extra.txt'
        hosts_file.write_text('$net.1\n$net.2\n')

        app._dispatch_cmd(f':source {hosts_file}')
        monitor_hosts = [m.host for m in app.monitors]
        assert '10.0.0.1' in monitor_hosts
        assert '10.0.0.2' in monitor_hosts
