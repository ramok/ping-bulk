"""Unit tests for :if/:elif/:else/:end conditional handling in parse_hosts_file().

Covers:
  - _evaluate_if_condition helper (in/not-in, edge cases)
  - top-level :if/:elif/:else/:end with :let variables
  - :if/:elif/:else/:end inside :for loops with named and numeric vars
  - nesting, error cases (:end without :if, :else after :else)
"""

import textwrap

import pytest

from utils.hosts_helper import write_hosts


# ===========================================================================
# TestEvaluateIfCondition
# ===========================================================================

class TestEvaluateIfCondition:
    """Unit tests for the _evaluate_if_condition helper."""

    def test_in_true(self, pb):
        """'foo in foo,bar' evaluates to True."""
        assert pb._evaluate_if_condition("foo in foo,bar") is True

    def test_in_false(self, pb):
        """'baz in foo,bar' evaluates to False."""
        assert pb._evaluate_if_condition("baz in foo,bar") is False

    def test_not_in_true(self, pb):
        """'baz not in foo,bar' evaluates to True."""
        assert pb._evaluate_if_condition("baz not in foo,bar") is True

    def test_not_in_false(self, pb):
        """'foo not in foo,bar' evaluates to False."""
        assert pb._evaluate_if_condition("foo not in foo,bar") is False

    def test_empty(self, pb):
        """Empty string evaluates to False (no syntax match)."""
        assert pb._evaluate_if_condition("") is False

    def test_bad_syntax(self, pb):
        """Unrecognised operator 'foo eq bar' evaluates to False."""
        assert pb._evaluate_if_condition("foo eq bar") is False

    def test_single_value(self, pb):
        """'1 in 1' (single-item list) evaluates to True."""
        assert pb._evaluate_if_condition("1 in 1") is True


# ===========================================================================
# TestIfTopLevel
# ===========================================================================

