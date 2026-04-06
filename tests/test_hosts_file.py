"""Unit tests for parse_hosts_file() — focusing on the backslash line-continuation
pre-pass that joins lines ending with '\\' to their successor.

These tests call pb.parse_hosts_file() directly with temporary files so no
curses session, ping threads, or network access is required.

Fixture
-------
pb
    The ping-bulk module, imported once per session via importlib (same
    pattern used in test_config.py).
"""

import os
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

from utils.hosts_helper import write_hosts

# ===========================================================================
# TestBackslashContinuation
# ===========================================================================

class TestBackslashContinuation:
    """Backslash at end of a line causes it to be joined with the next line."""

    # ------------------------------------------------------------------
    # 1. Polyglot shebang trick
    # ------------------------------------------------------------------

    def test_polyglot_shebang_trick(self, pb, tmp_path):
        """The self-executing hosts-file idiom must not produce any extra entries.

        The file contains:
            # \\
            exec ping-bulk -f "$0"
            8.8.8.8

        The continuation join produces '# exec ping-bulk …' which is a comment
        line and is therefore skipped.  Only 8.8.8.8 must appear in entries.
        """
        content = textwrap.dedent("""\
            # \\
            exec ping-bulk -f "$0" "$@"
            8.8.8.8
        """)
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [('host', '8.8.8.8')], (
            f"Polyglot shebang should produce only the real host entry; got {entries!r}"
        )

    # ------------------------------------------------------------------
    # 2. Host address split across two lines
    # ------------------------------------------------------------------

    def test_host_split_across_lines(self, pb, tmp_path):
        """A host/IP split with '\\' must be joined into a single host entry."""
        content = "10.0.0.\\\n1\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [('host', '10.0.0.1')], (
            f"Expected [('host', '10.0.0.1')], got {entries!r}"
        )

    # ------------------------------------------------------------------
    # 3. Section header split across two lines
    # ------------------------------------------------------------------

    def test_section_header_split(self, pb, tmp_path):
        """A '## …\\' section header split across two lines must be joined correctly."""
        content = "## My \\\nSection\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [('section', 'My Section', 1)], (
            f"Expected [('section', 'My Section')], got {entries!r}"
        )

    # ------------------------------------------------------------------
    # 4. Command split across two lines
    # ------------------------------------------------------------------

    def test_command_split_across_lines(self, pb, tmp_path):
        """:resolv split over two lines must produce a single 'cmd' entry."""
        content = ":resolv \\\n10.0.0.1 switch1\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [('cmd', ':resolv 10.0.0.1 switch1')], (
            f"Expected single cmd entry; got {entries!r}"
        )

    # ------------------------------------------------------------------
    # 5. Three-line continuation chain
    # ------------------------------------------------------------------

    def test_multiple_continuations(self, pb, tmp_path):
        """Three fragments joined by two consecutive backslash continuations."""
        content = "10.\\\n0.\\\n0.1\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [('host', '10.0.0.1')], (
            f"Expected [('host', '10.0.0.1')], got {entries!r}"
        )

    # ------------------------------------------------------------------
    # 6. Trailing continuation at EOF (no final newline)
    # ------------------------------------------------------------------

    def test_trailing_continuation_at_eof(self, pb, tmp_path):
        """A backslash-terminated line with no successor (EOF) is still parsed.

        The pre-pass flushes the accumulated buffer after the loop so the
        partial line is not silently discarded.
        """
        # Write bytes directly — no trailing newline after the backslash.
        p = tmp_path / 'hosts_eof.txt'
        p.write_bytes(b'10.0.0.2\\\n')  # backslash then newline — no following line
        entries = pb.parse_hosts_file(str(p))
        assert entries == [('host', '10.0.0.2')], (
            f"Expected [('host', '10.0.0.2')], got {entries!r}"
        )

    # ------------------------------------------------------------------
    # 7. Normal lines are unaffected
    # ------------------------------------------------------------------

    def test_normal_lines_unaffected(self, pb, tmp_path):
        """Lines without a trailing backslash must parse exactly as before."""
        content = textwrap.dedent("""\
            # comment
            ## Section A
            192.168.1.1
            :resolv 10.0.0.1 router1
        """)
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'Section A', 1),
            ('host',    '192.168.1.1'),
            ('cmd',     ':resolv 10.0.0.1 router1'),
        ], f"Normal-line parsing changed unexpectedly; got {entries!r}"


# ===========================================================================
# TestInlineComment
# ===========================================================================

