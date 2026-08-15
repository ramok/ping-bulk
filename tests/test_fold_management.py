"""Unit tests for fold management logic — D5.

Covers:
  _section_set_fold(section, state, recursive=False/True)
  _fold_all(state)
  _fold_level_step(direction)   — zm/zr level-by-level fold cycling
  _fold_healthy()               — fold sections where all monitors alive
  _fold_unhealthy()             — fold sections with any monitor down
  _fold_close_other(pattern)    — fold all except matching sections
"""

import os
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_app(pb, tmp_path, entries=None):
    cfg = tmp_path / "ping-bulk" / "config"
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('')
    if entries is None:
        entries = []
    with patch.object(pb, '_config_path', return_value=str(cfg)):
        app = pb.Application(entries, log_file=None)
    return app


def make_section(pb, title='S', level=1, folded=False):
    s = pb.SectionLabel(title, level=level, folded_default=folded)
    s.folded = folded  # ensure the actual folded state matches
    return s


def make_monitor_alive(pb, host='h', alive=True):
    m = pb.PingMonitor(host)
    m.alive = alive
    return m


def build_app_with_layout(pb, tmp_path, layout):
    """Build app with a custom entries list.

    layout — list of SectionLabel or PingMonitor objects in display order.
    """
    app = make_app(pb, tmp_path)
    app.entries = list(layout)
    app.monitors = [e for e in app.entries if isinstance(e, pb.PingMonitor)]
    return app


# ===========================================================================
# _section_set_fold
# ===========================================================================

