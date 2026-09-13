"""The browser and the terminal must agree about the same screen.

Two ways they did not, both silent — a miscoloured cell and a wrong-but-
plausible command look exactly like correct output:

**The strip was coloured per character, by the ping palette.**  Right for the
one-column modes and wrong for every wide cell, because a wide cell holds a
*reading*: '49 ' drew green-then-yellow where the terminal paints the cell
green, '120 ' drew entirely green where the terminal paints it yellow, and a
probe reading of 82 against ``--warn 60 --crit 80`` drew '8' yellow and '2'
green where the terminal paints the cell red.  That last one is AGENTS.md §8's
Phase 22 bug — a sensor judged by a latency scale — reappearing in the
browser, in the commit whose subject said it was fixed.

**``connect`` was built from the console operator's cursor.**  Every host in
the browser was shown the same command, and on a fresh run — where
``highlighted_index`` is None — every host showed "disabled".  The write path
addresses hosts by uid precisely so that a cursor somebody else moves cannot
steer it (§9d); the read path still consulted it.
"""

import os
import tempfile

import pytest
from unittest.mock import patch


def _app(pb, tmp_path, content='10.0.0.1\n10.0.0.2\n'):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    hosts = tmp_path / 'p.hosts'
    hosts.write_text(content)
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application(pb.parse_hosts_file(str(hosts)))
    app._monitoring_started = True
    return app


# ===========================================================================
# The history strip
# ===========================================================================

class TestWideCellsAreJudgedWhole:
    @pytest.fixture
    def app(self, pb, tmp_path):
        return _app(pb, tmp_path)

    @pytest.mark.parametrize('cell,expected', [
        ('49  ', 'g-ok'),     # under 50 — green, and it used to split
        ('50  ', 'g-late'),   # the boundary the terminal uses
        ('120 ', 'g-late'),   # drew ALL green per character: '1','2','0' <= '4'
        ('7   ', 'g-ok'),     # drew yellow per character
        ('X   ', 'g-bad'),
        ('?   ', 'g-bad'),
        ('>   ', 'g-late'),
        ('_   ', 'g-quiet'),
        ('o   ', 'g-quiet'),
        ('    ', 'g-none'),
    ])
    def test_an_rtt_cell_takes_one_class(self, app, cell, expected):
        assert app._history_cell_classes(cell, 4, None, 'rtt') == [expected]

    def test_a_scaled_cell_uses_the_scaled_threshold(self, app):
        assert app._history_cell_classes('4   ', 4, None, 'scaled') == ['g-ok']
        assert app._history_cell_classes('5   ', 4, None, 'scaled') == ['g-late']

    def test_one_class_per_cell_not_per_character(self, app):
        hist = '120 87  49  '
        assert app._history_cell_classes(hist, 4, None, 'rtt') == \
            ['g-late', 'g-late', 'g-ok']

    def test_one_column_modes_are_unchanged(self, app):
        hist = '.xX?>_o '
        assert app._history_cell_classes(hist, 1, None, 'success') == \
            ['g-ok', 'g-late', 'g-bad', 'g-bad', 'g-vslow',
             'g-quiet', 'g-quiet', 'g-none']

    def test_digits_still_split_when_a_cell_is_one_column(self, app):
        assert app._history_cell_classes('0459', 1, None, 'scaled') == \
            ['g-ok', 'g-ok', 'g-late', 'g-late']


