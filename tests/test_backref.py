"""Unit and integration tests for _apply_backref() and _has_backref().

Covers:
  _apply_backref
  - bare forms \\N / $N (regression guard — previously the only forms)
  - brace forms \\{N} / ${N} (adjacent-digit disambiguation)
  - \\0 / $0 / \\{0} / ${0}  (full-string back-reference)
  - out-of-range index → placeholder left unchanged
  - full_str=None with index-0 placeholder → placeholder left unchanged
  - mixed forms in one template

  _has_backref
  - True for each of the four forms individually
  - True when multiple forms are mixed
  - False for plain strings, escaped-looking but non-placeholder chars

  Integration (parse_hosts_file + :for/:done)
  - \\{N} and ${N} brace forms work inside a :for body
  - adjacent-digit disambiguation via ${1}9 in a :for body
  - mixed bare and brace forms in the same body line
"""

import textwrap

import pytest


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def write_hosts(tmp_path, content):
    """Write *content* to a temp file and return its path (str)."""
    p = tmp_path / 'hosts.txt'
    p.write_text(textwrap.dedent(content))
    return str(p)


# ===========================================================================
# TestApplyBackref — unit tests for _apply_backref()
# ===========================================================================

class TestApplyBackref:
    """Direct tests for _apply_backref(template, captures, full_str)."""

    # ── bare forms (regression guard) ────────────────────────────────────

    def test_bare_backslash_n(self, pb):
        r"""\\N (bare backslash) is substituted from captures."""
        result = pb._apply_backref(r'host-\1.lan', ['42'], full_str='host-42')
        assert result == 'host-42.lan'

    def test_bare_dollar_n(self, pb):
        """$N (bare dollar) is substituted from captures."""
        result = pb._apply_backref('host-$1.lan', ['42'], full_str='host-42')
        assert result == 'host-42.lan'

    def test_bare_zero_backslash(self, pb):
        r"""\\0 is replaced by full_str."""
        result = pb._apply_backref(r'\0.example.com', [], full_str='sensor-7')
        assert result == 'sensor-7.example.com'

    def test_bare_zero_dollar(self, pb):
        """$0 is replaced by full_str."""
        result = pb._apply_backref('$0.example.com', [], full_str='sensor-7')
        assert result == 'sensor-7.example.com'

    # ── brace forms ───────────────────────────────────────────────────────

    def test_brace_backslash_n(self, pb):
        r"""\\{N} is substituted from captures."""
        result = pb._apply_backref(r'\{1}.lan', ['web'], full_str='web')
        assert result == 'web.lan'

    def test_brace_dollar_n(self, pb):
        """${N} is substituted from captures."""
        result = pb._apply_backref('${1}.lan', ['web'], full_str='web')
        assert result == 'web.lan'

    def test_brace_zero_backslash(self, pb):
        r"""\\{0} is replaced by full_str."""
        result = pb._apply_backref(r'\{0}.example.com', [], full_str='node-5')
        assert result == 'node-5.example.com'

    def test_brace_zero_dollar(self, pb):
        """${0} is replaced by full_str."""
        result = pb._apply_backref('${0}.example.com', [], full_str='node-5')
        assert result == 'node-5.example.com'

    # ── adjacent-digit disambiguation ─────────────────────────────────────

    def test_adjacent_digit_dollar_brace(self, pb):
        """${1}9 → group-1 value followed by literal '9', not group 19."""
        result = pb._apply_backref('host${1}9.lan', ['X'], full_str='hostX9')
        assert result == 'hostX9.lan'

    def test_adjacent_digit_backslash_brace(self, pb):
        r"""\\{1}9 → group-1 value followed by literal '9', not group 19."""
        result = pb._apply_backref(r'host\{1}9.lan', ['X'], full_str='hostX9')
        assert result == 'hostX9.lan'

    def test_bare_adjacent_digit_not_disambiguated(self, pb):
        r"""Bare \\19 → group 1 then literal '9' (single-digit regex, so '1' matches)."""
        # The bare form only matches a single digit, so \19 → captures[0] + '9'
        result = pb._apply_backref(r'\19.lan', ['A'], full_str='A9')
        assert result == 'A9.lan'

    # ── multiple groups ───────────────────────────────────────────────────

    def test_two_groups_bare(self, pb):
        r"""Two \\N references in one template, both substituted."""
        result = pb._apply_backref(r'\1-\2', ['foo', 'bar'], full_str='foo-bar')
        assert result == 'foo-bar'

    def test_two_groups_brace(self, pb):
        r"""Two \\{N} references in one template, both substituted."""
        result = pb._apply_backref(r'\{1}-\{2}', ['foo', 'bar'], full_str='foo-bar')
        assert result == 'foo-bar'

    def test_mixed_forms(self, pb):
        r"""Mix of \\N, $N, \\{N}, ${N} in one template."""
        captures = ['alpha', 'beta']
        full_str = 'alpha-beta'
        tmpl = r'\1/$2/\{1}/${2}'
        result = pb._apply_backref(tmpl, captures, full_str=full_str)
        assert result == 'alpha/beta/alpha/beta'

    # ── out-of-range / missing full_str ───────────────────────────────────

    def test_out_of_range_bare(self, pb):
        r"""\\9 with only 2 captures → placeholder left unchanged."""
        result = pb._apply_backref(r'\9.lan', ['a', 'b'], full_str='x')
        assert result == r'\9.lan'

    def test_out_of_range_brace(self, pb):
        r"""\\{9} with only 2 captures → placeholder left unchanged."""
        result = pb._apply_backref(r'\{9}.lan', ['a', 'b'], full_str='x')
        assert result == r'\{9}.lan'

    def test_zero_full_str_none(self, pb):
        r"""\\0 when full_str=None → placeholder left unchanged."""
        result = pb._apply_backref(r'\0.lan', [], full_str=None)
        assert result == r'\0.lan'

    def test_brace_zero_full_str_none(self, pb):
        r"""${0} when full_str=None → placeholder left unchanged."""
        result = pb._apply_backref('${0}.lan', [], full_str=None)
        assert result == '${0}.lan'

    # ── no placeholders ───────────────────────────────────────────────────

    def test_no_placeholders(self, pb):
        """A template with no placeholders is returned unchanged."""
        result = pb._apply_backref('plain.host.lan', ['a', 'b'], full_str='x')
        assert result == 'plain.host.lan'