class TestSectionSetFold:

    def test_set_fold_true(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        s = make_section(pb, folded=False)
        app.entries = [s]
        app._section_set_fold(s, True)
        assert s.folded is True

    def test_set_fold_false(self, pb, tmp_path):
        app = make_app(pb, tmp_path)
        s = make_section(pb, folded=True)
        app.entries = [s]
        app._section_set_fold(s, False)
        assert s.folded is False

    def test_non_recursive_does_not_affect_children(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=False)
        s2 = make_section(pb, 'B', level=2, folded=False)
        app = build_app_with_layout(pb, tmp_path, [s1, s2])
        app._section_set_fold(s1, True, recursive=False)
        assert s1.folded is True
        assert s2.folded is False   # child NOT affected

    def test_recursive_closes_all_descendant_sections(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=False)
        s2 = make_section(pb, 'B', level=2, folded=False)
        s3 = make_section(pb, 'C', level=3, folded=False)
        app = build_app_with_layout(pb, tmp_path, [s1, s2, s3])
        app._section_set_fold(s1, True, recursive=True)
        assert s1.folded is True
        assert s2.folded is True
        assert s3.folded is True

    def test_recursive_stops_at_sibling(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=False)
        s2 = make_section(pb, 'B', level=2, folded=False)
        s3 = make_section(pb, 'Sibling', level=1, folded=False)
        app = build_app_with_layout(pb, tmp_path, [s1, s2, s3])
        app._section_set_fold(s1, True, recursive=True)
        assert s1.folded is True
        assert s2.folded is True
        assert s3.folded is False   # sibling NOT affected

    def test_recursive_open_all_descendants(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=True)
        s2 = make_section(pb, 'B', level=2, folded=True)
        app = build_app_with_layout(pb, tmp_path, [s1, s2])
        app._section_set_fold(s1, False, recursive=True)
        assert s1.folded is False
        assert s2.folded is False


# ===========================================================================
# _fold_all
# ===========================================================================

class TestFoldAll:

    def test_fold_all_closes_all(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=False)
        s2 = make_section(pb, 'B', level=2, folded=False)
        app = build_app_with_layout(pb, tmp_path, [s1, s2])
        app._fold_all(True)
        assert s1.folded is True
        assert s2.folded is True

    def test_fold_all_opens_all(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=True)
        s2 = make_section(pb, 'B', level=2, folded=True)
        app = build_app_with_layout(pb, tmp_path, [s1, s2])
        app._fold_all(False)
        assert s1.folded is False
        assert s2.folded is False

    def test_fold_all_no_sections_noop(self, pb, tmp_path):
        m = make_monitor_alive(pb)
        app = build_app_with_layout(pb, tmp_path, [m])
        app._fold_all(True)  # should not raise


# ===========================================================================
# _fold_level_step
# ===========================================================================

class TestFoldLevelStep:

    def test_zm_closes_shallowest_open_level(self, pb, tmp_path):
        """zm (direction>0): close the shallowest currently-open section level."""
        s1 = make_section(pb, 'A', level=1, folded=False)
        s2 = make_section(pb, 'B', level=2, folded=False)
        app = build_app_with_layout(pb, tmp_path, [s1, s2])
        app._fold_level_step(+1)
        assert s1.folded is True   # level 1 closed
        assert s2.folded is False  # level 2 not yet closed

    def test_zm_second_call_closes_next_level(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=False)
        s2 = make_section(pb, 'B', level=2, folded=False)
        app = build_app_with_layout(pb, tmp_path, [s1, s2])
        app._fold_level_step(+1)   # closes level 1
        app._fold_level_step(+1)   # closes level 2
        assert s1.folded is True
        assert s2.folded is True

    def test_zm_already_all_closed_is_noop(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=True)
        app = build_app_with_layout(pb, tmp_path, [s1])
        app._fold_level_step(+1)   # no open levels → noop
        assert s1.folded is True

    def test_zr_opens_deepest_closed_level(self, pb, tmp_path):
        """zr (direction<0): open the deepest currently-closed section level."""
        s1 = make_section(pb, 'A', level=1, folded=True)
        s2 = make_section(pb, 'B', level=2, folded=True)
        app = build_app_with_layout(pb, tmp_path, [s1, s2])
        app._fold_level_step(-1)
        assert s1.folded is True   # level 1 not yet opened
        assert s2.folded is False  # level 2 opened

    def test_zr_second_call_opens_next_level(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=True)
        s2 = make_section(pb, 'B', level=2, folded=True)
        app = build_app_with_layout(pb, tmp_path, [s1, s2])
        app._fold_level_step(-1)   # opens level 2
        app._fold_level_step(-1)   # opens level 1
        assert s1.folded is False
        assert s2.folded is False

    def test_zr_already_all_open_is_noop(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=False)
        app = build_app_with_layout(pb, tmp_path, [s1])
        app._fold_level_step(-1)   # no closed levels → noop
        assert s1.folded is False

    def test_no_sections_noop(self, pb, tmp_path):
        m = make_monitor_alive(pb)
        app = build_app_with_layout(pb, tmp_path, [m])
        app._fold_level_step(+1)
        app._fold_level_step(-1)


# ===========================================================================
# _fold_healthy / _fold_unhealthy
# (basic coverage; comprehensive tests are in test_autofold.py)
# ===========================================================================

class TestFoldHealthyUnhealthy:

    def test_fold_healthy_folds_all_alive_section(self, pb, tmp_path):
        s = make_section(pb, folded=False)
        m = make_monitor_alive(pb, alive=True)
        app = build_app_with_layout(pb, tmp_path, [s, m])
        app._fold_healthy()
        assert s.folded is True

    def test_fold_healthy_skips_section_with_down_monitor(self, pb, tmp_path):
        s = make_section(pb, folded=False)
        m = make_monitor_alive(pb, alive=False)
        app = build_app_with_layout(pb, tmp_path, [s, m])
        app._fold_healthy()
        assert s.folded is False

    def test_fold_unhealthy_folds_section_with_down_monitor(self, pb, tmp_path):
        s = make_section(pb, folded=False)
        m = make_monitor_alive(pb, alive=False)
        app = build_app_with_layout(pb, tmp_path, [s, m])
        app._fold_unhealthy()
        assert s.folded is True

    def test_fold_unhealthy_skips_all_alive_section(self, pb, tmp_path):
        s = make_section(pb, folded=False)
        m = make_monitor_alive(pb, alive=True)
        app = build_app_with_layout(pb, tmp_path, [s, m])
        app._fold_unhealthy()
        assert s.folded is False

    def test_fold_sequence_consistency(self, pb, tmp_path):
        """Fold-all then unfold-all returns all sections to open state."""
        s1 = make_section(pb, 'A', level=1, folded=False)
        s2 = make_section(pb, 'B', level=2, folded=False)
        app = build_app_with_layout(pb, tmp_path, [s1, s2])
        app._fold_all(True)
        assert all(s.folded for s in [s1, s2])
        app._fold_all(False)
        assert not any(s.folded for s in [s1, s2])


# ===========================================================================
# _fold_close_other — fold all except matching sections
# ===========================================================================

class TestFoldCloseOther:

    def test_pattern_matches_one_section(self, pb, tmp_path):
        s1 = make_section(pb, 'Alpha', level=1)
        m1 = make_monitor_alive(pb, 'a1')
        s2 = make_section(pb, 'Bravo', level=1)
        m2 = make_monitor_alive(pb, 'b1')
        s3 = make_section(pb, 'Charlie', level=1)
        m3 = make_monitor_alive(pb, 'c1')
        app = build_app_with_layout(pb, tmp_path, [s1, m1, s2, m2, s3, m3])
        app._fold_close_other('Bravo')
        assert s1.folded is True
        assert s2.folded is False
        assert s3.folded is True

    def test_pattern_matches_multiple_sections(self, pb, tmp_path):
        s1 = make_section(pb, 'sensor-hub-1', level=1)
        m1 = make_monitor_alive(pb, 'h1')
        s2 = make_section(pb, 'sensor-hub-2', level=1)
        m2 = make_monitor_alive(pb, 'h2')
        s3 = make_section(pb, 'harbour', level=1)
        m3 = make_monitor_alive(pb, 'h3')
        app = build_app_with_layout(pb, tmp_path, [s1, m1, s2, m2, s3, m3])
        app._fold_close_other('sensor-hub')
        assert s1.folded is False
        assert s2.folded is False
        assert s3.folded is True

    def test_no_pattern_cursor_on_section(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1)
        m1 = make_monitor_alive(pb, 'a1')
        s2 = make_section(pb, 'B', level=1)
        m2 = make_monitor_alive(pb, 'b1')
        app = build_app_with_layout(pb, tmp_path, [s1, m1, s2, m2])
        app.highlighted_index = 2  # s2
        app._fold_close_other()
        assert s1.folded is True
        assert s2.folded is False

    def test_no_pattern_cursor_on_monitor(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1)
        m1 = make_monitor_alive(pb, 'a1')
        s2 = make_section(pb, 'B', level=1)
        m2 = make_monitor_alive(pb, 'b1')
        app = build_app_with_layout(pb, tmp_path, [s1, m1, s2, m2])
        app.highlighted_index = 3  # m2 (under s2)
        app._fold_close_other()
        assert s1.folded is True
        assert s2.folded is False

    def test_recursive_unfold_of_matched_section(self, pb, tmp_path):
        s1 = make_section(pb, 'Top', level=1)
        s2 = make_section(pb, 'Sub', level=2)
        m1 = make_monitor_alive(pb, 'h1')
        s3 = make_section(pb, 'Other', level=1)
        m2 = make_monitor_alive(pb, 'h2')
        app = build_app_with_layout(pb, tmp_path, [s1, s2, m1, s3, m2])
        app._fold_close_other('Top')
        assert s1.folded is False
        assert s2.folded is False  # descendant also unfolded
        assert s3.folded is True

    def test_no_match_preserves_fold_state(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=False)
        s2 = make_section(pb, 'B', level=1, folded=True)
        app = build_app_with_layout(pb, tmp_path, [s1, s2])
        app._fold_close_other('nonexistent')
        assert s1.folded is False  # unchanged
        assert s2.folded is True   # unchanged

    def test_invalid_regex_falls_back_to_literal(self, pb, tmp_path):
        s1 = make_section(pb, 'test[1', level=1)
        m1 = make_monitor_alive(pb, 'h1')
        s2 = make_section(pb, 'other', level=1)
        m2 = make_monitor_alive(pb, 'h2')
        app = build_app_with_layout(pb, tmp_path, [s1, m1, s2, m2])
        app._fold_close_other('[1')
        assert s1.folded is False
        assert s2.folded is True

    def test_case_insensitive_matching(self, pb, tmp_path):
        s1 = make_section(pb, 'Sensor-HUB-3', level=1)
        m1 = make_monitor_alive(pb, 'h1')
        s2 = make_section(pb, 'other', level=1)
        m2 = make_monitor_alive(pb, 'h2')
        app = build_app_with_layout(pb, tmp_path, [s1, m1, s2, m2])
        app._fold_close_other('sensor-hub')
        assert s1.folded is False
        assert s2.folded is True
