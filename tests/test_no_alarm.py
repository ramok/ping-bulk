"""Unit tests for ':no-alarm' — hosts where a lost reply is expected.

For a device that is normally switched off, or one that drops ICMP: a red 'X'
per second and a permanently red section header is noise, not information.

Presentation only.  'alive' stays factual — it is read in some two dozen
places and feeds loss statistics, recovery detection and the clock probe — so
a marked host is still down, just not alarming.
"""

import os
from collections import deque
from unittest.mock import patch

import pytest

from utils.hosts_helper import write_hosts


def _app(pb, tmp_path, entries):
    cfg = tmp_path / 'ping-bulk' / 'config'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('')
    with patch.object(pb, '_config_path', return_value=str(cfg)):
        a = pb.Application(entries)
    a._monitoring_started = True
    a._cfg_path = str(cfg)
    return a


def _names(app):
    return {(app._prog_match_names(m)[1] or app._prog_match_names(m)[0]): m.no_alarm
            for m in app.monitors}


# ---------------------------------------------------------------------------
# The glyph
# ---------------------------------------------------------------------------

class TestHistoryGlyph:
    """A distinct symbol, not only a colour.

    Colour alone is lost in a screenshot, in a log, and to anyone colourblind
    — and a grey 'X' still reads as "lost" at a glance.
    """

    def _monitor(self, pb, no_alarm):
        m = pb.PingMonitor('h')
        m.history = deque([1.0, None, None, 2.0])
        m.no_alarm = no_alarm
        m.stop()
        return m

    def test_unmarked_host_shows_x(self, pb):
        assert self._monitor(pb, False).get_history_string(length=4) == '.XX.'

    def test_marked_host_shows_o(self, pb):
        assert self._monitor(pb, True).get_history_string(length=4) == '.oo.'

    def test_replies_are_unchanged(self, pb):
        """Only the miss changes meaning; a reply is still a reply."""
        bar = self._monitor(pb, True).get_history_string(length=4)
        assert bar.count('.') == 2

    def test_rtt_mode_fills_the_cell(self, pb):
        bar = self._monitor(pb, True).get_history_string(
            length=4, mode='rtt', cell_width=3)
        assert 'oo ' in bar, repr(bar)

    def test_process_error_still_shows(self, pb):
        """An 'o' means "expected silence", not "ignore this host"."""
        m = pb.PingMonitor('h')
        m.history = deque(['ERR'])
        m.no_alarm = True
        m.stop()
        assert m.get_history_string(length=1) == '?'

    def test_char_helper_is_explicit(self, pb):
        assert pb._history_char(None, 'success') == 'X'
        assert pb._history_char(None, 'success', no_alarm=True) == 'o'


# ---------------------------------------------------------------------------
# Marking in a hosts file
# ---------------------------------------------------------------------------