class TestIfTopLevel:
    """:if/:elif/:else/:end at the top level of _parse_entries."""

    def test_if_true(self, pb, tmp_path):
        """:if with a true condition includes the host."""
        content = """\
            :let env prod
            :if $env in prod
            10.0.0.1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert ('host', '10.0.0.1') in entries

    def test_if_false(self, pb, tmp_path):
        """:if with a false condition excludes the host."""
        content = """\
            :let env dev
            :if $env in prod
            10.0.0.1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == [], f"Expected no hosts but got: {hosts}"

    def test_if_else_true(self, pb, tmp_path):
        """True condition: if-branch host included, else-branch host excluded."""
        content = """\
            :let env prod
            :if $env in prod
            10.0.0.1
            :else
            10.0.0.2
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert '10.0.0.1' in hosts
        assert '10.0.0.2' not in hosts

    def test_if_else_false(self, pb, tmp_path):
        """False condition: else-branch host included, if-branch host excluded."""
        content = """\
            :let env dev
            :if $env in prod
            10.0.0.1
            :else
            10.0.0.2
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert '10.0.0.2' in hosts
        assert '10.0.0.1' not in hosts

    def test_elif_chain(self, pb, tmp_path):
        """With x=b: only the elif branch (B) is included."""
        content = """\
            :let x b
            :if $x in a
            hostA
            :elif $x in b
            hostB
            :else
            hostC
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['hostB'], f"Expected ['hostB'], got: {hosts!r}"

    def test_nested_if(self, pb, tmp_path):
        """Both conditions true: nested if includes the host."""
        content = """\
            :let a 1
            :let b 2
            :if $a in 1
            :if $b in 2
            10.0.0.1
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['10.0.0.1'], f"Expected ['10.0.0.1'], got: {hosts!r}"

    def test_nested_if_outer_false(self, pb, tmp_path):
        """Outer condition false: inner if never runs, host not included."""
        content = """\
            :let a 2
            :let b 2
            :if $a in 1
            :if $b in 2
            10.0.0.1
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == [], f"Expected no hosts but got: {hosts!r}"

    def test_not_in(self, pb, tmp_path):
        """:if with 'not in': env=prod is not in dev,test so host is included."""
        content = """\
            :let env prod
            :if $env not in dev,test
            10.0.0.1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['10.0.0.1'], f"Expected ['10.0.0.1'], got: {hosts!r}"

    def test_fi_without_if(self, pb, tmp_path):
        """Bare :end without any open block produces an error entry."""
        content = """\
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [v for k, v in entries if k == 'error']
        assert any(':end without' in e for e in errors), (
            f"Expected ':end without' error, got: {errors!r}"
        )

    def test_else_after_else(self, pb, tmp_path):
        """Two :else clauses in one :if block produce an ':else after :else' error."""
        content = """\
            :if 1 in 1
            :else
            :else
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [v for k, v in entries if k == 'error']
        assert any(':else after :else' in e for e in errors), (
            f"Expected ':else after :else' error, got: {errors!r}"
        )

    def test_if_with_section(self, pb, tmp_path):
        """Section header and host inside :if are both emitted when condition is true."""
        content = """\
            :let env prod
            :if $env in prod
            ## Prod hosts
            10.0.0.1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        kinds = [entry[0] for entry in entries]
        assert 'section' in kinds, f"Expected section entry, got: {entries!r}"
        hosts = [entry[1] for entry in entries if entry[0] == 'host']
        assert '10.0.0.1' in hosts


# ===========================================================================
# TestIfInsideFor
# ===========================================================================

class TestIfInsideFor:
    """:if/:elif/:else/:end inside :for loops."""

    def test_if_in_for_basic(self, pb, tmp_path):
        """:if inside :for includes only iterations matching the condition."""
        content = """\
            :for sh in {1,2,3}
            :if $sh in 1,2
            10.0.0.$sh
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['10.0.0.1', '10.0.0.2'], f"Unexpected hosts: {hosts!r}"

    def test_if_else_in_for(self, pb, tmp_path):
        """Different host template per iteration based on :if/:else."""
        content = """\
            :for sh in {1,2}
            :if $sh in 1
            host-a-$sh
            :else
            host-b-$sh
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['host-a-1', 'host-b-2'], f"Unexpected hosts: {hosts!r}"

    def test_if_with_inline_label(self, pb, tmp_path):
        """Inline ## label inside :if in :for emits :resolv + host for matching iteration."""
        content = """\
            :for sh in {1,2}
            :if $sh in 1
            10.0.0.$sh ## host$sh
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [v for k, v in entries if k == 'error']
        assert not errors, f"Unexpected errors: {errors!r}"

        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['host1'], f"Unexpected hosts: {hosts!r}"

        cmds = [v for k, v in entries if k == 'cmd']
        assert ':resolv 10.0.0.1 host1' in cmds, f"Expected resolv cmd, got: {cmds!r}"

    def test_nested_if_in_for(self, pb, tmp_path):
        """Two nested :if conditions on loop var: only sh satisfying both is included."""
        content = """\
            :for sh in {1,2,3}
            :if $sh in 1,2
            :if $sh in 2
            host-$sh
            :end
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['host-2'], f"Expected only 'host-2', got: {hosts!r}"

    def test_if_with_named_var(self, pb, tmp_path):
        """:for sh in pattern: $sh is the brace capture, :if $sh in 1,2 filters correctly."""
        content = """\
            :for sh in sensor-hub-{1,2,3}
            :if $sh in 1,2
            10.0.0.$sh
            :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        # $sh = brace capture ('1', '2', '3'), not full string ('sensor-hub-1', ...)
        assert hosts == ['10.0.0.1', '10.0.0.2'], f"Unexpected hosts: {hosts!r}"


# ===========================================================================
# TestIfInline
# ===========================================================================

class TestIfInline:
    """Tests for the inline :if COND -> BODY one-liner form."""

    def test_inline_true_top_level(self, pb, tmp_path):
        """:if COND -> host includes the host when condition is true."""
        content = """\
            :let env prod
            :if $env in prod -> 10.0.0.1
            10.0.0.2
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['10.0.0.1', '10.0.0.2']

    def test_inline_false_top_level(self, pb, tmp_path):
        """:if COND -> host skips the host when condition is false."""
        content = """\
            :let env dev
            :if $env in prod -> 10.0.0.1
            10.0.0.2
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['10.0.0.2']

    def test_inline_inside_for_true(self, pb, tmp_path):
        """:if COND -> host inside :for includes the host when condition is true."""
        content = """\
            :for hub-{1,2,3}
            10.0.0.$1
            :if $1 in 2 -> 10.0.1.$1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['10.0.0.1', '10.0.0.2', '10.0.1.2', '10.0.0.3']

    def test_inline_inside_for_false(self, pb, tmp_path):
        """:if COND -> host inside :for excludes the host when condition is false."""
        content = """\
            :for hub-{1,2,3}
            :if $1 in 9 -> 10.0.0.$1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == []

    def test_inline_with_label(self, pb, tmp_path):
        """:if COND -> 10.0.0.1 ## label registers :resolv and uses label as host."""
        content = """\
            :let env prod
            :if $env in prod -> 10.0.0.1 ## prod-server
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [v for k, v in entries if k == 'cmd']
        hosts = [v for k, v in entries if k == 'host']
        assert any('prod-server' in c for c in cmds), f"Expected :resolv, got: {cmds!r}"
        assert 'prod-server' in hosts

    def test_inline_inside_for_with_label(self, pb, tmp_path):
        """:if COND -> IP ## label$1 inside :for expands back-refs in label."""
        content = """\
            :for n in hub-{1,2}
            :if $n in 1 -> 10.0.$n.1 ## gw$n
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [v for k, v in entries if k == 'cmd']
        hosts = [v for k, v in entries if k == 'host']
        assert any('10.0.1.1' in c and 'gw1' in c for c in cmds)
        assert 'gw1' in hosts
        assert 'gw2' not in hosts

    def test_inline_empty_body_warns(self, pb, tmp_path):
        """:if COND -> with empty body emits a warning."""
        content = """\
            :let env prod
            :if $env in prod ->
            10.0.0.2
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        warns = [v for k, v in entries if k == 'warn']
        assert any('empty' in w for w in warns), f"Expected empty-body warning, got: {warns!r}"

    def test_inline_skipped_inside_false_block(self, pb, tmp_path):
        """:if COND -> BODY inside a false :if block is entirely skipped."""
        content = """\
            :let env dev
            :if $env in prod
            :if always in always -> 10.0.0.1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == [], f"Expected no hosts, got: {hosts!r}"

    def test_inline_does_not_require_end(self, pb, tmp_path):
        """:if COND -> BODY does not need a matching :end."""
        content = """\
            :let env prod
            :if $env in prod -> 10.0.0.1
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [v for k, v in entries if k == 'error']
        hosts = [v for k, v in entries if k == 'host']
        assert errors == [], f"Unexpected errors: {errors!r}"
        assert '10.0.0.1' in hosts

    def test_inline_named_var_in_for(self, pb, tmp_path):
        """:if $name in LIST -> host uses named back-ref from :for n in."""
        content = """\
            :for n in sensor-hub-{1,2,3}
            :if $n in 2 -> 10.0.0.$n
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['10.0.0.2'], f"Expected ['10.0.0.2'], got: {hosts!r}"

    def test_inline_multiple_per_for(self, pb, tmp_path):
        """Multiple inline :if lines per :for iteration combine correctly."""
        content = """\
            :for hub-{1,2,3}
            :if $1 in 1 -> 10.0.1.$1
            :if $1 in 2 -> 10.0.2.$1
            :if $1 in 3 -> 10.0.3.$1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        hosts = [v for k, v in entries if k == 'host']
        assert hosts == ['10.0.1.1', '10.0.2.2', '10.0.3.3']


