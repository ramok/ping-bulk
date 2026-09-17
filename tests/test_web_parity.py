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
            # The row's own width, not the view's.  Dividing by the view's
            # width is what this test used to do, and it passed only because
            # the default view happens to be one column wide.
            assert len(r['hist_class']) == len(r['history']) // r['cell_width']

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


# ===========================================================================
# A folded section summarises hosts the viewer cannot see
# ===========================================================================

def _folded_section(pb, tmp_path, slots):
    """An app with one folded section of len(slots[0]) hosts and known history.

    *slots* is a list of per-slot tuples, one entry per host, using the raw
    history encoding: a float is a reply, None is a lost probe, 'ERR' is a
    process error.
    """
    import time
    n = len(slots[0])
    hosts = ''.join(f'10.0.0.{i + 1}\n' for i in range(n))
    app = _app(pb, tmp_path, ':title Site\n' + hosts)
    now = time.time()
    monitors = [e for e in app.entries if isinstance(e, pb.Monitor)]
    for host_i, m in enumerate(monitors):
        m.history.clear()
        m.history_times.clear()
        for slot_i, per_host in enumerate(slots):
            m.history.append(per_host[host_i])
            m.history_times.append(now - (len(slots) - slot_i))
    for label in [e for e in app.entries if isinstance(e, pb.SectionLabel)]:
        label.folded = True
    return app, monitors


def _section_row(app, **kw):
    state = app._web_state(**kw)
    return next(r for r in state['rows'] if r['kind'] == 'section'), state


class TestAPartlyLostSlotIsNotATotalLoss:
    """``slot_ok_ratios`` is the whole reason a section strip differs from a
    host strip, and the serializer threw it away.

    The terminal paints an ``'X'`` **yellow** when more than half the hidden
    hosts replied in that slot — the section is degraded, not down. Discarding
    the ratios made every lost slot red, so a section two thirds of which was
    answering read in the browser exactly like one that was entirely dead.
    """

    @pytest.fixture
    def rows(self, pb, tmp_path):
        # Appended oldest-first, but the strip puts the NEWEST sample on the
        # left (AGENTS.md §8, Phase 22), so the last row here is cell 0.
        #   cell 0 <- two of three replied -> 0.67, mostly fine -> yellow
        #   cell 1 <- one of three replied -> 0.33, a real outage -> red
        app, _ = _folded_section(pb, tmp_path, [
            (12.0, None, None),
            (12.0, 12.0, None),
        ])
        return _section_row(app, history_len=10)

    def test_both_slots_are_a_lost_probe(self, rows):
        """Otherwise the test below is comparing two different glyphs."""
        row, _ = rows
        assert row['history'][:2] == 'XX'

    def test_the_two_slots_do_not_get_the_same_colour(self, rows):
        """The discriminating assertion: identical glyphs, different readings.

        If ``slot_ok_ratios`` is ever dropped again — or stubbed to a constant —
        both cells collapse to one class and this fails.  An assertion that
        merely compared ``hist_class`` against ``_section_cell_classes`` could
        not: it would be comparing the function with itself.
        """
        row, _ = rows
        assert row['hist_class'][0] != row['hist_class'][1]

    def test_the_mostly_ok_slot_is_the_yellow_one(self, rows):
        row, _ = rows
        assert row['hist_class'][0] == 'g-partial'   # newest: 2 of 3 replied
        assert row['hist_class'][1] == 'g-bad'       # older:  1 of 3 replied


