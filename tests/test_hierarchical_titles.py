"""Tests for hierarchical section titles (## / ### / :title / :title2 …).

Covers:
  - Parser: ## / ### / #### and :title / :title2 / :title3 produce correct levels
  - Parser: inline ## / ### / #### after a hostname are stripped as comments
  - SectionLabel.level attribute
  - _get_visible_entry_indices: hierarchical fold visibility
  - Render / UI: indentation via tmux
  - Hotkeys: z*, [, ] via tmux
"""

import textwrap
import uuid

import pytest

from tmux_helper import TmuxSession
from utils.hosts_helper import write_hosts


# ===========================================================================
# Unit tests — parser
# ===========================================================================

class TestHierarchicalTitleParser:
    """parse_hosts_file produces ('section', title, level) tuples."""

    def test_hash_level1(self, pb, tmp_path):
        """## Title → level 1."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "## Top\n1.1.1.1\n"))
        assert entries == [('section', 'Top', 1), ('host', '1.1.1.1')]

    def test_hash_level2(self, pb, tmp_path):
        """### Title → level 2."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "### Sub\n1.1.1.1\n"))
        assert entries == [('section', 'Sub', 2), ('host', '1.1.1.1')]

    def test_hash_level3(self, pb, tmp_path):
        """#### Title → level 3."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "#### Deep\n1.1.1.1\n"))
        assert entries == [('section', 'Deep', 3), ('host', '1.1.1.1')]

    def test_title_directive_level1(self, pb, tmp_path):
        """:title → level 1."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, ":title Top\n1.1.1.1\n"))
        assert entries == [('section', 'Top', 1), ('host', '1.1.1.1')]

    def test_title_directive_level2(self, pb, tmp_path):
        """:title2 → level 2."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, ":title2 Sub\n1.1.1.1\n"))
        assert entries == [('section', 'Sub', 2), ('host', '1.1.1.1')]

    def test_title_directive_level3(self, pb, tmp_path):
        """:title3 → level 3."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, ":title3 Deep\n1.1.1.1\n"))
        assert entries == [('section', 'Deep', 3), ('host', '1.1.1.1')]

    def test_mixed_hash_and_title_levels(self, pb, tmp_path):
        """## and :title2 can be mixed; levels are independent."""
        content = textwrap.dedent("""\
            ## Top
            1.1.1.1
            :title2 Sub
            1.1.1.2
        """)
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'Top', 1),
            ('host', '1.1.1.1'),
            ('section', 'Sub', 2),
            ('host', '1.1.1.2'),
        ]

    def test_nested_structure(self, pb, tmp_path):
        """Multi-level nesting: ## > ### > ####."""
        content = textwrap.dedent("""\
            ## Region
            region-gw
            ### Datacenter
            dc-core
            #### Pod
            pod-host
        """)
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        assert entries == [
            ('section', 'Region', 1),
            ('host', 'region-gw'),
            ('section', 'Datacenter', 2),
            ('host', 'dc-core'),
            ('section', 'Pod', 3),
            ('host', 'pod-host'),
        ]


# ===========================================================================
# Unit tests — inline comment stripping
# ===========================================================================

