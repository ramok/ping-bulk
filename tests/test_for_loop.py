"""Unit tests for :for/:done loop handling in parse_hosts_file().

Covers:
  - basic backref expansion $N
  - $0 (full-string back-reference)
  - no-backref host lines inside :for  → warn + add once
  - duplicate hosts (within loop, across iterations, vs. outside loop)
  - unclosed :for at EOF  → implicit :done (hosts produced, no error)
  - :done without :for    → error entry
  - nested :for           → error entry
  - :ssh-begin/:ssh-end inside :for → error entries
  - :for inside :ssh-begin block    → SSH commands emitted
  - section headers (## / :title) inside :for, with and without backrefs
  - comment lines (#) inside :for body are skipped
  - generic commands (:cmd …) inside :for body
"""

import textwrap

import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

from utils.hosts_helper import write_hosts



# ===========================================================================
# TestForLoopBasic
# ===========================================================================

class TestForLoopBasic:
    """Basic :for expansion with back-references."""

    def test_single_group_dollar_syntax(self, pb, tmp_path):
        """:for with $1 back-reference produces one host per iteration."""
        content = """\
            :for host-{a,b,c}
            $1.lan
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', 'a.lan'),
            ('host', 'b.lan'),
            ('host', 'c.lan'),
        ], f"Unexpected entries: {entries!r}"

    def test_full_string_backref_0(self, pb, tmp_path):
        """$0 expands to the fully-expanded pattern string."""
        content = """\
            :for node-{1,2}
            $0.cluster
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', 'node-1.cluster'),
            ('host', 'node-2.cluster'),
        ], f"Unexpected entries: {entries!r}"

    def test_dollar_zero_syntax(self, pb, tmp_path):
        """$0 (dollar-zero) expands to the fully-expanded pattern string."""
        content = """\
            :for gw-{10,20}
            $0.net
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', 'gw-10.net'),
            ('host', 'gw-20.net'),
        ], f"Unexpected entries: {entries!r}"

    def test_two_groups_two_backrefs(self, pb, tmp_path):
        """Two brace groups: $1 and $2 each capture their group value."""
        content = """\
            :for rack{1,2}-unit{3,4}
            $1-$2.mgmt
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == [
            '1-3.mgmt',
            '1-4.mgmt',
            '2-3.mgmt',
            '2-4.mgmt',
        ], f"Unexpected hosts: {hosts!r}"

    def test_for_with_range_dash_style(self, pb, tmp_path):
        """zsh-style n-m range inside :for pattern is supported."""
        content = """\
            :for sw{1-3}
            sw$1.local
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', 'sw1.local'),
            ('host', 'sw2.local'),
            ('host', 'sw3.local'),
        ], f"Unexpected entries: {entries!r}"

    def test_host_with_brace_expansion_after_backref(self, pb, tmp_path):
        """After back-reference substitution, remaining brace groups are expanded."""
        content = """\
            :for rack{1,2}
            rack$1-unit{1,2}
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == [
            'rack1-unit1',
            'rack1-unit2',
            'rack2-unit1',
            'rack2-unit2',
        ], f"Unexpected hosts: {hosts!r}"

    def test_multiple_host_lines_in_body(self, pb, tmp_path):
        """Multiple host lines in the body each get expanded per iteration."""
        content = """\
            :for zone{1,2}
            zone$1-primary
            zone$1-secondary
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', 'zone1-primary'),
            ('host', 'zone1-secondary'),
            ('host', 'zone2-primary'),
            ('host', 'zone2-secondary'),
        ], f"Unexpected entries: {entries!r}"


# ===========================================================================
# TestForLoopSectionHeaders
# ===========================================================================

class TestForLoopSectionHeaders:
    """Section headers (## / :title) inside :for body."""

    def test_section_header_with_backref(self, pb, tmp_path):
        """## headers with $N back-references are emitted per iteration."""
        content = """\
            :for dc{1,2}
            ## Data Centre $1
            dc$1-router
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'Data Centre 1', 1, False),
            ('host',    'dc1-router'),
            ('section', 'Data Centre 2', 1, False),
            ('host',    'dc2-router'),
        ], f"Unexpected entries: {entries!r}"

    def test_title_directive_with_backref(self, pb, tmp_path):
        """:title inside :for with $N back-reference."""
        content = """\
            :for pod{a,b}
            :title Pod $1
            pod$1-host
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'Pod a', 1, False),
            ('host',    'poda-host'),
            ('section', 'Pod b', 1, False),
            ('host',    'podb-host'),
        ], f"Unexpected entries: {entries!r}"

    def test_section_header_without_backref_emitted_per_iteration(self, pb, tmp_path):
        """## headers without back-references are still emitted every iteration
        (no warning — section headers are structural, not host entries)."""
        content = """\
            :for node{1,2}
            ## Servers
            node$1
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        # Section emitted twice; no 'warn' tuples expected
        assert entries == [
            ('section', 'Servers', 1, False),
            ('host',    'node1'),
            ('section', 'Servers', 1, False),
            ('host',    'node2'),
        ], f"Unexpected entries: {entries!r}"

    def test_title_directive_without_backref_emitted_per_iteration(self, pb, tmp_path):
        """:title without back-references emitted every iteration (no warning)."""
        content = """\
            :for sp{1,2}
            :title Static Section
            sp$1
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'Static Section', 1, False),
            ('host',    'sp1'),
            ('section', 'Static Section', 1, False),
            ('host',    'sp2'),
        ], f"Unexpected entries: {entries!r}"