class TestASectionStripIsOneCellPerSlot:
    """A section strip is built at ``cell_width=1`` whatever the view shows.

    ``_web_state`` handed it the *view's* width, so under ':set ping-view rtt'
    a ten-slot strip was cut into four cells while the host rows beside it drew
    ten — the folded section was out of step with the rows it summarises, which
    is a misalignment rather than a wrong colour.
    """

    @pytest.fixture
    def app(self, pb, tmp_path):
        app, _ = _folded_section(pb, tmp_path, [(12.0, None)] * 4)
        return app

    def test_the_row_declares_its_own_width(self, app, pb):
        row, _ = _section_row(app, history_len=10)
        assert row['cell_width'] == pb.Application.SECTION_STRIP_CELL_WIDTH == 1

    def test_one_class_per_character_even_in_a_wide_view(self, app, pb):
        app.history_mode = pb.HISTORY_MODES.index('rtt')
        row, state = _section_row(app, history_len=10)
        assert state['view']['cell_width'] > 1, 'rtt should widen the view'
        assert len(row['hist_class']) == len(row['history']) == 10

    def test_host_rows_still_follow_the_view(self, app, pb):
        """The section is the exception; the fix must not flatten everything."""
        for label in [e for e in app.entries if isinstance(e, pb.SectionLabel)]:
            label.folded = False        # a folded section hides its hosts
        app.history_mode = pb.HISTORY_MODES.index('rtt')
        state = app._web_state(history_len=10)
        host = next(r for r in state['rows'] if r['kind'] == 'host')
        assert host['cell_width'] == state['view']['cell_width'] > 1
        assert len(host['hist_class']) == len(host['history']) // host['cell_width']


class TestTheBadgeKeepsItsColours:
    """``_web_state`` kept only the badge text, and the page's one ``.badge``
    rule then painted every count dim — so "1 up, 2 down" arrived as grey and
    grey, which is the single distinction a badge exists to make.
    """

    @pytest.fixture
    def parts(self, pb, tmp_path):
        app, monitors = _folded_section(pb, tmp_path, [(12.0, None, None)])
        monitors[0].alive = True
        monitors[1].alive = False
        monitors[2].alive = False
        return app, monitors

    def test_a_count_carries_the_class_for_its_colour(self, parts):
        app, _ = parts
        row, _ = _section_row(app, history_len=10)
        classes = {seg['text']: seg['class'] for seg in row['badge']}
        assert classes.get('1↑') == 'b-up'
        assert classes.get('2↓') == 'b-down'

    def test_the_separator_is_left_classless(self, parts):
        """Pair id 0.  With parallel arrays it is one off-by-one from
        inheriting the colour of the count before it, which would read as a
        third status."""
        app, _ = parts
        row, _ = _section_row(app, history_len=10)
        assert [seg['class'] for seg in row['badge'] if seg['text'] == '/'] == ['']

    def test_an_errored_member_bolds_the_count_the_terminal_bolds(self, parts):
        """draw_hosts bolds pairs 2 and 3 when any member has an error: a host
        that is down and a host whose ping process died are not the same
        report.  b-err is a weight, so it composes rather than replacing."""
        app, monitors = parts
        row, _ = _section_row(app, history_len=10)
        assert 'b-err' not in ' '.join(seg['class'] for seg in row['badge'])

        monitors[1].error = 'ping: command not found'
        row, _ = _section_row(app, history_len=10)
        down = next(seg for seg in row['badge'] if seg['text'] == '2↓')
        assert down['class'] == 'b-down b-err'

    def test_the_client_renders_segments_rather_than_joining_them(self, pb):
        """A structural guard: `.join(' ')` on the texts throws the classes
        away again, and it is the obvious thing to write."""
        js = pb._WEB_JS
        assert 'badge.join' not in js, 'the badge is per-segment now'
        assert 'function badge(' in js

    def test_every_class_the_server_emits_is_styled(self, pb):
        """A class with no CSS rule is an invisible regression: the cell simply
        inherits, which looks like the bug this commit fixes."""
        css = pb._WEB_CSS
        emitted = set(pb.Application._BADGE_CLASSES.values()) | {
            'b-err', 'g-partial', 'g-err'}
        missing = sorted(c for c in emitted if f'.{c} ' not in css)
        assert not missing, f'emitted but unstyled: {missing}'