class TestMarkingInAScript:

    def test_glob_rule(self, pb, tmp_path):
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':no-alarm *-power-switch\n'
            '10.0.0.1 ## core-router\n'
            '10.0.0.2 ## sh1-power-switch\n'))
        assert _names(app) == {'core-router': False, 'sh1-power-switch': True}

    def test_a_rule_may_follow_the_hosts_it_names(self, pb, tmp_path):
        """The flag is applied after the whole entry list, not line by line."""
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            '10.0.0.2 ## sh1-power-switch\n'
            ':no-alarm *-power-switch\n'))
        assert _names(app)['sh1-power-switch'] is True

    def test_tilde_prefix(self, pb, tmp_path):
        app = _app(pb, tmp_path, pb._HostsParser().parse('~10.0.0.50\n'))
        assert _names(app)['10.0.0.50'] is True

    def test_tilde_with_an_inline_label(self, pb, tmp_path):
        """The host entry becomes the label, so the rule must name the label.

        A rule naming the IP would never match, since that is not what the
        monitor ends up called.
        """
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            '~10.0.0.42 ## blocked-cam\n'))
        assert _names(app)['blocked-cam'] is True

    def test_tilde_combines_with_the_optional_marker(self, pb, tmp_path):
        """'?' and '~' are independent, in either order."""
        for line in ('~?10.0.0.9\n', '?~10.0.0.9\n'):
            entries = pb._HostsParser().parse(line)
            assert any(e[0] == 'cmd' and e[1] == ':no-alarm 10.0.0.9'
                       for e in entries), line
            assert any(e[0] == 'optional_host' for e in entries), line

    def test_with_block(self, pb, tmp_path):
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':with no-alarm\n'
            '    *-nuc\n'
            '    *-cam*\n'
            ':end\n'
            '10.0.0.3 ## sh3-nuc\n'
            '10.0.0.4 ## sh1-cam1\n'
            '10.0.0.5 ## router\n'))
        assert _names(app) == {'sh3-nuc': True, 'sh1-cam1': True,
                               'router': False}

    def test_tilde_inside_a_for_loop(self, pb, tmp_path):
        entries = pb._HostsParser().parse(
            ':for hub-{1..3}\n'
            '    ~10.0.$1.20\n'
            ':end\n')
        rules = [e[1] for e in entries if e[0] == 'cmd' and 'no-alarm' in e[1]]
        assert rules == [':no-alarm 10.0.1.20', ':no-alarm 10.0.2.20',
                         ':no-alarm 10.0.3.20']

    def test_tilde_after_an_inline_if(self, pb, tmp_path):
        """':if cond -> ~host' — the marker sits on the body, not the line start.

        The '~' has to survive being unwrapped from the conditional; missed,
        it reaches ping as part of the hostname
        ('~10.0.0.5: Name or service not known').
        """
        entries = pb._HostsParser().parse(
            ':for i in hub-{1-3}\n'
            '    :if $i in 1 -> ~10.0.0.5\n'
            ':end\n')
        assert ('host', '10.0.0.5') in entries, entries
        assert not any('~' in e[1] for e in entries if e[0] == 'host')
        assert (('cmd', ':no-alarm 10.0.0.5')) in entries

    def test_tilde_after_an_inline_if_with_a_label(self, pb, tmp_path):
        """The shape from a real hosts file: '~ip  ## name' behind an ':if'."""
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':for i in hub-{1-3}\n'
            '    :if $i in 1 -> ~10.0.0.5  ## nray-slave\n'
            ':end\n'))
        assert [m.host for m in app.monitors] == ['nray-slave']
        assert _names(app) == {'nray-slave': True}

    def test_tilde_after_an_inline_if_inside_a_with_block(self, pb, tmp_path):
        """All three features at once — a relayed, looped, conditional host."""
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':with remote-ping relay\n'
            ':for i in hub-{1-2}\n'
            '    :if $i in 1 -> ~10.0.0.5  ## nray-slave\n'
            '    :if $i in 2 -> 10.0.0.6   ## nray-master\n'
            ':end\n'
            ':end\n'))
        assert [m._ping_host for m in app.monitors] == ['10.0.0.5', '10.0.0.6']
        assert [m.no_alarm for m in app.monitors] == [True, False]

    def test_tilde_after_an_inline_if_outside_a_loop(self, pb, tmp_path):
        """':if' works outside ':for' too, so the marker must as well."""
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':let site harbour\n'
            ':if $site in harbour -> ~10.0.0.7  ## switch\n'))
        assert _names(app) == {'switch': True}

    def test_tilde_on_a_remote_ping_target(self, pb, tmp_path):
        """Without this, ':remote-ping relay ~host' made a host named '~host'."""
        app = _app(pb, tmp_path, [('cmd', ':remote-ping relay ~10.9.9.9')])
        assert app.monitors[0]._ping_host == '10.9.9.9'
        assert app.monitors[0].no_alarm is True

    def test_relayed_host_in_a_with_block(self, pb, tmp_path):
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':with remote-ping relay\n'
            '    ~10.9.9.9\n'
            '    10.9.9.10\n'
            ':end\n'))
        assert [m.no_alarm for m in app.monitors] == [True, False]

    def test_command_inside_a_with_block_is_refused_with_a_hint(self, pb):
        """The block takes host lines only; a command there means a missing :end.

        Carrying on would quietly turn every following host into a relayed one,
        so it errors and pops the block — but the message has to say what to do,
        which for this command is one character.
        """
        entries = pb._HostsParser().parse(
            ':with remote-ping relay\n    :no-alarm *-ps\n:end\n')
        errs = [e[1] for e in entries if e[0] == 'error']
        assert errs and 'not allowed inside' in errs[0]
        assert "'~'" in errs[0], errs[0]

    def test_other_commands_get_the_generic_hint(self, pb):
        entries = pb._HostsParser().parse(
            ':with remote-ping relay\n    :resolv 10.0.0.1 gw\n:end\n')
        errs = [e[1] for e in entries if e[0] == 'error']
        assert 'close it with :end first' in errs[0], errs[0]

    def test_tilde_is_the_in_block_form(self, pb, tmp_path):
        """What the hint points at has to work."""
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':with remote-ping relay\n'
            '    ~10.123.1.20 ## sh1-power-switch\n'
            '    10.123.1.1   ## sh1-router\n'
            ':end\n'))
        assert _names(app) == {'sh1-power-switch': True, 'sh1-router': False}

    def test_a_glob_outside_covers_hosts_inside(self, pb, tmp_path):
        """Patterns match the :resolv alias, so one rule outside is enough."""
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':no-alarm *-power-switch\n'
            ':with remote-ping relay\n'
            '    10.123.1.20 ## sh1-power-switch\n'
            ':end\n'))
        assert app.monitors[0].no_alarm is True

    def test_unknown_with_block_type_still_refused(self, pb):
        entries = pb._HostsParser().parse(':with nonsense\n  x\n:end\n')
        assert any(e[0] == 'error' for e in entries)


