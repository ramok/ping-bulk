"""Integration tests for recursive fold keybindings.

Verifies that:
- zC: fold section + all descendants
- zA: toggle section + all descendants recursively
- Ctrl-Space: toggle recursively (terminal-dependent)
- Event log confirms child sections were folded
"""

import pytest
from utils.hosts_helper import write_hosts


class TestRecursiveFoldUI:
    """Test recursive fold keybindings via tmux UI."""

    @pytest.fixture(autouse=True)
    def setup(self, app_path, tmp_path, check_integration_deps):
        from tmux_helper import TmuxSession
        import uuid
        import os

        # Create hosts file with nested sections
        hosts = write_hosts(tmp_path, """
## services
### extra
admin
certs

nas

## web
google.com
github.com
""")
        # Start tmux session with the hosts file
        session_name = f"pytest-rfold-{uuid.uuid4().hex[:8]}"
        self.sess = TmuxSession(session_name, width=120, height=40)
        cmd = f"{app_path} -f {hosts}"
        self.sess.send_literal(cmd)
        self.sess.send_keys("Enter")

        # Wait for UI ready
        self.sess.wait_for("DNS:", timeout=10)
        # Wait for sections to appear
        self.sess.wait_for("services")
        self.sess.wait_for("extra")

        yield

        self.sess.kill()

    def test_zC_folds_section_and_children(self):
        """zC (close-recursive) sets parent AND child sections to folded.

        With the 'sections always navigable' model:
        - services [+] is visible
        - extra [+] is ALSO visible (sections always navigable)
        - Hosts under extra are hidden (extra.folded=True)
        The key difference from non-recursive zc: extra itself becomes [+].
        """
        # Initial state: all sections unfolded
        screen = self.sess.capture_pane()
        assert "[-] services" in screen
        assert "[-] extra" in screen

        # Navigate to services section
        self.sess.send_keys("j")
        self.sess.wait_for("(C-)SPACE fold")

        # Send zC to fold recursively
        self.sess.send_literal("zC")
        self.sess.wait_for("[+] services")
        self.sess.wait_for("[+] extra")  # extra still visible but now folded

        screen = self.sess.capture_pane()
        assert "[+] services" in screen
        assert "[+] extra" in screen   # visible but folded
        assert "admin" not in screen   # extra's hosts hidden (extra.folded=True)
        assert "nas-old" not in screen

        # Event log confirms 1 child section was folded
        assert "recursive fold services: 1 children folded" in screen

    def test_zA_toggles_recursively(self):
        """zA (toggle-recursive) should toggle parent and all descendants."""
        # Navigate to services
        self.sess.send_keys("j")
        self.sess.wait_for("(C-)SPACE fold")

        # First zA: fold services + extra
        self.sess.send_literal("zA")
        self.sess.wait_for("[+] services")
        self.sess.wait_for("[+] extra")

        screen = self.sess.capture_pane()
        assert "[+] services" in screen
        assert "[+] extra" in screen   # still visible, now folded
        assert "admin" not in screen   # hosts hidden

        # Second zA: unfold services + extra
        self.sess.send_literal("zA")
        self.sess.wait_for("[-] services")
        self.sess.wait_for("[-] extra")

        screen = self.sess.capture_pane()
        assert "[-] services" in screen
        assert "[-] extra" in screen
        assert "admin" in screen  # host visible again

    def test_zc_non_recursive_keeps_subsection_visible_and_unfolded(self):
        """zc (non-recursive) folds only services; extra stays visible and unfolded.

        This is the key distinction from zC: extra.folded is NOT changed.
        """
        # Navigate to services
        self.sess.send_keys("j")
        self.sess.wait_for("(C-)SPACE fold")

        # Fold non-recursively
        self.sess.send_literal("zc")
        self.sess.wait_for("[+] services")

        screen = self.sess.capture_pane()
        assert "[+] services" in screen
        assert "[-] extra" in screen   # still visible AND still unfolded
        assert "admin" in screen       # extra's hosts still visible

    def test_zC_only_affects_descendants(self):
        """zC on a section should not affect sibling sections."""
        # Navigate to services
        self.sess.send_keys("j")
        self.sess.wait_for("(C-)SPACE fold")

        # Fold services recursively
        self.sess.send_literal("zC")
        self.sess.wait_for("[+] services")

        screen = self.sess.capture_pane()
        # 'web' sibling should still be unfolded
        assert "[-] web" in screen

    def test_event_log_shows_child_count(self):
        """Event log should report how many children were affected."""
        # Navigate to services
        self.sess.send_keys("j")
        self.sess.wait_for("(C-)SPACE fold")

        # Fold recursively (services has 1 child section: extra)
        self.sess.send_literal("zC")
        self.sess.wait_for("[+] services")

        # Check the event log (visible in Events section)
        screen = self.sess.capture_pane()
        assert "1 children folded" in screen

    def test_zO_unfolds_recursively(self):
        """zO (open-recursive) should unfold parent and all descendants."""
        # First fold everything recursively
        self.sess.send_literal(":fold close-all")
        self.sess.send_keys("Enter")
        self.sess.wait_for("[+] services")
        self.sess.wait_for("[+] extra")  # extra still visible

        # Navigate to services
        self.sess.send_keys("j")
        self.sess.wait_for("(C-)SPACE fold")

        # Unfold recursively with zO
        self.sess.send_literal("zO")
        self.sess.wait_for("[-] services")
        self.sess.wait_for("[-] extra")

        screen = self.sess.capture_pane()
        assert "[-] services" in screen
        assert "[-] extra" in screen
        assert "admin" in screen

    def test_non_recursive_za_only_affects_parent(self):
        """za (toggle non-recursive) should only affect the selected section."""
        # Navigate to services
        self.sess.send_keys("j")
        self.sess.wait_for("(C-)SPACE fold")

        # Toggle with 'za' (non-recursive)
        self.sess.send_literal("za")
        self.sess.wait_for("[+] services")

        screen = self.sess.capture_pane()
        assert "[+] services" in screen
        assert "[-] extra" in screen  # extra still unfolded and visible

        # Unfold services with non-recursive
        self.sess.send_literal("za")
        self.sess.wait_for("[-] services")

        screen = self.sess.capture_pane()
        assert "[-] services" in screen
        assert "[-] extra" in screen


