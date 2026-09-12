"""Which hosts a ':probe-source' opens a connection to, and how it logs in.

A probe source is a persistent SSH connection per host.  Without a way to say
which hosts can serve it, a mixed file -- Linux boards, MikroTik routers,
cameras with no shell -- opens one to every host and the ones that cannot
answer hold a failing connection on a backoff loop for the life of the run.

Covers:
  - ':probe-source --hosts <globs>' parsing and its default
  - only matching hosts get a reader, matched on the ':resolv' alias too
  - ':prog-options ssh' supplies the probe login, and '--disable' suppresses it
  - a rule's own ProxyJump cannot displace the relay chain
  - ':edit' reload: narrowing the glob stops the readers it excluded
"""

from unittest.mock import patch

import pytest


def _make_app(pb, tmp_path, entries=None):
    cfg = tmp_path / 'ping-bulk' / 'config'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('')
    with patch.object(pb, '_config_path', return_value=str(cfg)):
        app = pb.Application(entries if entries is not None else [('host', '10.0.0.1')])
    app._monitoring_started = True
    return app


@pytest.fixture
def app(pb, tmp_path):
    return _make_app(pb, tmp_path)


def _last(app, n=1):
    return [e.text.split('   ', 1)[-1] for e in list(app.events)[-n:]]


def _hosts_app(pb, tmp_path, names):
    return _make_app(pb, tmp_path, [('host', n) for n in names])


def _start(app):
    with patch('threading.Thread'):
        app._start_probe_readers()
    return [r.monitor.host for r in app.probe_readers]


# ---------------------------------------------------------------------------
# ':probe-source --hosts' parsing
# ---------------------------------------------------------------------------

class TestHostsFlagParsing:

    def test_default_is_every_host(self, app):
        app._cmd_probe_source('--cmd /bin/true')
        assert app.probe_hosts == ['*']

    def test_single_glob(self, app):
        app._cmd_probe_source('--cmd /bin/true --hosts *-comm-mod')
        assert app.probe_hosts == ['*-comm-mod']

    def test_comma_separated_list(self, app):
        app._cmd_probe_source('--cmd /bin/true --hosts "*-comm-mod,*-jetson"')
        assert app.probe_hosts == ['*-comm-mod', '*-jetson']

    def test_space_separated_list_in_one_value(self, app):
        app._cmd_probe_source('--cmd /bin/true --hosts "sh1-comm-mod sh2-comm-mod"')
        assert app.probe_hosts == ['sh1-comm-mod', 'sh2-comm-mod']

    def test_empty_value_is_refused(self, app):
        app._cmd_probe_source('--cmd /bin/true --hosts ""')
        assert 'at least one host' in _last(app)[0]

    def test_absent_flag_resets_a_previous_scope(self, app):
        """':probe-source' restates the whole declaration on every call.

        Carrying the scope over would make a re-read of an edited file depend
        on what the previous read happened to contain.
        """
        app._cmd_probe_source('--cmd /bin/true --hosts *-comm-mod')
        app._cmd_probe_source('--cmd /bin/true')
        assert app.probe_hosts == ['*']

    def test_report_names_the_scope(self, app):
        app._cmd_probe_source('--cmd /bin/true --hosts *-comm-mod')
        app._cmd_probe_source()
        assert 'on *-comm-mod' in _last(app)[0]

    def test_report_stays_quiet_when_unscoped(self, app):
        app._cmd_probe_source('--cmd /bin/true')
        app._cmd_probe_source()
        assert ' on ' not in _last(app)[0]


# ---------------------------------------------------------------------------
# Which hosts get a reader
# ---------------------------------------------------------------------------

