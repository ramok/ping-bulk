"""Every settable parameter answers the same two words.

    :set <param>            report the value, change nothing
    :set <param> cycle      step to the next value  (cycle- steps back)
    :set <param> <value>    set it

A bare invocation used to *change* things — ':dns' cycled, ':sync-history'
toggled — which made a hosts file non-idempotent.  A plain ':sync-history'
line flipped whatever the saved config held, so the setting depended on the
order the two files were read, and every ':edit' reload flipped it again.
Measured on a real config (':set sync-history off') plus a real hosts file
(':sync-history'): sync was on after startup and off after the first reload.

Two spellings reach each parameter — ':set dns cycle' and ':dns cycle' — and
one implementation answers for both (``_handle_param_verb``), so they cannot
drift apart.  The tests below hold every parameter to the rule rather than
sampling a few, because uniformity is the whole point.
"""

import os
import pytest
from unittest.mock import patch

from utils.hosts_helper import write_hosts


def _make_app(pb, tmp_path, config='', entries=None):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, 'w') as f:
        f.write(config)
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application(entries or [('host', '127.0.0.1'),
                                         ('host', '127.0.0.2')])
    app._monitoring_started = True
    return app


@pytest.fixture
def app(pb, tmp_path):
    return _make_app(pb, tmp_path)


def _listed(param):
    """True when the parameter has a real list of values to walk."""
    vals = param.get_values()
    return bool(vals) and isinstance(vals, (list, tuple))


# The commands that also exist as a bare ':<name>', with the key bound to them.
STANDALONE = {
    'dns':          'D',
    'stats':        's',
    'sort':         'o',
    'ping-view':    'H',
    'layout':       '<C-l>',
    'sync-history': 'S',
    'autofold':     'A',
    'pause':        'P',
}


# ===========================================================================
# No argument reports
# ===========================================================================

class TestNoArgumentReports:

    def test_every_parameter_reports_its_value(self, pb, app):
        for param in pb.SET_PARAMS:
            expected = f'{param.name} {param.get_current(app)}'
            app._status_msg = None
            app._dispatch_cmd(f':set {param.name}')
            assert app._status_msg is not None, param.name
            assert app._status_msg['text'] == expected, param.name

    def test_no_parameter_is_changed_by_being_asked(self, pb, app):
        before = {p.name: p.get_current(app) for p in pb.SET_PARAMS}
        for name in before:
            app._dispatch_cmd(f':set {name}')
        after = {p.name: p.get_current(app) for p in pb.SET_PARAMS}
        assert after == before

    def test_the_report_is_the_command_that_would_set_it(self, pb, app):
        """'dns name+ip' is exactly what ':set dns name+ip' takes."""
        app._dispatch_cmd(':set dns name+ip')
        app._dispatch_cmd(':set dns')
        text = app._status_msg['text']
        assert text == 'dns name+ip'
        app._dispatch_cmd(':set dns off')
        app._dispatch_cmd(':set ' + text)
        assert pb.DNS_MODES[app.dns_mode].lower() == 'name+ip'

    def test_it_is_logged_as_well_as_shown(self, pb, app):
        """The status bar is visible at any log level; the log keeps a record."""
        app._dispatch_cmd(':set log-level info')
        n = len(app.events)
        app._dispatch_cmd(':set sort')
        assert any('sort none' in e.text for e in list(app.events)[n:])

    def test_it_does_not_open_an_overlay(self, pb, app):
        app._dispatch_cmd(':set autofold')
        assert not app.help_open

    def test_no_parameter_reports_a_question_mark(self, pb, app):
        """'?' is what get_current returns when the getter raises.

        ':set terminal' read app.terminal, but the attribute is
        app.terminal_emulator — so that row showed '?' in the settings tab
        from the day it was added, and cycling it started from nowhere.
        """
        broken = [p.name for p in pb.SET_PARAMS
                  if p.get_current(app) == '?']
        assert not broken, f'getter raises for: {broken}'


# ===========================================================================
# cycle / cycle-
# ===========================================================================