class TestInlineHashStripping:
    """Inline ## / ### / #### after a hostname are stripped as comments."""

    def test_inline_double_hash(self, pb, tmp_path):
        """host ## label → host entry only (hostname, not IP, to avoid resolv)."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "router.lan ## edge\n"))
        assert entries == [('host', 'router.lan')]

    def test_inline_triple_hash(self, pb, tmp_path):
        """host ### label → host entry only (treated same as ##)."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "router.lan ### edge\n"))
        assert entries == [('host', 'router.lan')]

    def test_inline_quad_hash(self, pb, tmp_path):
        """host #### label → host entry only."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "router.lan #### edge\n"))
        assert entries == [('host', 'router.lan')]

    def test_section_header_not_stripped(self, pb, tmp_path):
        """## at line start is a section header, not an inline comment."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "## Section\n"))
        assert entries == [('section', 'Section', 1)]

    def test_triple_hash_header_not_stripped(self, pb, tmp_path):
        """### at line start is a level-2 header, not an inline comment."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "### Sub\n"))
        assert entries == [('section', 'Sub', 2)]


# ===========================================================================
# Unit tests — SectionLabel.level
# ===========================================================================

class TestSectionLabelLevel:
    """SectionLabel carries the correct level attribute."""

    def test_default_level_is_1(self, pb):
        label = pb.SectionLabel("Test")
        assert label.level == 1
        assert label.folded is False

    def test_explicit_level(self, pb):
        for lvl in (1, 2, 3, 4):
            label = pb.SectionLabel("Test", lvl)
            assert label.level == lvl

    def test_level_from_application_init(self, pb):
        """Application.__init__ creates SectionLabel with the correct level."""
        entries = [
            ('section', 'Top', 1),
            ('host', '127.0.0.1'),
            ('section', 'Sub', 2),
            ('host', '127.0.0.2'),
        ]
        app = pb.Application(entries)
        labels = [e for e in app.entries if isinstance(e, pb.SectionLabel)]
        assert labels[0].level == 1
        assert labels[1].level == 2
        for m in app.monitors:
            m.stop()


# ===========================================================================
# Unit tests — visibility / hierarchical folding
# ===========================================================================

class TestHierarchicalFolding:
    """_get_visible_entry_indices respects hierarchical fold state."""

    def _make_app(self, pb):
        """Return an Application with a 2-level hierarchy, all unfolded."""
        entries = [
            ('section', 'Top A', 1),
            ('host', '10.0.0.1'),
            ('section', 'Sub A1', 2),
            ('host', '10.0.0.2'),
            ('section', 'Top B', 1),
            ('host', '10.0.0.3'),
        ]
        return pb.Application(entries)

    def _labels(self, app, pb):
        return [e for e in app.entries if isinstance(e, pb.SectionLabel)]

    def test_all_visible_when_unfolded(self, pb):
        app = self._make_app(pb)
        visible = app._get_visible_entry_indices()
        assert len(visible) == len(app.entries)
        for m in app.monitors: m.stop()

    def test_fold_level1_hides_subsection_and_hosts(self, pb):
        """Folding Top A hides Sub A1, 10.0.0.1, and 10.0.0.2."""
        app = self._make_app(pb)
        labels = self._labels(app, pb)
        top_a = labels[0]  # 'Top A', level 1
        top_a.folded = True

        visible_idx = app._get_visible_entry_indices()
        visible_entries = [app.entries[i] for i in visible_idx]

        assert top_a in visible_entries  # parent section itself stays visible
        assert not any(                   # no hosts from Top A's subtree
            getattr(e, 'host', None) in ('10.0.0.1', '10.0.0.2')
            for e in visible_entries
        )
        sub_a1 = labels[1]
        assert sub_a1 not in visible_entries  # sub-section hidden

        # Top B and its host are unaffected
        assert any(getattr(e, 'host', None) == '10.0.0.3' for e in visible_entries)
        for m in app.monitors: m.stop()

    def test_fold_level2_hides_only_its_hosts(self, pb):
        """Folding Sub A1 hides only 10.0.0.2; 10.0.0.1 under Top A stays visible."""
        app = self._make_app(pb)
        labels = self._labels(app, pb)
        sub_a1 = labels[1]  # 'Sub A1', level 2
        sub_a1.folded = True

        visible_idx = app._get_visible_entry_indices()
        visible_entries = [app.entries[i] for i in visible_idx]

        # 10.0.0.1 is directly under Top A (before Sub A1) → visible
        assert any(getattr(e, 'host', None) == '10.0.0.1' for e in visible_entries)
        # 10.0.0.2 is under Sub A1 → hidden
        assert not any(getattr(e, 'host', None) == '10.0.0.2' for e in visible_entries)
        for m in app.monitors: m.stop()

    def test_fold_all_helper(self, pb):
        """_fold_all(True) folds every SectionLabel."""
        app = self._make_app(pb)
        app._fold_all(True)
        labels = self._labels(app, pb)
        assert all(s.folded for s in labels)
        for m in app.monitors: m.stop()

    def test_unfold_all_helper(self, pb):
        """_fold_all(False) unfolds every SectionLabel."""
        app = self._make_app(pb)
        app._fold_all(True)
        app._fold_all(False)
        labels = self._labels(app, pb)
        assert all(not s.folded for s in labels)
        for m in app.monitors: m.stop()

    def test_section_set_fold_recursive(self, pb):
        """_section_set_fold with recursive=True folds subsections too."""
        app = self._make_app(pb)
        labels = self._labels(app, pb)
        top_a, sub_a1 = labels[0], labels[1]
        app._section_set_fold(top_a, True, recursive=True)
        assert top_a.folded is True
        assert sub_a1.folded is True
        # Top B unaffected
        assert labels[2].folded is False
        for m in app.monitors: m.stop()

    def test_section_set_fold_non_recursive(self, pb):
        """_section_set_fold with recursive=False only folds the target."""
        app = self._make_app(pb)
        labels = self._labels(app, pb)
        top_a, sub_a1 = labels[0], labels[1]
        app._section_set_fold(top_a, True, recursive=False)
        assert top_a.folded is True
        assert sub_a1.folded is False
        for m in app.monitors: m.stop()


# ===========================================================================
# Unit tests — section summary helpers
# ===========================================================================

class TestSectionSummaryHelpers:
    """_get_section_monitors and _section_summary logic."""

    def _make_app(self, pb):
        entries = [
            ('section', 'Top A', 1),
            ('host', '10.0.0.1'),
            ('section', 'Sub A1', 2),
            ('host', '10.0.0.2'),
            ('section', 'Top B', 1),
            ('host', '10.0.0.3'),
        ]
        return pb.Application(entries)

    def test_get_section_monitors_level1(self, pb):
        """Top A (level 1) collects hosts from itself and Sub A1."""
        app = self._make_app(pb)
        # Top A is at index 0
        monitors = app._get_section_monitors(0)
        assert len(monitors) == 2
        hosts = {m.host for m in monitors}
        assert hosts == {'10.0.0.1', '10.0.0.2'}
        for m in app.monitors: m.stop()

    def test_get_section_monitors_level2(self, pb):
        """Sub A1 (level 2) collects only its own host."""
        app = self._make_app(pb)
        # Sub A1 is at index 2
        monitors = app._get_section_monitors(2)
        assert len(monitors) == 1
        assert monitors[0].host == '10.0.0.2'
        for m in app.monitors: m.stop()

    def test_get_section_monitors_stops_at_sibling(self, pb):
        """Top B stops before collecting Top B's host."""
        app = self._make_app(pb)
        # Top A is index 0, Top B is index 4
        monitors_top_a = app._get_section_monitors(0)
        assert not any(m.host == '10.0.0.3' for m in monitors_top_a)
        for m in app.monitors: m.stop()

    def test_worst_history_char_priority(self, pb):
        """? beats X beats . beats space."""
        wc = pb.Application._worst_history_char
        assert wc(['?', 'X', '.']) == '?'
        assert wc(['X', '.', ' ']) == 'X'
        assert wc(['.', ' '])      == '.'
        assert wc([' ', ' '])      == ' '

    def test_badge_all_up(self, pb):
        """All-up monitors produce N↑ badge with no ↓ or - parts."""
        app = self._make_app(pb)
        for m in app.monitors:
            m.alive = True
        badge, _ = app._section_summary(app.monitors, length=5, offset=0)
        assert '↑' in badge
        assert '↓' not in badge
        assert '-' not in badge
        for m in app.monitors: m.stop()

    def test_badge_mixed(self, pb):
        """Mixed alive states show all three groups."""
        app = self._make_app(pb)
        monitors = app.monitors
        monitors[0].alive = True
        monitors[1].alive = False
        monitors[2].alive = None
        badge, _ = app._section_summary(monitors, length=5, offset=0)
        assert '1↑' in badge
        assert '1↓' in badge
        assert '1-' in badge
        for m in app.monitors: m.stop()

    def test_badge_zero_groups_omitted(self, pb):
        """Zero-count groups are not shown in the badge."""
        app = self._make_app(pb)
        for m in app.monitors:
            m.alive = True
        badge, _ = app._section_summary(app.monitors, length=5, offset=0)
        assert '-' not in badge
        assert '↓' not in badge
        for m in app.monitors: m.stop()

    def test_history_worst_aggregation(self, pb):
        """History picks worst char per slot across monitors."""
        app = self._make_app(pb)
        from collections import deque
        # monitor 0: success (.); monitor 1: timeout (X)
        app.monitors[0].history = deque([10.0], maxlen=100)
        app.monitors[1].history = deque([None], maxlen=100)
        monitors = app.monitors[:2]
        _, history = app._section_summary(monitors, length=1, offset=0)
        assert history == 'X'
        for m in app.monitors: m.stop()