class TestReaderScope:

    def _app(self, pb, tmp_path, hosts_flag):
        app = _hosts_app(pb, tmp_path,
                         ['sh1-comm-mod', 'sh1-jetson', 'sh1-cam1', 'sh1-router'])
        app._cmd_probe('gps')
        app._cmd_probe_source('--cmd /bin/true' + hosts_flag)
        return app

    def test_unscoped_reaches_every_host(self, pb, tmp_path):
        app = self._app(pb, tmp_path, '')
        assert len(_start(app)) == 4

    def test_glob_selects_one_kind(self, pb, tmp_path):
        app = self._app(pb, tmp_path, ' --hosts *-comm-mod')
        assert _start(app) == ['sh1-comm-mod']

    def test_several_globs(self, pb, tmp_path):
        app = self._app(pb, tmp_path, ' --hosts "*-comm-mod,*-jetson"')
        assert _start(app) == ['sh1-comm-mod', 'sh1-jetson']

    def test_a_glob_matching_nothing_opens_nothing(self, pb, tmp_path):
        app = self._app(pb, tmp_path, ' --hosts *-nosuch')
        assert _start(app) == []

    def test_port_monitors_are_still_skipped(self, pb, tmp_path):
        """A TCP check has no shell on the far side, whatever the glob says."""
        app = _hosts_app(pb, tmp_path, ['example.com:443'])
        app._cmd_probe('gps')
        app._cmd_probe_source('--cmd /bin/true --hosts *')
        assert _start(app) == []

    def test_relayed_host_matches_on_its_resolv_alias(self, pb, tmp_path):
        """The display name of a relayed host is a composite no glob matches.

        ':resolv' is what a '##' label becomes, so the alias is the name the
        file actually wrote and the one a glob has to reach.
        """
        app = _make_app(pb, tmp_path, [])
        m = pb.SshPingMonitor(['-J', 'wg', 'admin@relay'], '10.123.1.2')
        m._hosts_map = {'sh1-comm-mod': ('10.123.1.2', None)}
        app.monitors = [m]
        app._cmd_probe('gps')
        app._cmd_probe_source('--cmd /bin/true --hosts *-comm-mod')
        assert len(_start(app)) == 1


# ---------------------------------------------------------------------------
# ':prog-options ssh' is how a site records the probe login
# ---------------------------------------------------------------------------

class TestProbeLogin:

    def _app(self, pb, tmp_path, rule):
        app = _hosts_app(pb, tmp_path, ['sh1-comm-mod'])
        app._cmd_prog_options(rule)
        app._cmd_probe('gps')
        app._cmd_probe_source('--cmd /bin/true')
        return app

    def test_login_reaches_the_probe_connection(self, pb, tmp_path):
        """Every other ssh path respects these rules; this one silently did not,
        so a probe authenticated as the local user on every host whose login
        differs."""
        app = self._app(pb, tmp_path, 'ssh *-comm-mod -l root')
        with patch('threading.Thread'):
            app._start_probe_readers()
        cmd = app.probe_readers[0]._build_cmd()
        assert cmd[cmd.index('-l') + 1] == 'root'

    def test_disable_suppresses_the_reader(self, pb, tmp_path):
        """'--disable' means there is no shell there, and a probe reader is one."""
        app = self._app(pb, tmp_path, 'ssh *-comm-mod --disable')
        assert _start(app) == []

    def test_a_host_with_no_rule_gets_no_extra_options(self, pb, tmp_path):
        app = self._app(pb, tmp_path, 'ssh *-other -l root')
        with patch('threading.Thread'):
            app._start_probe_readers()
        assert '-l' not in app.probe_readers[0]._build_cmd()

    def test_rule_proxyjump_cannot_displace_the_relay_chain(self, pb, tmp_path):
        """ssh keeps the first value of a repeated option, and the reader puts
        its own chain first -- so the target is still reached through its relay
        and no ssh-option parsing is needed to guarantee it."""
        app = _make_app(pb, tmp_path, [])
        m = pb.SshPingMonitor(['-J', 'wg', 'admin@relay'], '10.123.1.2')
        m._hosts_map = {'sh1-comm-mod': ('10.123.1.2', None)}
        app.monitors = [m]
        app._cmd_prog_options('ssh sh1-comm-mod -J elsewhere')
        app._cmd_probe('gps')
        app._cmd_probe_source('--cmd /bin/true')
        with patch('threading.Thread'):
            app._start_probe_readers()
        cmd = app.probe_readers[0]._build_cmd()
        assert cmd[cmd.index('-J') + 1] == 'wg,admin@relay'


