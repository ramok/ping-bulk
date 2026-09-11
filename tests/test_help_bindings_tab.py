"""The Bindings tab says what each key *does*, not just what it runs.

It used to print ``key → :command`` and nothing else, which leaves the two
questions a keyboard reference exists to answer unanswered: ``c`` and ``C``
carry the same ``:mux ssh`` text and differ only in that one stops on the
command line, and ``--%d c`` next to ``c`` says nothing about which of them
is in force.  So each row now carries the binding's description — the same
text the Commands tab shows for a command — falling back to the command's own
one-line help for a binding written without ``--desc``.

Two things the layout has to get right, both of which were wrong before:

* **Alignment.** The old format padded the key notation *after* a
  variable-length context prefix, so every guarded row pushed its command out
  of column.
* **Escaping.** Overlay lines are drawn through ``_draw_hint_text``, where
  ``[`` opens a ``[key desc]`` token.  A notation like ``z[`` — or the
  ``:fold z[`` it runs — opened a token that ate the rest of the line.
"""

import os
import re
import pytest
from unittest.mock import patch


def _make_app(pb, tmp_path):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '127.0.0.1')])
    app._monitoring_started = True
    return app


def _rows(lines):
    """The binding rows — four-space indented, everything else is chrome."""
    return [l for l in lines
            if l.startswith('    ') and l.strip() and l != '-DIVIDER-']


@pytest.fixture
def lines(pb, tmp_path):
    return _make_app(pb, tmp_path)._build_all_bindings_lines()


class TestEveryRowIsDescribed:

    def test_no_row_is_left_without_a_description(self, pb, lines):
        """The column exists to be read; a blank one is the old tab back."""
        bare = []
        for row in _rows(lines):
            stripped = pb._strip_hint_markup(row)
            # Everything after the command is the description.
            m = re.search(r'\s(:[\w-]+)', stripped)
            assert m, row
            tail = stripped[m.start(1):]
            # Drop the command itself: it runs to the next two-space gap.
            parts = re.split(r'  +', tail, maxsplit=1)
            if len(parts) < 2 or not parts[1].strip():
                bare.append(row)
        assert not bare, f'rows with no description:\n' + '\n'.join(bare)

    def test_a_default_carries_its_own_desc(self, pb, lines):
        row = next(r for r in _rows(lines) if ':clear --confirm' in r)
        assert 'clear event log' in pb._strip_hint_markup(row)

    def test_the_two_ssh_keys_are_told_apart(self, pb, lines):
        """'c' and 'C' run the same text; only the description separates them."""
        c_rows = [pb._strip_hint_markup(r) for r in _rows(lines)
                  if re.match(r'^    c\s', r)]
        big_c = [pb._strip_hint_markup(r) for r in _rows(lines)
                 if re.match(r'^    C\s', r)]
        assert c_rows and big_c
        assert any('open SSH connection' in r for r in c_rows)
        assert any('before running it' in r for r in big_c)

    def test_the_relayed_variant_says_via_its_relay(self, pb, lines):
        row = next(r for r in _rows(lines)
                   if '--%d' in r and ':mux ssh %{J?' in r and r.strip().startswith('c'))
        assert 'via its relay' in pb._strip_hint_markup(row)


