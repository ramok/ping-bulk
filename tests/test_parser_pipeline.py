"""End-to-end parser pipeline tests — D7.

Uses _HostsParser.parse() to feed source text and assert on the resulting
entry-tuple list.  This covers the full preprocessing → _parse_lines path
including:

  - Plain host entries, IP hosts, brace expansion
  - ## section headers and :title directive
  - :let variable substitution
  - :for loop expansion (with and without back-references)
  - :with remote-ping block
  - :if / :elif / :else / :end conditionals
  - :resolv inline comment DNS override
  - Inline comments, ; separators, \\ continuations
  - Duplicate host deduplication (warn tuple)
  - Optional hosts (?host)
  - Error tuples for bad directives
"""

import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def parse(pb, src):
    """Parse *src* with a fresh _HostsParser and return entry list."""
    return pb._HostsParser().parse(src)


def hosts(entries):
    """Extract plain 'host' tuples from an entry list."""
    return [e[1] for e in entries if e[0] == 'host']


def cmds(entries):
    """Extract ('cmd', …) entries."""
    return [e[1] for e in entries if e[0] == 'cmd']


def sections(entries):
    """Extract ('section', title, level, …) tuples."""
    return [(e[1], e[2]) for e in entries if e[0] == 'section']


def warns(entries):
    return [e for e in entries if e[0] == 'warn']


def errors(entries):
    return [e for e in entries if e[0] == 'error']


# ===========================================================================
# Basic host lines
# ===========================================================================

class TestBasicHosts:

    def test_single_plain_host(self, pb):
        result = parse(pb, '10.0.0.1\n')
        assert hosts(result) == ['10.0.0.1']

    def test_multiple_hosts(self, pb):
        result = parse(pb, '10.0.0.1\n10.0.0.2\n')
        assert hosts(result) == ['10.0.0.1', '10.0.0.2']

    def test_blank_lines_ignored(self, pb):
        result = parse(pb, '\n10.0.0.1\n\n10.0.0.2\n')
        assert hosts(result) == ['10.0.0.1', '10.0.0.2']

    def test_comment_lines_ignored(self, pb):
        result = parse(pb, '# comment\n10.0.0.1\n')
        assert hosts(result) == ['10.0.0.1']

    def test_semicolon_separator(self, pb):
        result = parse(pb, '10.0.0.1; 10.0.0.2\n')
        assert hosts(result) == ['10.0.0.1', '10.0.0.2']

    def test_backslash_continuation(self, pb):
        result = parse(pb, '10.0.0.1\\\n 10.0.0.2\n')
        # After joining: '10.0.0.1 10.0.0.2' — treated as a spaced entry
        # (may produce a warn about space, but both should NOT appear as two hosts)
        # The important thing is the parse completes without crash
        # (exact behaviour depends on the spaced-host path; we just check no error)
        assert errors(result) == []

    def test_duplicate_host_produces_warn(self, pb):
        result = parse(pb, '10.0.0.1\n10.0.0.1\n')
        assert len(warns(result)) == 1
        assert '10.0.0.1' in warns(result)[0][1]


# ===========================================================================
# Brace expansion
# ===========================================================================

class TestBraceExpansion:

    def test_numeric_range(self, pb):
        result = parse(pb, '10.0.0.{1..3}\n')
        assert hosts(result) == ['10.0.0.1', '10.0.0.2', '10.0.0.3']

    def test_list_expansion(self, pb):
        result = parse(pb, 'host-{a,b,c}\n')
        assert hosts(result) == ['host-a', 'host-b', 'host-c']

    def test_nested_expansion(self, pb):
        result = parse(pb, 'h{1,2}.{a,b}\n')
        assert hosts(result) == ['h1.a', 'h1.b', 'h2.a', 'h2.b']


# ===========================================================================
# Section headers
# ===========================================================================

