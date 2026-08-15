"""Integration tests for the ping-bulk help overlay.

These tests drive a live ping-bulk process inside a tmux session and assert
on the rendered pane content.

Geometry recap
--------------
N = number of lines in tab-0 content (built by _build_tab_lines for tab 0);
NO_SCROLL_HEIGHT = N + 2  (smallest terminal height where all lines fit).

  height          | visible_count | max_scroll | indicator at scroll=0
  ----------------+---------------+------------+----------------------
    40            |      38       |   N-38     |  ↑↓ 1-38/N
    50            |      48       |   N-48     |  ↑↓ 1-48/N  (if N>48)
    NO_SCROLL_HEIGHT |    N       |    0       |  none
    15            |      13       |   N-13     |  ↑↓ 1-13/N

Scroll sequences at 120×40:
  scroll=0 → Down → scroll=1: '2-39/N'
  scroll=0 → NPage (+10) → scroll=10: '11-48/N'
  scroll=10 → Up → scroll=9: '10-47/N'
  scroll=10 → PPage (-10) → scroll=0: '1-38/N'

At 120×15:
  scroll=0 → NPage (+10) → scroll=10: '11-23/N'
"""

import importlib.machinery
import importlib.util
import os as _os

import pytest

_repo_root = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
_loader = importlib.machinery.SourceFileLoader(
    'ping_bulk', _os.path.join(_repo_root, 'ping-bulk')
)
_spec = importlib.util.spec_from_loader('ping_bulk', _loader)
_mod = importlib.util.module_from_spec(_spec)
_loader.exec_module(_mod)

# N: total number of help lines for tab 0; NO_SCROLL_HEIGHT: smallest height that fits all.
_tab0_fragments = _mod._join_help_fragments(
    _mod._HELP_LEGEND, _mod._HELP_HOTKEYS, _mod._HELP_SEARCH, _mod._HELP_FOLDING,
    _mod._HELP_CMDS_INTERACTIVE, _mod._HELP_SSH,
)
# _HELP_PINNED lines (tab bar + nav hint + -DIVIDER-) are always pinned at the top.
_PINNED = _mod.Application._HELP_PINNED
N = _PINNED + len(_tab0_fragments)  # tab bar + nav hint + -DIVIDER- + content
NO_SCROLL_HEIGHT = N + 2


def _indicator(total, height, scroll):
    """Return the 'first-last/total' portion of the scroll indicator string.

    *total* is the total number of lines in _build_tab_lines() (including
    pinned rows).  The indicator shows only the scrollable portion.
    """
    scrollable = total - _PINNED
    visible = height - 2 - _PINNED
    first = scroll + 1
    last = scroll + visible
    return f'{first}-{last}/{scrollable}'

# Substring always present in the tab bar at scroll=0.
OVERLAY_MARKER = 'Interactive'


def open_interactive(sess):
    """Open the help overlay on the Interactive tab (tab 0).

    `?` lands on the Bindings tab, so tests that assert against tab-0 content
    (N / _indicator) must select the tab explicitly rather than relying on
    whatever `?` happens to open.
    """
    sess.send_keys('?')
    sess.wait_for(OVERLAY_MARKER)
    sess.send_keys('1')

# Prefix of the scroll indicator embedded in the top border.
SCROLL_PREFIX = '↑↓'


# ===========================================================================
# TestOpenClose
# ===========================================================================

