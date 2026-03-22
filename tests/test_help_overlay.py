"""Integration tests for the ping-bulk help overlay.

These tests drive a live ping-bulk process inside a tmux session and assert
on the rendered pane content.

Geometry recap
--------------
_HELP_LINES has 47 lines; _HELP_INNER_W = 70; box_w = 72.

  height | box_h_available | visible_count | max_scroll | indicator at scroll=0
  -------+-----------------+---------------+------------+----------------------
    40   |      40         |      38       |     9      |  ↑↓ 1-38/47
    50   |      49         |      47       |     0      |  none
    15   |      15         |      13       |    34      |  ↑↓ 1-13/47

Scroll sequences at 120×40:
  scroll=0 → Down → scroll=1: '2-39/47'
  scroll=0 → NPage (+10) → clamped to 9: '10-47/47'
  scroll=9 → Up → scroll=8: '9-46/47'
  scroll=9 → PPage (-10) → clamped to 0: '1-38/47'

At 120×15:
  scroll=0 → NPage (+10) → scroll=10 (< max_scroll=34, no clamp): '11-23/47'
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
    """At 120×40 the overlay cannot show all 47 lines → scroll indicator present."""

    def test_indicator_present_at_open(self, tmux_app_40):
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)

    def test_indicator_shows_initial_range(self, tmux_app_40):
        """Indicator at scroll=0: '↑↓ 1-38/47'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for('1-38/47')

    def test_scroll_down_one_line(self, tmux_app_40):
        """Pressing ↓ once advances to scroll=1: '↑↓ 2-39/47'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('Down')
        tmux_app_40.wait_for('2-39/47')

    def test_npage_clamps_to_max_scroll(self, tmux_app_40):
        """NPage adds 10 but max_scroll=9, so it clamps: '↑↓ 10-47/47'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')
        tmux_app_40.wait_for('10-47/47')

    def test_scroll_up_from_bottom(self, tmux_app_40):
        """After clamping to max_scroll=9, ↑ gives scroll=8: '↑↓ 9-46/47'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')   # → clamped to 9
        tmux_app_40.wait_for('10-47/47')
        tmux_app_40.send_keys('Up')
        tmux_app_40.wait_for('9-46/47')

    def test_ppage_from_bottom_returns_to_top(self, tmux_app_40):
        """PPage from scroll=9 subtracts 10, clamped to 0: '↑↓ 1-38/47'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.send_keys('NPage')   # → clamped to 9
        tmux_app_40.wait_for('10-47/47')
        tmux_app_40.send_keys('PPage')   # → 9-10 = -1, clamped to 0
        tmux_app_40.wait_for('1-38/47')


# ===========================================================================
# TestNoIndicatorAt50Rows
# ===========================================================================

class TestNoIndicatorAt50Rows:
    """At 120×50 all 47 lines fit → no scroll indicator in the border."""

    def test_no_indicator_at_open(self, tmux_app_50):
        tmux_app_50.send_keys('?')
        tmux_app_50.wait_for(OVERLAY_MARKER)
        content = tmux_app_50.capture_pane()
        assert SCROLL_PREFIX not in content, (
            f"Expected no scroll indicator at 50 rows, but found {SCROLL_PREFIX!r}.\n"
            f"Pane content:\n{content}"
        )

    def test_all_content_visible(self, tmux_app_50):
        """When no scrolling is needed, content from the last section is visible."""
        tmux_app_50.send_keys('?')
        tmux_app_50.wait_for('cartesian product')


# ===========================================================================
# TestScrollIndicatorAt15Rows
# ===========================================================================

class TestScrollIndicatorAt15Rows:
    """At 120×15 only 13 lines fit → large scroll range (max_scroll=34)."""

    def test_indicator_present_at_open(self, tmux_app_15):
        tmux_app_15.send_keys('?')
        tmux_app_15.wait_for(SCROLL_PREFIX)

    def test_indicator_shows_1_to_13(self, tmux_app_15):
        """Initial indicator: '↑↓ 1-13/47'."""
        tmux_app_15.send_keys('?')
        tmux_app_15.wait_for('1-13/47')

    def test_npage_not_clamped(self, tmux_app_15):
        """NPage adds 10; scroll=10 < max_scroll=34 so no clamping: '↑↓ 11-23/47'."""
        tmux_app_15.send_keys('?')
        tmux_app_15.wait_for(SCROLL_PREFIX)
        tmux_app_15.send_keys('NPage')
        tmux_app_15.wait_for('11-23/47')


# ===========================================================================
# TestResize
# ===========================================================================

class TestResize:
    """Resizing the terminal while the overlay is open updates the indicator."""

    def test_shrink_changes_indicator(self, tmux_app_40):
        """Shrink 120×40 → 120×15: indicator changes from '1-38/47' to '1-13/47'."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for('1-38/47')
        tmux_app_40.resize(width=120, height=15)
        tmux_app_40.wait_for('1-13/47')

    def test_grow_removes_indicator(self, tmux_app_40):
        """Grow 120×40 → 120×15 → 120×50: indicator disappears at full size."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(SCROLL_PREFIX)
        tmux_app_40.resize(width=120, height=15)
        tmux_app_40.wait_for('1-13/47')
        tmux_app_40.resize(width=120, height=50)
        tmux_app_40.wait_for_absence(SCROLL_PREFIX)
        # Overlay is still open — the close marker must still be visible.
        tmux_app_40.wait_for(OVERLAY_MARKER)