# ===========================================================================
# Integration tests — indentation and fold keys via tmux
# ===========================================================================

class TestHierarchicalTitlesUI:
    """UI integration: section indentation and z* fold hotkeys."""

    @pytest.fixture(autouse=True)
    def setup(self, app_path, check_integration_deps, tmp_path):
        content = textwrap.dedent("""\
            ## Top
            127.0.0.1
            ### Sub
            127.0.0.2
        """)
        hosts_file = write_hosts(tmp_path, content)
        sess_name = f'pb-test-hier-{uuid.uuid4().hex[:8]}'
        sess = TmuxSession(sess_name, width=120, height=40)
        try:
            sess.send_literal(f'python3 {app_path} -f {hosts_file}')
            sess.send_keys('Enter')
            sess.wait_for('ping-bulk:', timeout=10)
        except Exception:
            sess.kill()
            raise
        self.sess = sess
        yield
        sess.kill()

    def test_level1_section_no_indent(self):
        """Level-1 section header starts at column 0 (no leading space)."""
        screen = self.sess.capture_pane()
        lines = screen.splitlines()
        top_line = next((l for l in lines if 'Top' in l and '──' in l), None)
        assert top_line is not None, f"No Top section line found in:\n{screen}"
        assert top_line.startswith('──'), (
            f"Level-1 section should start at column 0, got: {top_line!r}")

    def test_level2_section_indented(self):
        """Level-2 section header is indented by 1 space."""
        screen = self.sess.capture_pane()
        lines = screen.splitlines()
        sub_line = next((l for l in lines if 'Sub' in l and '──' in l), None)
        assert sub_line is not None, f"No Sub section line found in:\n{screen}"
        assert sub_line.startswith(' ──'), (
            f"Level-2 section should be indented 1 space, got: {sub_line!r}")

    def test_zM_folds_all(self):
        """zM folds all sections ([+] indicator appears)."""
        self.sess.send_keys("z")
        self.sess.wait_for("[z]")
        self.sess.send_keys("M")
        self.sess.wait_for("[+]")
        screen = self.sess.capture_pane()
        assert "[+]" in screen

    def test_zR_unfolds_all(self):
        """zM then zR restores all sections."""
        self.sess.send_keys("z")
        self.sess.wait_for("[z]")
        self.sess.send_keys("M")
        self.sess.wait_for("[+]")
        self.sess.send_keys("z")
        self.sess.wait_for("[z]")
        self.sess.send_keys("R")
        self.sess.wait_for("[-]")
        screen = self.sess.capture_pane()
        assert "[+]" not in screen

    def test_bracket_fold_unfold(self):
        """[ folds all, ] unfolds all (single-key aliases)."""
        self.sess.send_keys("[")
        self.sess.wait_for("[+]")
        self.sess.send_keys("]")
        self.sess.wait_for("[-]")
        screen = self.sess.capture_pane()
        assert "[+]" not in screen

    def test_pending_key_indicator_shown(self):
        """Pressing 'z' alone shows the pending-key indicator bottom-right."""
        self.sess.send_keys("z")
        self.sess.wait_for("[z]")
        screen = self.sess.capture_pane()
        assert "[z]" in screen
        self.sess.send_keys("Escape")

    def test_esc_cancels_pending_key(self):
        """ESC after 'z' cancels the sequence without folding anything."""
        self.sess.send_keys("z")
        self.sess.wait_for("[z]")
        self.sess.send_keys("Escape")
        self.sess.wait_for_absence("[z]")
        screen = self.sess.capture_pane()
        assert "[z]" not in screen
        assert "[-]" in screen  # sections still unfolded

    def test_badge_shown_on_open_section(self):
        """Badge (↑ or ↓ or -) appears on section row even when unfolded."""
        screen = self.sess.capture_pane()
        lines = screen.splitlines()
        top_line = next((l for l in lines if 'Top' in l and '──' in l), None)
        assert top_line is not None, f"No Top section line found in:\n{screen}"
        # The badge should contain at least one arrow/dash indicator
        assert any(ch in top_line for ch in ('↑', '↓', '-')), (
            f"Expected badge on section row, got: {top_line!r}")

    def test_history_shown_when_folded(self):
        """After folding, the section row shows a history bar (. or X chars)."""
        self.sess.send_keys("[")          # fold all
        self.sess.wait_for("[+]")
        import time; time.sleep(1.5)      # wait for at least one ping result
        screen = self.sess.capture_pane()
        lines = screen.splitlines()
        top_line = next((l for l in lines if 'Top' in l and '──' in l), None)
        assert top_line is not None, f"No Top section line found in:\n{screen}"
        assert any(ch in top_line for ch in ('.', 'X', '?')), (
            f"Expected history bar on folded section row, got: {top_line!r}")