class TestCycle:

    def test_cycle_walks_every_listed_parameter_forward(self, pb, app):
        for param in pb.SET_PARAMS:
            if not _listed(param):
                continue
            vals = [v.lower() for v in param.get_values()]
            start = param.get_current(app).lower()
            app._dispatch_cmd(f':set {param.name} cycle')
            now = param.get_current(app).lower()
            assert now != start or len(vals) == 1, param.name
            assert now in vals, (param.name, now, vals)

    def test_cycle_all_the_way_round_comes_home(self, pb, app):
        for param in pb.SET_PARAMS:
            if not _listed(param):
                continue
            start = param.get_current(app)
            for _ in param.get_values():
                app._dispatch_cmd(f':set {param.name} cycle')
            assert param.get_current(app) == start, param.name

    def test_cycle_back_undoes_cycle(self, pb, app):
        for param in pb.SET_PARAMS:
            if not _listed(param):
                continue
            start = param.get_current(app)
            app._dispatch_cmd(f':set {param.name} cycle')
            app._dispatch_cmd(f':set {param.name} cycle-')
            assert param.get_current(app) == start, param.name

    def test_a_boolean_cycles_between_its_two_values(self, app):
        app._dispatch_cmd(':set sync-history off')
        app._dispatch_cmd(':sync-history cycle')
        assert app.sync_history is True
        app._dispatch_cmd(':sync-history cycle')
        assert app.sync_history is False

    def test_stats_cycles_through_its_own_cycler(self, app):
        """Its values are free-form, so a plain value walk cannot do it."""
        app._dispatch_cmd(':set stats off')
        app._dispatch_cmd(':stats cycle')
        assert app.stats_mode != 0

    def test_a_free_form_value_says_so_instead_of_cycling_characters(self, app):
        """':set ssh-options cycle' used to set the options to '<'.

        Its 'values' is the usage synopsis '<flags>|default|none', a string —
        walking it stepped through the characters.
        """
        app._dispatch_cmd(':set ssh-options -o Foo=yes')
        before = app._dispatch_cmd(':set ssh-options') or None
        text = app._status_msg['text']
        app._dispatch_cmd(':set ssh-options cycle')
        assert any('cannot cycle a free-form value' in e.text
                   for e in app.events)
        app._dispatch_cmd(':set ssh-options')
        assert app._status_msg['text'] == text, 'the value must be untouched'


# ===========================================================================
# The two spellings agree
# ===========================================================================

class TestBothSpellingsAgree:

    def test_bare_command_reports_like_set(self, pb, tmp_path):
        for name in STANDALONE:
            a = _make_app(pb, tmp_path)
            b = _make_app(pb, tmp_path)
            a._dispatch_cmd(f':set {name}')
            b._dispatch_cmd(f':{name}')
            assert a._status_msg['text'] == b._status_msg['text'], name

    def test_bare_command_changes_nothing(self, pb, tmp_path):
        for name in STANDALONE:
            app = _make_app(pb, tmp_path)
            param = next(p for p in pb.SET_PARAMS if p.name == name)
            before = param.get_current(app)
            app._dispatch_cmd(f':{name}')
            assert param.get_current(app) == before, name

    def test_cycle_works_through_the_bare_spelling(self, pb, tmp_path):
        for name in STANDALONE:
            app = _make_app(pb, tmp_path)
            param = next(p for p in pb.SET_PARAMS if p.name == name)
            before = param.get_current(app)
            app._dispatch_cmd(f':{name} cycle')
            assert param.get_current(app) != before, name


# ===========================================================================
# Keys
# ===========================================================================

class TestKeysSpellTheActionOut:

    def test_each_key_names_the_verb(self, pb, app):
        expected = {
            'D': ':dns cycle', 's': ':stats cycle', 'o': ':sort cycle',
            'H': ':ping-view cycle', '<C-l>': ':layout cycle',
            'S': ':sync-history cycle', 'A': ':autofold cycle',
            'P': ':pause cycle', 'O': ':sort cycle-',
        }
        for notation, cmd in expected.items():
            binding, _ = app._key_trie.resolve(
                pb._parse_key_notation(notation), set())
            assert binding is not None, notation
            assert binding.commands == [cmd], notation

    def test_no_default_key_is_bound_to_a_bare_parameter(self, pb, app):
        """A key bound to a bare name would now report instead of act."""
        bare = {f':{n}' for n in STANDALONE}
        for _keys, b in app._key_trie:
            for cmd in b.commands:
                assert cmd not in bare, (b.key_notation, cmd)

    def test_the_keys_still_change_what_they_always_changed(self, pb, app):
        """The rule changed; the keyboard did not."""
        for name, notation in STANDALONE.items():
            param = next(p for p in pb.SET_PARAMS if p.name == name)
            before = param.get_current(app)
            binding, _ = app._key_trie.resolve(
                pb._parse_key_notation(notation), set())
            app._execute_binding(binding)
            assert param.get_current(app) != before, name


