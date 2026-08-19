"""Unit tests for $SCRIPT_DIR / $SCRIPT_FILE and the environment fallback.

Covers:
  - $SCRIPT_DIR / $SCRIPT_FILE are predefined while parsing a file
  - the pair is abspath-based, not realpath-based (a symlinked script logs
    next to the name that was typed, not next to the target)
  - a later ':let' overrides them, like any other variable
  - a ':source'd file gets its own $SCRIPT_DIR
  - undefined names fall back to the environment, with ':let' taking priority
  - an undefined variable inside a path argument warns instead of silently
    producing a truncated path such as '/x.log'
  - an undefined variable elsewhere stays silent — expanding to "" is a
    documented idiom (see the ${fold$1} pattern in examples/ping-bulk.advance)

$SCRIPT_DIR is seeded in _HostsParser.parse_file(), so parsing a plain string
(stdin, tests, ':source' from a string) has no value for it — that is the case
the path warning exists to catch.
"""

import pytest

from utils.hosts_helper import write_hosts


def parse(pb, content, tmp_path):
    return pb.parse_hosts_file(write_hosts(tmp_path, content))


def cmds(entries):
    return [e[1] for e in entries if e[0] == 'cmd']


def warns(entries):
    return [e[1] for e in entries if e[0] == 'warn']


# ---------------------------------------------------------------------------
# $SCRIPT_DIR / $SCRIPT_FILE
# ---------------------------------------------------------------------------

class TestScriptDirVars:

    def test_script_dir_is_the_files_directory(self, pb, tmp_path):
        entries = parse(pb, ':log $SCRIPT_DIR/pb.log\n', tmp_path)
        assert cmds(entries) == [f':log {tmp_path}/pb.log']

    def test_script_dir_has_no_trailing_slash(self, pb, tmp_path):
        entries = parse(pb, ':log $SCRIPT_DIR\n', tmp_path)
        assert cmds(entries) == [f':log {tmp_path}']

    def test_script_file_is_the_basename(self, pb, tmp_path):
        entries = parse(pb, ':log $SCRIPT_FILE.log\n', tmp_path)
        assert cmds(entries) == [':log hosts.txt.log']

    def test_both_together(self, pb, tmp_path):
        entries = parse(pb, ':log $SCRIPT_DIR/$SCRIPT_FILE.log\n', tmp_path)
        assert cmds(entries) == [f':log {tmp_path}/hosts.txt.log']

    def test_braced_form_works(self, pb, tmp_path):
        entries = parse(pb, ':log ${SCRIPT_DIR}/pb.log\n', tmp_path)
        assert cmds(entries) == [f':log {tmp_path}/pb.log']

    def test_usable_in_a_section_title(self, pb, tmp_path):
        """The variables are ordinary ':let' entries, not a ':log'-only feature."""
        entries = parse(pb, ':title hosts from $SCRIPT_FILE\n10.0.0.1\n', tmp_path)
        assert entries[0] == ('section', 'hosts from hosts.txt', 1, False, False)

    def test_let_overrides_script_dir(self, pb, tmp_path):
        entries = parse(pb, ':let SCRIPT_DIR /custom\n:log $SCRIPT_DIR/pb.log\n',
                        tmp_path)
        assert cmds(entries) == [':log /custom/pb.log']

    def test_abspath_not_realpath(self, pb, tmp_path):
        """A symlinked script resolves next to the link, not next to the target."""
        real_dir = tmp_path / 'real'
        real_dir.mkdir()
        target = real_dir / 'hosts.txt'
        target.write_text(':log $SCRIPT_DIR/pb.log\n')
        link_dir = tmp_path / 'link'
        link_dir.mkdir()
        link = link_dir / 'via-link'
        link.symlink_to(target)

        entries = pb.parse_hosts_file(str(link))
        assert cmds(entries) == [f':log {link_dir}/pb.log']

    def test_undefined_without_a_file(self, pb):
        """Parsing a string has no file, so the path warning must fire."""
        entries = pb._HostsParser().parse(':log $SCRIPT_DIR/pb.log\n')
        assert cmds(entries) == [':log /pb.log']
        assert any('SCRIPT_DIR' in w for w in warns(entries)), \
            "a truncated log path must not be silent"


class TestSourcedFileScriptDir:
    """A ':source'd file resolves $SCRIPT_DIR against itself, not its parent."""

    def _child(self, tmp_path, body):
        sub_dir = tmp_path / 'sub'
        sub_dir.mkdir()
        child = sub_dir / 'child.hosts'
        child.write_text(body)
        return sub_dir, str(child)

    def test_flattened_source_uses_the_child_directory(self, pb, tmp_path):
        sub_dir, child = self._child(tmp_path, ':log $SCRIPT_DIR/child.log\n')
        entries = pb._flatten_sourced(parse(pb, f':source {child}\n', tmp_path))
        assert f':log {sub_dir}/child.log' in cmds(entries)

    def test_runtime_source_uses_the_child_directory(self, pb, tmp_path):
        sub_dir, child = self._child(tmp_path, ':log $SCRIPT_DIR/child.log\n')
        app = pb.Application([('host', '127.0.0.1')])
        app._cmd_source(child)
        assert app.log_file == f'{sub_dir}/child.log'

    def test_parent_script_dir_is_unaffected(self, pb, tmp_path):
        """Sourcing a child must not leave the child's dir behind for the parent."""
        _sub_dir, child = self._child(tmp_path, '10.0.0.2\n')
        app = pb.Application([('host', '127.0.0.1')])
        app._cmd_source(child)
        assert 'SCRIPT_DIR' not in app.variables, \
            "the child's per-file variables must not leak into the app"


