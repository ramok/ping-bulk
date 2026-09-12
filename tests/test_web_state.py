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

    def test_folding_hides_rows_exactly_as_the_terminal_does(self, pb,
                                                             tmp_path):
        app = _app(pb, tmp_path, BASE)
        assert len(app._web_state()['rows']) == 4     # section + 3 hosts
        app.entries[0].folded = True
        assert len(app._web_state()['rows']) == len(
            app._get_visible_entry_indices())

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

        def stale():
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