# ===========================================================================
# TestMalformedConditionWarning
# ===========================================================================

class TestMalformedConditionWarning:
    """A condition that cannot be parsed evaluates to False and (in block
    form) silently skips everything until :end — so the parser must warn.
    The most common cause is a missing '->' before an inline body."""

    def test_missing_arrow_top_level_warns(self, pb, tmp_path):
        content = """\
            :if 1 in 1 10.0.0.1 ## victim
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        warns = [e[1] for e in entries if e[0] == 'warn']
        assert any("missing '->'" in w for w in warns), warns

    def test_missing_arrow_inside_for_warns(self, pb, tmp_path):
        content = """\
            :for i in hub-{4,5}
                :if $i not in 5    10.123.$i.41 ## sh$i-cam1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        warns = [e[1] for e in entries if e[0] == 'warn']
        arrow_warns = [w for w in warns if "missing '->'" in w]
        assert len(arrow_warns) == 2, warns  # one per iteration

    def test_bad_operator_warns_malformed(self, pb, tmp_path):
        content = """\
            :if foo equals bar
            10.0.0.1
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        warns = [e[1] for e in entries if e[0] == 'warn']
        assert any('is malformed' in w for w in warns), warns

    def test_malformed_elif_warns(self, pb, tmp_path):
        content = """\
            :let env dev
            :if $env in prod
            10.0.0.1
            :elif $env
            10.0.0.2
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        warns = [e[1] for e in entries if e[0] == 'warn']
        assert any('is malformed' in w for w in warns), warns

    def test_malformed_inline_condition_warns(self, pb, tmp_path):
        content = """\
            :if justoneword -> 10.0.0.1
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        warns = [e[1] for e in entries if e[0] == 'warn']
        assert any('is malformed' in w for w in warns), warns

    def test_valid_conditions_do_not_warn(self, pb, tmp_path):
        content = """\
            :let env prod
            :if $env in prod
            10.0.0.1
            :elif $env not in dev,staging
            10.0.0.2
            :else
            10.0.0.3
            :end
            :if $env in prod -> 10.0.0.4
            :for i in hub-{1,2}
                :if $i in 1 -> 10.0.$i.1
                :if $i not in 1
                10.0.$i.2
                :end
            :end
        """
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        warns = [e[1] for e in entries if e[0] == 'warn']
        assert not warns, warns
