"""Generated-fleet features: ':source!', named/local probe sources,
per-host probe thresholds, per-host askpass and pipe hosts files.

All unit-level: nothing here needs a terminal or a network.
"""

import os
import stat
from unittest.mock import patch

import pytest


def _make_app(pb, tmp_path, entries=None, **kw):
    cfg = tmp_path / 'ping-bulk' / 'config'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('')
    with patch.object(pb, '_config_path', return_value=str(cfg)):
        app = pb.Application(entries if entries is not None else [('host', '10.0.0.1')], **kw)
    app._monitoring_started = True
    return app


@pytest.fixture
def app(pb, tmp_path):
    return _make_app(pb, tmp_path)


def _texts(app):
    return [e.text for e in app.events]


def _script(tmp_path, name, body):
    p = tmp_path / name
    p.write_text('#!/bin/sh\n' + body)
    p.chmod(0o755)
    return str(p)


# ---------------------------------------------------------------------------
# :source!
# ---------------------------------------------------------------------------

class TestSourceBang:

    def test_loads_hosts_and_logs_stderr(self, pb, app, tmp_path):
        gen = _script(tmp_path, 'gen', 'printf "## G\\n127.0.0.2\\n127.0.0.3\\n"; echo oops >&2\n')
        app._cmd_source_bang(gen)
        hosts = [m.host for m in app.monitors]
        assert '127.0.0.2' in hosts and '127.0.0.3' in hosts
        assert any('oops' in t for t in _texts(app))

    def test_nonzero_exit_without_cache_loads_nothing(self, pb, app, tmp_path):
        gen = _script(tmp_path, 'bad', 'echo 127.0.0.2; exit 3\n')
        app._cmd_source_bang(gen)
        assert [m.host for m in app.monitors] == ['10.0.0.1']
        assert any('status 3' in t and 'nothing loaded' in t for t in _texts(app))

    def test_failure_keeps_previous_output(self, pb, app, tmp_path):
        flag = tmp_path / 'down'
        gen = _script(tmp_path, 'gen',
                      f'[ -e {flag} ] && exit 1\necho 127.0.0.2\n')
        app._cmd_source_bang(gen)
        flag.write_text('')
        before = len(app.monitors)
        app._cmd_source_bang(gen)
        assert len(app.monitors) == before          # duplicates ignored, none lost
        assert any('keeping the hosts' in t for t in _texts(app))

    def test_timeout_kills_and_refuses(self, pb, app, tmp_path):
        gen = _script(tmp_path, 'slow', 'sleep 30\n')
        app._cmd_source_bang(f'--timeout 0.5 {gen}')
        assert any('timed out' in t for t in _texts(app))
        assert [m.host for m in app.monitors] == ['10.0.0.1']

    @pytest.mark.parametrize('arg', ['', '--timeout x /bin/true',
                                     '--timeout 0 /bin/true',
                                     '--timeout 9999 /bin/true', "'unterminated"])
    def test_bad_arguments_are_refused(self, app, arg):
        app._cmd_source_bang(arg)
        assert any('source!' in t for t in _texts(app))

    def test_missing_command_is_refused(self, app):
        app._cmd_source_bang('/nonexistent/generator')
        assert any('cannot run' in t for t in _texts(app))

    def test_no_shell(self, pb, app, tmp_path):
        marker = tmp_path / 'pwned'
        app._cmd_source_bang(f'/bin/echo ; touch {marker}')
        assert not marker.exists()

    def test_no_stdin(self, pb, app, tmp_path):
        gen = _script(tmp_path, 'rd', 'read x && echo 127.0.0.4\n')
        app._cmd_source_bang(gen)
        assert '127.0.0.4' not in [m.host for m in app.monitors]

    def test_recursion_guard(self, pb, app):
        app._source_depth = pb._SOURCE_CMD_MAX_DEPTH
        app._cmd_source_bang('/bin/true')
        assert any('nested' in t for t in _texts(app))

    def test_directives_in_output(self, pb, app, tmp_path):
        gen = _script(tmp_path, 'dir',
                      "printf ':let n 7\\n127.0.0.$n\\n'\n")
        app._cmd_source_bang(gen)
        assert '127.0.0.7' in [m.host for m in app.monitors]

    def test_registered_and_dispatchable(self, pb, app, tmp_path):
        gen = _script(tmp_path, 'g', 'echo 127.0.0.5\n')
        app._dispatch_cmd(f'source! {gen}')
        assert '127.0.0.5' in [m.host for m in app.monitors]


