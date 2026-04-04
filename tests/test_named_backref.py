#!/usr/bin/env python3
"""Tests for named back-reference syntax in :for loops.

Named backrefs allow pattern groups to be referenced by name instead of number:
  :for x,y in 10.{1..2}.{3..4}
    server-$x-$y      → server-1-3, server-1-4, server-2-3, server-2-4
    host${x}net${y}   → host1net3, host1net4, host2net3, host2net4

This complements the existing numbered backref syntax ($1, $2, ${1}, ${2}).
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


class TestApplyNamedBackref:
    def test_single_var(self, pb, tmp_path):
        """Test :for loop with single named variable."""
        content = """\
            :for x in web{1..3}
            server-$x
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [val for kind, val in entries if kind == 'host']
        assert hosts == ['server-1', 'server-2', 'server-3']


    def test_braced_syntax(self, pb, tmp_path):
        """Test ${name} braced syntax to avoid ambiguity.
            - Without braces would try to expand $x9
        """
        content = """\
            :for x in {1..3}
            host${x}9
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [val for kind, val in entries if kind == 'host']
        assert hosts == ['host19', 'host29', 'host39']


    def test_multiple_vars(self, pb, tmp_path):
        """Test :for loop with multiple named variables (cartesian product).
           - $y is undefined
        """
        content = """\
            :for x,y in 10.{1..2}.{3..4}
            server-$x-$y
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [val for kind, val in entries if kind == 'host']
        # Cartesian product: {1,2} × {3,4}
        assert hosts == ['server-1-3', 'server-1-4', 'server-2-3', 'server-2-4']


    def test_with_resolv(self, pb, tmp_path):
        """Test named backrefs in :resolv command."""
        content = """\
            :for ip,host in 10.0.0.{1..3}
            :resolv 10.0.0.$ip host-$ip
            10.0.0.$ip
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        # Should have 3 :resolv commands and 3 hosts
        cmds = [val for kind, val in entries if kind == 'cmd' and val.startswith(':resolv')]
        hosts = [val for kind, val in entries if kind == 'host']

        assert len(cmds) == 3
        assert ':resolv 10.0.0.1 host-1' in cmds
        assert ':resolv 10.0.0.2 host-2' in cmds
        assert ':resolv 10.0.0.3 host-3' in cmds

        assert hosts == ['10.0.0.1', '10.0.0.2', '10.0.0.3']


    def test_with_section_titles(self, pb, tmp_path):
        """Test named backrefs in :title commands."""
        content = """\
            :for env in {prod,stage,dev}
            :title Environment: $env
            server-$env-1
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        sections = [val for kind, val in entries if kind == 'section']
        hosts = [val for kind, val in entries if kind == 'host']

        assert sections == ['Environment: prod', 'Environment: stage', 'Environment: dev']
        assert hosts == ['server-prod-1', 'server-stage-1', 'server-dev-1']


    def test_undefined_var(self, pb, tmp_path):
        """Test behavior when referencing undefined variable name."""
        content = """\
            :for x in {1..2}
            server-$x-$y
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [val for kind, val in entries if kind == 'host']
        # Undefined variables should remain as-is (placeholder visible)
        assert hosts == ['server-1-$y', 'server-2-$y']


    def test_mixed_with_literal_dollar(self, pb, tmp_path):
        """Test that numbered backrefs take precedence over literal dollar signs.

        The pattern {1..2} creates one capture group, so:
        - $1 refers to the first group (numbered backref)
        - $x refers to the named variable 'x'
        - $100 gets parsed as $1 followed by literal "00"
        """
        content = """\
            :for x in {1..2}
            price$100-host$x
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [val for kind, val in entries if kind == 'host']
        # $1 captures the brace expansion value {1..2}
        # So $100 becomes: <value-of-$1> + "00"
        # And $x becomes: <value-of-x>
        # Result: "price$100-host1" and "price$100-host2"
        assert hosts == ['price$100-host1', 'price$100-host2']


    def test_alphanum_names(self, pb, tmp_path):
        """Test that variable names can contain alphanumeric and underscores."""
        content = """\
            :for env_name,host_num in {prod}.{1..2}
            $env_name-server-$host_num
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [val for kind, val in entries if kind == 'host']
        assert hosts == ['prod-server-1', 'prod-server-2']


    def test_with_ssh(self, pb, tmp_path):
        """Test named backrefs in :ssh commands."""
        content = """\
            :for dc in {us,eu}
            :ssh user@gateway-$dc sensor-$dc-1
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [val for kind, val in entries if kind == 'cmd']

        assert ':ssh user@gateway-us sensor-us-1' in cmds
        assert ':ssh user@gateway-eu sensor-eu-1' in cmds


    def test_fallback_to_numbered(self, pb, tmp_path):
        """Test that old numbered syntax still works (backward compatibility)."""
        content = """\
            :for 10.{1..2}.{3..4}
            server-$1-$2
            :done
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [val for kind, val in entries if kind == 'host']
        # Numbered backrefs: $1 = first group, $2 = second group
        assert hosts == ['server-1-3', 'server-1-4', 'server-2-3', 'server-2-4']

if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])