class TestSectionHeaders:

    def test_double_hash_section(self, pb):
        result = parse(pb, '## My Section\n')
        s = sections(result)
        assert len(s) == 1
        assert s[0][0] == 'My Section'
        assert s[0][1] == 1  # level

    def test_triple_hash_level_2(self, pb):
        result = parse(pb, '### Sub Section\n')
        s = sections(result)
        assert s[0][1] == 2

    def test_title_directive(self, pb):
        result = parse(pb, ':title My Title\n')
        s = sections(result)
        assert s[0][0] == 'My Title'
        assert s[0][1] == 1

    def test_title2_level_2(self, pb):
        result = parse(pb, ':title2 Sub\n')
        s = sections(result)
        assert s[0][1] == 2

    def test_section_fold_modifier(self, pb):
        result = parse(pb, ':title- Folded\n')
        folded_sections = [e for e in result if e[0] == 'section' and e[3]]  # index 3 = folded
        assert len(folded_sections) == 1
        assert folded_sections[0][1] == 'Folded'


# ===========================================================================
# :let variable substitution
# ===========================================================================

class TestLetVariables:

    def test_simple_let(self, pb):
        result = parse(pb, ':let prefix 10.0.0\n$prefix.1\n')
        assert '10.0.0.1' in hosts(result)

    def test_let_overrides(self, pb):
        result = parse(pb, ':let x a\n:let x b\n$x.host\n')
        assert 'b.host' in hosts(result)

    def test_let_in_section_title(self, pb):
        result = parse(pb, ':let env prod\n## $env servers\n')
        s = sections(result)
        assert s[0][0] == 'prod servers'

    def test_let_with_brace_expansion(self, pb):
        result = parse(pb, ':let rack{1..2} row$1\nhost-$rack1\nhost-$rack2\n')
        h = hosts(result)
        assert 'host-row1' in h
        assert 'host-row2' in h

    def test_let_missing_name_produces_error(self, pb):
        result = parse(pb, ':let\n')
        assert len(errors(result)) == 1


# ===========================================================================
# :for loop
# ===========================================================================

class TestForLoop:

    def test_basic_for_loop(self, pb):
        result = parse(pb, ':for host{1..3}\nserver-$0\n:done\n')
        h = hosts(result)
        assert h == ['server-host1', 'server-host2', 'server-host3']

    def test_for_list_pattern(self, pb):
        result = parse(pb, ':for {alpha,beta}\n$0.example.com\n:done\n')
        h = hosts(result)
        assert h == ['alpha.example.com', 'beta.example.com']

    def test_for_body_without_backref_included_once(self, pb):
        result = parse(pb, ':for {a,b}\nstatic.host\n:done\n')
        h = hosts(result)
        # No back-reference: body host is included once and a warn emitted
        assert h.count('static.host') == 1
        assert len(warns(result)) >= 1

    def test_for_uses_end_as_closer(self, pb):
        result = parse(pb, ':for host{1..2}\nserver-$0\n:end\n')
        h = hosts(result)
        assert h == ['server-host1', 'server-host2']

    def test_for_with_let_variable(self, pb):
        result = parse(pb, ':let n 5\n:for server{1..$n}\n$0\n:done\n')
        h = hosts(result)
        assert h == [f'server{i}' for i in range(1, 6)]


# ===========================================================================
# :if conditional
# ===========================================================================

