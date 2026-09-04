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

    def _run(self, pb, lines, defs=None, retain=100):
        m = pb.PingMonitor('10.0.0.1')
        defs = defs or {'temp': pb.ProbeDef('temp'), 'rpm': pb.ProbeDef('rpm')}
        r = pb.ProbeReader(m, 'pb-probe', 0.2, defs, retain=retain)
        proc = FakeProc(stdout_lines=lines, close=True)
        with patch('subprocess.Popen', return_value=proc), patch('time.sleep'):
            t = threading.Thread(target=r.run, daemon=True)
            t.start()
            deadline = time.time() + 5
            while time.time() < deadline and not m.probes:
                time.sleep(0.01)
            time.sleep(0.2)
            r.running = False
            t.join(5)
        return m, r

    def test_values_are_collected_as_a_series(self, pb):
        m, _ = self._run(pb, ['temp=54.2\n', '---\n', 'temp=55.9\n', '---\n'])
        assert list(m.probes['temp'].values) == [54.2, 55.9]
        assert m.probes['temp'].state == 'ok'

    def test_timestamps_are_recorded_alongside(self, pb):
        """The strip and the sparkline both need when, not just what."""
        m, _ = self._run(pb, ['temp=54.2\n', '---\n'])
        s = m.probes['temp']
        assert len(s.times) == len(s.values) == 1

    def test_undeclared_keys_are_ignored(self, pb):
        """One site-wide script may serve hosts that display different subsets."""
        m, _ = self._run(pb, ['temp=1\n', 'humidity=40\n', '---\n'])
        assert 'humidity' not in m.probes

    def test_unparsable_value_marks_err(self, pb):
        m, _ = self._run(pb, ['temp=warm\n', '---\n'])
        assert m.probes['temp'].state == 'err'

    def test_retain_bounds_the_series(self, pb):
        lines = [f'temp={i}\n' for i in range(20)]
        m, _ = self._run(pb, lines, retain=5)
        assert len(m.probes['temp'].values) == 5

    def test_garbage_lines_do_not_raise(self, pb):
        m, _ = self._run(pb, ['not a pair\n', '\n', '---\n', 'temp=1\n'])
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
