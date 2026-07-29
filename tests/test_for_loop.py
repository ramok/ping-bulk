"""Unit tests for :for/:end loop handling in parse_hosts_file().

Covers:
  - basic backref expansion $N
  - $0 (full-string back-reference)
  - no-backref host lines inside :for  → warn + add once
  - duplicate hosts (within loop, across iterations, vs. outside loop)
  - unclosed :for at EOF  → implicit :end (hosts produced, no error)
  - :end without :for    → error entry
  - nested :for           → error entry
  - :with/:end inside :for → :remote-ping commands emitted
  - :for inside :with remote-ping block    → SSH commands emitted
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
            :end
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
            :end
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
            :end
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
            :end
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
            :end
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
            :end
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
            :end
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
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'Data Centre 1', 1, False, False),
            ('host',    'dc1-router'),
            ('section', 'Data Centre 2', 1, False, False),
            ('host',    'dc2-router'),
        ], f"Unexpected entries: {entries!r}"

    def test_title_directive_with_backref(self, pb, tmp_path):
        """:title inside :for with $N back-reference."""
        content = """\
            :for pod{a,b}
            :title Pod $1
            pod$1-host
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'Pod a', 1, False, False),
            ('host',    'poda-host'),
            ('section', 'Pod b', 1, False, False),
            ('host',    'podb-host'),
        ], f"Unexpected entries: {entries!r}"

    def test_section_header_without_backref_emitted_per_iteration(self, pb, tmp_path):
        """## headers without back-references are still emitted every iteration
        (no warning — section headers are structural, not host entries)."""
        content = """\
            :for node{1,2}
            ## Servers
            node$1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        # Section emitted twice; no 'warn' tuples expected
        assert entries == [
            ('section', 'Servers', 1, False, False),
            ('host',    'node1'),
            ('section', 'Servers', 1, False, False),
            ('host',    'node2'),
        ], f"Unexpected entries: {entries!r}"

    def test_title_directive_without_backref_emitted_per_iteration(self, pb, tmp_path):
        """:title without back-references emitted every iteration (no warning)."""
        content = """\
            :for sp{1,2}
            :title Static Section
            sp$1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'Static Section', 1, False, False),
            ('host',    'sp1'),
            ('section', 'Static Section', 1, False, False),
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
            :end
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
            :end
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
            :end
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
            :end
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
            :end
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
            :end
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
            :end
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
            :end
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
            :end
            :for grp{2}
            shared-host
            :end
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
    """Error conditions: implicit :end at EOF, :end without :for, nested :for."""

    def test_unclosed_for_at_eof_is_implicit_done(self, pb, tmp_path):
        """A :for loop that reaches EOF without :end is treated as implicit :end."""
        content = """\
            :for node{1,2}
            node$1
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        error_entries = [(k, v) for k, v in entries if k == 'error']
        host_entries = [v for k, v in entries if k == 'host']

        assert not error_entries, (
            f"Expected no error for implicit :end at EOF; got {error_entries!r}"
        )
        assert host_entries == ['node1', 'node2'], (
            f"Expected hosts node1, node2 from implicit :end; got {host_entries!r}"
        )

    def test_done_without_for_produces_error(self, pb, tmp_path):
        """:end outside any :for loop produces an error entry."""
        content = """\
            host1
            :end
            host2
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        error_entries = [(k, v) for k, v in entries if k == 'error']

        assert any(':end' in v.lower() or 'without' in v.lower()
                   for _, v in error_entries), (
            f"Expected an error mentioning ':end without :for'; got {error_entries!r}"
        )

    def test_nested_for_produces_error(self, pb, tmp_path):
        """A :for inside another :for body produces an error entry."""
        content = """\
            :for dc{1,2}
            :for node{1,2}
            dc$1-node$2
            :end
            :end
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

    def test_with_inside_for_emits_remote_ping(self, pb, tmp_path):
        """:with remote-ping inside :for body emits :remote-ping commands with back-references."""
        content = """\
            :for dc{1,2}
            :with remote-ping user@dc$1
            target-$1
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']
        error_entries = [(k, v) for k, v in entries if k == 'error']

        assert not error_entries, f"Expected no errors; got {error_entries!r}"
        assert ':remote-ping user@dc1 target-1' in cmd_entries, (
            f"Expected :remote-ping for dc1; got {cmd_entries!r}"
        )
        assert ':remote-ping user@dc2 target-2' in cmd_entries, (
            f"Expected :remote-ping for dc2; got {cmd_entries!r}"
        )

    def test_orphan_done_produces_error(self, pb, tmp_path):
        """A :end with no open :with or :for block inside a :for body produces an error entry."""
        content = """\
            :for dc{1,2}
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        error_entries = [(k, v) for k, v in entries if k == 'error']

        assert len(error_entries) >= 1, (
            f"Expected at least one error; got {entries!r}"
        )
        assert any(':end' in v.lower() or 'without' in v.lower()
                   for _, v in error_entries), (
            f"Error should mention ':end without'; got {error_entries!r}"
        )

    def test_invalid_brace_in_for_pattern_produces_error(self, pb, tmp_path):
        """An invalid brace group in the :for pattern produces an error, not a crash."""
        content = """\
            :for host{}
            host$1
            :end
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
    """:for loop inside an :with remote-ping / :end block."""

    def test_for_inside_ssh_block_emits_ssh_commands(self, pb, tmp_path):
        """Host lines with back-references inside :for / :with remote-ping emit :remote-ping commands."""
        content = """\
            :with remote-ping user@gateway
            :for node{1,2}
            192.168.1.$1
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']

        assert ':remote-ping user@gateway 192.168.1.1' in cmd_entries, (
            f"Expected SSH command for node1; got {cmd_entries!r}"
        )
        assert ':remote-ping user@gateway 192.168.1.2' in cmd_entries, (
            f"Expected SSH command for node2; got {cmd_entries!r}"
        )
        # No 'host' entries should be produced — all go through SSH
        assert not any(k == 'host' for k, _ in entries), (
            f"Expected no plain host entries inside SSH block; got {entries!r}"
        )

    def test_for_inside_ssh_block_deduplication(self, pb, tmp_path):
        """Duplicate SSH hosts from :for are warned and deduplicated."""
        content = """\
            :with remote-ping jump@bastion
            :for group{1,1,2}
            app$1.internal
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']
        warn_entries = [v for k, v in entries if k == 'warn']

        # app1.internal appears twice (group {1,1} → same host); app2.internal once
        ssh1 = ':remote-ping jump@bastion app1.internal'
        ssh2 = ':remote-ping jump@bastion app2.internal'
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
            :with remote-ping user@gw
            :for zone{1,2}
            fixed.host
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmd_entries = [v for k, v in entries if k == 'cmd']
        warn_entries = [v for k, v in entries if k == 'warn']

        ssh_cmd = ':remote-ping user@gw fixed.host'
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
            :end
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
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries[0] == ('section', 'My Group', 1, False, False), (
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
            :end
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
            :end
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
            :end
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
            :end
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
            :end
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
            :end
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
            :with remote-ping user@gw
            :for x{1}
            target.host
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        host_entries = [v for k, v in entries if k == 'host']
        cmd_entries  = [v for k, v in entries if k == 'cmd']
        warn_entries = [v for k, v in entries if k == 'warn']

        assert host_entries == ['target.host'], (
            f"Expected one plain host; got {host_entries!r}"
        )
        # The SSH command uses 'target.host' as the no-backref line → warn, added once
        ssh_cmd = ':remote-ping user@gw target.host'
        assert ssh_cmd in cmd_entries, (
            f"Expected SSH command; got {cmd_entries!r}"
        )
        # No duplicate warn — they are different keys
        dup_warns = [w for w in warn_entries if 'duplicate' in w]
        assert not dup_warns, (
            f"Plain host and SSH host should not cross-dedup; got warn {warn_entries!r}"
        )



# ===========================================================================
# TestForResolv - :resolv inside :for body
# ===========================================================================

class TestForResolv:
    """Tests for :resolv directives inside :for bodies.

    Key known limitation: inside a :for loop $1 is consumed as the loop
    variable. A :resolv line with a second brace group (e.g. {41,42}) produces
    $2 back-references in the hostname template that refer to the *second*
    capture inside _cmd_resolv — but after the loop substitutes $1, only one
    brace group remains, so $2 is out of range and is left as the literal
    string '$2' instead of the expected value.
    """

    def test_resolv_single_brace_inside_for_works(self, pb, tmp_path):
        """:resolv with a single brace group inside :for emits correct cmd entries."""
        content = """\
            :for hub-{1-2}
                :resolv 10.0.$1.1  $1-gw
                $1-gw
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [v for k, v in entries if k in ('error', 'warn')]
        assert not errors, f"Unexpected errors: {errors}"

        resolv_cmds = [v for k, v in entries if k == 'cmd' and 'resolv' in v]
        assert ':resolv 10.0.1.1  1-gw' in resolv_cmds
        assert ':resolv 10.0.2.1  2-gw' in resolv_cmds

        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['1-gw', '2-gw']

    def test_resolv_double_brace_inside_for_bug(self, pb, tmp_path):
        """:resolv with two brace groups inside :for hits the $2-lost bug.

        When :resolv 10.0.$1.{41,42} sh$1-cam$2 is in a :for body,
        the loop substitutes $1 (hub number) but $2 (camera suffix from
        {41,42}) is out of range at :resolv dispatch time and left as the
        literal string '$2'.  This test documents the bug so any fix is noticed.

        The recommended workaround is inline ## label with :for named var:
            :for sh in hub-{1-4}
                10.0.$sh.{41,42} ## sh$sh-cam$1
        """
        content = """\
            :for hub-{1-1}
                :resolv 10.0.$1.{41,42}  sh$1-cam$2
                sh$1-cam41
                sh$1-cam42
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))

        # There is ONE resolv cmd entry with brace expansion not yet applied
        resolv_cmds = [v for k, v in entries if k == 'cmd' and 'resolv' in v
                       and 'cam' in v]
        assert len(resolv_cmds) == 1, f"Expected 1 cam resolv cmd: {resolv_cmds}"

        # The hostname template still contains literal '$2' — the bug
        assert '$2' in resolv_cmds[0], (
            "Bug: $2 should remain unresolved when only one capture is "
            f"available inside :for; got: {resolv_cmds}"
        )

    def test_resolv_double_brace_workaround_explicit_lines(self, pb, tmp_path):
        """Workaround: explicit :resolv lines with literal suffixes avoid the $2 bug."""
        content = """\
            :for hub-{1-2}
                :resolv 10.0.$1.41  sh$1-cam41
                :resolv 10.0.$1.42  sh$1-cam42
                sh$1-cam41
                sh$1-cam42
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [v for k, v in entries if k in ('error', 'warn')]
        assert not errors, f"Unexpected errors: {errors}"

        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['sh1-cam41', 'sh1-cam42', 'sh2-cam41', 'sh2-cam42']

    def test_inline_label_in_for_body(self, pb, tmp_path):
        """Inline ## label in :for body emits :resolv cmd + host entry per IP."""
        content = """\
            :for hub-{1-2}
                10.0.$1.41 ## sh$1-cam41
                10.0.$1.42 ## sh$1-cam42
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [v for k, v in entries if k in ('error', 'warn')]
        assert not errors, f"Unexpected errors: {errors}"

        resolv_cmds = [v for k, v in entries if k == 'cmd' and 'resolv' in v]
        assert ':resolv 10.0.1.41 sh1-cam41' in resolv_cmds
        assert ':resolv 10.0.2.42 sh2-cam42' in resolv_cmds

        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['sh1-cam41', 'sh1-cam42', 'sh2-cam41', 'sh2-cam42']

    def test_inline_label_named_var_brace_capture(self, pb, tmp_path):
        """':for sh in' named var + inline ## uses $1 for brace capture in label.

        With :for sh in hub-{1-2}, $sh = hub number and $1 is free to refer
        to the back-reference from a brace group in the host IP pattern.
        This is the preferred idiom for multi-suffix entries like cameras.
        """
        content = """\
            :for sh in hub-{1-2}
                10.0.$sh.{41,42} ## sh$sh-cam$1
                10.0.$sh.{31,32} ## sh$sh-ps$1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [v for k, v in entries if k in ('error', 'warn')]
        assert not errors, f"Unexpected errors: {errors}"

        resolv_cmds = [v for k, v in entries if k == 'cmd' and 'resolv' in v]
        assert ':resolv 10.0.1.41 sh1-cam41' in resolv_cmds
        assert ':resolv 10.0.1.42 sh1-cam42' in resolv_cmds
        assert ':resolv 10.0.2.31 sh2-ps31' in resolv_cmds
        assert ':resolv 10.0.2.32 sh2-ps32' in resolv_cmds

        hosts = [v for k, v in entries if k == 'host']
        assert hosts == [
            'sh1-cam41', 'sh1-cam42', 'sh1-ps31', 'sh1-ps32',
            'sh2-cam41', 'sh2-cam42', 'sh2-ps31', 'sh2-ps32',
        ]


