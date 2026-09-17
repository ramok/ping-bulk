"""The JSON snapshot a web viewer renders from.

`_web_state()` is the whole read side of the web interface: pure, no curses,
no mutation.  It exists so the browser and the terminal cannot disagree — the
stats columns come from `STAT_NAMES`/`_compute_stat` and the history strip is
the same string `draw_hosts` gets from `get_history_string`.

Two things here are load-bearing and neither is obvious.

**Host identity has to be stable and is the one thing that cannot be
retrofitted.**  Row indices are not identity: the ':edit' reload rebuilds
`entries` and `monitors` wholesale, and `highlighted_index` is a single global
cursor shared with whoever is at the console.  A viewer that says "pause row
7" three seconds after it fetched the list can pause a different host.  `uid`
is derived from the display name, so it survives a reload, survives a process
restart, and changes exactly when the row genuinely becomes a different row.

**Everything in the payload is attacker-controlled.**  Display names come from
the hosts file, `ip` from reverse DNS — whoever owns a PTR record chooses that
string — and `error` text comes from ping's stderr.  The payload must carry
them as inert data.
"""

import json
import os
import threading
import time

import pytest
from unittest.mock import patch

from utils.hosts_helper import write_hosts


HOSTILE = '</script><img src=x onerror=alert(1)>'
# A bare host line may not contain spaces (the parser rejects it and says
# so), so the cases that go through one use this equivalent.
HOSTILE_HOST = '</script><img/src=x/onerror=alert(1)>'


def _app(pb, tmp_path, content):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    hosts = tmp_path / 'web.hosts'
    hosts.write_text(content)
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application(pb.parse_hosts_file(str(hosts)))
    app._monitoring_started = True
    app._web_hosts_path = str(hosts)
    return app


def _reload(app, content):
    with open(app._web_hosts_path, 'w') as f:
        f.write(content)
    with patch.object(app, '_start_monitor_thread', lambda m: None):
        app._edit_reload_inplace(app._web_hosts_path)


def _uids(state):
    return [r['uid'] for r in state['rows'] if r['kind'] == 'host']


BASE = """### group
10.0.0.1
10.0.0.2
10.0.0.3
"""


# ===========================================================================
# Identity
# ===========================================================================

class TestHostIdentity:

    def test_uids_survive_a_reload_that_renumbers_the_list(self, pb, tmp_path):
        """The reason uid exists: indices move, hosts do not."""
        app = _app(pb, tmp_path, BASE)
        before = _uids(app._web_state())
        app.highlighted_index = app.entries.index(app.monitors[2])
        index_before = app.highlighted_index

        _reload(app, "### group\n10.0.0.0\n10.0.0.1\n10.0.0.2\n10.0.0.3\n")

        after = _uids(app._web_state())
        assert before == after[1:], 'every original host kept its uid'
        assert app.highlighted_index != index_before, 'the index really moved'

    def test_a_renamed_host_gets_a_new_uid(self, pb, tmp_path):
        """A different name is a different row, and should look like one."""
        app = _app(pb, tmp_path, '10.0.0.1 ## router\n')
        before = _uids(app._web_state())
        _reload(app, '10.0.0.1 ## gateway\n')
        assert _uids(app._web_state()) != before

    def test_the_same_host_has_the_same_uid_in_a_fresh_process(self, pb,
                                                               tmp_path):
        """Derived from the name, not handed out by a counter.

        A counter would renumber on restart and break any link a browser kept.
        """
        a = _app(pb, tmp_path / 'a', BASE)
        b = _app(pb, tmp_path / 'b', BASE)
        assert _uids(a._web_state()) == _uids(b._web_state())

    def test_uids_are_unique_and_url_safe(self, pb, tmp_path):
        app = _app(pb, tmp_path, BASE + '10.0.0.4:80\n')
        uids = [r['uid'] for r in app._web_state()['rows']]
        assert len(uids) == len(set(uids))
        assert all(u.isalnum() for u in uids), uids

    def test_a_section_uid_distinguishes_nesting_depth(self, pb, tmp_path):
        """The same title at two depths is two rows."""
        app = _app(pb, tmp_path, '### group\n10.0.0.1\n#### group\n10.0.0.2\n')
        sections = [r for r in app._web_state()['rows']
                    if r['kind'] == 'section']
        assert len(sections) == 2
        assert sections[0]['uid'] != sections[1]['uid']


