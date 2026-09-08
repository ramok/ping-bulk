"""Integration tests for the host details overlay.

The details overlay is opened by pressing Enter when a host is highlighted,
and displays comprehensive statistics in a centered bordered popup.
"""
import re
import time


DETAILS_MARKER = '[Enter/q/Esc] Close'


def _open_details(pane, wait_sec=1.0):
    """Navigate to first host (127.0.0.1) and open details overlay.

    Standard procedure:
      1. Press Down to highlight first visible entry (127.0.0.1)
      2. Press Enter to open overlay
      3. Wait for DETAILS_MARKER to appear
    """
    pane.send_keys('Down')
    time.sleep(0.2)
    pane.send_keys('Enter')
    time.sleep(wait_sec)


class TestDetailsOverlayOpenClose:
    """Test opening and closing the details overlay with all supported keys."""

    def test_open_with_enter(self, tmux_app_40):
        """Details overlay opens when Enter is pressed on a highlighted host."""
        pane = tmux_app_40
        _open_details(pane)

        screen = pane.capture_pane()
        assert DETAILS_MARKER in screen
        assert 'Host:' in screen

    def test_close_with_q(self, tmux_app_40):
        """Details overlay closes when 'q' is pressed."""
        pane = tmux_app_40
        _open_details(pane)

        # Verify overlay is open
        screen = pane.capture_pane()
        assert DETAILS_MARKER in screen

        # Close with 'q'
        pane.send_keys('q')
        time.sleep(1.0)

        # Verify overlay is closed
        screen = pane.capture_pane()
        assert DETAILS_MARKER not in screen

    def test_close_with_shift_q(self, tmux_app_40):
        """Details overlay closes when 'Q' (Shift+q) is pressed."""
        pane = tmux_app_40
        _open_details(pane)

        screen = pane.capture_pane()
        assert DETAILS_MARKER in screen

        # Close with 'Q'
        pane.send_keys('Q')
        time.sleep(1.0)

        screen = pane.capture_pane()
        assert DETAILS_MARKER not in screen

    def test_close_with_escape(self, tmux_app_40):
        """Details overlay closes when Escape is pressed."""
        pane = tmux_app_40
        _open_details(pane)

        screen = pane.capture_pane()
        assert DETAILS_MARKER in screen

        # Close with Escape
        pane.send_keys('Escape')
        time.sleep(1.0)

        screen = pane.capture_pane()
        assert DETAILS_MARKER not in screen

    def test_close_with_enter(self, tmux_app_40):
        """Details overlay closes when Enter is pressed while overlay is open."""
        pane = tmux_app_40
        _open_details(pane)

        screen = pane.capture_pane()
        assert DETAILS_MARKER in screen

        # Close with Enter
        pane.send_keys('Enter')
        time.sleep(1.0)

        screen = pane.capture_pane()
        assert DETAILS_MARKER not in screen

    def test_close_with_ctrl_c(self, tmux_app_40):
        """Details overlay closes when Ctrl+C is pressed."""
        pane = tmux_app_40
        _open_details(pane)

        screen = pane.capture_pane()
        assert DETAILS_MARKER in screen

        # Close with Ctrl+C (send literal control sequence)
        pane.send_keys('C-c')
        time.sleep(1.0)

        screen = pane.capture_pane()
        assert DETAILS_MARKER not in screen


class TestDetailsOverlayContent:
    """Test that the details overlay displays all expected content."""

    def test_host_label(self, tmux_app_40):
        """Details overlay shows 'Host:' label with host name."""
        pane = tmux_app_40
        _open_details(pane)

        screen = pane.capture_pane()
        assert 'Host: 127.0.0.1' in screen

    def test_status_up(self, tmux_app_40):
        """Details overlay shows 'Status: UP' for reachable host."""
        pane = tmux_app_40

        # Wait for host to come up (127.0.0.1 should be reachable)
        time.sleep(2.0)

        _open_details(pane)

        screen = pane.capture_pane()
        assert 'Status: UP' in screen

    def test_uptime_present(self, tmux_app_40):
        """Details overlay shows 'Uptime:' when host is up."""
        pane = tmux_app_40

        # Wait for host to come up
        time.sleep(2.0)

        _open_details(pane)

        screen = pane.capture_pane()
        assert 'Uptime:' in screen

    def test_last_rtt_present(self, tmux_app_40):
        """Details overlay shows 'Last RTT:' field."""
        pane = tmux_app_40

        # Wait for at least one ping response
        time.sleep(2.0)

        _open_details(pane)

        screen = pane.capture_pane()
        assert 'Last RTT:' in screen

    def test_packet_statistics_section(self, tmux_app_40):
        """Details overlay shows 'Packet Statistics:' section with all fields."""
        pane = tmux_app_40

        time.sleep(2.0)
        _open_details(pane)

        screen = pane.capture_pane()
        assert 'Packet Statistics:' in screen
        assert 'Total sent (TX):' in screen
        assert 'Received (RX):' in screen
        assert 'Lost (XX):' in screen
        assert 'Loss rate:' in screen

    def test_latency_statistics_section(self, tmux_app_40):
        """Details overlay shows 'Latency Statistics:' section with all fields."""
        pane = tmux_app_40

        time.sleep(2.0)
        _open_details(pane)

        screen = pane.capture_pane()
        assert 'Latency Statistics:' in screen
        assert 'Min:' in screen
        assert 'Max:' in screen
        assert 'Average:' in screen
        assert 'StdDev:' in screen

    def test_close_instruction(self, tmux_app_40):
        """Details overlay shows closing instruction at bottom."""
        pane = tmux_app_40
        _open_details(pane)

        screen = pane.capture_pane()
        assert DETAILS_MARKER in screen

    def test_numeric_values_present(self, tmux_app_40):
        """Details overlay shows numeric values for statistics (not just dashes)."""
        pane = tmux_app_40

        # Wait for multiple pings to accumulate statistics
        time.sleep(3.0)

        _open_details(pane)

        screen = pane.capture_pane()

        # Should have numeric RTT value (e.g. "Last RTT: 0.42 ms")
        assert re.search(r'Last RTT:\s+\d+\.\d+\s+ms', screen)

        # Should have numeric packet counts (e.g. "Total sent (TX): 3")
        assert re.search(r'Total sent \(TX\):\s+\d+', screen)
        assert re.search(r'Received \(RX\):\s+\d+', screen)

        # Should have numeric latency stats
        assert re.search(r'Min:\s+\d+\.\d+\s+ms', screen)
        assert re.search(r'Max:\s+\d+\.\d+\s+ms', screen)
        assert re.search(r'Average:\s+\d+\.\d+\s+ms', screen)