# ===========================================================================
# TestHasBackref — unit tests for _has_backref()
# ===========================================================================

class TestHasBackref:
    """Direct tests for _has_backref(s)."""

    # ── each form alone ───────────────────────────────────────────────────

    def test_bare_backslash(self, pb):
        r"""\\1 → True."""
        assert pb._has_backref(r'\1') is True

    def test_bare_dollar(self, pb):
        """$1 → True."""
        assert pb._has_backref('$1') is True

    def test_brace_backslash(self, pb):
        r"""\\{1} → True."""
        assert pb._has_backref(r'\{1}') is True

    def test_brace_dollar(self, pb):
        """${1} → True."""
        assert pb._has_backref('${1}') is True

    def test_bare_zero_backslash(self, pb):
        r"""\\0 → True."""
        assert pb._has_backref(r'\0') is True

    def test_bare_zero_dollar(self, pb):
        """$0 → True."""
        assert pb._has_backref('$0') is True

    def test_brace_zero_backslash(self, pb):
        r"""\\{0} → True."""
        assert pb._has_backref(r'\{0}') is True

    def test_brace_zero_dollar(self, pb):
        """${0} → True."""
        assert pb._has_backref('${0}') is True

    # ── mixed forms ───────────────────────────────────────────────────────

    def test_mixed_forms_true(self, pb):
        r"""String with both \\N and ${N} → True."""
        assert pb._has_backref(r'\1-${2}') is True

    # ── False cases ───────────────────────────────────────────────────────

    def test_plain_string(self, pb):
        """A string with no placeholders → False."""
        assert pb._has_backref('plain.host.lan') is False

    def test_dollar_letter(self, pb):
        """$a (non-digit) → False."""
        assert pb._has_backref('$a') is False

    def test_backslash_letter(self, pb):
        r"""\\n (letter, not digit) → False."""
        assert pb._has_backref(r'\n') is False

    def test_brace_nondecimal(self, pb):
        """${x} → False (non-digit inside braces)."""
        assert pb._has_backref('${x}') is False

    def test_empty_string(self, pb):
        """Empty string → False."""
        assert pb._has_backref('') is False