class TestIfConditional:

    def test_if_true_includes_body(self, pb):
        result = parse(pb, ':let env prod\n:if $env in prod,staging\nprod.host\n:end\n')
        assert 'prod.host' in hosts(result)

    def test_if_false_skips_body(self, pb):
        result = parse(pb, ':let env dev\n:if $env in prod,staging\nprod.host\n:end\n')
        assert 'prod.host' not in hosts(result)

    def test_if_else(self, pb):
        result = parse(pb, ':let env dev\n:if $env in prod\nprod.host\n:else\ndev.host\n:end\n')
        assert 'dev.host' in hosts(result)
        assert 'prod.host' not in hosts(result)

    def test_if_elif(self, pb):
        result = parse(pb, ':let env staging\n:if $env in prod\np.host\n:elif $env in staging\ns.host\n:else\nd.host\n:end\n')
        assert 's.host' in hosts(result)
        assert 'p.host' not in hosts(result)
        assert 'd.host' not in hosts(result)

    def test_inline_if(self, pb):
        result = parse(pb, ':let x yes\n:if $x in yes -> myhost\n')
        assert 'myhost' in hosts(result)

    def test_inline_if_false(self, pb):
        result = parse(pb, ':let x no\n:if $x in yes -> myhost\n')
        assert 'myhost' not in hosts(result)


# ===========================================================================
# :with remote-ping block
# ===========================================================================

class TestWithBlock:

    def test_with_block_emits_remote_ping_cmds(self, pb):
        result = parse(pb, ':with remote-ping relay.host\n10.0.0.1\n:end\n')
        c = cmds(result)
        # Should produce a :remote-ping cmd for the enclosed host
        assert any('remote-ping' in cmd and '10.0.0.1' in cmd for cmd in c)

    def test_with_block_multiple_hosts(self, pb):
        result = parse(pb, ':with remote-ping relay\nh1\nh2\n:end\n')
        c = cmds(result)
        remote = [cmd for cmd in c if 'remote-ping' in cmd]
        assert len(remote) == 2


# ===========================================================================
# :resolv inline comment DNS override
# ===========================================================================

class TestResolvInlineComment:

    def test_ip_with_inline_comment_creates_resolv_cmd(self, pb):
        result = parse(pb, '10.0.0.1 ## myserver\n')
        c = cmds(result)
        assert any(':resolv 10.0.0.1 myserver' in cmd for cmd in c)

    def test_ip_with_inline_comment_uses_label_as_host(self, pb):
        # When an IP has an inline comment label, the 'host' entry uses the label
        result = parse(pb, '10.0.0.1 ## myserver\n')
        h = hosts(result)
        assert 'myserver' in h
        assert '10.0.0.1' not in h

    def test_hostname_with_inline_comment_no_resolv(self, pb):
        # Non-IP host + inline comment: no :resolv cmd
        result = parse(pb, 'example.com ## label\n')
        c = cmds(result)
        assert not any(':resolv' in cmd for cmd in c)


# ===========================================================================
# Optional hosts
# ===========================================================================

class TestOptionalHosts:

    def test_optional_host_prefix(self, pb):
        result = parse(pb, '?10.0.0.1\n')
        opt = [e for e in result if e[0] == 'optional_host']
        assert len(opt) == 1
        assert opt[0][1] == '10.0.0.1'

    def test_optional_host_not_in_host_list(self, pb):
        result = parse(pb, '?10.0.0.1\n')
        assert '10.0.0.1' not in hosts(result)


# ===========================================================================
# Mixed multi-directive file
# ===========================================================================

class TestComplexFile:

    def test_full_pipeline(self, pb):
        src = """\
## Infrastructure
:let env prod
:for web{1..2}
$0.$env.internal
:done
## Databases
db1.$env.internal
db2.$env.internal
"""
        result = parse(pb, src)
        h = hosts(result)
        assert 'web1.prod.internal' in h
        assert 'web2.prod.internal' in h
        assert 'db1.prod.internal' in h
        assert 'db2.prod.internal' in h
        s = sections(result)
        assert any(t == 'Infrastructure' for t, _ in s)
        assert any(t == 'Databases' for t, _ in s)

    def test_section_before_for_loop(self, pb):
        src = """\
## Group A
:for node{1..3}
node-$0
:done
"""
        result = parse(pb, src)
        h = hosts(result)
        assert h == ['node-node1', 'node-node2', 'node-node3']
        s = sections(result)
        assert s[0][0] == 'Group A'