# ---------------------------------------------------------------------------
# ':edit' reload
# ---------------------------------------------------------------------------

class TestResyncHonoursTheScope:

    def _app(self, pb, tmp_path):
        app = _hosts_app(pb, tmp_path, ['sh1-comm-mod', 'sh1-jetson'])
        app._cmd_probe('gps')
        app._cmd_probe_source('--cmd /bin/true')
        _start(app)
        return app

    def test_narrowing_the_glob_stops_the_excluded_readers(self, pb, tmp_path):
        """An adopted monitor is the same object, so a live monitor is not by
        itself a reason to keep its reader."""
        app = self._app(pb, tmp_path)
        assert len(app.probe_readers) == 2
        app._cmd_probe_source('--cmd /bin/true --hosts *-comm-mod')
        with patch('threading.Thread'):
            app._resync_probe_readers()
        assert [r.monitor.host for r in app.probe_readers] == ['sh1-comm-mod']

    def test_widening_the_glob_opens_the_missing_ones(self, pb, tmp_path):
        app = self._app(pb, tmp_path)
        app._cmd_probe_source('--cmd /bin/true --hosts *-comm-mod')
        with patch('threading.Thread'):
            app._resync_probe_readers()
            app._cmd_probe_source('--cmd /bin/true')
            app._resync_probe_readers()
        assert len(app.probe_readers) == 2

    def test_a_stopped_reader_is_told_to_stop(self, pb, tmp_path):
        app = self._app(pb, tmp_path)
        excluded = [r for r in app.probe_readers if r.monitor.host == 'sh1-jetson'][0]
        app._cmd_probe_source('--cmd /bin/true --hosts *-comm-mod')
        with patch('threading.Thread'):
            app._resync_probe_readers()
        assert excluded.running is False


# ---------------------------------------------------------------------------
# ':probe-source --script' — ship a local file instead of installing it
# ---------------------------------------------------------------------------