# ===========================================================================
# Hostile strings
# ===========================================================================

class TestThePayloadIsInertData:

    def test_a_hostile_display_name_survives_as_a_value_not_as_markup(
            self, pb, tmp_path):
        """json.dumps alone would leave '</script>' literal in the bytes.

        It escapes quotes, backslashes and control characters only, so a
        display name closes an HTML script block wherever that payload is
        later embedded.  _web_json escapes the three characters that matter.
        """
        app = _app(pb, tmp_path, f'10.0.0.1 ## {HOSTILE}\n')
        raw = pb.Application._web_json(app._web_state())
        assert b'<' not in raw and b'>' not in raw
        assert json.loads(raw)['rows'][0]['name'] == HOSTILE, \
            'and it still means exactly what it said'

    def test_a_hostile_resolv_alias_is_escaped_too(self, pb, tmp_path):
        """':resolv' names reach the payload the way a PTR record would."""
        app = _app(pb, tmp_path,
                   f':resolv 10.0.0.9 {HOSTILE_HOST}\n{HOSTILE_HOST}\n')
        raw = pb.Application._web_json(app._web_state())
        assert b'</script>' not in raw
        rows = json.loads(raw)['rows']
        assert rows, 'the hostile name must still produce a host row'
        assert HOSTILE_HOST in rows[0]['name']

    def test_hostile_event_text_is_escaped_too(self, pb, tmp_path):
        app = _app(pb, tmp_path, BASE)
        app.add_event('test', HOSTILE)
        raw = pb.Application._web_json(app._web_state())
        assert b'<img' not in raw
        assert any(HOSTILE in e['text'] for e in json.loads(raw)['events'])

    def test_the_escaping_is_lossless_for_ordinary_text(self, pb, tmp_path):
        """The relayed-host display name contains a '\u2192' arrow."""
        app = _app(pb, tmp_path,
                   ':with remote-ping -J proxy root@relay\n10.1.0.1\n:with-end\n')
        raw = pb.Application._web_json(app._web_state())
        assert '\u2192' in json.loads(raw)['rows'][0]['name']

    def test_the_whole_snapshot_is_json_serializable(self, pb, tmp_path):
        """No datetime, no deque, no Monitor object leaking into the payload."""
        app = _app(pb, tmp_path, BASE + '10.0.0.4:443\n')
        app.monitors[0].alive = True
        app.monitors[0].latency = 1.25
        json.dumps(app._web_state())        # must not raise


# ===========================================================================
# What a viewer asks first
# ===========================================================================

class TestTheDownList:

    def _down(self, app):
        return {d['name'] for d in app._web_state()['down']}

    def test_a_down_host_is_named(self, pb, tmp_path):
        app = _app(pb, tmp_path, BASE)
        m = app.monitors[1]
        m.alive = False
        m.down_since = time.monotonic() - 30
        assert '10.0.0.2' in self._down(app)

    def test_an_expected_silence_is_not_down(self, pb, tmp_path):
        """':no-alarm' means a lost reply is expected, so it is not news."""
        app = _app(pb, tmp_path, ':no-alarm 10.0.0.2\n' + BASE)
        m = next(m for m in app.monitors if m.host == '10.0.0.2')
        m.alive = False
        m.down_since = time.monotonic() - 30
        assert '10.0.0.2' not in self._down(app)

    def test_a_paused_host_is_not_down(self, pb, tmp_path):
        app = _app(pb, tmp_path, BASE)
        m = app.monitors[1]
        m.alive = False
        m.down_since = time.monotonic() - 30
        m.pause()
        assert '10.0.0.2' not in self._down(app)

    def test_an_up_fleet_reports_nothing(self, pb, tmp_path):
        app = _app(pb, tmp_path, BASE)
        for m in app.monitors:
            m.alive = True
            m.up_since = time.monotonic() - 30
        assert self._down(app) == set()


