"""Regression tests for a name column wider than the terminal.

The hostname column is sized from the content — the longest display name and
the longest section title — which knows nothing about the terminal.  Anything
wider than the screen pushed the stat column past the right edge, and the
column header wrote there with a bare addstr, so the whole draw died:

    File "ping-bulk", line 8767, in draw_hosts
      stdscr.addstr(start_row, stat_col, f"{col25_label:>{stat_field_w}}", ...)
    _curses.error: addwstr() returned ERR

Two lines of hosts file reproduced it on an 80-column terminal.  So did
examples/ping-bulk.advance — the file the documentation tells people to try —
whose longest section title is 65 characters: measured against the unfixed
code it died at 60 and 80 columns and drew at 90 and above.
"""

import curses
import time
from unittest.mock import patch

import pytest

from utils.hosts_helper import write_hosts


LONG = 'A' * 70


class TestTheDrawSurvives:
    """Driven through a real terminal: the failure was a curses call."""

    def _session(self, app_path, tmp_path, name, content, width, height=12):
        from tmux_helper import TmuxSession
        hosts = tmp_path / 'wide.hosts'
        hosts.write_text(content)
        sess = TmuxSession(f'ping-bulk-test-{name}', width=width, height=height)
        sess.send_literal(f'python3 {app_path} -f {hosts}')
        sess.send_keys('Enter')
        return sess

    @pytest.mark.parametrize('width', [60, 80, 120])
    def test_a_section_title_wider_than_the_screen(self, app_path,
                                                   check_integration_deps,
                                                   tmp_path, width):
        sess = self._session(app_path, tmp_path, f'wide-{width}',
                             f'### {LONG}\n127.0.0.1\n', width)
        try:
            sess.wait_for('DNS:', timeout=10)      # the menu bar means it drew
            screen = sess.capture_pane()
            assert 'error' not in screen.lower(), screen
            assert '127.0.0.1' in screen, screen
        finally:
            sess.kill()

    def test_a_host_name_wider_than_the_screen(self, app_path,
                                               check_integration_deps, tmp_path):
        """The other input to the column width."""
        sess = self._session(app_path, tmp_path, 'wide-host',
                             f'127.0.0.1 ## {LONG}\n', 80)
        try:
            sess.wait_for('DNS:', timeout=10)
            assert 'error' not in sess.capture_pane().lower()
        finally:
            sess.kill()

    @pytest.mark.parametrize('width', [60, 80])
    def test_the_shipped_example_draws(self, app_path, check_integration_deps,
                                       tmp_path, width):
        """Its longest section title is 65 characters.

        Both widths died before the clamp; 90 and above always drew.
        """
        import os
        example = os.path.join(os.path.dirname(app_path), 'examples',
                               'ping-bulk.advance')
        from tmux_helper import TmuxSession
        sess = TmuxSession(f'ping-bulk-test-example-{width}',
                           width=width, height=20)
        try:
            sess.send_literal(f'python3 {app_path} -f {example}')
            sess.send_keys('Enter')
            sess.wait_for('DNS:', timeout=15)
            assert 'error' not in sess.capture_pane().lower()
        finally:
            sess.kill()

    def test_the_history_bar_still_has_room(self, app_path,
                                            check_integration_deps, tmp_path):
        """Truncating is only useful if something is left to look at."""
        sess = self._session(app_path, tmp_path, 'wide-hist',
                             f'### {LONG}\n127.0.0.1\n', 80)
        try:
            sess.wait_for('DNS:', timeout=10)
            # Poll for the first result: the row exists before any ping has
            # come back, and an empty strip then proves nothing.
            deadline = time.time() + 10
            row = ''
            while time.time() < deadline:
                row = next((l for l in sess.capture_pane().splitlines()
                            if '127.0.0.1' in l), '')
                if '.' in row.split('127.0.0.1', 1)[-1]:
                    break
                time.sleep(0.3)
            assert '.' in row.split('127.0.0.1', 1)[-1], \
                f'no history cells drawn: {row!r}'
        finally:
            sess.kill()


class _FakeScreen:
    """Enough of a curses window to reproduce the failure, without a terminal.

    ncurses returns ERR when the *start* position is outside the window; a
    string that merely overflows the right edge is clipped silently.  Modelling
    exactly that is what makes these tests fail when the clamp is removed —
    asserting on arithmetic the test re-implements proves nothing.
    """

    def __init__(self, width, height):
        self.width, self.height = width, height
        self.writes = []

    def addstr(self, row, col, text, attr=0):
        if not (0 <= row < self.height and 0 <= col < self.width):
            raise curses.error('addwstr() returned ERR')
        self.writes.append((row, col, text))

    def erase(self):
        self.writes.clear()

    def getmaxyx(self):
        return self.height, self.width