# ---------------------------------------------------------------------------
# The command
# ---------------------------------------------------------------------------

class TestCommand:

    @pytest.fixture
    def app(self, pb, tmp_path):
        return _app(pb, tmp_path, [('cmd', ':resolv 10.0.0.2 sw1'),
                                   ('host', '10.0.0.1'), ('host', 'sw1')])

    def _last(self, app):
        return list(app.events)[-1].text.split('   ', 1)[-1]

    def test_adds_a_pattern(self, app):
        app._cmd_no_alarm('10.0.0.1')
        assert app.no_alarm_patterns == ['10.0.0.1']
        assert app.monitors[0].no_alarm is True

    def test_several_patterns_at_once(self, app):
        app._cmd_no_alarm('a b c')
        assert app.no_alarm_patterns == ['a', 'b', 'c']

    def test_a_duplicate_is_not_added_twice(self, app):
        app._cmd_no_alarm('10.0.0.1')
        app._cmd_no_alarm('10.0.0.1')
        assert app.no_alarm_patterns == ['10.0.0.1']

    def test_remove(self, app):
        app._cmd_no_alarm('10.0.0.1')
        app._cmd_no_alarm('--remove 10.0.0.1')
        assert app.no_alarm_patterns == []
        assert app.monitors[0].no_alarm is False

    def test_removing_an_absent_rule_is_reported(self, app):
        app._cmd_no_alarm('--remove nosuch')
        assert 'no rule' in self._last(app)

    def test_query_lists_the_rules(self, app):
        app._cmd_no_alarm('*-cam*')
        app._cmd_no_alarm('')
        assert '*-cam*' in self._last(app)

    def test_query_with_no_rules(self, app):
        app._cmd_no_alarm('')
        assert 'no patterns' in self._last(app)

    def test_missing_argument_is_reported(self, app):
        app._cmd_no_alarm('--remove')
        assert 'missing host or glob' in self._last(app)

    def test_matches_the_resolv_alias(self, app):
        """Patterns match the shown name as well as the address."""
        app._cmd_no_alarm('sw1')
        assert _names(app)['sw1'] is True