class TestAProbeIsJudgedByItsOwnThresholds:
    @pytest.fixture
    def app(self, pb, tmp_path):
        return _app(pb, tmp_path)

    @pytest.fixture
    def probe(self, pb):
        p = pb.ProbeDef('sig')
        p.warn, p.crit = 60, 80
        return p

    @pytest.mark.parametrize('value,expected', [
        (0, 'g-ok'), (59, 'g-ok'), (60, 'g-late'), (79, 'g-late'),
        (80, 'g-bad'), (82, 'g-bad'), (999, 'g-bad'),
    ])
    def test_the_class_follows_warn_and_crit(self, app, probe, value, expected):
        assert app._probe_strip_class(probe, value) == expected

    def test_the_cell_is_judged_by_value_not_by_its_digits(self, app, probe):
        """82 is red; per character it was '8' yellow then '2' green."""
        assert app._history_cell_classes('82  ', 4, probe, 'rtt') == ['g-bad']

    def test_a_probe_with_no_thresholds_is_never_late(self, app, pb):
        bare = pb.ProbeDef('gpssat')
        bare.warn = bare.crit = None
        # 28 satellites out of 32 drew yellow for being good, because '8' is
        # in the ping palette's slow half.  Nothing about a probe reaches that.
        assert app._history_cell_classes('28  ', 4, bare, 'rtt') == ['g-ok']
        assert app._history_cell_classes('31  ', 4, bare, 'rtt') == ['g-ok']

    def test_it_mirrors_the_curses_twin_across_the_range(self, app, probe, pb):
        """Compared by value, not by which branches somebody remembered."""
        import curses
        bits = {1: 1 << 4, 2: 1 << 5, 3: 1 << 6}
        name = {1 << 4: 'g-ok', 1 << 5: 'g-bad', 1 << 6: 'g-late'}
        with patch.object(curses, 'color_pair', lambda n: bits.get(n, 0)), \
             patch.object(curses, 'A_BOLD', 1):
            for value in range(0, 120):
                attr = app._probe_strip_attr(probe, value, 0)
                drawn = next(v for bit, v in name.items() if attr & bit)
                assert app._probe_strip_class(probe, value) == drawn, value


class TestTheServerDecidesTheColour:
    def test_the_payload_carries_a_class_for_every_cell(self, pb, tmp_path):
        app = _app(pb, tmp_path)
        state = app._web_state(history_len=20)
        rows = [r for r in state['rows'] if r['kind'] == 'host']
        assert rows
        width = state['view']['cell_width']
        for r in rows:
            assert len(r['hist_class']) == len(r['history']) // width

    def test_section_rows_carry_one_too(self, pb, tmp_path):
        app = _app(pb, tmp_path, ':title Site\n10.0.0.1\n10.0.0.2\n')
        state = app._web_state(history_len=20)
        sections = [r for r in state['rows'] if r['kind'] == 'section']
        assert sections
        for r in sections:
            assert r['hist_class']
            assert len(r['hist_class']) == \
                len(r['history']) // state['view']['cell_width']

    def test_the_client_no_longer_classifies_characters_itself(self, pb):
        """The whole point: one implementation of the rule, next to the other."""
        js = pb._WEB_JS
        assert 'glyphClass' not in js
        assert 'hist_class' in js

    def test_the_class_helper_sits_beside_the_curses_one(self, pb):
        import inspect
        lines = inspect.getsource(pb).splitlines()
        at = {n: i for i, line in enumerate(lines)
              for n in ('_probe_strip_class', '_probe_strip_attr')
              if line.startswith('    def ' + n)}
        assert len(at) == 2
        between = [i for i in range(min(at.values()) + 1, max(at.values()))
                   if lines[i].startswith('    def ')]
        assert not between, f'something moved in between: {between}'