class TestTheStripSummarisesOnlyWhatFoldingHid:
    """The badge counts every host; the strip summarises the *hidden* ones.

    Those are different sets whenever a folded section holds an **unfolded**
    subsection — that subsection's hosts are drawn in their own right, so a
    summary that repeats them answers the wrong question. ``draw_hosts`` passes
    ``history_monitors=_get_hidden_section_monitors(...)`` for exactly this;
    ``_web_state`` did not.

    It cost nothing while every lost slot was painted the same red. It began to
    cost a wrong reading the moment the ``> 0.5`` branch became reachable,
    which is what the commit before this one did: the browser could call a
    section degraded where the terminal calls it down.
    """

    @pytest.fixture
    def app(self, pb, tmp_path):
        import time
        # '##'/'###' is what nests sections; ':title' has no level flag, and
        # writing one puts the flag text in the title instead.
        app = _app(pb, tmp_path,
                   '## Parent\n10.0.0.1\n10.0.0.2\n'
                   '### Child\n10.0.0.3\n')
        now = time.time()
        # One slot: .1 lost it, .2 and .3 replied.  Hidden hosts alone are
        # .1 and .2 -> 0.50, not a majority -> red.  Counting .3 as well gives
        # 0.67 -> yellow, which is the bug.
        for m, value in zip([e for e in app.entries if isinstance(e, pb.Monitor)],
                            [None, 12.0, 12.0]):
            m.history.clear()
            m.history_times.clear()
            m.history.append(value)
            m.history_times.append(now - 1)
        labels = [e for e in app.entries if isinstance(e, pb.SectionLabel)]
        labels[0].folded = True     # Parent folds ...
        labels[1].folded = False    # ... Child stays open, so .3 is on screen
        return app

    def test_the_two_host_sets_really_do_differ(self, app, pb):
        """Otherwise the assertion below proves nothing."""
        idx = next(i for i, e in enumerate(app.entries)
                   if isinstance(e, pb.SectionLabel))
        assert len(app._get_section_monitors(idx)) == 3
        assert len(app._get_hidden_section_monitors(idx)) == 2

    def test_a_half_lost_slot_is_not_called_degraded(self, app):
        row, _ = _section_row(app, history_len=1)
        assert row['history'] == 'X'
        assert row['hist_class'] == ['g-bad'], (
            'the strip counted a host the viewer can already see, which '
            'turned an even split into a majority'
        )


class TestAProcessErrorIsNotAPlainLoss:
    """The terminal bolds ``'?'`` apart from ``'X'``: a host that lost a probe
    and a host whose ping process failed are not the same report. Both reached
    the browser as ``g-bad``."""

    def test_an_errored_slot_gets_its_own_class(self, pb, tmp_path):
        app, _ = _folded_section(pb, tmp_path, [('ERR', 'ERR')])
        row, _ = _section_row(app, history_len=1)
        assert row['history'] == '?'
        assert row['hist_class'] == ['g-err']


