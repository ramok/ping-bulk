"""Integration tests for Ctrl+C handling in ping-bulk.

Ctrl+C behaviour per UI layer
------------------------------
normal mode      — opens a ``quit_confirm`` prompt ("Quit? [y/N]:")
help overlay     — closes the overlay (same as q / Q / Esc)
command mode     — cancels the command line (same as Esc)
any prompt       — cancels the prompt (same as Esc)

quit_confirm prompt
-------------------
y / Y  → set running=False (app exits; "ping-bulk:" disappears from pane)
any other key (n, Esc, Enter, Ctrl+C) → dismiss without quitting
"""

import pytest

# Substrings used as wait targets / absence markers.
MENU_BAR       = 'ping-bulk:'
QUIT_PROMPT    = 'Quit? [y/N]:'
HELP_MARKER    = '[q / Esc] close'
CLEAR_PROMPT   = 'Clear event log? [y/N]:'


# ===========================================================================
# TestQuitConfirmPrompt
# ===========================================================================

class TestQuitConfirmPrompt:
    """Ctrl+C in normal mode opens a quit_confirm prompt; keys are handled correctly."""

    def test_ctrl_c_opens_quit_prompt(self, tmux_app_40):
        """Ctrl+C in normal mode shows 'Quit? [y/N]:' on the bottom line."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_PROMPT)

    def test_y_confirms_quit(self, tmux_app_40):
        """Pressing y in the quit_confirm prompt exits the application."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_PROMPT)
        tmux_app_40.send_keys('y')
        tmux_app_40.wait_for_absence(MENU_BAR)

    def test_capital_Y_confirms_quit(self, tmux_app_40):
        """Pressing Y (uppercase) in the quit_confirm prompt also exits the application."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_PROMPT)
        tmux_app_40.send_keys('Y')
        tmux_app_40.wait_for_absence(MENU_BAR)

    def test_n_dismisses_without_quitting(self, tmux_app_40):
        """Pressing n dismisses the prompt; the app keeps running."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_PROMPT)
        tmux_app_40.send_keys('n')
        tmux_app_40.wait_for_absence(QUIT_PROMPT)
        tmux_app_40.wait_for(MENU_BAR)

    def test_escape_dismisses_without_quitting(self, tmux_app_40):
        """Esc dismisses the prompt; the app keeps running."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_PROMPT)
        tmux_app_40.send_keys('Escape')
        tmux_app_40.wait_for_absence(QUIT_PROMPT)
        tmux_app_40.wait_for(MENU_BAR)

    def test_enter_dismisses_without_quitting(self, tmux_app_40):
        """Enter (not y/Y) dismisses the prompt; the app keeps running."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_PROMPT)
        tmux_app_40.send_keys('Enter')
        tmux_app_40.wait_for_absence(QUIT_PROMPT)
        tmux_app_40.wait_for(MENU_BAR)

    def test_ctrl_c_in_prompt_dismisses_without_quitting(self, tmux_app_40):
        """Ctrl+C inside the quit_confirm prompt cancels it (does not quit)."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_PROMPT)
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for_absence(QUIT_PROMPT)
        tmux_app_40.wait_for(MENU_BAR)

    def test_second_ctrl_c_can_reopen_prompt(self, tmux_app_40):
        """After dismissing with n, Ctrl+C can open the quit prompt again."""
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_PROMPT)
        tmux_app_40.send_keys('n')
        tmux_app_40.wait_for_absence(QUIT_PROMPT)
        # Re-open
        tmux_app_40.send_keys('C-c')
        tmux_app_40.wait_for(QUIT_PROMPT)


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