class TestForRemotePingLabel:
    """Regression tests: ## label on :remote-ping lines inside :for body."""

    def test_remote_ping_label_does_not_corrupt_command(self, pb, tmp_path):
        """:remote-ping relay target ## label inside :for must NOT include the label
        in the emitted command — it would corrupt shlex parsing and cause SSH to
        try to connect to the wrong host."""
        content = """\
            :for i in hub-{1..2}
                10.0.$1.1 ## h$i-router
                :remote-ping sh$1-relay 10.87.0.1 ## ps-jetson
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [v for k, v in entries if k == 'cmd']
        errors = [v for k, v in entries if k in ('error', 'warn')]

        assert not errors, f"Unexpected errors/warns: {errors}"
        # Commands must be clean — no '##' or 'ps-jetson' in the remote-ping cmd.
        rp_cmds = [c for c in cmds if c.startswith(':remote-ping')]
        assert ':remote-ping sh1-relay 10.87.0.1' in rp_cmds, (
            f"Clean :remote-ping for hub-1 not found; got {rp_cmds!r}"
        )
        assert ':remote-ping sh2-relay 10.87.0.1' in rp_cmds, (
            f"Clean :remote-ping for hub-2 not found; got {rp_cmds!r}"
        )
        assert all('##' not in c for c in rp_cmds), (
            f"'##' leaked into :remote-ping commands: {rp_cmds!r}"
        )
