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

from utils.hosts_helper import write_hosts



class TestApplyNamedBackref:
    def test_single_var(self, pb, tmp_path):
        """Test :for loop with single named variable."""
        content = """\
            :for x in web{1..3}
            server-$x
            :end
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
            :end
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
            :end
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
            :end
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
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        sections = [title for kind, title, *_ in entries if kind == 'section']
        hosts = [rest[0] for kind, *rest in entries if kind == 'host']

        assert sections == ['Environment: prod', 'Environment: stage', 'Environment: dev']
        assert hosts == ['server-prod-1', 'server-stage-1', 'server-dev-1']


    def test_undefined_var(self, pb, tmp_path):
        """Test behavior when referencing undefined variable name."""
        content = """\
            :for x in {1..2}
            server-$x-$y
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [val for kind, val in entries if kind == 'host']
        # Undefined $y expands to "" (empty string)
        assert hosts == ['server-1-', 'server-2-']


    def test_mixed_with_literal_dollar(self, pb, tmp_path):
        """In named :for loops, $N is positional (= Nth named var value).

        With :for x in {1..2}: captures = {'x': '1'} then {'x': '2'}.
        $1 = positional first = $x's value.
        $100 is parsed as $1 followed by literal "00", so:
          $100 → <$x value> + "00"  (e.g. "100", "200")
        """
        content = """\
            :for x in {1..2}
            price$100-host$x
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [val for kind, val in entries if kind == 'host']
        # $1 (positional) == $x, so $100 → x_value + "00"
        assert hosts == ['price100-host1', 'price200-host2']


    def test_alphanum_names(self, pb, tmp_path):
        """Test that variable names can contain alphanumeric and underscores."""
        content = """\
            :for env_name,host_num in {prod}.{1..2}
            $env_name-server-$host_num
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [val for kind, val in entries if kind == 'host']
        assert hosts == ['prod-server-1', 'prod-server-2']


    def test_with_ssh(self, pb, tmp_path):
        """Test named backrefs in :ssh commands."""
        content = """\
            :for dc in {us,eu}
            :ssh user@gateway-$dc sensor-$dc-1
            :end
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
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [val for kind, val in entries if kind == 'host']
        # Numbered backrefs: $1 = first group, $2 = second group
        assert hosts == ['server-1-3', 'server-1-4', 'server-2-3', 'server-2-4']

    def test_numbered_alias_in_named_loop(self, pb, tmp_path):
        """$1 works as positional alias for the first named var in a :for loop.

        Regression test: :for i in sensor-hub-{1-4} with :remote-ping sh$1-host
        used to silently produce 4 identical commands (because $1 was unresolved
        with dict captures), emitting 3 spurious 'duplicate' warnings.
        """
        content = """\
            :for i in sensor-hub-{1..3}
            :remote-ping sh$1-ps31 10.87.0.$1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        warns = [v for k, v in entries if k == 'warn']
        cmds  = [v for k, v in entries if k == 'cmd']
        assert not any('duplicate' in w for w in warns), f"Unexpected duplicate warn: {warns}"
        assert ':remote-ping sh1-ps31 10.87.0.1' in cmds
        assert ':remote-ping sh2-ps31 10.87.0.2' in cmds
        assert ':remote-ping sh3-ps31 10.87.0.3' in cmds


if __name__ == '__main__':
    import pytest
    pytest.main([__file__, '-v'])