class TestScriptShipping:

    def _script(self, tmp_path, text="echo gps=0\n"):
        f = tmp_path / 'pb-probe-gps'
        f.write_text(text)
        return f

    def test_the_script_text_is_read_not_its_path(self, app, tmp_path):
        f = self._script(tmp_path, "echo gps=1\n")
        app._cmd_probe_source(f'--script {f}')
        assert app.probe_script == "echo gps=1\n"
        assert app.probe_script_path == str(f)

    def test_the_remote_command_carries_it_as_base64(self, pb, tmp_path):
        """Base64 is the point: no '$', quote or backslash in the payload, so
        the hosts-file expander, shlex and the remote shell all pass it through.
        Inline shell cannot survive that -- a hosts file eats '$name' and reads
        '$1' as a ':for' backreference."""
        import base64
        text = "t=$(date +%s); echo \"gps=$t\"  # 'quoted' \\ backslash\n"
        r = pb.ProbeReader(pb.PingMonitor('h'), None, 30,
                           {'gps': pb.ProbeDef('gps')}, retain=10, script=text)
        remote = r._build_cmd()[-1]
        blob = base64.b64encode(text.encode()).decode()
        assert blob in remote
        assert text not in remote          # never shipped as literal shell

    def test_the_script_is_decoded_once_per_connection(self, pb, tmp_path):
        """Not once per round: the decode sits before the loop."""
        r = pb.ProbeReader(pb.PingMonitor('h'), None, 30,
                           {'gps': pb.ProbeDef('gps')}, retain=10, script="echo gps=0\n")
        remote = r._build_cmd()[-1]
        assert remote.index('base64 -d') < remote.index('while :')
        assert remote.count('base64 -d') == 1

    def test_stdin_is_left_to_the_script(self, pb):
        """'sh -c \"$var\"' rather than a pipe into sh, which would spend the
        script's own stdin on the script."""
        r = pb.ProbeReader(pb.PingMonitor('h'), None, 30,
                           {'gps': pb.ProbeDef('gps')}, retain=10, script="echo gps=0\n")
        assert 'sh -c "$_pb"' in r._build_cmd()[-1]

    def test_a_plain_cmd_ships_nothing(self, pb):
        r = pb.ProbeReader(pb.PingMonitor('h'), '/usr/local/bin/pb-probe', 30,
                           {'gps': pb.ProbeDef('gps')}, retain=10)
        remote = r._build_cmd()[-1]
        assert 'base64' not in remote and '/usr/local/bin/pb-probe' in remote

    def test_cmd_and_script_are_alternatives(self, app, tmp_path):
        f = self._script(tmp_path)
        app._cmd_probe_source(f'--cmd /bin/true --script {f}')
        assert 'alternatives' in _last(app)[0]
        assert app.probe_source is None

    def test_neither_is_refused(self, app):
        app._cmd_probe_source('--interval 30')
        assert 'missing --cmd or --script' in _last(app)[0]

    def test_a_missing_file_is_reported(self, app, tmp_path):
        app._cmd_probe_source(f'--script {tmp_path}/nope')
        assert 'nope' in _last(app)[0]
        assert app.probe_source is None

    def test_an_empty_script_is_refused(self, app, tmp_path):
        app._cmd_probe_source(f'--script {self._script(tmp_path, "  \n")}')
        assert 'is empty' in _last(app)[0]

    def test_an_oversized_script_is_refused(self, app, tmp_path, pb):
        """Better than an E2BIG from Popen once per reconnect in a backoff loop."""
        big = self._script(tmp_path, 'x' * (pb._PROBE_SCRIPT_MAX + 10))
        app._cmd_probe_source(f'--script {big}')
        assert 'larger than' in _last(app)[0]
        assert app.probe_source is None

    def test_off_clears_a_shipped_script(self, app, tmp_path):
        app._cmd_probe_source(f'--script {self._script(tmp_path)}')
        app._cmd_probe_source('off')
        assert app.probe_script is None and app.probe_source is None


class TestScriptPathResolution:

    def test_relative_is_resolved_against_the_hosts_file(self, pb, tmp_path):
        """Not the working directory: a hosts file names the script beside it,
        and resolving against the cwd makes the same file work or silently read
        nothing depending on where ping-bulk was started."""
        (tmp_path / 'probe.sh').write_text('echo gps=0\n')
        hosts = tmp_path / 'my.hosts'
        hosts.write_text('10.0.0.1\n')
        cfg = tmp_path / 'ping-bulk' / 'config'
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([('host', '10.0.0.1')], hosts_file=str(hosts))
        app._monitoring_started = True
        app._cmd_probe_source('--script probe.sh')
        assert app.probe_script == 'echo gps=0\n'

    def test_absolute_is_left_alone(self, app, tmp_path):
        f = tmp_path / 'probe.sh'
        f.write_text('echo gps=0\n')
        app._cmd_probe_source(f'--script {f}')
        assert app.probe_script_path == str(f)


