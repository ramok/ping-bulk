"""Integration tests for host/section navigation wrap-around.

Up/Down (and k/j) must cycle: pressing Down on the last visible entry wraps
to the first, and pressing Up on the first visible entry wraps to the last.
"""
import time

import pytest

from tmux_helper import TmuxSession


DETAILS_MARKER = '[Enter/q/Esc] Close'


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wait_details(pane):
    pane.send_keys('Enter')
    pane.wait_for(DETAILS_MARKER, timeout=5)


def _close_details(pane):
    pane.send_keys('Escape')
    pane.wait_for_absence(DETAILS_MARKER, timeout=5)


# ---------------------------------------------------------------------------
# Fixture: two hosts so wrap-around is observable
# ---------------------------------------------------------------------------

@pytest.fixture
def two_host_app(app_path, check_integration_deps, tmp_path):
    """ping-bulk with two hosts: 127.0.0.1 and 127.0.0.2."""
    config = tmp_path / 'two_hosts'
    config.write_text('127.0.0.1\n127.0.0.2\n')
    sess_name = 'ping-bulk-test-nav-wrap'
    sess = TmuxSession(sess_name, width=120, height=40)
    try:
        sess.send_literal(f'python3 {app_path} -f {config}')
        sess.send_keys('Enter')
        sess.wait_for('DNS:', timeout=10)
    except Exception:
        sess.kill()
        raise
    yield sess
    sess.kill()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestNavigationWrap:
    """Up/Down/j/k navigation wraps around at list boundaries."""

    def test_down_wraps_from_last_to_first(self, two_host_app):
        """Pressing Down past the last entry wraps back to the first."""
        pane = two_host_app

        # Select first entry
        pane.send_keys('Down')
        time.sleep(0.2)
        # Select second (last) entry
        pane.send_keys('Down')
        time.sleep(0.2)
        # One more Down: should wrap to first (127.0.0.1)
        pane.send_keys('Down')
        time.sleep(0.2)

        # Open details — must show 127.0.0.1
        _wait_details(pane)
        screen = pane.capture_pane()
        assert '127.0.0.1' in screen, (
            f"After wrapping Down from last to first, details should show 127.0.0.1; got:\n{screen}"
        )
        _close_details(pane)

    def test_up_wraps_from_first_to_last(self, two_host_app):
        """Pressing Up on the first entry wraps to the last."""
        pane = two_host_app

        # Select first entry
        pane.send_keys('Down')
        time.sleep(0.2)
        # Up from first: should wrap to last (127.0.0.2)
        pane.send_keys('Up')
        time.sleep(0.2)

        _wait_details(pane)
        screen = pane.capture_pane()
        assert '127.0.0.2' in screen, (
            f"After wrapping Up from first to last, details should show 127.0.0.2; got:\n{screen}"
        )
        _close_details(pane)

    def test_j_wraps_from_last_to_first(self, two_host_app):
        """vim 'j' key wraps the same way as Down."""
        pane = two_host_app

        pane.send_keys('Down')
        time.sleep(0.2)
        pane.send_keys('Down')
        time.sleep(0.2)
        # j from last → wrap to first
        pane.send_literal('j')
        time.sleep(0.2)

        _wait_details(pane)
        screen = pane.capture_pane()
        assert '127.0.0.1' in screen, (
            f"'j' wrap from last to first failed; got:\n{screen}"
        )
        _close_details(pane)

    def test_k_wraps_from_first_to_last(self, two_host_app):
        """vim 'k' key wraps the same way as Up."""
        pane = two_host_app

        pane.send_keys('Down')
        time.sleep(0.2)
        # k from first → wrap to last
        pane.send_literal('k')
        time.sleep(0.2)

        _wait_details(pane)
        screen = pane.capture_pane()
        assert '127.0.0.2' in screen, (
            f"'k' wrap from first to last failed; got:\n{screen}"
        )
        _close_details(pane)
