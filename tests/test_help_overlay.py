"""Integration tests for the ping-bulk help overlay.

These tests drive a live ping-bulk process inside a tmux session and assert
on the rendered pane content.

Geometry recap
--------------
N = len(_FULL_HELP); inner_w is dynamic.
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

# N: total number of help lines; NO_SCROLL_HEIGHT: smallest height that fits all.
N = len(_mod._FULL_HELP)
NO_SCROLL_HEIGHT = N + 2


def _indicator(total, height, scroll):
    """Return the 'first-last/total' portion of the scroll indicator string."""
    visible = height - 2
    first = scroll + 1
    last = scroll + visible
    return f'{first}-{last}/{total}'

# Substring always present in the first help line, visible at scroll=0.
OVERLAY_MARKER = '[q / Esc] close'

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
        tmux_app_40.wait_for('ping-bulk:')


# ===========================================================================
# TestScrollIndicatorAt40Rows
# ===========================================================================

class TestScrollIndicatorAt40Rows:
    """At 120×40 the overlay cannot show all 51 lines → scroll indicator present."""

    def test_indicator_present_at_open(self, tmux_app_40):
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)

    def test_indicator_shows_initial_range(self, tmux_app_40):
        """Indicator at scroll=0: '↑↓ 1-38/N'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(_indicator(N, 40, 0))

    def test_scroll_down_one_line(self, tmux_app_40):
        """Pressing ↓ once advances to scroll=1: '↑↓ 2-39/N'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('Down')
        tmux_app_40.wait_for(_indicator(N, 40, 1))

    def test_npage_clamps_to_max_scroll(self, tmux_app_40):
        """NPage adds 10; max_scroll=13 so no clamp at scroll=10."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')
        tmux_app_40.wait_for(_indicator(N, 40, 10))

    def test_scroll_up_from_bottom(self, tmux_app_40):
        """After NPage to scroll=10, ↑ gives scroll=9."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')   # → scroll=10 (< max_scroll=13, no clamp)
        tmux_app_40.wait_for(_indicator(N, 40, 10))
        tmux_app_40.send_keys('Up')
        tmux_app_40.wait_for(_indicator(N, 40, 9))

    def test_ppage_from_bottom_returns_to_top(self, tmux_app_40):
        """PPage from scroll=10 subtracts 10, clamped to 0."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')   # → scroll=10
        tmux_app_40.wait_for(_indicator(N, 40, 10))
        tmux_app_40.send_keys('PPage')   # → 10-10 = 0
        tmux_app_40.wait_for(_indicator(N, 40, 0))


# ===========================================================================
# TestNoIndicatorAt50Rows
# ===========================================================================

class TestNoIndicatorAt53Rows:
    """At 120×53 all 51 lines fit (visible_count=51, max_scroll=0) → no scroll indicator."""

    def test_no_indicator_at_open(self, tmux_app_53):
        tmux_app_53.send_keys('?')
        tmux_app_53.wait_for(OVERLAY_MARKER)
        content = tmux_app_53.capture_pane()
        assert SCROLL_PREFIX not in content, (
            f"Expected no scroll indicator at 53 rows, but found {SCROLL_PREFIX!r}.\n"
            f"Pane content:\n{content}"
        )

    def test_all_content_visible(self, tmux_app_53):
        """When no scrolling is needed, content from the last section is visible."""
        tmux_app_53.send_keys('?')
        tmux_app_53.wait_for('cartesian product')


# ===========================================================================
# TestScrollIndicatorAt15Rows
# ===========================================================================

class TestScrollIndicatorAt15Rows:
    """At 120×15 only 13 lines fit → large scroll range (max_scroll=38)."""

    def test_indicator_present_at_open(self, tmux_app_15):
        tmux_app_15.send_keys('?')
        tmux_app_15.wait_for(SCROLL_PREFIX)

    def test_indicator_shows_1_to_13(self, tmux_app_15):
        """Initial indicator: '↑↓ 1-13/N'."""
        tmux_app_15.send_keys('?')
        tmux_app_15.wait_for(_indicator(N, 15, 0))

    def test_npage_not_clamped(self, tmux_app_15):
        """NPage adds 10; scroll=10 < max_scroll=N-13 so no clamping: '↑↓ 11-23/N'."""
        tmux_app_15.send_keys('?')
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
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(_indicator(N, 40, 0))
        tmux_app_40.resize(width=120, height=15)
        tmux_app_40.wait_for(_indicator(N, 15, 0))

    def test_grow_removes_indicator(self, tmux_app_40):
        """Grow 120×40 → 120×15 → NO_SCROLL_HEIGHT: indicator disappears at full size."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.resize(width=120, height=15)
        tmux_app_40.wait_for(_indicator(N, 15, 0))
        tmux_app_40.resize(width=120, height=NO_SCROLL_HEIGHT)
        tmux_app_40.wait_for_absence(SCROLL_PREFIX)
        # Overlay is still open — the close marker must still be visible.
        tmux_app_40.wait_for(OVERLAY_MARKER)