class TestTheNameColumnIsSizedFromItsContent:
    """A fixed 24em was a guess: too wide for a list of IPs, too narrow for
    long names. The terminal sizes this column from what is in it, and now so
    does the browser."""

    def test_short_names_get_a_narrow_column(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n10.0.0.2\n')
        assert app._web_state()['view']['name_width'] == len('Hostname')

    def test_a_longer_name_widens_it(self, pb, tmp_path):
        app = _app(pb, tmp_path, 'a-rather-long-host-name.example.com\n')
        assert app._web_state()['view']['name_width'] == \
            len('a-rather-long-host-name.example.com')

    def test_a_relayed_name_is_not_cut(self, pb, tmp_path):
        """A relayed host draws its whole jump chain, which runs well past any
        plain hostname. The first cap was 48 and cut exactly this."""
        name = 'ses-wg-video \u2192 proxmox \u2192 nray-set2-slave (10.123.254.1)'
        app = _app(pb, tmp_path, '10.0.0.1\n')
        app.entries[0].host = name
        assert app._web_state()['view']['name_width'] >= len(name)

    def test_a_long_section_title_cannot_take_the_row(self, pb, tmp_path):
        """The sanity bound still exists. The binding limit is the client's
        max-width, which is a share of the real window; this only stops a
        hosts file with an absurd title in it."""
        app = _app(pb, tmp_path, '## ' + 'T' * 300 + '\n10.0.0.1\n')
        assert app._web_state()['view']['name_width'] == pb._WEB_MAX_NAME_COLS

    def test_a_folded_section_does_not_widen_it(self, pb, tmp_path):
        """Hosts nobody can see must not size a column for the ones they can.
        Measuring from the emitted rows gets this for free — they are not in
        the payload — which is the other reason not to reuse the terminal's
        cached helper."""
        app = _app(pb, tmp_path,
                   '## S\nshort\n' + 'x' * 40 + '.example.com\n')
        wide = app._web_state()['view']['name_width']
        for label in [e for e in app.entries if isinstance(e, pb.SectionLabel)]:
            label.folded = True
        assert app._web_state()['view']['name_width'] < wide

    def test_reading_the_state_still_mutates_nothing(self, pb, tmp_path):
        """_get_name_col_width caches into _name_col_cache and clears
        _name_col_dirty. _web_state runs on the server thread under a promise
        not to mutate, and the first cut of this feature broke it."""
        app = _app(pb, tmp_path, '## S\n10.0.0.1\n')
        before = dict(app.__dict__)
        app._web_state()
        assert dict(app.__dict__) == before


class TestTheStripFillsTheWindow:
    """It was a fixed 60 cells, so a wide window had dead space after it and a
    narrow one cut the strip off. The client now says how many fit."""

    @pytest.mark.parametrize('query,expected', [
        ('',              60),      # a client that says nothing is unchanged
        ('cols=120',     120),
        ('t=x&cols=200', 200),      # not the first parameter
        ('cols=99999',   600),      # clamped: the ceiling is the server's
        ('cols=-5',        8),
        ('cols=abc',      60),      # garbage falls back, never raises
        ('cols=',         60),
        ('colsx=9',       60),      # not our parameter
    ])
    def test_the_request_is_parsed_and_clamped(self, pb, query, expected):
        assert pb._web_history_cols(query) == expected

    def test_the_ceiling_is_the_servers_alone(self, pb, tmp_path):
        """The number sizes a payload built on every poll from a value the
        client supplies. §9d's own history is an unauthenticated client
        manufacturing work at 1117/s; clamping in the page would be no clamp.

        Asserted against the strip that actually comes back, and against an
        absolute bound — comparing the parser's output to the constant it
        divides by would pass for any ceiling, including none.
        """
        app = _app(pb, tmp_path, '10.0.0.1\n')
        asked = pb._web_history_cols('cols=10000000')
        assert asked <= 2000
        got = app._web_state(history_len=asked)['rows'][0]['history']
        assert len(got) == asked <= 2000

    def test_asking_for_more_gets_more(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        short = app._web_state(history_len=20)['rows'][0]['history']
        long_ = app._web_state(history_len=90)['rows'][0]['history']
        assert len(short) == 20 and len(long_) == 90

    def test_the_client_asks_for_what_fits(self, pb):
        """Only that the machinery exists. What it *does* — correcting the
        width without waiting out a poll, and then settling — is asserted by
        running the real client, in
        test_web_assets.TestTheMeasuredWidthIsAskedForAtOnce."""
        assert 'function measureCols' in pb._WEB_JS

    def test_the_strip_width_does_not_depend_on_its_text(self, pb):
        """The loop only settles because the element's width is the space the
        other columns leave. With `flex: 1 1 auto` the new text would resize
        it, which would change the next request, for ever."""
        css = pb._WEB_CSS
        block = css[css.index('.strip {'):]
        block = block[:block.index('}')]
        assert 'flex: 1 1 0' in block, block
        assert 'min-width: 0' in block, block

    def test_it_does_not_ask_again_once_it_has_settled(self, pb):
        """Rounding at the edge of a fractional character width would
        otherwise flip the request back and forth every poll. The behaviour is
        pinned by the node harness (test_web_assets); this only keeps the
        deadband from being deleted as redundant-looking arithmetic."""
        assert 'wantCols' in pb._WEB_JS and '< 2' in pb._WEB_JS


class TestAHostIsIndentedUnderItsSection:
    """The terminal indents a host by its section's level (the `indent =
    level * 2` in `_get_name_col_width`). The browser drew section titles
    stepping right and left every host flush against the edge."""

    def test_the_payload_carries_each_hosts_level(self, pb, tmp_path):
        app = _app(pb, tmp_path,
                   '## One\n10.0.0.1\n### Two\n10.0.0.2\n#### Three\n10.0.0.3\n')
        rows = app._web_state()['rows']
        got = [(r['kind'], r.get('level')) for r in rows]
        assert got == [('section', 1), ('host', 1),
                       ('section', 2), ('host', 2),
                       ('section', 3), ('host', 3)], got

    def test_a_host_outside_any_section_is_level_zero(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        assert app._web_state()['rows'][0]['level'] == 0

    def test_the_level_follows_the_most_recent_title(self, pb, tmp_path):
        """Entries are in order, so the last label seen is the immediate
        parent — the same reading `_get_name_col_width` takes from its stack.
        A host after a nested section belongs to that one, not its parent."""
        app = _app(pb, tmp_path, '## Outer\n### Inner\n10.0.0.1\n')
        host = next(r for r in app._web_state()['rows'] if r['kind'] == 'host')
        assert host['level'] == 2


class TestAnAnonymousViewerCanStillSeeAHostsEvents:
    """The host pane ended after the readings, with no 'Recent events'.

    Reported as "looks like frame window cut from buttom", and it was not a
    layout bug: ``_WEB_ANON_WITHHELD`` drops ``events`` for a viewer with no
    session, because ``_host_event_lines`` is **not** level-filtered and would
    hand them the debug lines the global tail withholds.  So the section was
    absent from the payload and the pane simply stopped early.

    Nothing has to be un-redacted to fix it.  ``/api/state``'s tail is already
    sent anonymously, is already level-filtered, and carries the category each
    line was filed under — so the client can pick one host's lines out of what
    it already holds.  That is *less* exposure than the redaction it replaces,
    not more.

    ``event_key`` is what makes it possible: ``name`` follows the current
    ``:set dns`` and the category does not.
    """

    def test_the_key_is_the_category_host_events_are_filed_under(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n10.0.0.2 ##friendly-name\n')
        for monitor in app.monitors:
            app.add_event(monitor.get_display_name(dns_mode='off'), 'is down')

        tail = app._web_state()['events']
        for monitor in app.monitors:
            data = app._web_host_detail(monitor.uid)
            picked = [e['text'] for e in tail if e['category'] == data['event_key']]
            assert picked == data['events'], (
                'the client-side filter must select the same lines the '
                "terminal's own host pane shows: " + repr(data['event_key']))

    def test_the_key_survives_a_dns_mode_the_name_follows(self, pb, tmp_path):
        """``name`` is rendered with ``DNS_MODES[self.dns_mode]``, so it moves
        when the console operator presses ``D`` — and the category does not.
        Keying the filter on ``name`` would empty every host's pane the moment
        somebody else changed a shared setting."""
        app = _app(pb, tmp_path, '10.0.0.1\n')
        monitor = app.monitors[0]
        monitor.resolved_hostname = 'named.example'
        keys, names = set(), set()
        for mode in range(len(pb.DNS_MODES)):
            app.dns_mode = mode
            data = app._web_host_detail(monitor.uid)
            keys.add(data['event_key'])
            names.add(data['name'])
        # Without this the test passes on a fixture where nothing moved, which
        # is how a guard becomes decoration.
        assert len(names) > 1, 'the fixture must actually exercise :set dns'
        assert len(keys) == 1, 'event_key must not follow :set dns: ' + repr(keys)

    def test_the_redaction_is_untouched(self, pb, tmp_path):
        """The point of the change is that it buys the events back *without*
        widening what an anonymous viewer is sent."""
        app = _app(pb, tmp_path, '10.0.0.1\n')
        uid = app.monitors[0].uid
        anon = app._web_host_detail(uid, redacted=True)
        leaked = [f for f in app._WEB_ANON_WITHHELD if f in anon]
        assert not leaked, leaked
        assert 'event_key' in anon, 'the key itself must still reach the client'
