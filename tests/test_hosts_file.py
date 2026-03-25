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

import importlib.machinery
import importlib.util
import os
import textwrap

import pytest


# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def pb(app_path):
    """The ping-bulk module, imported once for the whole test session."""
    loader = importlib.machinery.SourceFileLoader('ping_bulk', app_path)
    spec   = importlib.util.spec_from_loader('ping_bulk', loader)
    mod    = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def write_hosts(tmp_path, content):
    """Write *content* to a temp file and return its path (str)."""
    p = tmp_path / 'hosts.txt'
    p.write_text(content)
    return str(p)


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
        assert entries == [('section', 'My Section')], (
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
            ('section', 'Section A'),
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
            ('section', 'Routers'),
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

