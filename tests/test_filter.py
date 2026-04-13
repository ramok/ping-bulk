"""Unit tests for filter mode.

Covers:
  _update_filter_visible()       — match computation, section inclusion, auto-expand
  _get_visible_entry_indices()   — respects _filter_visible when filter is active
  _cmd_filter()                  — set/clear filter via command
  _cmd_select 'none'             — Esc priority: clears filter before selection
  _mode_banners()                — emits HISTORY and FILTER banners as expected
  filter prompt                  — Tab-to-search, Esc-cancel, Enter-confirm, live preview
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
    s.folded = folded
    return s


def make_monitor(pb, host):
    m = pb.PingMonitor(host)
    m.alive = True
    return m


def build_app(pb, tmp_path, entries):
    app = make_app(pb, tmp_path)
    app.entries = list(entries)
    app.monitors = [e for e in app.entries if isinstance(e, pb.PingMonitor)]
    return app


# ===========================================================================
# _update_filter_visible — core matching logic
# ===========================================================================

class TestUpdateFilterVisible:

    def test_empty_query_clears_visible_sets(self, pb, tmp_path):
        m = make_monitor(pb, '10.0.0.1')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = ''
        app._update_filter_visible()
        assert app._filter_visible == set()
        assert app._filter_visible_monitors == set()

    def test_exact_hostname_match(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'web01'
        app._update_filter_visible()
        assert 0 in app._filter_visible

    def test_bare_string_auto_wrapped_as_glob(self, pb, tmp_path):
        """Bare string (no metacharacters) is wrapped as *query*."""
        m = make_monitor(pb, 'web01.example.com')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'web'
        app._update_filter_visible()
        assert 0 in app._filter_visible

    def test_no_match_host_not_visible(self, pb, tmp_path):
        m = make_monitor(pb, 'db01')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'web'
        app._update_filter_visible()
        assert 0 not in app._filter_visible

    def test_glob_pattern_star(self, pb, tmp_path):
        m1 = make_monitor(pb, 'web01')
        m2 = make_monitor(pb, 'db01')
        app = build_app(pb, tmp_path, [m1, m2])
        app._filter_query = 'web*'
        app._update_filter_visible()
        assert 0 in app._filter_visible      # web01 matches
        assert 1 not in app._filter_visible  # db01 does not

    def test_glob_question_mark(self, pb, tmp_path):
        m1 = make_monitor(pb, 'web1')
        m2 = make_monitor(pb, 'web12')
        app = build_app(pb, tmp_path, [m1, m2])
        app._filter_query = 'web?'
        app._update_filter_visible()
        assert 0 in app._filter_visible      # web1 matches
        assert 1 not in app._filter_visible  # web12 does not

    def test_section_included_when_child_matches(self, pb, tmp_path):
        s = make_section(pb, 'Servers')
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [s, m])
        app._filter_query = 'web'
        app._update_filter_visible()
        # Section (index 0) should be included because child matches
        assert 0 in app._filter_visible
        assert 1 in app._filter_visible

    def test_section_excluded_when_no_child_matches(self, pb, tmp_path):
        s = make_section(pb, 'Servers')
        m = make_monitor(pb, 'db01')
        app = build_app(pb, tmp_path, [s, m])
        app._filter_query = 'web'
        app._update_filter_visible()
        assert 0 not in app._filter_visible
        assert 1 not in app._filter_visible

    def test_nested_section_both_included(self, pb, tmp_path):
        s1 = make_section(pb, 'DC1', level=1)
        s2 = make_section(pb, 'Web', level=2)
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [s1, s2, m])
        app._filter_query = 'web01'
        app._update_filter_visible()
        # Both ancestor sections (0 and 1) should be in visible
        assert 0 in app._filter_visible
        assert 1 in app._filter_visible
        assert 2 in app._filter_visible

    def test_auto_expand_folded_section_with_matching_child(self, pb, tmp_path):
        s = make_section(pb, 'Servers', folded=True)
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [s, m])
        assert s.folded is True
        app._filter_query = 'web'
        app._update_filter_visible()
        # Section should be auto-expanded so the match is visible
        assert s.folded is False

    def test_folded_section_not_expanded_when_no_match(self, pb, tmp_path):
        s = make_section(pb, 'Servers', folded=True)
        m = make_monitor(pb, 'db01')
        app = build_app(pb, tmp_path, [s, m])
        app._filter_query = 'web'
        app._update_filter_visible()
        assert s.folded is True  # should remain folded

    def test_monitor_count_in_visible_monitors(self, pb, tmp_path):
        m1 = make_monitor(pb, 'web01')
        m2 = make_monitor(pb, 'web02')
        m3 = make_monitor(pb, 'db01')
        app = build_app(pb, tmp_path, [m1, m2, m3])
        app._filter_query = 'web'
        app._update_filter_visible()
        assert len(app._filter_visible_monitors) == 2

    def test_case_insensitive_matching(self, pb, tmp_path):
        m = make_monitor(pb, 'WebServer')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'webserver'
        app._update_filter_visible()
        assert 0 in app._filter_visible

    def test_match_against_resolved_ip(self, pb, tmp_path):
        m = make_monitor(pb, 'myhost')
        m.resolved_ip = '192.168.1.100'
        app = build_app(pb, tmp_path, [m])
        app._filter_query = '192.168'
        app._update_filter_visible()
        assert 0 in app._filter_visible

    def test_match_against_resolved_hostname(self, pb, tmp_path):
        m = make_monitor(pb, '10.0.0.1')
        m.resolved_hostname = 'myserver.local'
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'myserver'
        app._update_filter_visible()
        assert 0 in app._filter_visible


# ===========================================================================
# _get_visible_entry_indices — filter-aware
# ===========================================================================

class TestGetVisibleEntryIndicesWithFilter:

    def test_no_filter_returns_all_entries(self, pb, tmp_path):
        m1 = make_monitor(pb, 'h1')
        m2 = make_monitor(pb, 'h2')
        app = build_app(pb, tmp_path, [m1, m2])
        result = app._get_visible_entry_indices()
        assert result == [0, 1]

    def test_filter_hides_non_matching_monitors(self, pb, tmp_path):
        m1 = make_monitor(pb, 'web01')
        m2 = make_monitor(pb, 'db01')
        app = build_app(pb, tmp_path, [m1, m2])
        app._filter_query = 'web'
        app._update_filter_visible()
        result = app._get_visible_entry_indices()
        assert 0 in result   # web01 visible
        assert 1 not in result  # db01 hidden

    def test_filter_includes_matching_section(self, pb, tmp_path):
        s = make_section(pb, 'Servers')
        m1 = make_monitor(pb, 'web01')
        m2 = make_monitor(pb, 'db01')
        app = build_app(pb, tmp_path, [s, m1, m2])
        app._filter_query = 'web'
        app._update_filter_visible()
        result = app._get_visible_entry_indices()
        assert 0 in result   # section
        assert 1 in result   # web01
        assert 2 not in result  # db01

    def test_filter_hides_empty_section(self, pb, tmp_path):
        s = make_section(pb, 'DB')
        m = make_monitor(pb, 'db01')
        app = build_app(pb, tmp_path, [s, m])
        app._filter_query = 'web'
        app._update_filter_visible()
        result = app._get_visible_entry_indices()
        assert 0 not in result  # section hidden
        assert 1 not in result  # db01 hidden

    def test_clearing_filter_restores_all_entries(self, pb, tmp_path):
        m1 = make_monitor(pb, 'web01')
        m2 = make_monitor(pb, 'db01')
        app = build_app(pb, tmp_path, [m1, m2])
        app._filter_query = 'web'
        app._update_filter_visible()
        app._filter_query = ''
        app._update_filter_visible()
        result = app._get_visible_entry_indices()
        assert 0 in result
        assert 1 in result


# ===========================================================================
# _cmd_filter — command handler
# ===========================================================================

class TestCmdFilter:

    def test_filter_with_pattern_sets_query(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._cmd_filter('web')
        assert app._filter_query == 'web'

    def test_filter_clear_clears_query(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'web'
        app._update_filter_visible()
        app._cmd_filter('--clear')
        assert app._filter_query == ''
        assert app._filter_visible == set()

    def test_filter_no_args_opens_prompt(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._cmd_filter()
        assert app.prompt is not None
        assert app.prompt['type'] == 'filter'

    def test_filter_updates_visible_on_set(self, pb, tmp_path):
        m1 = make_monitor(pb, 'web01')
        m2 = make_monitor(pb, 'db01')
        app = build_app(pb, tmp_path, [m1, m2])
        app._cmd_filter('web')
        assert len(app._filter_visible_monitors) == 1


# ===========================================================================
# _cmd_select 'none' — Esc priority
# ===========================================================================

class TestEscFilterPriority:

    def test_esc_clears_filter_when_active(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'web'
        app._update_filter_visible()
        app.highlighted_index = 0

        app._cmd_select('none')

        # Filter should be cleared; selection preserved (first Esc just clears filter)
        assert app._filter_query == ''
        assert app.highlighted_index == 0  # still selected

    def test_esc_without_filter_clears_selection(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app.highlighted_index = 0

        app._cmd_select('none')

        assert app.highlighted_index is None

    def test_esc_twice_clears_filter_then_selection(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'web'
        app._update_filter_visible()
        app.highlighted_index = 0

        app._cmd_select('none')  # first Esc: clear filter
        assert app._filter_query == ''
        assert app.highlighted_index == 0

        app._cmd_select('none')  # second Esc: clear selection
        assert app.highlighted_index is None


# ===========================================================================
# _mode_banners — universal banner generator
# ===========================================================================

class TestModeBanners:

    def test_no_banners_when_idle(self, pb, tmp_path):
        m = make_monitor(pb, 'h')
        app = build_app(pb, tmp_path, [m])
        banners = list(app._mode_banners())
        assert banners == []

    def test_history_banner_when_offset_nonzero(self, pb, tmp_path):
        m = make_monitor(pb, 'h')
        app = build_app(pb, tmp_path, [m])
        app.history_offset = 3
        banners = list(app._mode_banners())
        assert len(banners) == 1
        label, attr = banners[0]
        assert 'HISTORY' in label
        assert '3 steps back' in label

    def test_filter_banner_when_query_set(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'web'
        app._update_filter_visible()
        banners = list(app._mode_banners())
        assert len(banners) == 1
        label, attr = banners[0]
        assert 'FILTER' in label
        assert 'web' in label

    def test_both_banners_coexist(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app.history_offset = 5
        app._filter_query = 'web'
        app._update_filter_visible()
        banners = list(app._mode_banners())
        assert len(banners) == 2
        labels = [b[0] for b in banners]
        assert any('HISTORY' in l for l in labels)
        assert any('FILTER' in l for l in labels)

    def test_history_banner_singular_step(self, pb, tmp_path):
        m = make_monitor(pb, 'h')
        app = build_app(pb, tmp_path, [m])
        app.history_offset = 1
        banners = list(app._mode_banners())
        label, _ = banners[0]
        assert '1 step back' in label
        assert 'steps' not in label

    def test_filter_banner_shows_match_count(self, pb, tmp_path):
        m1 = make_monitor(pb, 'web01')
        m2 = make_monitor(pb, 'web02')
        m3 = make_monitor(pb, 'db01')
        app = build_app(pb, tmp_path, [m1, m2, m3])
        app._filter_query = 'web'
        app._update_filter_visible()
        banners = list(app._mode_banners())
        label, _ = banners[0]
        assert '[2/3]' in label


# ===========================================================================
# Filter prompt — state machine
# ===========================================================================

class TestFilterPrompt:

    def test_open_prompt_stores_prev_query(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'web'
        app._cmd_filter_open()
        assert app.prompt['type'] == 'filter'
        assert app.prompt['prev_query'] == 'web'

    def test_esc_restores_previous_query(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'web'
        app._update_filter_visible()
        app._cmd_filter_open()
        # User types something new, then cancels
        app.prompt['chars'] = list('newquery')
        app._filter_query = 'newquery'
        app._update_filter_visible()
        app._handle_prompt_key(27)  # Esc
        assert app.prompt is None
        assert app._filter_query == 'web'  # restored

    def test_enter_confirms_query(self, pb, tmp_path):
        import curses
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._cmd_filter_open()
        app.prompt['chars'] = list('web')
        app._handle_prompt_key(ord('\n'))
        assert app.prompt is None
        assert app._filter_query == 'web'

    def test_typing_updates_live_preview(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._cmd_filter_open()
        app._handle_prompt_key(ord('w'))
        app._handle_prompt_key(ord('e'))
        app._handle_prompt_key(ord('b'))
        # Live preview: _filter_query should be updated
        assert app._filter_query == 'web'

    def test_backspace_updates_live_preview(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._cmd_filter_open()
        app.prompt['chars'] = list('web')
        app._filter_query = 'web'
        app._handle_prompt_key(127)  # backspace
        assert app._filter_query == 'we'

    def test_tab_switches_to_search_prompt(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._filter_query = 'web'
        app._update_filter_visible()
        app._cmd_filter_open()
        app._handle_prompt_key(ord('\t'))  # Tab
        assert app.prompt is not None
        assert app.prompt['type'] == 'search'
        # Filter should be restored to what it was before opening
        assert app._filter_query == 'web'

    def test_search_tab_switches_to_filter_prompt(self, pb, tmp_path):
        m = make_monitor(pb, 'web01')
        app = build_app(pb, tmp_path, [m])
        app._cmd_search_open()
        assert app.prompt['type'] == 'search'
        app._handle_prompt_key(ord('\t'))  # Tab
        assert app.prompt is not None
        assert app.prompt['type'] == 'filter'