class TestInlineComment:
    """'host ## comment' inline annotation: emits :resolv for IPs, ignored for hostnames."""

    def test_ip_with_inline_comment_emits_resolv(self, pb, tmp_path):
        """An IP followed by '## label' must emit a :resolv command before the host entry."""
        content = "10.0.0.1 ## router\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('cmd',  ':resolv 10.0.0.1 router'),
            ('host', '10.0.0.1'),
        ], f"Expected resolv+host for IP with inline comment; got {entries!r}"

    def test_hostname_with_inline_comment_no_resolv(self, pb, tmp_path):
        """A hostname followed by '## label' must emit only a host entry (no :resolv)."""
        content = "web.example.com ## webserver\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', 'web.example.com'),
        ], f"Expected host-only for hostname with inline comment; got {entries!r}"

    def test_ip_without_inline_comment_no_resolv(self, pb, tmp_path):
        """A plain IP with no inline comment must emit only a host entry."""
        content = "192.168.1.1\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', '192.168.1.1'),
        ], f"Expected host-only for plain IP; got {entries!r}"

    def test_section_header_not_treated_as_inline_comment(self, pb, tmp_path):
        """A '## Section' line must produce a section entry, not a resolv command."""
        content = "## Routers\n10.0.0.1\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'Routers', 1),
            ('host',    '10.0.0.1'),
        ], f"Section header must not be treated as inline comment; got {entries!r}"

    def test_multiple_ips_with_inline_comments(self, pb, tmp_path):
        """Each IP with an inline comment gets its own :resolv + host pair."""
        content = textwrap.dedent("""\
            10.0.0.1 ## gw1
            10.0.0.2 ## gw2
            hostname.local ## ignored
        """)
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('cmd',  ':resolv 10.0.0.1 gw1'),
            ('host', '10.0.0.1'),
            ('cmd',  ':resolv 10.0.0.2 gw2'),
            ('host', '10.0.0.2'),
            ('host', 'hostname.local'),
        ], f"Unexpected entries for multiple annotated lines; got {entries!r}"


# ===========================================================================
# TestInlineCommentBackref
# ===========================================================================

class TestInlineCommentBackref:
    """Inline '## comment' may contain $N back-references that are
    resolved against the brace-group captures for each expanded IP row.

    Example:  192.168.1.{2..5} ## workstation$1
      →  :resolv 192.168.1.2 workstation2
         :resolv 192.168.1.3 workstation3  …etc.
    """

    def test_single_group_dollar_backref(self, pb, tmp_path):
        """$1 in the inline comment is replaced by the value of the first brace group."""
        content = "192.168.1.{2..5} ## workstation$1\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('cmd',  ':resolv 192.168.1.2 workstation2'),
            ('host', '192.168.1.2'),
            ('cmd',  ':resolv 192.168.1.3 workstation3'),
            ('host', '192.168.1.3'),
            ('cmd',  ':resolv 192.168.1.4 workstation4'),
            ('host', '192.168.1.4'),
            ('cmd',  ':resolv 192.168.1.5 workstation5'),
            ('host', '192.168.1.5'),
        ], f"$1 back-reference in inline comment not expanded; got {entries!r}"

    def test_dollar0_full_host_backref(self, pb, tmp_path):
        """$0 in the inline comment is replaced by the full expanded IP string."""
        content = "10.0.0.{1,2} ## ip-$0\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('cmd',  ':resolv 10.0.0.1 ip-10.0.0.1'),
            ('host', '10.0.0.1'),
            ('cmd',  ':resolv 10.0.0.2 ip-10.0.0.2'),
            ('host', '10.0.0.2'),
        ], f"$0 back-reference in inline comment not expanded; got {entries!r}"

    def test_no_backref_comment_used_verbatim(self, pb, tmp_path):
        """An inline comment without any back-reference is used as-is for every row."""
        content = "10.2.0.{1,2} ## gateway\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('cmd',  ':resolv 10.2.0.1 gateway'),
            ('host', '10.2.0.1'),
            ('cmd',  ':resolv 10.2.0.2 gateway'),
            ('host', '10.2.0.2'),
        ], f"Comment without back-reference should be used verbatim; got {entries!r}"

    def test_two_brace_groups_two_backrefs(self, pb, tmp_path):
        """Two brace groups produce $1 and $2 back-references independently."""
        content = "10.{1,2}.0.{3,4} ## rack$1-port$2\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('cmd',  ':resolv 10.1.0.3 rack1-port3'),
            ('host', '10.1.0.3'),
            ('cmd',  ':resolv 10.1.0.4 rack1-port4'),
            ('host', '10.1.0.4'),
            ('cmd',  ':resolv 10.2.0.3 rack2-port3'),
            ('host', '10.2.0.3'),
            ('cmd',  ':resolv 10.2.0.4 rack2-port4'),
            ('host', '10.2.0.4'),
        ], f"Two-group back-reference in inline comment failed; got {entries!r}"

    def test_plain_ip_no_brace_no_backref(self, pb, tmp_path):
        """A plain IP with a literal inline comment (no braces) still works correctly."""
        content = "172.16.0.1 ## firewall\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('cmd',  ':resolv 172.16.0.1 firewall'),
            ('host', '172.16.0.1'),
        ], f"Plain IP with literal comment failed; got {entries!r}"