class TestSourceBangKiosk:

    def test_typed_is_refused(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, kiosk_mode=True)
        gen = _script(tmp_path, 'g', 'echo 127.0.0.5\n')
        app._cmd_source_bang(gen)
        assert '127.0.0.5' not in [m.host for m in app.monitors]
        assert any('not allowed interactively' in t for t in _texts(app))


class TestReload:

    def test_without_hosts_file(self, app):
        app.hosts_file = None
        app._cmd_reload()
        assert any('reload' in t for t in _texts(app))

    def test_pipe_message(self, app):
        app.hosts_file = None
        app.hosts_pipe = '/dev/fd/63'
        app._cmd_reload()
        assert any('pipe' in t for t in _texts(app))


# ---------------------------------------------------------------------------
# Named and local probe sources
# ---------------------------------------------------------------------------

class TestProbeSources:

    def test_two_named_sources_are_independent(self, pb, app):
        app._cmd_probe_source('--name a --cmd /bin/true --hosts 10.0.0.*')
        app._cmd_probe_source('--name b --cmd /bin/true --hosts nothing')
        assert set(app.probe_named) == {'a', 'b'}
        app._cmd_probe_source('--name a off')
        assert set(app.probe_named) == {'b'}

    def test_local_source_needs_no_ssh(self, pb, app):
        app._cmd_probe_source('--name l --local "/bin/echo %h"')
        assert app.probe_named['l'].local

    def test_template_substitution_is_per_token(self, pb):
        f = pb._expand_probe_template
        assert f('%h:%i', 'a b', '1.2.3.4') == 'a b:1.2.3.4'
        assert f('100%%', 'h', 'i') == '100%'
        assert f('50%x', 'h', 'i') == '50%x'

    def test_local_reader_reads_values(self, pb, app, tmp_path):
        gen = _script(tmp_path, 'p', 'echo "t=42"\necho ---\n')
        app._cmd_probe('t --range 0:100')
        r = pb.LocalProbeReader(app.monitors[0], f'{gen} %h %i', 1,
                                app.probe_defs, 10, source_name='l')
        r._one_round()
        assert r.monitor.probes['t'].state == 'ok'
        assert r.monitor.probes['t'].last[0] == 42
        assert r._build_argv()[1:] == [app.monitors[0].host] * 2

    def test_local_reader_nonzero_exit_fails_values(self, pb, app, tmp_path):
        gen = _script(tmp_path, 'p', 'echo t=5\nexit 2\n')
        app._cmd_probe('t --range 0:100')
        r = pb.LocalProbeReader(app.monitors[0], gen, 1, app.probe_defs, 10)
        r._one_round()
        assert r.monitor.probes['t'].state != 'ok'

    def test_local_reader_timeout_is_bounded(self, pb, app):
        r = pb.LocalProbeReader(app.monitors[0], '/bin/true', 1000,
                                app.probe_defs, 10)
        assert r._timeout == pb._LOCAL_PROBE_TIMEOUT_MAX

    def test_kiosk_refuses_typed_local_source(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, kiosk_mode=True)
        app._cmd_probe_source('--name l --local /bin/true')
        assert 'l' not in app.probe_named


# ---------------------------------------------------------------------------
# Per-host probe thresholds
# ---------------------------------------------------------------------------