class TestAUserBindingIsDescribedToo:

    def test_its_own_desc_wins(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._cmd_bindkey('--desc "jump to the top" gt :select first')
        row = next(r for r in _rows(app._build_all_bindings_lines())
                   if r.strip().startswith('gt'))
        assert 'jump to the top' in pb._strip_hint_markup(row)
        assert '[user]' in row

    def test_without_desc_it_borrows_the_command_help(self, pb, tmp_path):
        """':bind-key' does not require --desc, so the column needs a fallback."""
        app = _make_app(pb, tmp_path)
        app._cmd_bindkey('gq :quit')
        row = next(r for r in _rows(app._build_all_bindings_lines())
                   if r.strip().startswith('gq'))
        cmd = next(c for c in pb.CMD_REGISTRY if 'quit' in c.names)
        assert cmd.help in pb._strip_hint_markup(row)

    def test_an_unknown_command_is_not_an_error(self, pb, tmp_path):
        """A typo in a binding must not take the whole tab down."""
        app = _make_app(pb, tmp_path)
        app._cmd_bindkey('gz :nosuchcommand')
        row = next(r for r in _rows(app._build_all_bindings_lines())
                   if r.strip().startswith('gz'))
        assert ':nosuchcommand' in pb._strip_hint_markup(row)

    def test_a_default_carries_no_user_tag(self, pb, lines):
        assert not any('[user]' in r for r in _rows(lines))


class TestTheColumnsLineUp:

    def _cmd_col(self, pb, row):
        """Rendered column where the command starts."""
        stripped = pb._strip_hint_markup(row)
        m = re.search(r'\s(:[\w-]+)', stripped)
        assert m, row
        return m.start(1)

    def test_every_row_starts_its_command_in_the_same_column(self, pb, lines):
        cols = {self._cmd_col(pb, r) for r in _rows(lines)}
        assert len(cols) == 1, f'command column varies: {sorted(cols)}'

    def test_a_context_guard_does_not_shift_the_command(self, pb, lines):
        """The old format padded the notation after the guard prefix."""
        guarded = next(r for r in _rows(lines) if '--%h' in r and '<PageUp>' in r)
        plain = next(r for r in _rows(lines)
                     if '<PageUp>' in r and '--%' not in r)
        assert self._cmd_col(pb, guarded) == self._cmd_col(pb, plain)

    def test_the_overlay_modes_align_with_normal_mode(self, pb, lines):
        """Widths are measured across all modes, so the sections match."""
        overlay = next(r for r in _rows(lines) if ':scroll-overlay ' in r)
        normal = next(r for r in _rows(lines) if ':select up' in r)
        assert self._cmd_col(pb, overlay) == self._cmd_col(pb, normal)


class TestBracketsSurviveTheMarkupParser:

    def test_the_fold_keys_keep_their_bracket(self, pb, lines):
        """'z[' and ':fold z[' both have to reach the screen intact."""
        row = next(r for r in _rows(lines) if 'z\\[' in r)
        rendered = pb._strip_hint_markup(row)
        assert 'z[' in rendered
        assert ':fold z[' in rendered
        assert 'close sections where all hosts are up' in rendered

    def test_a_bare_bracket_key_is_escaped(self, pb, lines):
        row = next(r for r in _rows(lines) if ':fold-all' in r)
        assert '\\[' in row, row
        assert 'close (fold) ALL sections' in pb._strip_hint_markup(row)

    def test_the_width_the_drawer_measures_matches_the_text(self, pb, lines):
        """A swallowed token renders shorter than its text — that was the bug."""
        for row in _rows(lines):
            width = pb.Application._hint_text_width(row)
            assert width == len(pb._strip_hint_markup(row)), row

    def test_a_user_desc_with_brackets_does_not_break_the_line(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._cmd_bindkey('--desc "trace [t] host" gT :mux mtr %r')
        row = next(r for r in _rows(app._build_all_bindings_lines())
                   if r.strip().startswith('gT'))
        assert 'trace [t] host' in pb._strip_hint_markup(row)
        assert pb.Application._hint_text_width(row) == len(
            pb._strip_hint_markup(row))


class TestTheTabItself:

    def test_tab_5_renders_these_rows(self, pb, tmp_path):
        """The tab bar prints it as '5 Bindings'; help_tab is 0-based."""
        app = _make_app(pb, tmp_path)
        app.help_tab = 4
        lines = app._build_tab_lines()
        assert '[5:tabactive Bindings]' in lines[0]
        assert any(':clear --confirm' in l for l in lines)
        assert any('clear event log' in l for l in lines)

    def test_it_explains_the_context_column(self, pb, lines):
        """'--%h' next to a key is unreadable without a word about it."""
        head = ' '.join(lines[:5])
        assert '--%x' in head
        assert 'context guard' in head

    def test_nothing_is_lost_from_the_old_format(self, pb, tmp_path):
        """Same set of (key, command, context) rows as before, one per line."""
        app = _make_app(pb, tmp_path)
        rows = _rows(app._build_all_bindings_lines())
        for notation, cmds in (('q', ':quit'), ('X', ':clear --confirm'),
                               ('gg', ':select first'), ('zx', ':fold zx')):
            assert any(r.strip().startswith(notation + ' ') and cmds in r
                       for r in rows), (notation, cmds)