# ===========================================================================
# TestBackrefIntegration — brace forms inside :for/:done via parse_hosts_file
# ===========================================================================

class TestBackrefIntegration:
    """Integration tests: brace-form back-references inside :for/:done blocks."""

    def test_brace_backslash_in_for(self, pb, tmp_path):
        r"""\\{1} inside :for body → correct host per iteration."""
        content = """\
            :for node-{1..3}
            node-\\{1}.example.com
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', 'node-1.example.com'),
            ('host', 'node-2.example.com'),
            ('host', 'node-3.example.com'),
        ], f"Unexpected entries: {entries!r}"

    def test_brace_dollar_in_for(self, pb, tmp_path):
        """${1} inside :for body → correct host per iteration."""
        content = """\
            :for node-{1..3}
            node-${1}.example.com
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', 'node-1.example.com'),
            ('host', 'node-2.example.com'),
            ('host', 'node-3.example.com'),
        ], f"Unexpected entries: {entries!r}"

    def test_brace_zero_in_for(self, pb, tmp_path):
        """${0} inside :for body → full expanded string per iteration."""
        content = """\
            :for web-{a,b,c}
            ${0}.lan
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', 'web-a.lan'),
            ('host', 'web-b.lan'),
            ('host', 'web-c.lan'),
        ], f"Unexpected entries: {entries!r}"

    def test_adjacent_digit_disambiguation_in_for(self, pb, tmp_path):
        """${1}9 inside :for → group-1 value + literal '9', not group 19."""
        content = """\
            :for host-{A,B}
            host-${1}9.lan
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('host', 'host-A9.lan'),
            ('host', 'host-B9.lan'),
        ], f"Unexpected entries: {entries!r}"

    def test_two_groups_brace_form(self, pb, tmp_path):
        r"""Two-group pattern with \\{1} and \\{2} in body line."""
        content = """\
            :for {web,db}-{1,2}
            \\{1}-\\{2}.local
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [e[1] for e in entries if e[0] == 'host']
        assert hosts == [
            'web-1.local',
            'web-2.local',
            'db-1.local',
            'db-2.local',
        ], f"Unexpected hosts: {hosts!r}"

    def test_mixed_bare_and_brace_forms(self, pb, tmp_path):
        r"""Bare \\1 and brace ${2} mixed in same body line."""
        content = """\
            :for {web,db}-{1,2}
            \\1-${2}.internal
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [e[1] for e in entries if e[0] == 'host']
        assert hosts == [
            'web-1.internal',
            'web-2.internal',
            'db-1.internal',
            'db-2.internal',
        ], f"Unexpected hosts: {hosts!r}"

    def test_section_header_brace_form(self, pb, tmp_path):
        """## header with ${1} inside :for → section titles with substitution."""
        content = """\
            :for cluster-{A,B}
            ## Cluster ${1}
            node-${1}.example.com
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'Cluster A'),
            ('host', 'node-A.example.com'),
            ('section', 'Cluster B'),
            ('host', 'node-B.example.com'),
        ], f"Unexpected entries: {entries!r}"

    def test_ssh_command_brace_form(self, pb, tmp_path):
        """Generic command with ${1} inside :for → commands with substitution."""
        content = """\
            :for gw-{1,2}
            :ssh gw-${1}.example.com localhost
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [e[1] for e in entries if e[0] == 'cmd']
        assert cmds == [
            ':ssh gw-1.example.com localhost',
            ':ssh gw-2.example.com localhost',
        ], f"Unexpected cmds: {cmds!r}"