class TestANegativeReadingKeepsTheGrid:
    """A cell wider than its slot shifts every cell after it in the row.

    ``:probe rssi --range -100:0`` is an ordinary radio config — dBm is
    negative — and the width came from ``vmax`` alone, so it sized to two
    columns and then wrote ``-58`` into them.  The grid the reader slices by
    stopped lining up with the samples, and a boundary could land on a lone
    ``-``: ``int('-')`` raises.  ``draw_hosts`` raises there too and loses a
    frame; the serializer runs per poll, where it is a 500 for every browser
    every two seconds.  Temperature and clock drift have the same shape.
    """

    @pytest.fixture
    def app(self, pb, tmp_path):
        return _app(pb, tmp_path, '10.0.0.1\n')

    @pytest.fixture
    def rssi(self, pb):
        return pb.ProbeDef('rssi', vmin=-100, vmax=0, warn=-70, crit=-85)

    def test_the_width_allows_for_the_sign(self, app, rssi):
        assert app._probe_cell_width(rssi) >= len('-100') + 1

    def test_the_strip_is_an_exact_number_of_cells(self, app, rssi):
        width = app._probe_cell_width(rssi)
        strip = self._strip(app, rssi, [-60, -72, -58], width)
        assert len(strip) % width == 0

    def test_every_cell_gets_a_class(self, app, rssi):
        width = app._probe_cell_width(rssi)
        strip = self._strip(app, rssi, [-60, -72, -58], width)
        classes = app._history_cell_classes(strip, width, rssi, 'rtt')
        assert len(classes) == len(strip) // width

    def test_a_reading_too_wide_for_its_slot_is_clamped_not_overflowed(
            self, app, pb):
        """The invariant holds even if the width calculation is wrong."""
        narrow = pb.ProbeDef('x', vmin=0, vmax=9)
        width = app._probe_cell_width(narrow)
        strip = self._strip(app, narrow, [-12345, 99999], width)
        assert len(strip) % width == 0
        for i in range(0, len(strip), width):
            assert len(strip[i:i + width]) == width

    def test_an_unparseable_cell_is_uncoloured_rather_than_fatal(self, app, rssi):
        assert app._history_cell_classes('-   ', 4, rssi, 'rtt') == ['g-none']
        assert app._history_cell_classes('--  ', 4, None, 'rtt') == ['g-none']

    @staticmethod
    def _strip(app, probe, values, width):
        class Series:
            pass
        series = Series()
        series.values = values
        monitor = app.monitors[0]
        monitor.probes = {probe.name: series}
        return app._probe_history_string(monitor, probe, 5, 0, width)


# ===========================================================================
# The connect command
# ===========================================================================

RELAYED = 'router-a\nrouter-b\n:remote-ping relay1 behind-the-relay\n'


class TestConnectNamesTheHostThatWasAskedFor:
    @pytest.fixture
    def app(self, pb, tmp_path):
        return _app(pb, tmp_path, RELAYED)

    def _monitors(self, pb, app):
        return [e for e in app.entries if isinstance(e, pb.Monitor)]

    def test_it_does_not_move_with_the_cursor(self, pb, app):
        """The test this replaces compared _connect_preview to itself."""
        mons = self._monitors(pb, app)
        answers = []
        for cursor in [None] + list(range(len(app.entries))):
            app.highlighted_index = cursor
            answers.append([app._connect_preview(m) for m in mons])
        assert all(a == answers[0] for a in answers), answers

    def test_a_fresh_run_is_not_all_disabled(self, pb, app):
        """highlighted_index is None at startup, which returned None for all."""
        app.highlighted_index = None
        for m in self._monitors(pb, app):
            assert app._connect_preview(m), m.host

    def test_each_host_gets_its_own_command(self, pb, app):
        app.highlighted_index = None
        got = {m.host: app._connect_preview(m)
               for m in self._monitors(pb, app)}
        assert got['router-a'] == 'ssh router-a'
        assert got['router-b'] == 'ssh router-b'
        relayed = [v for k, v in got.items() if 'behind-the-relay' in k][0]
        assert '-J relay1' in relayed

    def test_a_plain_host_is_not_wrapped_in_another_hosts_relay(self, pb, app):
        """With the cursor on the relayed row, router-a came back as
        'ssh -t relay1 ssh router-a' — a relay it has nothing to do with."""
        idx = next(i for i, e in enumerate(app.entries)
                   if isinstance(e, pb.SshPingMonitor))
        app.highlighted_index = idx
        plain = next(m for m in self._monitors(pb, app)
                     if m.host == 'router-a')
        assert app._connect_preview(plain) == 'ssh router-a'

    def test_the_details_payload_agrees_with_the_overlay(self, pb, app):
        """Both format from _details_data, so this pins the shared source."""
        app.highlighted_index = None
        for m in self._monitors(pb, app):
            assert app._details_data(m)['connect'] == app._connect_preview(m)