class TestInteractiveToggle:

    @pytest.fixture
    def app(self, pb, tmp_path):
        a = _app(pb, tmp_path, [('host', '10.0.0.1')])
        a.highlighted_index = a.entries.index(a.monitors[0])
        return a

    def _press_o(self, app, pb):
        binding, _ = app._key_trie.resolve(
            pb._parse_key_notation('o'), set(app._binding_context().keys()))
        assert binding is not None, "'o' should be bound with a host selected"
        app._execute_binding(binding)

    def test_toggles_on(self, app, pb):
        self._press_o(app, pb)
        assert app.monitors[0].no_alarm is True

    def test_toggles_off_again(self, app, pb):
        self._press_o(app, pb)
        self._press_o(app, pb)
        assert app.monitors[0].no_alarm is False
        assert app.no_alarm_patterns == []

    def test_toggling_off_clears_a_matching_glob(self, app, pb):
        """Turning it off must actually turn it off, even via a glob."""
        app._cmd_no_alarm('10.0.0.*')
        self._press_o(app, pb)
        assert app.monitors[0].no_alarm is False

    def test_no_host_selected_is_reported(self, app):
        app.highlighted_index = None
        app._cmd_no_alarm('--toggle')
        assert 'no host selected' in list(app.events)[-1].text

    def test_the_alias_is_persisted_when_there_is_one(self, pb, tmp_path):
        """The alias survives a renumbering that the address does not."""
        a = _app(pb, tmp_path, [('cmd', ':resolv 10.0.0.2 sw1'), ('host', 'sw1')])
        a.highlighted_index = a.entries.index(a.monitors[0])
        a._cmd_no_alarm('--toggle')
        assert a.no_alarm_patterns == ['sw1']


# ---------------------------------------------------------------------------
# What the mark changes, and what it does not
# ---------------------------------------------------------------------------

class TestPresentationOnly:

    @pytest.fixture
    def app(self, pb, tmp_path):
        return _app(pb, tmp_path, pb._HostsParser().parse(
            '~10.0.0.1\n10.0.0.2\n'))

    def test_alive_stays_factual(self, app):
        """Read in ~28 places; rewriting it would ripple into statistics."""
        marked = app.monitors[0]
        marked.alive = False
        assert marked.alive is False

    def test_a_marked_down_host_is_counted_apart_in_the_badge(self, app, pb):
        marked, plain = app.monitors
        marked.alive = False
        plain.alive = False
        parts, _h, _r = app._section_summary(app.monitors, length=10, offset=0)
        text = ''.join(t for t, _c in parts)
        assert '1↓' in text and '1○' in text, text

    def test_the_quiet_segment_is_dim_not_red(self, app, pb):
        marked = app.monitors[0]
        marked.alive = False
        parts, _h, _r = app._section_summary([marked], length=10, offset=0)
        colours = {t: c for t, c in parts}
        assert colours['1○'] < 0, parts

    def test_an_unmarked_down_host_still_reads_red(self, app, pb):
        plain = app.monitors[1]
        plain.alive = False
        parts, _h, _r = app._section_summary([plain], length=10, offset=0)
        assert dict(parts)['1↓'] == 2

    def test_a_marked_host_in_error_reads_red(self, app, pb):
        """A process error is not expected silence, and the badge must say so.

        Under autofold this is the only way a section of marked hosts stays
        open, so a dim '1○' there would leave '(autofold lock)' unexplained.
        """
        marked = app.monitors[0]
        marked.alive = False
        marked.error = 'Name or service not known'
        parts, _h, _r = app._section_summary([marked], length=10, offset=0)
        text = dict(parts)
        assert '1↓' in text and '1○' not in text, parts
        assert text['1↓'] == 2, 'red'

    def test_down_event_is_demoted(self, app, pb):
        """Still logged, so the file stays greppable — just not at the default."""
        marked = app.monitors[0]
        app.add_event(marked.get_display_name('off'), 'host down',
                      level=(pb.LEVEL_INFO if marked.no_alarm else None))
        assert list(app.events)[-1].level == pb.LEVEL_INFO

    def test_unmarked_down_event_keeps_its_level(self, app, pb):
        plain = app.monitors[1]
        app.add_event(plain.get_display_name('off'), 'host down',
                      level=(pb.LEVEL_INFO if plain.no_alarm else None))
        assert list(app.events)[-1].level == pb.LEVEL_QUIET


class TestPersistence:

    def test_patterns_are_saved(self, pb, tmp_path):
        app = _app(pb, tmp_path, [('host', '10.0.0.1')])
        app._cmd_no_alarm('*-power-switch')
        with patch.object(pb, '_config_path', return_value=app._cfg_path):
            app._save_config()
        assert any(':no-alarm *-power-switch' in l for l in open(app._cfg_path))

    def test_round_trip(self, pb, tmp_path):
        app = _app(pb, tmp_path, [('host', '10.0.0.1')])
        app._cmd_no_alarm('10.0.0.1')
        with patch.object(pb, '_config_path', return_value=app._cfg_path):
            app._save_config()
            reloaded = pb.Application([('host', '10.0.0.1')])
        assert reloaded.no_alarm_patterns == ['10.0.0.1']
        assert reloaded.monitors[0].no_alarm is True

    def test_nothing_written_when_unused(self, pb, tmp_path):
        app = _app(pb, tmp_path, [('host', '10.0.0.1')])
        with patch.object(pb, '_config_path', return_value=app._cfg_path):
            app._save_config()
        assert not any('no-alarm' in l for l in open(app._cfg_path))