# ===========================================================================
# A typo is not a toggle
# ===========================================================================

class TestATypoIsRejected:

    def test_sync_history_rejects_an_unknown_value(self, app):
        app._dispatch_cmd(':set sync-history on')
        app._dispatch_cmd(':sync-history yes')
        assert app.sync_history is True
        assert any("unknown value 'yes'" in e.text for e in app.events)

    def test_pause_rejects_an_unknown_value(self, app):
        """':pause yes' used to unpause a paused fleet."""
        app._dispatch_cmd(':set pause on')
        app._dispatch_cmd(':pause yes')
        assert all(m.paused for m in app.monitors)
        assert any("unknown value 'yes'" in e.text for e in app.events)

    def test_autofold_rejects_an_unknown_value(self, app):
        app._dispatch_cmd(':set autofold on')
        app._dispatch_cmd(':autofold yes')
        assert app.autofold is True


# ===========================================================================
# What this was for: a hosts file that means the same thing twice
# ===========================================================================

class TestAHostsFileIsIdempotent:

    def test_a_bare_toggle_line_no_longer_depends_on_the_config(self, pb,
                                                                tmp_path):
        """The reported bug, end to end.

        Config said ':set sync-history off'; the hosts file said
        ':sync-history'.  Startup read both and ended up on; the first
        ':edit' reload re-read the hosts file and flipped it back off.
        """
        app = _make_app(pb, tmp_path, config=':set sync-history off\n')
        hosts = write_hosts(tmp_path, ':sync-history\n127.0.0.1\n')
        assert app.sync_history is False
        app._cmd_source(hosts)
        first = app.sync_history
        app._cmd_source(hosts)
        assert app.sync_history == first, 're-reading the file changed it'
        assert app.sync_history is False, 'a query must not set it either'

    def test_the_explicit_form_survives_any_number_of_reloads(self, pb,
                                                              tmp_path):
        app = _make_app(pb, tmp_path, config=':set sync-history off\n')
        hosts = write_hosts(tmp_path, ':sync-history on\n127.0.0.1\n')
        for _ in range(3):
            app._cmd_source(hosts)
            assert app.sync_history is True

    def test_a_cycle_line_in_a_file_still_steps(self, pb, tmp_path):
        """'cycle' is explicit, so a file may still ask for it."""
        app = _make_app(pb, tmp_path, config=':set sync-history off\n')
        hosts = write_hosts(tmp_path, ':sync-history cycle\n127.0.0.1\n')
        app._cmd_source(hosts)
        assert app.sync_history is True


# ===========================================================================
# Things that must not have changed
# ===========================================================================

class TestUnchanged:

    def test_sort_reverse_is_still_accepted(self, app):
        """Documented alias for 'cycle-'."""
        app._dispatch_cmd(':sort cycle')
        assert app.sort_by == 'name'
        app._dispatch_cmd(':sort reverse')
        assert app.sort_by == 'none'

    def test_layout_toggle_keeps_its_own_meaning(self, app):
        """'--toggle' remembers where it came from; a cycle cannot."""
        app._dispatch_cmd(':layout cycle')          # all -> ping
        assert app.layout == 'ping'
        app._dispatch_cmd(':layout --toggle log')
        assert app.layout == 'log'
        app._dispatch_cmd(':layout --toggle log')
        assert app.layout == 'ping', 'must return to ping, not step to all'

    def test_setting_a_value_still_works_everywhere(self, pb, app):
        for param in pb.SET_PARAMS:
            if not _listed(param):
                continue
            for value in param.get_values():
                app._dispatch_cmd(f':set {param.name} {value}')
                assert param.get_current(app).lower() == value.lower(), \
                    (param.name, value)

    def test_set_with_no_parameter_still_opens_the_overlay(self, app):
        app._dispatch_cmd(':set')
        assert app.help_open
        assert app.help_show_settings

    def test_an_unknown_parameter_is_still_an_error(self, app):
        app._dispatch_cmd(':set nosuchthing')
        assert any("unknown setting 'nosuchthing'" in e.text
                   for e in app.events)