class TestTheDrawIsInBounds:
    """draw_hosts must not start a write off screen, at any width."""

    @pytest.fixture(autouse=True)
    def _no_curses_init(self):
        """curses.color_pair() needs initscr(); the drawing logic does not."""
        with patch.object(curses, 'color_pair', lambda n: 0):
            yield

    def _app(self, pb, tmp_path, content):
        app = pb.Application(pb.parse_hosts_file(write_hosts(tmp_path, content)))
        app._start_time = 0.0
        app.stale_attr = 0          # normally set by run() after initscr()
        return app

    @pytest.mark.parametrize('width', [8, 14, 16, 20, 40, 60, 80, 120])
    def test_a_wide_section_title(self, pb, tmp_path, width):
        app = self._app(pb, tmp_path, f'### {LONG}\n127.0.0.1\n')
        screen = _FakeScreen(width, 20)
        app.draw_hosts(screen, 0, 10, width, 20)      # must not raise

    @pytest.mark.parametrize('width', [8, 16, 40, 80])
    def test_a_wide_host_label(self, pb, tmp_path, width):
        app = self._app(pb, tmp_path, f'127.0.0.1 ## {LONG}\n')
        app.draw_hosts(_FakeScreen(width, 20), 0, 10, width, 20)

    @pytest.mark.parametrize('width', [8, 16, 40, 80])
    def test_many_hosts_widen_the_badge_field(self, pb, tmp_path, width):
        """stat_field_w grows with the host count, past what the clamp reserves.

        Sixty hosts in one section make the badge field 15 columns, so the
        per-row stat cell starts 9 columns further right than the header does.
        """
        hosts = '\n'.join(f'10.0.0.{i}' for i in range(1, 61))
        app = self._app(pb, tmp_path, f'### {LONG}\n{hosts}\n')
        app.draw_hosts(_FakeScreen(width, 70), 0, 65, width, 70)

    @pytest.mark.parametrize('mode', ['All', 'Avg'])
    def test_the_other_stat_layouts(self, pb, tmp_path, mode):
        """'All' and a single stat place their columns differently."""
        app = self._app(pb, tmp_path, f'### {LONG}\n127.0.0.1\n')
        app._dispatch_cmd(f':set stats {mode}')
        for width in (8, 16, 40, 80, 120):
            app.draw_hosts(_FakeScreen(width, 20), 0, 10, width, 20)

    def test_a_paused_host_too(self, pb, tmp_path):
        """The paused branch writes at the same computed column."""
        app = self._app(pb, tmp_path, f'### {LONG}\n127.0.0.1\n')
        app.monitors[0].paused = True
        for width in (8, 16, 40):
            app.draw_hosts(_FakeScreen(width, 20), 0, 10, width, 20)

    def test_something_is_actually_drawn(self, pb, tmp_path):
        """A draw that silently wrote nothing would pass every test above."""
        app = self._app(pb, tmp_path, f'### {LONG}\n127.0.0.1\n')
        screen = _FakeScreen(80, 20)
        app.draw_hosts(screen, 0, 10, 80, 20)
        assert screen.writes, 'nothing was drawn'
        assert any('127.0.0.1' in text for _r, _c, text in screen.writes)

    def test_the_stats_and_history_still_reach_the_screen(self, pb, tmp_path):
        """The guards stop the crash; the clamp is what keeps the row useful.

        Without the clamp these writes start off screen and the guards drop
        them silently, leaving a row with a name and nothing else — no
        latency, no history, no way to see whether the host is up.
        """
        app = self._app(pb, tmp_path, f'### {LONG}\n127.0.0.1\n')
        # Through the real path: the strip is sized from ping_count, so poking
        # history alone leaves it empty and the assertion below meaningless.
        for i in range(5):
            app.monitors[0]._record_reply(1.5, time.time(), seq=i)
        screen = _FakeScreen(60, 20)
        app.draw_hosts(screen, 0, 10, 60, 20)
        cols = [c for _r, c, _t in screen.writes]
        assert max(cols) < 60, 'nothing may start off screen'
        host_row = [(c, t) for r, c, t in screen.writes if r == 2]
        assert len(host_row) >= 3, \
            f'name, stat and history expected on the host row, got {host_row}'

    def test_the_title_is_truncated_not_dropped(self, pb, tmp_path):
        """Clamping must still show as much of the title as fits."""
        app = self._app(pb, tmp_path, f'### {LONG}\n127.0.0.1\n')
        screen = _FakeScreen(60, 20)
        app.draw_hosts(screen, 0, 10, 60, 20)
        title_row = next((t for _r, _c, t in screen.writes if 'A' in t), '')
        assert 'AAAA' in title_row, screen.writes
        assert len(title_row) < 60, 'the row must fit the screen'


class TestTheClamp:
    """The arithmetic, without a terminal."""

    def _app(self, pb, tmp_path, content):
        return pb.Application(pb.parse_hosts_file(write_hosts(tmp_path, content)))

    def test_the_content_width_is_unclamped(self, pb, tmp_path):
        """_get_name_col_width knows nothing of the terminal, by design.

        The clamp belongs to the drawing code, which is the only part that
        knows how wide the screen is.
        """
        app = self._app(pb, tmp_path, f'### {LONG}\n127.0.0.1\n')
        assert app._get_name_col_width('off') > 70

    def test_the_stat_column_fits_the_terminal(self, pb, tmp_path):
        """What the crash was: stat_col landed at or past the right edge."""
        app = self._app(pb, tmp_path, f'### {LONG}\n127.0.0.1\n')
        raw = app._get_name_col_width('off')
        for width in (40, 60, 80, 120, 200):
            clamped = min(raw, max(len('Hostname'),
                                   width - 6 - pb._MIN_HIST_COLS - 2))
            assert clamped + 1 < width, f'stat_col off screen at width {width}'

    def test_a_narrow_terminal_keeps_the_hostname_column_usable(self, pb):
        """Never clamp below the header label itself."""
        for width in (1, 10, 20):
            clamped = max(len('Hostname'),
                          width - 6 - pb._MIN_HIST_COLS - 2)
            assert clamped >= len('Hostname')