# ---------------------------------------------------------------------------
# Environment fallback
# ---------------------------------------------------------------------------

class TestEnvFallback:

    def test_environment_variable_is_used(self, pb, tmp_path, monkeypatch):
        monkeypatch.setenv('PB_TEST_LOGDIR', '/var/log/pb')
        entries = parse(pb, ':log $PB_TEST_LOGDIR/pb.log\n', tmp_path)
        assert cmds(entries) == [':log /var/log/pb/pb.log']

    def test_braced_environment_variable(self, pb, tmp_path, monkeypatch):
        monkeypatch.setenv('PB_TEST_LOGDIR', '/var/log/pb')
        entries = parse(pb, ':log ${PB_TEST_LOGDIR}/pb.log\n', tmp_path)
        assert cmds(entries) == [':log /var/log/pb/pb.log']

    def test_let_takes_priority_over_environment(self, pb, tmp_path, monkeypatch):
        monkeypatch.setenv('PB_TEST_LOGDIR', '/from/env')
        entries = parse(pb, ':let PB_TEST_LOGDIR /from/let\n'
                            ':log $PB_TEST_LOGDIR/pb.log\n', tmp_path)
        assert cmds(entries) == [':log /from/let/pb.log']

    def test_environment_works_on_host_lines(self, pb, tmp_path, monkeypatch):
        monkeypatch.setenv('PB_TEST_NET', '10.9.9')
        entries = parse(pb, '$PB_TEST_NET.1\n', tmp_path)
        assert entries == [('host', '10.9.9.1')]

    def test_unset_environment_variable_still_empty(self, pb, tmp_path, monkeypatch):
        monkeypatch.delenv('PB_TEST_ABSENT', raising=False)
        entries = parse(pb, ':log $PB_TEST_ABSENT/pb.log\n', tmp_path)
        assert cmds(entries) == [':log /pb.log']


# ---------------------------------------------------------------------------
# Undefined-variable warning: path arguments only
# ---------------------------------------------------------------------------

class TestUndefinedPathWarning:

    @pytest.mark.parametrize('cmd', [':log', ':save', ':source'])
    def test_undefined_in_path_argument_warns(self, pb, tmp_path, cmd):
        entries = parse(pb, f'{cmd} $PB_NO_SUCH_VAR/pb.log\n', tmp_path)
        assert any('PB_NO_SUCH_VAR' in w for w in warns(entries)), \
            f'{cmd} with an undefined variable should warn'

    def test_warning_names_the_command(self, pb, tmp_path):
        entries = parse(pb, ':log $PB_NO_SUCH_VAR/pb.log\n', tmp_path)
        assert any('/pb.log' in w for w in warns(entries)), \
            'the warning should show the path that resulted'

    def test_defined_variable_in_path_does_not_warn(self, pb, tmp_path):
        entries = parse(pb, ':let d /tmp\n:log $d/pb.log\n', tmp_path)
        assert warns(entries) == []

    def test_script_dir_in_path_does_not_warn(self, pb, tmp_path):
        entries = parse(pb, ':log $SCRIPT_DIR/pb.log\n', tmp_path)
        assert warns(entries) == []

    def test_undefined_elsewhere_stays_silent(self, pb, tmp_path):
        """Expanding to "" is a documented idiom outside path arguments."""
        content = """
        :let fold3 -
        :for sensor-hub-{1..4}
            :title${fold$1} hub-$1
            10.0.$1.1
        :end
        """
        entries = parse(pb, content, tmp_path)
        assert warns(entries) == [], \
            'the ${fold$1} pattern from examples/ping-bulk.advance must stay quiet'

    def test_undefined_on_a_host_line_stays_silent(self, pb, tmp_path):
        entries = parse(pb, ':title${nosuch} Section\n10.0.0.1\n', tmp_path)
        assert warns(entries) == []

    def test_warning_is_visible_at_the_default_loglevel(self, pb, tmp_path):
        """A warning filtered out of the UI would leave the hole open.

        Parse warnings become add_event('hosts', …), and draw_events filters on
        'level <= self.loglevel', so category 'hosts' must sit at or below the
        default level — otherwise ':log $TYPO/pb.log' is silent after all.
        """
        entries = parse(pb, ':log $PB_NO_SUCH_VAR/pb.log\n10.0.0.1\n', tmp_path)
        app = pb.Application(entries)
        visible = [e for e in app.events if e.level <= app.loglevel]
        assert any('PB_NO_SUCH_VAR' in e.text for e in visible), \
            'the warning never reaches the event log the user actually sees'