class TestProbeThresholds:

    def test_override_applies_only_to_matching_hosts(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, [('host', 'a-1'), ('host', 'b-1')])
        app._cmd_probe('t --warn 50 --crit 80')
        app._cmd_probe('t --hosts a-* --warn 10 --crit 20')
        ma, mb = app.monitors
        d = app.probe_defs['t']
        assert (app._probe_for(ma, d).warn, app._probe_for(ma, d).crit) == (10, 20)
        assert app._probe_for(mb, d) is d

    def test_later_rule_wins_per_field(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, [('host', 'a-1')])
        app._cmd_probe('t --warn 50 --crit 80')
        app._cmd_probe('t --hosts * --warn 10')
        app._cmd_probe('t --hosts a-* --crit 15')
        d = app._probe_for(app.monitors[0], app.probe_defs['t'])
        assert (d.warn, d.crit) == (10, 15)

    def test_severity_uses_the_override(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, [('host', 'a-1')])
        app._cmd_probe('t --warn 50 --crit 80')
        app._cmd_probe('t --hosts a-* --warn 10 --crit 20')
        m = app.monitors[0]
        with m.lock:
            s = pb.ProbeSeries(10)
            s.values.append(25)
            s.times.append(0)
            s.state = 'ok'
            m.probes['t'] = s
        assert app._probe_severity(m, 't') == 3

    def test_override_does_not_change_the_declaration(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._cmd_probe('t --warn 50 --crit 80')
        app._cmd_probe('t --hosts x* --warn 1')
        assert (app.probe_defs['t'].warn, app.probe_defs['t'].crit) == (50, 80)


# ---------------------------------------------------------------------------
# Per-host askpass
# ---------------------------------------------------------------------------

class TestAskpass:

    def test_default_flags_forbid_asking(self, pb):
        assert pb._ssh_batch_flags() == ['-o', 'BatchMode=yes']
        env = pb._ssh_child_env()
        assert env.get('SSH_ASKPASS_REQUIRE') == 'never'

    def test_askpass_drops_batchmode(self, pb):
        flags = pb._ssh_batch_flags('/x/askpass')
        assert 'BatchMode=yes' not in flags
        assert 'NumberOfPasswordPrompts=1' in flags
        env = pb._ssh_child_env('/x/askpass')
        assert env['SSH_ASKPASS'] == '/x/askpass'
        assert env['SSH_ASKPASS_REQUIRE'] == 'force'
        assert 'DISPLAY' in env

    def test_rule_matches_by_glob_and_exact_beats_glob(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, [('host', 'a-1'), ('host', 'b-1')])
        gen = _script(tmp_path, 'ap1', 'true\n')
        gen2 = _script(tmp_path, 'ap2', 'true\n')
        app._cmd_prog_options(f'ssh a-* --askpass {gen}')
        app._cmd_prog_options(f'ssh a-1 --askpass {gen2}')
        ma, mb = app.monitors
        assert app._askpass_for(ma) == gen2
        assert app._askpass_for(mb) is None

    def test_multiword_program_is_refused(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, [('host', 'a-1')])
        app._cmd_prog_options('ssh a-1 --askpass "evo-prod ssh-askpass"')
        assert app._askpass_for(app.monitors[0]) is None

    def test_disable_and_askpass_conflict(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, [('host', 'a-1')])
        gen = _script(tmp_path, 'ap', 'true\n')
        app._cmd_prog_options(f'ssh a-1 --disable --askpass {gen}')
        assert app._askpass_for(app.monitors[0]) is None

    def test_kiosk_typed_is_refused(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, [('host', 'a-1')], kiosk_mode=True)
        gen = _script(tmp_path, 'ap', 'true\n')
        app._cmd_prog_options(f'ssh a-1 --askpass {gen}')
        assert app._askpass_for(app.monitors[0]) is None

    def test_reader_built_with_askpass(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, [('host', 'a-1')])
        gen = _script(tmp_path, 'ap', 'true\n')
        app._cmd_prog_options(f'ssh a-1 --askpass {gen}')
        src = pb.ProbeSource('', '/bin/true', interval=5)
        r = app._make_probe_reader(src, app.monitors[0], [])
        assert r.askpass == gen
        assert 'BatchMode=yes' not in r._build_cmd()


# ---------------------------------------------------------------------------
# Pipe hosts files
# ---------------------------------------------------------------------------

class TestPipeHostsFile:

    def test_regular_file_is_not_transient(self, pb, tmp_path):
        p = tmp_path / 'h'
        p.write_text('')
        assert not pb._is_transient_hosts_path(str(p))

    def test_fifo_is_transient(self, pb, tmp_path):
        p = tmp_path / 'fifo'
        os.mkfifo(p)
        assert stat.S_ISFIFO(os.stat(p).st_mode)
        assert pb._is_transient_hosts_path(str(p))

    def test_edit_is_refused_for_a_pipe(self, app):
        app.hosts_file = None
        app.hosts_pipe = '/dev/fd/63'
        app._cmd_edit('')
        assert any('pipe' in t for t in _texts(app))


# ---------------------------------------------------------------------------
# :dump-script
# ---------------------------------------------------------------------------

class TestDumpScript:

    def _fleet(self, pb, tmp_path):
        gen = _script(tmp_path, 'gen',
                      'printf "## G\\n~127.0.0.2  ## b\\n:probe temp --unit C\\n"\n')
        hosts = tmp_path / 'fleet'
        hosts.write_text(f':source! {gen}\n127.0.0.9\n')
        entries = pb.parse_hosts_file(str(hosts))
        app = _make_app(pb, tmp_path, entries, hosts_file=str(hosts))
        return app, gen

    def test_inlines_the_last_source_output(self, pb, tmp_path):
        app, gen = self._fleet(pb, tmp_path)
        app._cmd_source_bang(gen)
        out = tmp_path / 'flat'
        app._cmd_dump_script(str(out))
        text = out.read_text()
        assert text.startswith('#!/bin/sh')
        assert ':source!' not in text
        assert '127.0.0.2' in text and '127.0.0.9' in text
        assert ':probe temp --unit C' in text
        assert out.stat().st_mode & stat.S_IXUSR

    def test_runs_nothing(self, pb, tmp_path):
        app, gen = self._fleet(pb, tmp_path)
        marker = tmp_path / 'ran'
        (tmp_path / 'gen').write_text(f'#!/bin/sh\ntouch {marker}\n')
        out = tmp_path / 'flat'
        app.source_cache = {}
        app._cmd_dump_script(str(out))
        assert not marker.exists()
        # never run: the line is kept and the reader is told why
        assert ':source!' in out.read_text()
        assert any('no output to inline' in t for t in _texts(app))

    def test_hosts_only(self, pb, tmp_path):
        app, gen = self._fleet(pb, tmp_path)
        app._cmd_source_bang(gen)
        out = tmp_path / 'inv'
        app._cmd_dump_script(f'--hosts-only {out}')
        text = out.read_text()
        assert not text.startswith('#!')
        assert ':probe' not in text and '127.0.0.9' in text

    def test_existing_file_needs_force(self, pb, tmp_path):
        app, _ = self._fleet(pb, tmp_path)
        out = tmp_path / 'flat'
        out.write_text('keep')
        app._cmd_dump_script(str(out))
        assert out.read_text() == 'keep'
        assert any('--force' in t for t in _texts(app))
        app._cmd_dump_script(f'--force {out}')
        assert out.read_text().startswith('#!/bin/sh')

    @pytest.mark.parametrize('arg', ['', '-', '/dev/stdout', '--bogus x',
                                     'a b'])
    def test_bad_arguments_refused(self, pb, app, arg):
        app._cmd_dump_script(arg)
        assert any(t for t in _texts(app) if 'dump-script' in t)

    def test_directory_refused(self, pb, app, tmp_path):
        app._cmd_dump_script(str(tmp_path))
        assert any('directory' in t for t in _texts(app))

    def test_without_hosts_file_uses_startup_entries(self, pb, app, tmp_path):
        out = tmp_path / 'flat'
        app._cmd_dump_script(str(out))
        assert '10.0.0.1' in out.read_text()

    def test_registered(self, pb):
        assert any('dump-script' in c.names for c in pb.CMD_REGISTRY)