class TestResyncOnADeclarationChange:

    def _app(self, pb, tmp_path, script_text):
        f = tmp_path / 'probe.sh'
        f.write_text(script_text)
        app = _hosts_app(pb, tmp_path, ['sh1-comm-mod'])
        app._cmd_probe('gps')
        app._cmd_probe_source(f'--script {f}')
        _start(app)
        return app, f

    def test_an_edited_script_replaces_the_reader(self, pb, tmp_path):
        """The command is baked into the child at spawn time, so keeping the
        reader would leave the old bytes running with nothing to say so."""
        app, f = self._app(pb, tmp_path, 'echo gps=0\n')
        first = app.probe_readers[0]
        f.write_text('echo gps=1\n')
        app._cmd_probe_source(f'--script {f}')
        with patch('threading.Thread'):
            app._resync_probe_readers()
        assert app.probe_readers[0] is not first
        assert app.probe_readers[0].script == 'echo gps=1\n'
        assert first.running is False

    def test_an_unchanged_script_keeps_the_reader(self, pb, tmp_path):
        app, f = self._app(pb, tmp_path, 'echo gps=0\n')
        first = app.probe_readers[0]
        app._cmd_probe_source(f'--script {f}')
        with patch('threading.Thread'):
            app._resync_probe_readers()
        assert app.probe_readers[0] is first

    def test_a_changed_interval_replaces_the_reader(self, pb, tmp_path):
        app, f = self._app(pb, tmp_path, 'echo gps=0\n')
        first = app.probe_readers[0]
        app._cmd_probe_source(f'--script {f} --interval 5')
        with patch('threading.Thread'):
            app._resync_probe_readers()
        assert app.probe_readers[0] is not first

    def test_a_symlinked_hosts_file_finds_the_script_by_the_link_target(
            self, pb, tmp_path):
        """A hosts file reached through a symlink has two directories with a
        claim to 'beside it', and the script lives with the real file."""
        import os
        real = tmp_path / 'checkout'
        real.mkdir()
        (real / 'probe.sh').write_text('echo gps=0\n')
        (real / 'my.hosts').write_text('10.0.0.1\n')
        link_dir = tmp_path / 'elsewhere'
        link_dir.mkdir()
        link = link_dir / 'my.hosts'
        os.symlink(real / 'my.hosts', link)
        cfg = tmp_path / 'ping-bulk' / 'config'
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([('host', '10.0.0.1')], hosts_file=str(link))
        app._monitoring_started = True
        app._cmd_probe_source('--script probe.sh')
        assert app.probe_script == 'echo gps=0\n'

    def test_the_typed_directory_wins_when_both_have_the_file(self, pb, tmp_path):
        import os
        real = tmp_path / 'checkout'; real.mkdir()
        (real / 'probe.sh').write_text('echo gps=REAL\n')
        (real / 'my.hosts').write_text('10.0.0.1\n')
        link_dir = tmp_path / 'elsewhere'; link_dir.mkdir()
        (link_dir / 'probe.sh').write_text('echo gps=TYPED\n')
        link = link_dir / 'my.hosts'
        os.symlink(real / 'my.hosts', link)
        cfg = tmp_path / 'ping-bulk' / 'config'
        cfg.parent.mkdir(parents=True, exist_ok=True); cfg.write_text('')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([('host', '10.0.0.1')], hosts_file=str(link))
        app._monitoring_started = True
        app._cmd_probe_source('--script probe.sh')
        assert app.probe_script == 'echo gps=TYPED\n'


class TestScriptInKioskMode:
    """The ownership rules apply to the LOCAL script file.

    Not to the composed remote one-liner: that contains '|' and '$' by
    construction, so a metacharacter rule would refuse every --script.
    """

    def _app(self, pb, tmp_path, started):
        hosts = tmp_path / 'my.hosts'
        hosts.write_text('10.0.0.1\n')
        cfg = tmp_path / 'ping-bulk' / 'config'
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([('host', '10.0.0.1')], hosts_file=str(hosts),
                                 kiosk_mode=True)
        app._monitoring_started = started
        return app

    def test_typed_at_the_prompt_is_refused(self, pb, tmp_path):
        """A probe runs a command of someone's choosing on every host, so in
        kiosk mode the declaration must come from the admin-owned hosts file."""
        app = self._app(pb, tmp_path, started=True)
        f = tmp_path / 'probe.sh'
        f.write_text('echo gps=0\n')
        app._cmd_probe_source(f'--script {f}')
        assert 'not allowed interactively' in _last(app)[0]
        assert app.probe_script is None

    def test_a_writable_script_is_refused_from_the_hosts_file(self, pb, tmp_path):
        app = self._app(pb, tmp_path, started=False)
        f = tmp_path / 'probe.sh'
        f.write_text('echo gps=0\n')
        f.chmod(0o666)
        app._cmd_probe_source(f'--script {f}')
        assert app.probe_script is None
        assert 'writable' in _last(app)[0]

    def test_outside_kiosk_a_writable_script_is_fine(self, pb, tmp_path):
        """The rule exists because the kiosk console user is the adversary."""
        app = _make_app(pb, tmp_path)
        f = tmp_path / 'probe.sh'
        f.write_text('echo gps=0\n')
        f.chmod(0o666)
        app._cmd_probe_source(f'--script {f}')
        assert app.probe_script == 'echo gps=0\n'