class TestRecursiveFoldSpaceKey:
    """Test Space vs Ctrl-Space behavior."""

    @pytest.fixture(autouse=True)
    def setup(self, app_path, tmp_path, check_integration_deps):
        from tmux_helper import TmuxSession
        import uuid

        hosts = write_hosts(tmp_path, """
## A
host2
### B
host1
""")
        session_name = f"pytest-rfold-space-{uuid.uuid4().hex[:8]}"
        self.sess = TmuxSession(session_name, width=120, height=30)
        cmd = f"{app_path} -f {hosts}"
        self.sess.send_literal(cmd)
        self.sess.send_keys("Enter")
        self.sess.wait_for("DNS:", timeout=10)
        self.sess.wait_for("[-] A")

        yield
        self.sess.kill()

    def test_space_toggles_non_recursive(self):
        """Space should toggle only the selected section."""
        # Navigate to A
        self.sess.send_keys("j")
        self.sess.wait_for("(C-)SPACE fold")

        # Press Space
        self.sess.send_keys("Space")
        self.sess.wait_for("[+] A")

        screen = self.sess.capture_pane()
        assert "[+] A" in screen
        # B is still visible — sections are always navigable (non-recursive fold)
        assert "[-] B" in screen
        # host2 (direct child of A) is hidden
        lines = screen.split('\n')
        main_lines = '\n'.join(l for l in lines
                               if 'Events' not in l and 'starts' not in l)
        assert "host2" not in main_lines

        # host1 (under B, which is unfolded) is still visible
        assert "host1" in screen

        # Unfold again
        self.sess.send_keys("Space")
        self.sess.wait_for("[-] A")

        screen = self.sess.capture_pane()
        assert "[-] A" in screen
        assert "[-] B" in screen   # child section still visible
        assert "host2" in screen   # direct hosts back
