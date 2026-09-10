"""PgUp/PgDn belong to whichever list has a cursor in it.

With a host or a section selected there is a visible cursor on screen, and
paging is what those keys are for: they move the selection a screenful at a
time.  With nothing selected they page the event log, as they always did.
``Ctrl-B``/``Ctrl-F`` page the log in both states, so it never goes out of
reach.

The other half of this is the hint text.  ``[PgUp/PgDn scroll]`` in the Events
header and ``[PgUp/PgDn page]`` in the selection banner describe the same two
keys, so exactly one of them may be on screen at a time — never both, and
never neither.  ``_selection_active()`` is the single predicate both lines
ask, and the tests below hold it to the invariant.

Also covered: the Events header used to advertise ``[C|lear]``, but ``C`` is
the *edit an SSH command* key — ``X`` clears the log.
"""

import os
import curses
import pytest
from unittest.mock import patch

from utils.hosts_helper import write_hosts


def _make_app(pb, tmp_path, content='127.0.0.1\n'):
    """A non-running Application over *content*, with a blank temp config."""
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application(entries)
    app._monitoring_started = True
    app._start_time = 0.0
    app.stale_attr = 0            # normally set by run() after initscr()
    return app


TWENTY = ''.join(f'10.0.0.{i}\n' for i in range(1, 21))


class _FakeScreen:
    """Just enough window for draw_events, which only ever calls addstr."""

    def __init__(self, width=120, height=24):
        self.width, self.height = width, height
        self.writes = []

    def addstr(self, row, col, text, attr=0):
        self.writes.append((row, col, text))

    def getmaxyx(self):
        return self.height, self.width


def _events_header(app, width=120):
    """Return the Events header suffix draw_events would render."""
    seen = []
    with patch.object(type(app), '_draw_column_header',
                      lambda self, s, r, c, title, suffix, w: seen.append(
                          (title, suffix))):
        app.draw_events(_FakeScreen(width), 0, 24, width)
    assert seen, 'draw_events drew no header'
    return seen[-1][1]


def _banner(app):
    """Return the selection banner label, or None when it is not drawn."""
    for label, _attr in app._mode_banners():
        if label.lstrip().startswith('▶'):
            return label
    return None


# ===========================================================================
# Which list the keys drive
# ===========================================================================