# ===========================================================================
# TestForLoopComments
# ===========================================================================

class TestForLoopComments:
    """Comments inside the :for body."""

    def test_comment_lines_skipped(self, pb, tmp_path):
        """Lines starting with '#' (but not '##') inside :for are ignored."""
        content = """\
            :for srv{1,2}
            # this is a comment
            srv$1
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', 'srv1'),
            ('host', 'srv2'),
        ], f"Unexpected entries: {entries!r}"


# ===========================================================================
# TestForLoopNoBackref
# ===========================================================================

class TestForLoopNoBackref:
    """Host lines without any back-reference inside :for."""

    def test_no_backref_host_added_once_with_warning(self, pb, tmp_path):
        """A host with no back-reference inside :for is added once with a warn entry."""
        content = """\
            :for dc{1,2}
            static-host.example.com
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        warn_entries = [(k, v) for k, v in entries if k == 'warn']
        host_entries = [(k, v) for k, v in entries if k == 'host']

        assert len(warn_entries) == 1, (
            f"Expected exactly one warn entry; got {warn_entries!r}"
        )
        assert 'no back-reference' in warn_entries[0][1], (
            f"Warn message should mention 'no back-reference'; got {warn_entries[0][1]!r}"
        )
        assert host_entries == [('host', 'static-host.example.com')], (
            f"Host should appear exactly once; got {host_entries!r}"
        )

    def test_no_backref_host_added_once_across_multiple_iterations(self, pb, tmp_path):
        """A no-backref host inside a 5-iteration loop is still added only once."""
        content = """\
            :for node{1..5}
            always-same.lan
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        warn_entries = [v for k, v in entries if k == 'warn']

        assert host_entries == ['always-same.lan'], (
            f"Expected one host; got {host_entries!r}"
        )
        assert len(warn_entries) == 1, (
            f"Expected one warn; got {warn_entries!r}"
        )

    def test_no_backref_with_brace_expansion(self, pb, tmp_path):
        """No-backref host with its own brace expansion is expanded, added once."""
        content = """\
            :for dc{1,2}
            host{a,b}.static
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        warn_entries = [v for k, v in entries if k == 'warn']

        # Both expansions should appear exactly once
        assert sorted(host_entries) == ['hosta.static', 'hostb.static'], (
            f"Expected two hosts from expansion; got {host_entries!r}"
        )
        assert len(warn_entries) == 1, (
            f"Expected exactly one warn (for the unexpanded template); got {warn_entries!r}"
        )

    def test_multiple_no_backref_hosts_each_warned_once(self, pb, tmp_path):
        """Each distinct no-backref host line in the body produces its own warn."""
        content = """\
            :for shard{1,2}
            always-a.lan
            always-b.lan
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        warn_entries = [v for k, v in entries if k == 'warn']

        assert sorted(host_entries) == ['always-a.lan', 'always-b.lan'], (
            f"Expected two hosts; got {host_entries!r}"
        )
        assert len(warn_entries) == 2, (
            f"Expected two warns (one per no-backref line); got {warn_entries!r}"
        )


# ===========================================================================
# TestForLoopDuplicates
# ===========================================================================

class TestForLoopDuplicates:
    """Duplicate host deduplication inside and around :for loops."""

    def test_duplicate_across_iterations_warned(self, pb, tmp_path):
        """When the pattern expansion yields the same host twice (same backref value
        appearing twice), the second occurrence is warned and skipped."""
        content = """\
            :for dc{1,1,2}
            dc$1-server
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        warn_entries = [v for k, v in entries if k == 'warn']

        # dc1-server appears twice (iterations 0 and 1 both yield '1')
        assert sorted(host_entries) == ['dc1-server', 'dc2-server'], (
            f"Expected two unique hosts; got {host_entries!r}"
        )
        assert len(warn_entries) == 1, (
            f"Expected one duplicate warn; got {warn_entries!r}"
        )
        assert 'duplicate' in warn_entries[0].lower(), (
            f"Warn message should mention 'duplicate'; got {warn_entries[0]!r}"
        )

    def test_duplicate_between_for_loop_and_plain_host_before(self, pb, tmp_path):
        """A plain host declared before the :for loop is deduped if it also
        appears inside the loop."""
        content = """\
            node1.example.com
            :for node{1,2}
            node$1.example.com
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        warn_entries = [v for k, v in entries if k == 'warn']

        assert sorted(host_entries) == [
            'node1.example.com',
            'node2.example.com',
        ], f"Expected two unique hosts; got {host_entries!r}"
        assert len(warn_entries) == 1, (
            f"Expected one duplicate warn; got {warn_entries!r}"
        )

    def test_duplicate_between_for_loop_and_plain_host_after(self, pb, tmp_path):
        """A plain host declared after the :for loop is deduped if already added."""
        content = """\
            :for node{1,2}
            node$1.example.com
            :done
            node1.example.com
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        warn_entries = [v for k, v in entries if k == 'warn']

        assert sorted(host_entries) == [
            'node1.example.com',
            'node2.example.com',
        ], f"Expected two unique hosts; got {host_entries!r}"
        assert len(warn_entries) == 1, (
            f"Expected one duplicate warn; got {warn_entries!r}"
        )

    def test_duplicate_plain_host_outside_for_warned(self, pb, tmp_path):
        """Two identical plain host lines outside any :for are also deduped."""
        content = """\
            router.lan
            router.lan
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        warn_entries = [v for k, v in entries if k == 'warn']

        assert host_entries == ['router.lan'], (
            f"Expected one host; got {host_entries!r}"
        )
        assert len(warn_entries) == 1, (
            f"Expected one duplicate warn; got {warn_entries!r}"
        )
        assert 'duplicate' in warn_entries[0].lower(), (
            f"Warn should say 'duplicate'; got {warn_entries[0]!r}"
        )

    def test_same_host_in_two_for_loops_deduped(self, pb, tmp_path):
        """The same host appearing in two separate :for loops is deduped on the second."""
        content = """\
            :for grp{1}
            shared-host
            :done
            :for grp{2}
            shared-host
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        # shared-host has no backref → warn twice, host once
        host_entries = [v for k, v in entries if k == 'host']
        warn_entries = [v for k, v in entries if k == 'warn']

        assert host_entries.count('shared-host') == 1, (
            f"shared-host should appear once; got {host_entries!r}"
        )
        # First loop → no-backref warn; second loop → no-backref warn (new loop, same line)
        # AND duplicate warn from seen_hosts
        no_backref_warns = [w for w in warn_entries if 'no back-reference' in w]
        dup_warns = [w for w in warn_entries if 'duplicate' in w]
        assert len(no_backref_warns) >= 1, (
            f"Expected at least one no-backref warn; got {warn_entries!r}"
        )
        assert len(dup_warns) >= 1, (
            f"Expected at least one duplicate warn; got {warn_entries!r}"
        )