# ===========================================================================
# One source of truth with the terminal
# ===========================================================================

class TestItAgreesWithTheTerminal:

    def test_the_history_strip_is_the_terminal_string(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        m = app.monitors[0]
        for v in (1.0, None, 2.0, 'ERR'):
            m.history.append(v)
            m.history_times.append(time.time())
        render_time, sync = app._history_render_time()
        expected = m.get_history_string(
            12, 0, pb.HISTORY_MODES[app.history_mode], 1,
            sync=sync, end_time=render_time)
        assert app._web_state(history_len=12)['rows'][0]['history'] == expected

    def test_the_columns_follow_set_stats(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        app._dispatch_cmd(':set stats last,avg,stdev')
        state = app._web_state()
        assert state['columns'] == ['Last', 'Avg', 'StDev']
        assert set(state['rows'][0]['stats']) == {'Last', 'Avg', 'StDev'}

    def test_each_stat_is_the_terminal_value(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        app._dispatch_cmd(':set stats avg')
        m = app.monitors[0]
        with m.lock:
            m._record_latency(4.0)
            m._record_latency(6.0)
        got = app._web_state()['rows'][0]['stats']['Avg']
        assert got == app._compute_stat(m, 'Avg').strip()

    def test_folding_does_not_take_rows_out_of_the_payload(self, pb,
                                                           tmp_path):
        """Folding is a view choice each browser makes for itself, so the
        payload carries every host and the page decides what it is showing —
        the same shape as the client-side filter.

        While the serializer took the terminal's visible rows, a section the
        console had folded had no hosts in the payload at all, so a browser
        could not *un*fold it however local its own state was.
        """
        app = _app(pb, tmp_path, BASE)
        assert len(app._web_state()['rows']) == 4     # section + 3 hosts
        app.entries[0].folded = True
        assert len(app._web_state()['rows']) == 4
        # ... and the terminal is unchanged: it still hides them.
        assert len(app._get_visible_entry_indices()) == 1

    def test_a_console_sort_does_not_empty_the_browsers_list(self, pb,
                                                            tmp_path):
        """':set sort' makes the terminal drop every section header, and the
        serializer inherited that — so with a sort on the console the browser
        received hosts in the console's order and **no sections at all**.

        The browser has its own sort control and its own fold state, so the
        order and the headers are its business: the payload is always the
        file's order with the labels in it. The terminal is untouched.
        """
        app = _app(pb, tmp_path, BASE)
        in_order = [r.get('uid') for r in app._web_state()['rows']]
        assert any(r['kind'] == 'section' for r in app._web_state()['rows'])

        app._dispatch_cmd(':set sort latency')
        rows = app._web_state()['rows']
        assert [r.get('uid') for r in rows] == in_order, (
            'the console\'s sort must not reorder the browser')
        assert any(r['kind'] == 'section' for r in rows), (
            'and must not take the section headers away, which is what left '
            'nothing to fold'
        )
        # The terminal still sorts, and still hides its headers while it does.
        assert all(not isinstance(app.entries[i], pb.SectionLabel)
                   for i in app._get_visible_entry_indices())

    def test_the_view_block_reports_the_display_settings(self, pb, tmp_path):
        app = _app(pb, tmp_path, BASE)
        app._dispatch_cmd(':set dns hostname')
        app._dispatch_cmd(':sync-history on')
        app._dispatch_cmd(':set sort name')
        view = app._web_state()['view']
        assert view['dns'] == 'hostname'
        assert view['sync'] is True
        assert view['sort'] == 'name'

    def test_generation_changes_when_the_row_list_does(self, pb, tmp_path):
        app = _app(pb, tmp_path, BASE)
        g0 = app._web_state()['generation']
        assert app._web_state()['generation'] == g0, 'a read must not bump it'
        _reload(app, BASE + '10.0.0.9\n')
        assert app._web_state()['generation'] != g0


# ===========================================================================
# Thread safety
# ===========================================================================

class TestItIsSafeToReadFromAnotherThread:

    def test_serializing_while_events_are_appended_does_not_raise(self, pb,
                                                                  tmp_path):
        """The failure this guards is a RuntimeError, so it is a race.

        Sized like tests/test_event_deque_race.py: a Python-level loop over
        self.events failed 186 times in 7000 attempts against a hammering
        writer, while list() of the same deque failed 0 times in 26000.
        """
        app = _app(pb, tmp_path, BASE)
        stop = threading.Event()
        errors = []

        def writer():
            i = 0
            while not stop.is_set():
                app.add_event('test', f'line {i}')
                i += 1

        t = threading.Thread(target=writer, daemon=True)
        t.start()
        try:
            for _ in range(400):
                try:
                    app._web_state(event_tail=50)
                except RuntimeError as exc:
                    errors.append(exc)
        finally:
            stop.set()
            t.join(5)
        assert not errors, errors

    def test_it_does_not_touch_the_live_filtered_list(self, pb):
        """`_get_filtered_events()` returns a list background threads mutate.

        A plain list has no 'mutated during iteration' guard, so a concurrent
        read gets silently wrong results instead of an exception.  The
        serializer filters its own snapshot instead; this asserts it stays
        that way, the same way test_thread_supervision.py guards thread names.
        """
        import inspect
        src = inspect.getsource(pb.Application._web_state)
        body = src.split('"""')[2]          # skip the docstring, which names it
        assert '_get_filtered_events' not in body
        assert '_events_snapshot' in body

    def test_it_tolerates_the_entry_list_shrinking_under_it(self, pb,
                                                            tmp_path):
        """':edit' replaces `entries` wholesale, with no lock to take."""
        app = _app(pb, tmp_path, BASE)
        visible = app._get_visible_entry_indices()
        real = app._get_visible_entry_indices

        def stale(include_folded=False, ignore_sort=False):
            del app.entries[1:]       # shrink after the indices were computed
            return visible

        app._get_visible_entry_indices = stale
        try:
            app._web_state()          # must not raise IndexError
        finally:
            app._get_visible_entry_indices = real

    def test_it_does_not_mutate_the_application(self, pb, tmp_path):
        """Pure: draw_hosts sets cached widths as a side effect; this must not."""
        app = _app(pb, tmp_path, BASE)
        before = {k: v for k, v in app.__dict__.items()
                  if isinstance(v, (int, float, str, bool, type(None)))}
        app._web_state()
        after = {k: v for k, v in app.__dict__.items()
                 if isinstance(v, (int, float, str, bool, type(None)))}
        assert after == before


# ===========================================================================
# Probe columns and the probe strip
# ===========================================================================

class TestProbesLookTheSameAsInTheTerminal:
    """Both of these drew *something plausible and wrong* in the browser.

    A probe column read '-' while the terminal beside it showed the reading,
    because `_compute_stat` is a pure function over one monitor and knows
    nothing about the app's ':probe' declarations — `_stat_cell` is the
    dispatcher that does.  And with ':set ping-view <probe>' the strip came
    back blank, because a probe series is not one of the HISTORY_MODES that
    `get_history_string` understands.

    Neither failed loudly.  A blank cell and an empty strip are what a host
    with no data looks like, so the browser would have quietly disagreed with
    the screen next to it.
    """

    HOSTS = (":probe-source --cmd 'echo temp=41'\n"
             ':probe temp --unit C --range 0:80 --warn 50 --crit 70\n'
             '10.0.0.1\n')

    def _built(self, pb, tmp_path):
        app = _app(pb, tmp_path, self.HOSTS)
        monitor = app.monitors[0]
        with monitor.lock:
            series = monitor.probes.setdefault('temp', pb.ProbeSeries(20))
            for value in (40.0, 41.5, 42.0):
                series.add(value, time.time())
        return app, monitor

    def test_a_probe_column_carries_the_reading(self, pb, tmp_path):
        app, monitor = self._built(pb, tmp_path)
        app._dispatch_cmd(':set stats last,temp')
        state = app._web_state()
        assert state['columns'] == ['Last', 'Temp']
        assert state['rows'][0]['stats']['Temp'] == '42'

    def test_every_column_matches_the_terminal_cell(self, pb, tmp_path):
        app, monitor = self._built(pb, tmp_path)
        app._dispatch_cmd(':set stats last,temp,avg')
        state = app._web_state()
        for name, value in state['rows'][0]['stats'].items():
            assert value == app._stat_cell(monitor, name).strip(), name

    def test_the_strip_shows_the_probe_series(self, pb, tmp_path):
        app, monitor = self._built(pb, tmp_path)
        app._dispatch_cmd(':set ping-view temp')
        state = app._web_state(history_len=8)
        probe = app.probe_defs['temp']
        width = app._probe_cell_width(probe)
        assert state['rows'][0]['history'] == app._probe_history_string(
            monitor, probe, 8, 0, width)
        assert '42' in state['rows'][0]['history'], 'the reading, not a bucket'

    def test_the_cell_width_comes_with_it(self, pb, tmp_path):
        """A probe cell holds a number, so the client cannot assume one column."""
        app, _m = self._built(pb, tmp_path)
        app._dispatch_cmd(':set ping-view temp')
        state = app._web_state()
        assert state['view']['cell_width'] == app._probe_cell_width(
            app.probe_defs['temp'])

    def test_rtt_view_uses_the_wide_cell_too(self, pb, tmp_path):
        app, monitor = self._built(pb, tmp_path)
        with monitor.lock:
            monitor.history.append(12.0)
            monitor.history_times.append(time.time())
        app._dispatch_cmd(':set ping-view rtt')
        state = app._web_state(history_len=8)
        width = app._rtt_cell_width()
        assert state['view']['cell_width'] == width
        render_time, sync = app._history_render_time()
        assert state['rows'][0]['history'] == monitor.get_history_string(
            8, 0, 'rtt', width, sync=sync, end_time=render_time)

    def test_success_view_is_still_one_column_per_ping(self, pb, tmp_path):
        app, _m = self._built(pb, tmp_path)
        app._dispatch_cmd(':set ping-view success')
        assert app._web_state()['view']['cell_width'] == 1


# ===========================================================================
# The details view
# ===========================================================================

class TestDetailsData:
    """`_details_data` is what the overlay and the web view both format from.

    The overlay used to read all of it inline, which made it the only host
    view in the program with no accessor — anything else wanting the same
    figures had to duplicate the reads or scrape formatted text.
    """

    def _seeded(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        m = app.monitors[0]
        with m.lock:
            m._record_latency(4.0)
            m._record_latency(6.0)
            m.rx_count, m.xx_count, m.ping_count = 9, 1, 10
            m.latency = 5.5
            m.alive = True
            m.up_since = time.monotonic() - 125
        return app, m

    def test_it_carries_the_figures_the_overlay_shows(self, pb, tmp_path):
        app, m = self._seeded(pb, tmp_path)
        d = app._details_data(m)
        assert (d['tx'], d['rx'], d['xx']) == (10, 9, 1)
        assert d['loss_pct'] == pytest.approx(10.0)
        assert d['lat_min'] == 4.0 and d['lat_max'] == 6.0
        assert d['lat_avg'] == pytest.approx(5.0)
        assert d['lat_stdev'] == pytest.approx(1.0)
        assert d['last'] == 5.5

    def test_durations_are_seconds_not_monotonic_stamps(self, pb, tmp_path):
        """up_since is a time.monotonic() value.

        It means nothing outside this process and less than nothing in JSON,
        so the accessor converts rather than passing it through.
        """
        app, m = self._seeded(pb, tmp_path)
        d = app._details_data(m)
        assert 120 < d['uptime'] < 130
        assert d['downtime'] is None
        assert 'up_since' not in d and 'down_since' not in d

    def test_loss_is_none_rather_than_zero_when_nothing_was_sent(self, pb,
                                                                 tmp_path):
        """'-' and '0.00%' are different claims."""
        app = _app(pb, tmp_path, '10.0.0.1\n')
        assert app._details_data(app.monitors[0])['loss_pct'] is None

    def test_it_names_the_command_and_the_connect_preview(self, pb, tmp_path):
        app, m = self._seeded(pb, tmp_path)
        d = app._details_data(m)
        assert d['cmd'] == ' '.join(m._build_ping_cmd())
        assert d['connect'] == app._connect_preview(m)

    def test_a_port_monitor_has_no_ping_command(self, pb, tmp_path):
        """PortMonitor has no _build_ping_cmd; the overlay shows '-' for it."""
        app = _app(pb, tmp_path, '10.0.0.1:443\n')
        assert app._details_data(app.monitors[0])['cmd'] == ''

    def test_it_is_json_serializable(self, pb, tmp_path):
        app, m = self._seeded(pb, tmp_path)
        json.dumps(app._details_data(m))

    def test_the_overlay_formats_from_it(self, pb, tmp_path):
        """One snapshot, so the two views cannot disagree about one host."""
        import inspect
        src = inspect.getsource(pb.Application._draw_details_overlay)
        assert '_details_data(monitor)' in src
        assert 'monitor._lat_count' not in src, 'no second set of reads'
        assert 'monitor.up_since' not in src


class TestColourIsDecidedHere:
    """A class name per cell, decided by the same rules the terminal paints by.

    The client used to guess the event colour by looking for 'error:' in the
    text, which knew nothing about the level or the category — and it had no
    way at all to judge a probe reading, whose thresholds only ping-bulk knows.
    """

    PROBE = (":probe-source --cmd 'echo t=1'\n"
             ':probe t --range 0:100 --warn 50 --crit 80\n'
             '10.0.0.1\n')

    def _with_reading(self, pb, tmp_path, value):
        app = _app(pb, tmp_path, self.PROBE)
        app.stale_attr = 0
        m = app.monitors[0]
        with m.lock:
            series = m.probes.setdefault('t', pb.ProbeSeries(5))
            series.add(value, time.time())
            series.state = 'ok'
        app._dispatch_cmd(':set stats t')
        return app, m

    @pytest.mark.parametrize('value,expected',
                             [(10.0, 'ok'), (60.0, 'warn'), (90.0, 'error')])
    def test_a_probe_cell_is_judged_by_its_own_thresholds(self, pb, tmp_path,
                                                          value, expected):
        app, _m = self._with_reading(pb, tmp_path, value)
        assert app._web_state()['rows'][0]['stat_class']['T'] == expected

    def test_every_cell_carries_a_class(self, pb, tmp_path):
        app, _m = self._with_reading(pb, tmp_path, 10.0)
        app._dispatch_cmd(':set stats last,avg,down,t')
        row = app._web_state()['rows'][0]
        assert set(row['stat_class']) == set(row['stats'])

    @pytest.mark.parametrize('latency,expected',
                             [(10.0, 'ok'), (80.0, 'warn'), (None, 'error')])
    def test_the_latency_cell_is_coloured_three_ways(self, pb, tmp_path,
                                                     latency, expected):
        """The default stats mode is a single 'Last' column, so this is *the*
        cell most rows show — and 'no reply' is red, not blank."""
        app = _app(pb, tmp_path, '10.0.0.1\n')
        app.stale_attr = 0
        m = app.monitors[0]
        m.alive, m.up_since = True, time.monotonic() - 60
        m.latency = latency
        assert app._stat_class(m, 'Last') == expected

    def test_the_default_column_is_not_left_uncoloured(self, pb, tmp_path):
        """':set stats off' still shows Last; it must not come through blank."""
        app = _app(pb, tmp_path, '10.0.0.1\n')
        app.stale_attr = 0
        m = app.monitors[0]
        m.alive, m.up_since, m.latency = True, time.monotonic() - 60, 12.0
        state = app._web_state()
        assert state['columns'] == ['Last']
        assert state['rows'][0]['stat_class']['Last'] == 'ok'

    @pytest.mark.parametrize('offset,expected',
                             [(500.0, 'ok'), (5000.0, 'warn'),
                              (120000.0, 'vslow'), (None, 'stale')])
    def test_the_clock_columns_follow_the_offset(self, pb, tmp_path, offset,
                                                 expected):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        app.stale_attr = 0
        m = app.monitors[0]
        m.alive, m.up_since, m.latency = True, time.monotonic() - 60, 5.0
        m.clock_offset_ms = offset
        m.clock_state = 'ok' if offset is not None else 'idle'
        assert app._stat_class(m, 'Drift') == expected
        assert app._stat_class(m, 'RTime') == expected

    def test_an_errored_host_is_marked_everywhere(self, pb, tmp_path):
        app, m = self._with_reading(pb, tmp_path, 10.0)
        m.error = 'ssh: permission denied'
        classes = app._web_state()['rows'][0]['stat_class']
        assert set(classes.values()) == {'error'}

    def test_a_down_cell_is_marked(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        m = app.monitors[0]
        m.alive, m.down_since = False, time.monotonic() - 20
        app._dispatch_cmd(':set stats down')
        assert app._web_state()['rows'][0]['stat_class']['Down'] == 'error'

    def test_events_carry_the_class_the_terminal_would_paint(self, pb,
                                                             tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        app._dispatch_cmd(':set log-level debug')
        app.add_event('warn', 'warning: something')
        app.add_event('save', 'error: nope')
        app.add_event('bind-key', 'chatter')
        events = app._web_state()['events']

        def cls_of(message):
            hits = [e['cls'] for e in events if e['text'].endswith(message)]
            assert hits, f'{message!r} not in {[e["text"] for e in events]}'
            return hits[-1]

        assert cls_of('warning: something') == 'warn'
        assert cls_of('error: nope') == 'error'
        assert cls_of('chatter') == 'dim'

    def test_stat_class_covers_every_column_stat_attr_does(self, pb):
        """The guard that would have caught the gap this test was added for.

        `_stat_class` shipped mirroring five of `_stat_attr`'s seven branches.
        'Last' and 'Drift'/'RTime' fell through to no class — and since the
        default stats mode maps to a single 'Last' column, *every* row in the
        browser had an uncoloured latency cell while the terminal coloured it
        three ways, red included for "no reply".

        Comparing the column names each function names is what catches the
        next one; the value tests below only cover the branches somebody
        thought to write.
        """
        import inspect
        import re

        def columns_named(func):
            src = inspect.getsource(func)
            names = set(re.findall(r"cname == '([A-Za-z%]+)'", src))
            for group in re.findall(r"cname in \(([^)]*)\)", src):
                names |= set(re.findall(r"'([A-Za-z%]+)'", group))
            return names

        attr = columns_named(pb.Application._stat_attr)
        cls = columns_named(pb.Application._stat_class)
        assert attr, 'the parser found nothing — it has stopped working'
        assert attr <= cls, f'_stat_class ignores {sorted(attr - cls)}'

    def test_the_class_helper_sits_beside_the_curses_one(self, pb):
        """Twins, so neither can be changed without seeing the other."""
        import inspect
        lines = inspect.getsource(pb).splitlines()
        at = {name: i for i, line in enumerate(lines)
              for name in ('_stat_class', '_stat_attr', '_event_class',
                           '_event_color_attr')
              if line.startswith(('def ' + name, '    def ' + name))}
        # Adjacent definitions, not a character distance: an unrelated
        # insertion between them is exactly what must fail this.
        between = [i for i in range(min(at['_stat_class'], at['_stat_attr']) + 1,
                                    max(at['_stat_class'], at['_stat_attr']))
                   if lines[i].startswith('    def ')]
        assert not between, f'something moved in between: {between}'
        assert abs(at['_event_class'] - at['_event_color_attr']) < 40