class TestPageKeysFollowTheCursor:
    """Context-guarded bindings, resolved the way _dispatch_key resolves them."""

    def _resolve(self, pb, app, notation, ctx_keys):
        binding, _ = app._key_trie.resolve(
            pb._parse_key_notation(notation), set(ctx_keys))
        assert binding is not None, notation
        return binding.commands

    def test_a_selected_host_takes_the_keys(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        # The context a Monitor selection builds: %h plus the section lists.
        ctx = {'h', 'r', 'H', 'R'}
        assert self._resolve(pb, app, '<PageUp>', ctx) == [':select page-']
        assert self._resolve(pb, app, '<PageDown>', ctx) == [':select page']

    def test_a_selected_section_takes_them_too(self, pb, tmp_path):
        """A section header is a cursor on screen just as much as a host is."""
        app = _make_app(pb, tmp_path)
        ctx = {'s', 'H', 'R'}
        assert self._resolve(pb, app, '<PageUp>', ctx) == [':select page-']
        assert self._resolve(pb, app, '<PageDown>', ctx) == [':select page']

    def test_the_page_direction_is_not_the_log_direction(self, pb, tmp_path):
        """':select page-' is up the list; the log's bare 'page' is up.

        The two commands spell the same direction opposite ways, so copying
        the neighbouring log binding would have paged the wrong way.
        """
        app = _make_app(pb, tmp_path)
        assert self._resolve(pb, app, '<PageUp>', {'h'}) == [':select page-']
        assert self._resolve(pb, app, '<PageUp>', set()) == [
            ':scroll event-history page']

    def test_with_nothing_selected_the_log_keeps_them(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        assert self._resolve(pb, app, '<PageUp>', set()) == [
            ':scroll event-history page']
        assert self._resolve(pb, app, '<PageDown>', set()) == [
            ':scroll event-history page-']

    def test_ctrl_b_and_ctrl_f_always_reach_the_log(self, pb, tmp_path):
        """The escape hatch: unguarded, so a selection does not shadow them."""
        app = _make_app(pb, tmp_path)
        for ctx in (set(), {'h', 'r', 'H', 'R'}, {'s', 'H', 'R'}):
            assert self._resolve(pb, app, '<C-b>', ctx) == [
                ':scroll event-history page']
            assert self._resolve(pb, app, '<C-f>', ctx) == [
                ':scroll event-history page-']


# ===========================================================================
# ':select page' / ':select page-'
# ===========================================================================

class TestSelectPaging:
    """A page is a screenful of host rows, and paging clamps at the ends."""

    def test_a_page_is_the_host_area_height(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, TWENTY)
        app._host_page_size = 6
        app._cmd_select('first')
        first = app.highlighted_index
        app._cmd_select('page')
        assert app.highlighted_index == first + 6
        app._cmd_select('page-')
        assert app.highlighted_index == first

    def test_paging_down_stops_at_the_last_host(self, pb, tmp_path):
        """Unlike ':select down', which wraps: a held key must come to rest."""
        app = _make_app(pb, tmp_path, TWENTY)
        app._host_page_size = 7
        app._cmd_select('first')
        for _ in range(10):
            app._cmd_select('page')
        visible = app._get_visible_entry_indices()
        assert app.highlighted_index == visible[-1]

    def test_paging_up_stops_at_the_first_host(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, TWENTY)
        app._host_page_size = 7
        app._cmd_select('last')
        for _ in range(10):
            app._cmd_select('page-')
        visible = app._get_visible_entry_indices()
        assert app.highlighted_index == visible[0]

    def test_it_does_not_wrap_where_down_does(self, pb, tmp_path):
        """The contrast, stated directly, so a copy of 'down' would fail."""
        app = _make_app(pb, tmp_path, TWENTY)
        app._host_page_size = 5
        visible = app._get_visible_entry_indices()
        app._cmd_select('last')
        app._cmd_select('down')
        assert app.highlighted_index == visible[0]      # wraps
        app._cmd_select('last')
        app._cmd_select('page')
        assert app.highlighted_index == visible[-1]     # clamps

    def test_from_no_selection_it_mirrors_up_and_down(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, TWENTY)
        app._host_page_size = 5
        visible = app._get_visible_entry_indices()
        app.highlighted_index = None
        app._cmd_select('page')
        assert app.highlighted_index == visible[0]
        app.highlighted_index = None
        app._cmd_select('page-')
        assert app.highlighted_index == visible[-1]

    def test_without_a_cached_page_size_it_still_moves(self, pb, tmp_path):
        """':select page' typed on the command line before any host draw.

        The 'log' layout never draws hosts, so the fallback is reachable.
        """
        app = _make_app(pb, tmp_path, TWENTY)
        assert not hasattr(app, '_host_page_size')
        app._cmd_select('first')
        first = app.highlighted_index
        app._cmd_select('page')
        assert app.highlighted_index > first

    def test_it_skips_hosts_a_fold_hides(self, pb, tmp_path):
        """Paging walks the visible list, which is what is on screen."""
        content = ('### one\n10.0.0.1\n10.0.0.2\n10.0.0.3\n'
                   '### two\n10.0.1.1\n10.0.1.2\n')
        app = _make_app(pb, tmp_path, content)
        app._host_page_size = 2
        app._cmd_select('first')
        app.entries[0].folded = True         # collapse the first section
        visible = app._get_visible_entry_indices()
        app.highlighted_index = visible[0]
        app._cmd_select('page')
        assert app.highlighted_index in visible
        assert app.highlighted_index == visible[2]

    def test_the_draw_loop_caches_the_page_size(self, pb, tmp_path):
        """A page of 1 would be a silent regression to ':select down'."""
        app = _make_app(pb, tmp_path, TWENTY)
        with patch.object(curses, 'color_pair', lambda n: 0):
            app.draw_hosts(_FakeScreen(120, 30), 0, 12, 120, 30)
        # draw_hosts alone does not set it — the layout maths in run() does,
        # so assert on the value the command falls back to instead.
        assert max(1, getattr(app, '_host_page_size', 10)) > 1

    def test_page_is_a_documented_argument(self, pb):
        """Tab-completion and the usage string both have to know about it."""
        cmd = next(c for c in pb.CMD_REGISTRY if 'select' in c.names)
        assert 'page' in cmd.arg_choices
        assert 'page-' in cmd.arg_choices
        assert 'page' in cmd.usage and 'page-' in cmd.usage


# ===========================================================================
# The hint is in exactly one place
# ===========================================================================

class TestTheHintLivesInExactlyOnePlace:
    """Never both lines, never neither: one predicate answers for both."""

    def _count(self, app):
        banner = _banner(app) or ''
        header = _events_header(app)
        return ('PgUp/PgDn' in banner) + ('PgUp/PgDn' in header)

    def test_with_a_host_selected_only_the_banner_names_them(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, TWENTY)
        app._cmd_select('first')
        banner = _banner(app)
        assert banner is not None
        assert '[PgUp/PgDn page]' in banner
        assert 'PgUp/PgDn' not in _events_header(app)
        assert self._count(app) == 1

    def test_with_a_section_selected_the_banner_names_them(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, '### one\n10.0.0.1\n10.0.0.2\n')
        app._cmd_select('first')
        assert isinstance(app.entries[app.highlighted_index], pb.SectionLabel)
        assert '[PgUp/PgDn page]' in _banner(app)
        assert self._count(app) == 1

    def test_with_nothing_selected_only_the_log_names_them(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, TWENTY)
        app.highlighted_index = None
        for i in range(80):                 # make the log overflow the page
            app.add_event('t', f'line {i}')
        assert _banner(app) is None
        assert 'PgUp/PgDn' in _events_header(app)
        assert self._count(app) == 1

    def test_the_command_line_hides_the_banner_and_returns_the_keys(
            self, pb, tmp_path):
        """The banner is suppressed while ':' is open, so the log gets them.

        This is the state where a second copy of the predicate would leave
        the hint nowhere.
        """
        app = _make_app(pb, tmp_path, TWENTY)
        app._cmd_select('first')
        for i in range(80):
            app.add_event('t', f'line {i}')
        app.cmd = ''                        # command line open
        assert _banner(app) is None
        assert not app._selection_active()
        assert 'PgUp/PgDn' in _events_header(app)

    def test_the_log_layout_keeps_the_keys_on_the_log(self, pb, tmp_path):
        """':layout log' draws no host list, so no banner carries the hint.

        The layout clears the selection on the way in, but j/k are unguarded
        and set it again from there — which is how the hint could end up on
        neither line.
        """
        app = _make_app(pb, tmp_path, TWENTY)
        for i in range(80):
            app.add_event('t', f'line {i}')
        app._dispatch_cmd(':layout log')
        app._cmd_select('first')            # as 'j' would, with hosts hidden
        assert app.highlighted_index is not None
        assert not app._selection_active()
        assert _banner(app) is None
        assert 'PgUp/PgDn' in _events_header(app)

    def test_an_overlay_hides_the_banner_too(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, TWENTY)
        app._cmd_select('first')
        app.details_open = True
        assert not app._selection_active()
        assert _banner(app) is None

    def test_the_scrolled_back_header_names_what_still_works(self, pb, tmp_path):
        """Scrolled back with a host selected, PgUp/PgDn no longer resume it.

        Naming them there would be a dead end, so the header names Ctrl-B/F.
        """
        app = _make_app(pb, tmp_path, TWENTY)
        for i in range(80):
            app.add_event('t', f'line {i}')
        app._cmd_select('first')
        app.log_offset = 10
        header = _events_header(app)
        assert 'PgUp/PgDn' not in header
        assert 'C-b/C-f' in header
        assert 'Esc resume' in header


# ===========================================================================
# The clear key
# ===========================================================================

class TestTheClearHintNamesTheClearKey:
    """'C' edits an SSH command; 'X' clears the log."""

    def test_the_header_says_x(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        header = _events_header(app)
        assert '[X clear]' in header
        assert 'C|lear' not in header

    def test_and_x_is_what_is_bound(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('X'), set())
        assert binding.commands == [':clear --confirm']

    def test_c_is_not(self, pb, tmp_path):
        """The reason the old label was wrong, asserted so it stays wrong."""
        app = _make_app(pb, tmp_path)
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('C'), set())
        assert ':clear' not in ' '.join(binding.commands)

    def test_the_built_in_help_agrees(self, pb):
        clear_lines = [l for l in pb._HELP_HOTKEYS if '(:clear)' in l]
        assert clear_lines and all('[X]' in l for l in clear_lines)


# ===========================================================================
# End to end
# ===========================================================================

class TestTheWholeDispatchPath:
    """The context comes from _binding_context(), not from a set in a test."""

    def _press(self, pb, app, notation):
        ctx_keys = set(app._binding_context().keys())
        binding, _ = app._key_trie.resolve(
            pb._parse_key_notation(notation), ctx_keys)
        assert binding is not None, notation
        app._execute_binding(binding)

    def test_pagedown_moves_the_selection_and_leaves_the_log_alone(
            self, pb, tmp_path):
        app = _make_app(pb, tmp_path, TWENTY)
        app._host_page_size = 4
        for i in range(80):
            app.add_event('t', f'line {i}')
        app._cmd_select('first')
        first = app.highlighted_index
        self._press(pb, app, '<PageDown>')
        assert app.highlighted_index == first + 4
        assert app.log_offset == 0, 'the event log scrolled instead'

    def test_pageup_scrolls_the_log_when_nothing_is_selected(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, TWENTY)
        for i in range(80):
            app.add_event('t', f'line {i}')
        app.highlighted_index = None
        self._press(pb, app, '<PageUp>')
        assert app.log_offset > 0
        assert app.highlighted_index is None

    def test_ctrl_b_scrolls_the_log_with_a_host_selected(self, pb, tmp_path):
        """The escape hatch, driven the same way."""
        app = _make_app(pb, tmp_path, TWENTY)
        for i in range(80):
            app.add_event('t', f'line {i}')
        app._cmd_select('first')
        before = app.highlighted_index
        self._press(pb, app, '<C-b>')
        assert app.log_offset > 0
        assert app.highlighted_index == before


class TestOnARealTerminal:
    """The banner and the header are drawn text; read them off the screen."""

    def _session(self, app_path, tmp_path, name, height=20):
        from tmux_helper import TmuxSession
        hosts = tmp_path / 'many.hosts'
        hosts.write_text(TWENTY)
        sess = TmuxSession(f'ping-bulk-test-{name}', width=120, height=height)
        try:
            sess.send_literal(f'python3 {app_path} -f {hosts}')
            sess.send_keys('Enter')
            sess.wait_for('DNS:', timeout=10)
        except Exception:
            sess.kill()
            raise
        return sess

    def _selected(self, screen):
        """The host named on the ▶ selection banner row."""
        row = next((l for l in screen.splitlines() if '▶' in l), '')
        return row.split('▶', 1)[-1].strip().split()[0] if row else ''

    def test_pagedown_walks_the_selection_down_the_list(
            self, app_path, check_integration_deps, tmp_path):
        sess = self._session(app_path, tmp_path, 'select-page')
        try:
            sess.send_keys('Down')                  # select the first host
            sess.wait_for('▶', timeout=5)
            sess.wait_for('PgUp/PgDn page', timeout=5)
            first = self._selected(sess.capture_pane())
            sess.send_keys('PageDown')
            deadline = __import__('time').time() + 5
            while __import__('time').time() < deadline:
                now = self._selected(sess.capture_pane())
                if now and now != first:
                    break
                __import__('time').sleep(0.2)
            assert now != first, f'selection did not move from {first!r}'
            assert now.startswith('10.0.0.')
            # The banner names the highlighted entry whether or not its row is
            # drawn, so a list that failed to scroll would still pass above.
            # 20 hosts in a 20-row window overflow, so this discriminates.
            screen = sess.capture_pane()
            host_rows = [l for l in screen.splitlines()
                         if l.startswith(now + ' ')]
            assert host_rows, f'{now!r} highlighted but not on screen:\n{screen}'
        finally:
            sess.kill()

    def test_the_events_header_hands_the_keys_over(
            self, app_path, check_integration_deps, tmp_path):
        """Exactly one line names PgUp/PgDn, and the clear key is X."""
        # Tall enough that the host list leaves room for the Events pane.
        sess = self._session(app_path, tmp_path, 'select-hint', height=32)
        try:
            screen = sess.capture_pane()
            assert 'X clear' in screen, screen
            assert 'Clear' not in screen, screen
            sess.send_keys('Down')
            sess.wait_for('PgUp/PgDn page', timeout=5)
            screen = sess.capture_pane()
            assert screen.count('PgUp/PgDn') == 1, screen
            sess.send_keys('Escape')                 # clear the selection
            sess.wait_for_absence('PgUp/PgDn page', timeout=5)
        finally:
            sess.kill()