# ===========================================================================
# TestForLoopErrors
# ===========================================================================

class TestForLoopErrors:
    """Error conditions: implicit :done at EOF, :done without :for, nested :for."""

    def test_unclosed_for_at_eof_is_implicit_done(self, pb, tmp_path):
        """A :for loop that reaches EOF without :done is treated as implicit :done."""
        content = """\
            :for node{1,2}
            node$1
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        error_entries = [(k, v) for k, v in entries if k == 'error']
        host_entries = [v for k, v in entries if k == 'host']

        assert not error_entries, (
            f"Expected no error for implicit :done at EOF; got {error_entries!r}"
        )
        assert host_entries == ['node1', 'node2'], (
            f"Expected hosts node1, node2 from implicit :done; got {host_entries!r}"
        )

    def test_done_without_for_produces_error(self, pb, tmp_path):
        """:done outside any :for loop produces an error entry."""
        content = """\
            host1
            :done
            host2
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        error_entries = [(k, v) for k, v in entries if k == 'error']

        assert any(':done' in v.lower() or 'without' in v.lower()
                   for _, v in error_entries), (
            f"Expected an error mentioning ':done without :for'; got {error_entries!r}"
        )

    def test_nested_for_produces_error(self, pb, tmp_path):
        """A :for inside another :for body produces an error entry."""
        content = """\
            :for dc{1,2}
            :for node{1,2}
            dc$1-node$2
            :done
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        error_entries = [(k, v) for k, v in entries if k == 'error']

        assert len(error_entries) >= 1, (
            f"Expected at least one error for nested :for; got {entries!r}"
        )
        assert any('nested' in v.lower() or ':for' in v.lower()
                   for _, v in error_entries), (
            f"Error should mention 'nested' or ':for'; got {error_entries!r}"
        )

    def test_ssh_begin_inside_for_produces_error(self, pb, tmp_path):
        """:ssh-begin inside a :for body produces an error entry."""
        content = """\
            :for dc{1,2}
            :ssh-begin user@dc$1
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        error_entries = [(k, v) for k, v in entries if k == 'error']

        assert len(error_entries) >= 1, (
            f"Expected at least one error; got {entries!r}"
        )
        assert any('ssh-begin' in v.lower() for _, v in error_entries), (
            f"Error should mention 'ssh-begin'; got {error_entries!r}"
        )

    def test_ssh_end_inside_for_produces_error(self, pb, tmp_path):
        """:ssh-end inside a :for body produces an error entry."""
        content = """\
            :for dc{1,2}
            :ssh-end
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        error_entries = [(k, v) for k, v in entries if k == 'error']

        assert len(error_entries) >= 1, (
            f"Expected at least one error; got {entries!r}"
        )
        assert any('ssh-end' in v.lower() for _, v in error_entries), (
            f"Error should mention 'ssh-end'; got {error_entries!r}"
        )

    def test_invalid_brace_in_for_pattern_produces_error(self, pb, tmp_path):
        """An invalid brace group in the :for pattern produces an error, not a crash."""
        content = """\
            :for host{}
            host$1
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        error_entries = [(k, v) for k, v in entries if k == 'error']

        assert len(error_entries) >= 1, (
            f"Expected at least one error for invalid brace group; got {entries!r}"
        )


