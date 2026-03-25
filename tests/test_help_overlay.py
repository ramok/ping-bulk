"""Integration tests for the ping-bulk help overlay.

These tests drive a live ping-bulk process inside a tmux session and assert
on the rendered pane content.

Geometry recap
--------------
_HELP_LINES has 50 lines; _HELP_INNER_W = 70; box_w = 72.

  height | box_h_available | visible_count | max_scroll | indicator at scroll=0
  -------+-----------------+---------------+------------+----------------------
    40   |      40         |      38       |    12      |  ↑↓ 1-38/50
    50   |      50         |      48       |     2      |  ↑↓ 1-48/50
    52   |      52         |      50       |     0      |  none
    15   |      15         |      13       |    37      |  ↑↓ 1-13/50

Scroll sequences at 120×40:
  scroll=0 → Down → scroll=1: '2-39/50'
  scroll=0 → NPage (+10) → scroll=10 (< max_scroll=12, no clamp): '11-48/50'
  scroll=10 → Up → scroll=9: '10-47/50'
  scroll=10 → PPage (-10) → scroll=0: '1-38/50'

At 120×15:
  scroll=0 → NPage (+10) → scroll=10 (< max_scroll=37, no clamp): '11-23/50'
"""

import pytest

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
    """At 120×40 the overlay cannot show all 50 lines → scroll indicator present."""

    def test_indicator_present_at_open(self, tmux_app_40):
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)

    def test_indicator_shows_initial_range(self, tmux_app_40):
        """Indicator at scroll=0: '↑↓ 1-38/50'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for('1-38/50')

    def test_scroll_down_one_line(self, tmux_app_40):
        """Pressing ↓ once advances to scroll=1: '↑↓ 2-39/50'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('Down')
        tmux_app_40.wait_for('2-39/50')

    def test_npage_clamps_to_max_scroll(self, tmux_app_40):
        """NPage adds 10; max_scroll=12 so no clamp at scroll=10: '↑↓ 11-48/50'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')
        tmux_app_40.wait_for('11-48/50')

    def test_scroll_up_from_bottom(self, tmux_app_40):
        """After NPage to scroll=10, ↑ gives scroll=9: '↑↓ 10-47/50'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')   # → scroll=10 (< max_scroll=12, no clamp)
        tmux_app_40.wait_for('11-48/50')
        tmux_app_40.send_keys('Up')
        tmux_app_40.wait_for('10-47/50')

    def test_ppage_from_bottom_returns_to_top(self, tmux_app_40):
        """PPage from scroll=10 subtracts 10, clamped to 0: '↑↓ 1-38/50'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')   # → scroll=10
        tmux_app_40.wait_for('11-48/50')
        tmux_app_40.send_keys('PPage')   # → 10-10 = 0
        tmux_app_40.wait_for('1-38/50')


# ===========================================================================
# TestNoIndicatorAt50Rows
# ===========================================================================

class TestNoIndicatorAt52Rows:
    """At 120×52 all 50 lines fit (visible_count=50, max_scroll=0) → no scroll indicator."""

    def test_no_indicator_at_open(self, tmux_app_52):
        tmux_app_52.send_keys('?')
        tmux_app_52.wait_for(OVERLAY_MARKER)
        content = tmux_app_52.capture_pane()
        assert SCROLL_PREFIX not in content, (
            f"Expected no scroll indicator at 52 rows, but found {SCROLL_PREFIX!r}.\n"
            f"Pane content:\n{content}"
        )

    def test_all_content_visible(self, tmux_app_52):
        """When no scrolling is needed, content from the last section is visible."""
        tmux_app_52.send_keys('?')
        tmux_app_52.wait_for('cartesian product')


# ===========================================================================
# TestScrollIndicatorAt15Rows
# ===========================================================================

class TestScrollIndicatorAt15Rows:
    """At 120×15 only 13 lines fit → large scroll range (max_scroll=37)."""

    def test_indicator_present_at_open(self, tmux_app_15):
        tmux_app_15.send_keys('?')
        tmux_app_15.wait_for(SCROLL_PREFIX)

    def test_indicator_shows_1_to_13(self, tmux_app_15):
        """Initial indicator: '↑↓ 1-13/50'."""
        tmux_app_15.send_keys('?')
        tmux_app_15.wait_for('1-13/50')

    def test_npage_not_clamped(self, tmux_app_15):
        """NPage adds 10; scroll=10 < max_scroll=37 so no clamping: '↑↓ 11-23/50'."""
        tmux_app_15.send_keys('?')
        tmux_app_15.wait_for(SCROLL_PREFIX)
        tmux_app_15.send_keys('NPage')
        tmux_app_15.wait_for('11-23/50')


# ===========================================================================
# TestResize
# ===========================================================================

class TestResize:
    """Resizing the terminal while the overlay is open updates the indicator."""

    def test_shrink_changes_indicator(self, tmux_app_40):
        """Shrink 120×40 → 120×15: indicator changes from '1-38/50' to '1-13/50'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for('1-38/50')
        tmux_app_40.resize(width=120, height=15)
        tmux_app_40.wait_for('1-13/50')

    def test_grow_removes_indicator(self, tmux_app_40):
        """Grow 120×40 → 120×15 → 120×52: indicator disappears at full size."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.resize(width=120, height=15)
        tmux_app_40.wait_for('1-13/50')
        tmux_app_40.resize(width=120, height=52)
        tmux_app_40.wait_for_absence(SCROLL_PREFIX)
        # Overlay is still open — the close marker must still be visible.
        tmux_app_40.wait_for(OVERLAY_MARKER)