class TestDetailsOverlayNoOp:
    """Test that Enter does nothing in certain contexts."""

    def test_enter_without_navigation(self, tmux_app_40):
        """Enter does nothing when no host is highlighted."""
        pane = tmux_app_40

        # Press Enter without navigating first
        pane.send_keys('Enter')
        time.sleep(0.5)

        # Details overlay should not open
        screen = pane.capture_pane()
        assert DETAILS_MARKER not in screen

    def test_enter_on_section_label(self, tmux_app_with_section):
        """Enter does nothing when a section label is highlighted."""
        pane = tmux_app_with_section

        # First Down press highlights the section label "── [-] My Section"
        pane.send_keys('Down')
        time.sleep(0.2)

        # Pressing Enter on section label should do nothing
        pane.send_keys('Enter')
        time.sleep(0.5)

        # Details overlay should not open
        screen = pane.capture_pane()
        assert DETAILS_MARKER not in screen

    def test_enter_on_host_after_section(self, tmux_app_with_section):
        """Enter opens details when pressing Down twice to reach host after section."""
        pane = tmux_app_with_section

        # First Down: section label
        pane.send_keys('Down')
        time.sleep(0.2)

        # Second Down: 127.0.0.1 host
        pane.send_keys('Down')
        time.sleep(0.2)

        # Enter should now open details overlay
        pane.send_keys('Enter')
        time.sleep(1.0)

        screen = pane.capture_pane()
        assert DETAILS_MARKER in screen
        assert 'Host: 127.0.0.1' in screen



class TestDetailsConnectLine:
    """'Connect:' previews what 'c' would run, drawn through the real overlay.

    The unit tests in test_bindkey.py cover _connect_preview itself; these go
    through _draw_details_overlay, which is where a missing variable once
    crashed the whole overlay.
    """

    def _app(self, app_path, tmp_path, hosts, name):
        import uuid
        from tmux_helper import TmuxSession
        f = tmp_path / 'connect.hosts'
        f.write_text(hosts)
        sess = TmuxSession(f'{name}-{uuid.uuid4().hex[:8]}',
                           width=120, height=40)
        sess.send_literal(f'python3 {app_path} -f {f}')
        sess.send_keys('Enter')
        sess.wait_for('DNS:', timeout=10)
        return sess

    def test_relayed_host_shows_the_jump(self, app_path, tmp_path,
                                         check_integration_deps):
        """The old preview printed 'relay→target', which ssh cannot resolve."""
        sess = self._app(app_path, tmp_path,
                         ':remote-ping relay.example.com 10.1.2.3\n',
                         'pytest-conn-relay')
        try:
            _open_details(sess)
            sess.wait_for(DETAILS_MARKER)
            screen = sess.capture_pane()
            assert 'Connect: ssh -J relay.example.com 10.1.2.3' in screen, screen
            assert '→' not in screen.split('Connect:')[1].split('\n')[0]
        finally:
            sess.kill()

    def test_prog_options_username_is_shown(self, app_path, tmp_path,
                                            check_integration_deps):
        sess = self._app(app_path, tmp_path,
                         ':prog-options ssh 127.0.0.1 -l admin\n127.0.0.1\n',
                         'pytest-conn-opts')
        try:
            _open_details(sess)
            sess.wait_for(DETAILS_MARKER)
            assert 'Connect: ssh -l admin 127.0.0.1' in sess.capture_pane()
        finally:
            sess.kill()

    def test_disabled_host_hides_the_connect_hint(self, app_path, tmp_path,
                                                  check_integration_deps):
        """'--disable' must show 'disabled' and drop the '[c]' footer hint."""
        sess = self._app(app_path, tmp_path,
                         ':prog-options ssh 127.0.0.1 --disable\n127.0.0.1\n',
                         'pytest-conn-dis')
        try:
            _open_details(sess)
            sess.wait_for(DETAILS_MARKER)
            screen = sess.capture_pane()
            assert 'Connect: disabled' in screen, screen
            assert '[c] SSH connect' not in screen
        finally:
            sess.kill()

    def test_enabled_host_keeps_the_connect_hint(self, app_path, tmp_path,
                                                 check_integration_deps):
        """The footer hint read a variable the rewrite removed, crashing the box."""
        sess = self._app(app_path, tmp_path, '127.0.0.1\n', 'pytest-conn-en')
        try:
            _open_details(sess)
            sess.wait_for(DETAILS_MARKER)
            screen = sess.capture_pane()
            assert '[c] SSH connect' in screen, screen
            assert 'Connect: ssh 127.0.0.1' in screen
        finally:
            sess.kill()