# ===========================================================================
# TestForLoopInsideSshBlock
# ===========================================================================

class TestForLoopInsideSshBlock:
    """:for loop inside an :ssh-begin / :ssh-end block."""

    def test_for_inside_ssh_block_emits_ssh_commands(self, pb, tmp_path):
        """Host lines with back-references inside :for / :ssh-begin emit :ssh commands."""
        content = """\
            :ssh-begin user@gateway
            :for node{1,2}
            192.168.1.$1
            :done
            :ssh-end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        assert ':ssh user@gateway 192.168.1.1' in cmd_entries, (
            f"Expected SSH command for node1; got {cmd_entries!r}"
        )
        assert ':ssh user@gateway 192.168.1.2' in cmd_entries, (
            f"Expected SSH command for node2; got {cmd_entries!r}"
        )
        # No 'host' entries should be produced — all go through SSH
        assert not any(k == 'host' for k, _ in entries), (
            f"Expected no plain host entries inside SSH block; got {entries!r}"
        )

    def test_for_inside_ssh_block_deduplication(self, pb, tmp_path):
        """Duplicate SSH hosts from :for are warned and deduplicated."""
        content = """\
            :ssh-begin jump@bastion
            :for group{1,1,2}
            app$1.internal
            :done
            :ssh-end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']
        warn_entries = [v for k, v in entries if k == 'warn']

        # app1.internal appears twice (group {1,1} → same host); app2.internal once
        ssh1 = ':ssh jump@bastion app1.internal'
        ssh2 = ':ssh jump@bastion app2.internal'
        assert cmd_entries.count(ssh1) == 1, (
            f"app1.internal SSH command should appear once; got {cmd_entries!r}"
        )
        assert ssh2 in cmd_entries, (
            f"app2.internal SSH command should appear; got {cmd_entries!r}"
        )
        assert len(warn_entries) == 1, (
            f"Expected one duplicate warn; got {warn_entries!r}"
        )

    def test_no_backref_inside_for_inside_ssh_block(self, pb, tmp_path):
        """No-backref host in :for inside SSH block: added once as SSH command."""
        content = """\
            :ssh-begin user@gw
            :for zone{1,2}
            fixed.host
            :done
            :ssh-end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']
        warn_entries = [v for k, v in entries if k == 'warn']

        ssh_cmd = ':ssh user@gw fixed.host'
        assert cmd_entries.count(ssh_cmd) == 1, (
            f"fixed.host SSH command should appear once; got {cmd_entries!r}"
        )
        assert len(warn_entries) == 1, (
            f"Expected one no-backref warn; got {warn_entries!r}"
        )
        assert 'no back-reference' in warn_entries[0], (
            f"Warn message should mention 'no back-reference'; got {warn_entries[0]!r}"
        )


# ===========================================================================
# TestForLoopMixed
# ===========================================================================

class TestForLoopMixed:
    """Integration-style tests combining :for with other file features."""

    def test_for_loop_between_plain_hosts(self, pb, tmp_path):
        """:for loop surrounded by plain host lines in the file."""
        content = """\
            before.example.com
            :for mid{1,2}
            mid$1.example.com
            :done
            after.example.com
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        assert host_entries == [
            'before.example.com',
            'mid1.example.com',
            'mid2.example.com',
            'after.example.com',
        ], f"Unexpected host order: {host_entries!r}"

    def test_for_loop_after_section_header(self, pb, tmp_path):
        """A section header before :for is preserved; loop entries follow it."""
        content = """\
            ## My Group
            :for app{1,2}
            app$1
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries[0] == ('section', 'My Group', 1, False), (
            f"First entry should be section header; got {entries[0]!r}"
        )
        host_entries = [rest[0] for k, *rest in entries if k == 'host']
        assert host_entries == ['app1', 'app2'], (
            f"Expected two hosts after section; got {host_entries!r}"
        )

    def test_empty_for_body_produces_no_entries(self, pb, tmp_path):
        """:for with a body that consists only of comments produces no host entries."""
        content = """\
            :for node{1,2}
            # just a comment
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert not any(k in ('host', 'warn', 'error') for k, _ in entries), (
            f"Empty :for body should produce no host/warn/error entries; got {entries!r}"
        )

    def test_resolv_command_in_for_body(self, pb, tmp_path):
        """Generic commands like :resolv inside :for are emitted per iteration
        with back-reference substitution applied."""
        content = """\
            :for {1,2}
            :resolv 10.0.0.$1 node$1
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']
        assert ':resolv 10.0.0.1 node1' in cmd_entries, (
            f"Expected resolv command for iteration 1; got {cmd_entries!r}"
        )
        assert ':resolv 10.0.0.2 node2' in cmd_entries, (
            f"Expected resolv command for iteration 2; got {cmd_entries!r}"
        )

    def test_for_pattern_without_braces_single_iteration(self, pb, tmp_path):
        """:for pattern without brace groups runs a single iteration (full_str = pattern)."""
        content = """\
            :for static-host
            $0.local
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [('host', 'static-host.local')], (
            f"Expected single host; got {entries!r}"
        )

    def test_for_pattern_let_var_expansion(self, pb, tmp_path):
        """:let variable in :for pattern is expanded before brace expansion.

        Regression test: previously the :for branch skipped variable expansion,
        so ':let x {1..3}; :for host-$x' would iterate once over the literal
        string 'host-{1..3}' instead of three times.
        """
        content = """\
            :let x {1..3}
            :for host-$x
            node$1
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        assert host_entries == ['node1', 'node2', 'node3'], (
            f"Expected 3 hosts from let-expanded :for pattern; got {host_entries!r}"
        )

    def test_for_pattern_let_var_dash_range(self, pb, tmp_path):
        """:let variable with dash-range syntax {n-m} expands correctly in :for.

        Regression test for the sensor-station use-case: ':let sh_num {1-4}'
        then ':for sensor-hub-$sh_num' with body 'sh$1-router' should produce
        four hosts (sh1-router through sh4-router).
        """
        content = """\
            :let sh_num {1-4}
            :for sensor-hub-$sh_num
            sh$1-router
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        assert host_entries == [
            'sh1-router', 'sh2-router', 'sh3-router', 'sh4-router',
        ], (
            f"Expected 4 hosts from dash-range let-expanded :for pattern; "
            f"got {host_entries!r}"
        )

    def test_for_pattern_let_var_multiple_bodies(self, pb, tmp_path):
        """Multiple hosts in :for body all get back-reference substitution."""
        content = """\
            :let nums {1,2}
            :for hub-$nums
            $1-router
            $1-switch
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        assert host_entries == [
            '1-router', '1-switch', '2-router', '2-switch',
        ], f"Unexpected hosts: {host_entries!r}"

    def test_ssh_host_and_plain_host_not_cross_deduped(self, pb, tmp_path):
        """The same hostname used as a plain host and as an SSH ping-target
        are NOT considered duplicates (different dedup keys)."""
        content = """\
            target.host
            :ssh-begin user@gw
            :for x{1}
            target.host
            :done
            :ssh-end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        cmd_entries  = [v for k, v in entries if k == 'cmd']
        warn_entries = [v for k, v in entries if k == 'warn']

        assert host_entries == ['target.host'], (
            f"Expected one plain host; got {host_entries!r}"
        )
        # The SSH command uses 'target.host' as the no-backref line → warn, added once
        ssh_cmd = ':ssh user@gw target.host'
        assert ssh_cmd in cmd_entries, (
            f"Expected SSH command; got {cmd_entries!r}"
        )
        # No duplicate warn — they are different keys
        dup_warns = [w for w in warn_entries if 'duplicate' in w]
        assert not dup_warns, (
            f"Plain host and SSH host should not cross-dedup; got warn {warn_entries!r}"
        )