class TestOpenClose:
    """The overlay opens via '?' or ':help' and closes via q, Q, or Esc."""

    def test_open_with_question_mark(self, tmux_app_40):
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(OVERLAY_MARKER)

    def test_open_with_colon_help(self, tmux_app_40):
        tmux_app_40.send_keys(':', 'h', 'e', 'l', 'p', 'Enter')
        tmux_app_40.wait_for(OVERLAY_MARKER)

    def test_close_with_q(self, tmux_app_40):
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(OVERLAY_MARKER)
        tmux_app_40.send_keys('q')
        tmux_app_40.wait_for_absence(OVERLAY_MARKER)

    def test_close_with_capital_Q(self, tmux_app_40):
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(OVERLAY_MARKER)
        tmux_app_40.send_keys('Q')
        tmux_app_40.wait_for_absence(OVERLAY_MARKER)

    def test_close_with_escape(self, tmux_app_40):
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(OVERLAY_MARKER)
        tmux_app_40.send_keys('Escape')
        tmux_app_40.wait_for_absence(OVERLAY_MARKER)

    def test_menu_bar_restored_after_close(self, tmux_app_40):
        """After closing the overlay the main UI (menu bar) must be visible."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(OVERLAY_MARKER)
        tmux_app_40.send_keys('q')
        tmux_app_40.wait_for_absence(OVERLAY_MARKER)
        tmux_app_40.wait_for('DNS:')


# ===========================================================================
# TestScrollIndicatorAt40Rows
# ===========================================================================

class TestScrollIndicatorAt40Rows:
    """At 120×40 the overlay cannot show all lines → scroll indicator present."""

    def test_indicator_present_at_open(self, tmux_app_40):
        open_interactive(tmux_app_40)
        tmux_app_40.wait_for(SCROLL_PREFIX)

    def test_indicator_shows_initial_range(self, tmux_app_40):
        """Indicator at scroll=0: '↑↓ 1-38/N'."""
        open_interactive(tmux_app_40)
        tmux_app_40.wait_for(_indicator(N, 40, 0))

    def test_scroll_down_one_line(self, tmux_app_40):
        """Pressing ↓ once advances to scroll=1: '↑↓ 2-39/N'."""
        open_interactive(tmux_app_40)
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('Down')
        tmux_app_40.wait_for(_indicator(N, 40, 1))

    def test_npage_clamps_to_max_scroll(self, tmux_app_40):
        """NPage adds 10."""
        open_interactive(tmux_app_40)
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')
        tmux_app_40.wait_for(_indicator(N, 40, 10))

    def test_scroll_up_from_bottom(self, tmux_app_40):
        """After NPage to scroll=10, ↑ gives scroll=9."""
        open_interactive(tmux_app_40)
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')
        tmux_app_40.wait_for(_indicator(N, 40, 10))
        tmux_app_40.send_keys('Up')
        tmux_app_40.wait_for(_indicator(N, 40, 9))

    def test_ppage_from_bottom_returns_to_top(self, tmux_app_40):
        """PPage from scroll=10 subtracts 10, clamped to 0."""
        open_interactive(tmux_app_40)
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')
        tmux_app_40.wait_for(_indicator(N, 40, 10))
        tmux_app_40.send_keys('PPage')
        tmux_app_40.wait_for(_indicator(N, 40, 0))


# ===========================================================================
# TestNoIndicatorAtNoScrollRows
# ===========================================================================

class TestNoIndicatorAt53Rows:
    """At 120×NO_SCROLL_HEIGHT all lines fit (visible_count=N, max_scroll=0) → no scroll indicator."""

    def test_no_indicator_at_open(self, tmux_app_53):
        open_interactive(tmux_app_53)
        tmux_app_53.wait_for(OVERLAY_MARKER)
        content = tmux_app_53.capture_pane()
        assert SCROLL_PREFIX not in content, (
            f"Expected no scroll indicator at NO_SCROLL_HEIGHT rows, but found {SCROLL_PREFIX!r}.\n"
            f"Pane content:\n{content}"
        )

    def test_all_content_visible(self, tmux_app_53):
        """When no scrolling is needed, content from the last section is visible."""
        open_interactive(tmux_app_53)
        tmux_app_53.wait_for(':set terminal')


# ===========================================================================
# TestScrollIndicatorAt15Rows
# ===========================================================================

class TestScrollIndicatorAt15Rows:
    """At 120×15 only 13 lines fit → large scroll range."""

    def test_indicator_present_at_open(self, tmux_app_15):
        open_interactive(tmux_app_15)
        tmux_app_15.wait_for(SCROLL_PREFIX)

    def test_indicator_shows_1_to_13(self, tmux_app_15):
        """Initial indicator: '↑↓ 1-13/N'."""
        open_interactive(tmux_app_15)
        tmux_app_15.wait_for(_indicator(N, 15, 0))

    def test_npage_not_clamped(self, tmux_app_15):
        """NPage adds 10; scroll=10 < max_scroll so no clamping."""
        open_interactive(tmux_app_15)
        tmux_app_15.wait_for(SCROLL_PREFIX)
        tmux_app_15.send_keys('NPage')
        tmux_app_15.wait_for(_indicator(N, 15, 10))


# ===========================================================================
# TestResize
# ===========================================================================

class TestResize:
    """Resizing the terminal while the overlay is open updates the indicator."""

    def test_shrink_changes_indicator(self, tmux_app_40):
        """Shrink 120×40 → 120×15: indicator updates from '1-38/N' to '1-13/N'."""
        open_interactive(tmux_app_40)
        tmux_app_40.wait_for(_indicator(N, 40, 0))
        tmux_app_40.resize(width=120, height=15)
        tmux_app_40.wait_for(_indicator(N, 15, 0))

    def test_grow_removes_indicator(self, tmux_app_40):
        """Grow 120×40 → NO_SCROLL_HEIGHT: indicator disappears at full size."""
        open_interactive(tmux_app_40)
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.resize(width=120, height=15)
        tmux_app_40.wait_for(_indicator(N, 15, 0))
        tmux_app_40.resize(width=120, height=NO_SCROLL_HEIGHT)
        tmux_app_40.wait_for_absence(SCROLL_PREFIX)
        # Overlay is still open — the marker must still be visible.
        tmux_app_40.wait_for(OVERLAY_MARKER)


# ===========================================================================
# :help <tab> argument and toggle memory  (unit-level, no tmux)
# ===========================================================================

def _unit_app(tmp_path):
    """Build a non-running Application with a temp config path."""
    import os
    from unittest.mock import patch
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    with patch.object(_mod, '_config_path', return_value=cfg):
        return _mod.Application([('host', '127.0.0.1')])


class TestHelpTabArgument:
    """:help used to accept an argument and silently ignore it."""

    def test_no_arg_opens_interactive(self, tmp_path):
        app = _unit_app(tmp_path)
        app._cmd_help()
        assert app.help_open is True
        assert app.help_tab == 0

    @pytest.mark.parametrize('arg,expected', [
        ('interactive', 0),
        ('hosts', 1),
        ('example', 2),
        ('commands', 3),
        ('bindings', 4),
        ('settings', 5),
    ])
    def test_tab_by_name(self, tmp_path, arg, expected):
        app = _unit_app(tmp_path)
        app._cmd_help(arg)
        assert app.help_tab == expected

    def test_name_is_case_insensitive(self, tmp_path):
        app = _unit_app(tmp_path)
        app._cmd_help('BINDINGS')
        assert app.help_tab == 4

    def test_unique_prefix_accepted(self, tmp_path):
        app = _unit_app(tmp_path)
        app._cmd_help('bind')
        assert app.help_tab == 4

    @pytest.mark.parametrize('num,expected', [
        ('1', 0), ('2', 1), ('3', 2), ('4', 3), ('5', 4), ('6', 5),
    ])
    def test_tab_by_number_is_one_based(self, tmp_path, num, expected):
        """Numbers match the tab bar labels and the 1-6 overlay keys."""
        app = _unit_app(tmp_path)
        app._cmd_help(num)
        assert app.help_tab == expected

    def test_number_matches_overlay_key(self, tmp_path):
        """':help 5' must land where pressing '5' in the overlay lands."""
        app = _unit_app(tmp_path)
        binding, _ = app._key_trie.resolve([ord('5')], set(), mode='help')
        assert binding is not None
        assert binding.commands == [':help 5']
        app._cmd_help('5')
        assert app._TAB_NAMES[app.help_tab] == 'Bindings'

    def test_unknown_tab_does_not_open(self, tmp_path):
        app = _unit_app(tmp_path)
        app._cmd_help('nope')
        assert app.help_open is False
        assert any('unknown tab' in e.text for e in app.events)

    def test_out_of_range_number_rejected(self, tmp_path):
        app = _unit_app(tmp_path)
        app._cmd_help('9')
        assert app.help_open is False

    def test_zero_is_rejected(self, tmp_path):
        """Numbering starts at 1, so 0 is not a tab."""
        app = _unit_app(tmp_path)
        app._cmd_help('0')
        assert app.help_open is False

    def test_question_mark_binding_targets_bindings_tab(self, tmp_path):
        app = _unit_app(tmp_path)
        binding, _ = app._key_trie.resolve(_mod._parse_key_notation('?'), set())
        assert binding is not None
        assert binding.commands == [':help bindings']


class TestHelpTabSwitching:
    """:help doubles as the tab switcher; the separate :help-tab command is gone."""

    def test_help_tab_command_removed(self, pb=None):
        assert 'help-tab' not in _mod._CMD_MAP

    def test_switch_by_name_while_open(self, tmp_path):
        app = _unit_app(tmp_path)
        app._cmd_help()
        app._cmd_help('settings')
        assert app.help_tab == 5

    def test_next_and_prev_wrap(self, tmp_path):
        app = _unit_app(tmp_path)
        app._cmd_help()
        app._cmd_help('prev')
        assert app.help_tab == 5
        app._cmd_help('next')
        assert app.help_tab == 0

    def test_bare_help_keeps_tab_when_already_open(self, tmp_path):
        """Re-running :help must not yank an open overlay back to tab 1."""
        app = _unit_app(tmp_path)
        app._cmd_help('bindings')
        app._cmd_help()
        assert app.help_tab == 4

    def test_switching_tabs_preserves_scroll(self, tmp_path):
        """Per-tab scroll offsets survive a tab switch in an open overlay."""
        app = _unit_app(tmp_path)
        app._cmd_help()
        app._tab_scroll[0] = 7
        app._cmd_help('commands')
        app._cmd_help('interactive')
        assert app._tab_scroll[0] == 7

    def test_fresh_open_resets_scroll(self, tmp_path):
        app = _unit_app(tmp_path)
        app._cmd_help()
        app._tab_scroll[0] = 7
        app.help_open = False          # simulate closing the overlay
        app._cmd_help()
        assert app._tab_scroll[0] == 0

    def test_toggle_settings_returns_to_origin_tab(self, tmp_path):
        """Toggling out of Settings must return where you came from.

        It used to step to index-1, so leaving Settings always landed on
        Bindings regardless of the origin tab.
        """
        app = _unit_app(tmp_path)
        app._cmd_help('example')          # tab 2
        app._cmd_help_toggle_settings()   # -> 5
        assert app.help_tab == 5
        app._cmd_help_toggle_settings()   # -> back to 2, not 4
        assert app.help_tab == 2

    def test_toggle_all_returns_to_origin_tab(self, tmp_path):
        app = _unit_app(tmp_path)
        app._cmd_help('hosts')            # tab 1
        app._cmd_help_toggle_all()        # -> 4
        assert app.help_tab == 4
        app._cmd_help_toggle_all()        # -> back to 1, not 3
        assert app.help_tab == 1
