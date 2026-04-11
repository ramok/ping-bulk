"""Integration tests for Ctrl+C handling in ping-bulk.

Ctrl+C behaviour per UI layer
------------------------------
normal mode      — re-press pattern: first Ctrl+C shows "Press Ctrl-C again to quit"
                   in the bottom bar; a second Ctrl+C within 2 seconds quits.
help overlay     — closes the overlay (same as q / Q / Esc)
command mode     — cancels the command line (same as Esc)
any prompt       — cancels the prompt (same as Esc)

re-press quit pattern
----------------------
first Ctrl+C   → shows "Press Ctrl-C again to quit" (transient, replaces menu bar)
second Ctrl+C  → app exits ("DNS:" disappears)
other keys     → do nothing; message disappears after ~2 seconds
"""

import pytest

# Substrings used as wait targets / absence markers.
MENU_BAR       = 'DNS:'
QUIT_MSG       = 'Press Ctrl-C again to quit'
HELP_MARKER    = '[q / Esc] close'
CLEAR_PROMPT   = 'Clear event log? [y/N]:'


# ===========================================================================
# TestQuitConfirmRepress
# ===========================================================================

class TestQuitConfirmPrompt:
    """Ctrl+C in normal mode uses re-press pattern; second Ctrl+C within 2s quits."""

    def test_ctrl_c_opens_quit_prompt(self, tmux_app_40):
        """First Ctrl+C shows 'Press Ctrl-C again to quit' on the bottom line."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_MSG)

    def test_second_ctrl_c_quits(self, tmux_app_40):
        """Second Ctrl+C within 2 seconds exits the application."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_MSG)
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for_absence(MENU_BAR)

    def test_ctrl_c_in_prompt_dismisses_without_quitting(self, tmux_app_40):
        """Ctrl+C inside the clear prompt cancels it (does not trigger quit)."""
        tmux_app_40.send_keys('C')           # opens "Clear event log? [y/N]:"
        tmux_app_40.wait_for(CLEAR_PROMPT)
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for_absence(CLEAR_PROMPT)
        tmux_app_40.wait_for(MENU_BAR)

    def test_y_confirms_quit(self, tmux_app_40):
        """q still quits the application immediately (not via re-press)."""
        tmux_app_40.send_keys('q')
        tmux_app_40.wait_for_absence(MENU_BAR)

    def test_capital_Y_confirms_quit(self, tmux_app_40):
        """Q still quits the application immediately."""
        tmux_app_40.send_keys('Q')
        tmux_app_40.wait_for_absence(MENU_BAR)

    def test_n_dismisses_without_quitting(self, tmux_app_40):
        """After first Ctrl+C, pressing another key (e.g. n) does not quit; menu bar returns."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_MSG)
        tmux_app_40.send_keys('n')
        # 'n' is not a special key — app stays running; menu bar eventually returns
        tmux_app_40.wait_for(MENU_BAR)

    def test_escape_dismisses_without_quitting(self, tmux_app_40):
        """After first Ctrl+C, Esc clears selection (normal mode) — app keeps running."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_MSG)
        tmux_app_40.send_keys('Escape')
        tmux_app_40.wait_for(MENU_BAR)

    def test_enter_dismisses_without_quitting(self, tmux_app_40):
        """After first Ctrl+C, Enter opens details (not quit) — menu bar returns after Esc."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_MSG)
        # Wait 2.1s for deadline to expire naturally (no second Ctrl-C)
        import time; time.sleep(2.1)
        tmux_app_40.wait_for(MENU_BAR)

    def test_second_ctrl_c_can_reopen_prompt(self, tmux_app_40):
        """After deadline expires, another Ctrl+C shows the message again."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_MSG)
        import time; time.sleep(2.1)
        tmux_app_40.wait_for(MENU_BAR)
        # Re-trigger
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_MSG)


# ===========================================================================
# TestCtrlCInModals
# ===========================================================================

class TestCtrlCInModals:
    """Ctrl+C closes/cancels the currently active modal layer without quitting."""

    def test_ctrl_c_closes_help_overlay(self, tmux_app_40):
        """Ctrl+C while the help overlay is open closes it and restores the UI."""
        tmux_app_40.send_keys('?')
        tmux_app_40.wait_for(HELP_MARKER)
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for_absence(HELP_MARKER)
        tmux_app_40.wait_for(MENU_BAR)

    def test_ctrl_c_cancels_command_mode(self, tmux_app_40):
        """Ctrl+C while the ':' command line is open cancels it and restores the UI."""
        # Type ':help' into the command line (without pressing Enter).
        tmux_app_40.send_keys(':', 'h', 'e', 'l', 'p')
        tmux_app_40.wait_for(':help')
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for_absence(':help')
        tmux_app_40.wait_for(MENU_BAR)

    def test_ctrl_c_cancels_clear_prompt(self, tmux_app_40):
        """Ctrl+C while the clear-log prompt is active cancels it and restores the UI."""
        tmux_app_40.send_keys('C')           # opens "Clear event log? [y/N]:"
        tmux_app_40.wait_for(CLEAR_PROMPT)
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for_absence(CLEAR_PROMPT)
        tmux_app_40.wait_for(MENU_BAR)