class TestSharedHostsMap:
    """The first monitor must share the app's hosts_map, empty or not.

    'hosts_map or {}' treated an empty dict as falsy and handed the first
    monitor a private copy, so a host built before any ':resolv' never saw the
    mappings that arrived later: its display name stayed an IP, and
    ':prog-options' / ':no-alarm' globs could not match its alias.  Found while
    testing that a glob outside a ':with' block covers hosts inside it.
    """

    def test_first_relayed_host_shares_the_map(self, pb, tmp_path):
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':with remote-ping relay\n'
            '    10.0.0.20 ## first-host\n'
            '    10.0.0.21 ## second-host\n'
            ':end\n'))
        for m in app.monitors:
            assert m._hosts_map is app.hosts_map, m._ping_host

    def test_first_relayed_host_resolves_its_alias(self, pb, tmp_path):
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':with remote-ping relay\n    10.0.0.20 ## first-host\n:end\n'))
        assert app._prog_match_names(app.monitors[0])[1] == 'first-host'

    def test_a_glob_reaches_the_first_relayed_host(self, pb, tmp_path):
        """The user-visible consequence: rules matched every host but the first."""
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':no-alarm *-switch\n'
            ':with remote-ping relay\n'
            '    10.0.0.20 ## power-switch\n'
            ':end\n'))
        assert app.monitors[0].no_alarm is True

    def test_an_explicit_empty_map_is_still_shared(self, pb):
        """A map handed in empty must stay the same object."""
        shared = {}
        m = pb.SshPingMonitor(['relay'], '10.0.0.1', hosts_map=shared)
        # Both directions, as _apply_hosts_entry stores them; the reverse
        # lookup skips the self-mapping so the readable alias wins.
        shared['10.0.0.1'] = ('10.0.0.1', 'alias')
        shared['alias'] = ('10.0.0.1', 'alias')
        assert m._hosts_map is shared
        assert m._reverse_lookup_alias('10.0.0.1') == 'alias'

    def test_no_map_still_gets_its_own(self, pb):
        m = pb.SshPingMonitor(['relay'], '10.0.0.1')
        assert m._hosts_map == {}


class TestFoldedSectionStrip:
    """A folded section of expected-silent hosts must not read as 'no data'.

    Now that such a section folds on its own, its one-line summary is all the
    user sees of it.
    """

    def test_expected_silence_survives_to_the_summary(self, pb):
        wc = pb.Application._worst_history_char
        assert wc(['o', 'o']) == 'o'
        assert wc(['o', ' ']) == 'o'

    def test_a_real_answer_outranks_it(self, pb):
        """One host answering is the better news for the slot."""
        assert pb.Application._worst_history_char(['o', '.']) == '.'

    def test_a_real_loss_still_wins(self, pb):
        wc = pb.Application._worst_history_char
        assert wc(['o', 'X']) == 'X'
        assert wc(['o', '?']) == '?'
        assert wc(['o', 'x']) == 'x'

    def test_no_ping_running_ranks_last_but_one(self, pb):
        """'_' (sync mode, no process yet) is not a loss either."""
        wc = pb.Application._worst_history_char
        assert wc(['_', ' ']) == '_'
        assert wc(['_', 'o']) == 'o'
        assert wc(['_', 'X']) == 'X'

    def test_nothing_measured_is_still_blank(self, pb):
        assert pb.Application._worst_history_char([' ', ' ']) == ' '

    def test_the_section_summary_uses_it(self, pb, tmp_path):
        """End to end: a marked, down host gives the header an 'o' strip."""
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            '## Quiet\n~10.0.0.1\n'))
        monitor = app.monitors[0]
        monitor.alive = False
        monitor.history.extend([None] * 5)
        _, history, _ = app._section_summary([monitor], length=5, offset=0)
        assert set(history.strip()) == {'o'}, history