class TestShippedScriptStaleness:

    def test_the_same_text_read_by_another_path_keeps_the_readers(self, pb, tmp_path):
        """A symlink and the real file give the same bytes under different
        paths; replacing every reader over that is pure churn."""
        a = tmp_path / 'a.sh'; a.write_text('echo gps=0\n')
        b = tmp_path / 'b.sh'; b.write_text('echo gps=0\n')
        app = _hosts_app(pb, tmp_path, ['sh1-comm-mod'])
        app._cmd_probe('gps')
        app._cmd_probe_source(f'--script {a}')
        _start(app)
        first = app.probe_readers[0]
        app._cmd_probe_source(f'--script {b}')
        with patch('threading.Thread'):
            app._resync_probe_readers()
        assert app.probe_readers[0] is first


# ---------------------------------------------------------------------------
# ':probe --label' and the ordering trap it sits next to
# ---------------------------------------------------------------------------

class TestProbeLabel:

    def test_default_label_capitalises_the_name(self, app):
        app._cmd_probe('temp')
        assert app.probe_defs['temp'].label == 'Temp'

    def test_label_overrides_it_for_an_acronym(self, app):
        """'gps' capitalises to 'Gps', and a column header is read as a word."""
        app._cmd_probe('gps --label GPS')
        assert app.probe_defs['gps'].label == 'GPS'

    def test_the_header_uses_the_label_with_the_unit(self, app):
        app._cmd_probe('gps --unit s --label GPS')
        assert app._stat_header('GPS') == 'GPS,s'

    def test_the_column_is_still_selected_by_the_probe_name(self, app):
        """The label is presentation; ':set stats' still takes the key the
        probe script emits."""
        app._cmd_probe('gps --label GPS')
        app._cmd_stats('gps,last')
        assert app.stats_custom == ['GPS', 'Last']

    def test_a_label_does_not_disturb_the_reading(self, pb, app):
        app._cmd_probe('gps --range 0:5 --label GPS')
        m = app.monitors[0]
        series = pb.ProbeSeries(10)
        series.add(3.0, 1.0)
        m.probes['gps'] = series
        assert app._probe_cell(m, app.probe_defs['gps']) == '3'


class TestStatsRefusalIsVisible:
    """A refused ':set stats' discards what the user asked for, so it cannot
    be reported at a level the default log level hides."""

    def test_an_unknown_column_keeps_the_previous_ones(self, app):
        app._cmd_stats('last,avg')
        app._cmd_stats('gps,rtime,down')
        assert app.stats_custom == ['Last', 'Avg']

    def test_the_refusal_shows_at_the_default_log_level(self, pb, app):
        app._cmd_stats('gps,rtime')
        entry = list(app.events)[-1]
        assert entry.level <= app.loglevel, entry.text
        assert entry.level == pb.LEVEL_NORMAL

    def test_an_unknown_single_mode_is_visible_too(self, pb, app):
        app._cmd_stats('nosuchthing')
        assert list(app.events)[-1].level == pb.LEVEL_NORMAL

    def test_a_probe_declared_first_is_accepted(self, app):
        """Which is the ordering the message points at."""
        app._cmd_probe('gps --label GPS')
        app._cmd_stats('gps,rtime,down')
        assert app.stats_custom == ['GPS', 'RTime', 'Down']
