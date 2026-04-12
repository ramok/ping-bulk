"""Unit tests for search and navigation logic — D6.

Covers:
  _get_ancestor_sections(entry_idx)  — find enclosing sections
  _update_search_results()           — match computation (hosts and log modes)
  _apply_search_result(raw_idx)      — selection jump and wrap-around
  _search_live_update()              — auto-unfold on match, restore on no-match
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


def open_host_search(app):
    """Prime the search state machine for a host search."""
    app._search_query = ''
    app._search_mode = 'hosts'
    app._search_results = []
    app._search_idx = 0
    app._search_pre_highlighted = app.highlighted_index
    app._search_pre_fold = {s: s.folded
                            for s in app.entries if isinstance(s, app.__class__.__bases__[0].__subclasscheck__.__self_class__ if False else object)
                            and hasattr(s, 'folded')}
    # simpler: just capture the fold state
    from importlib.machinery import SourceFileLoader
    app._search_pre_fold = {e: e.folded
                             for e in app.entries
                             if hasattr(e, 'folded')}
    app._search_auto_unfolded = set()


# ===========================================================================
# _get_ancestor_sections
# ===========================================================================

class TestGetAncestorSections:

    def test_no_sections_returns_empty(self, pb, tmp_path):
        m = make_monitor(pb, 'h')
        app = build_app(pb, tmp_path, [m])
        result = app._get_ancestor_sections(0)
        assert result == []

    def test_single_section_before_host(self, pb, tmp_path):
        s = make_section(pb)
        m = make_monitor(pb, 'h')
        app = build_app(pb, tmp_path, [s, m])
        result = app._get_ancestor_sections(1)  # index of 'm'
        assert result == [s]

    def test_nested_sections(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1)
        s2 = make_section(pb, 'B', level=2)
        m = make_monitor(pb, 'h')
        app = build_app(pb, tmp_path, [s1, s2, m])
        result = app._get_ancestor_sections(2)
        assert result == [s1, s2]

    def test_sibling_section_not_included(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1)
        m1 = make_monitor(pb, 'h1')
        s2 = make_section(pb, 'B', level=1)
        m2 = make_monitor(pb, 'h2')
        app = build_app(pb, tmp_path, [s1, m1, s2, m2])
        # ancestors of m2 (index 3) should only include s2
        result = app._get_ancestor_sections(3)
        assert result == [s2]

    def test_entry_at_index_0_has_no_ancestors(self, pb, tmp_path):
        m = make_monitor(pb, 'h')
        app = build_app(pb, tmp_path, [m])
        result = app._get_ancestor_sections(0)
        assert result == []

    def test_section_at_index_not_included_in_its_own_ancestors(self, pb, tmp_path):
        s = make_section(pb)
        m = make_monitor(pb, 'h')
        app = build_app(pb, tmp_path, [s, m])
        # Asking for ancestors of the section itself (index 0)
        result = app._get_ancestor_sections(0)
        assert s not in result


# ===========================================================================
# _update_search_results — hosts mode
# ===========================================================================

class TestUpdateSearchResultsHosts:

    def _prime(self, app, query):
        app._search_query = query
        app._search_mode = 'hosts'
        app._search_results = []
        app._update_search_results()

    def test_empty_query_returns_empty(self, pb, tmp_path):
        m = make_monitor(pb, '10.0.0.1')
        app = build_app(pb, tmp_path, [m])
        self._prime(app, '')
        assert app._search_results == []

    def test_match_by_host_name(self, pb, tmp_path):
        m = make_monitor(pb, '10.0.0.1')
        app = build_app(pb, tmp_path, [m])
        self._prime(app, '10.0')
        assert 0 in app._search_results

    def test_no_match_returns_empty(self, pb, tmp_path):
        m = make_monitor(pb, '10.0.0.1')
        app = build_app(pb, tmp_path, [m])
        self._prime(app, 'xyz')
        assert app._search_results == []

    def test_case_insensitive_match(self, pb, tmp_path):
        m = make_monitor(pb, 'MyHost')
        app = build_app(pb, tmp_path, [m])
        self._prime(app, 'myhost')
        assert 0 in app._search_results

    def test_section_labels_not_matched(self, pb, tmp_path):
        s = make_section(pb, 'MySection')
        m = make_monitor(pb, '10.0.0.1')
        app = build_app(pb, tmp_path, [s, m])
        self._prime(app, '10.0')
        # Index 0 is section (should not be in results); index 1 is monitor
        assert 0 not in app._search_results
        assert 1 in app._search_results

    def test_multiple_matches(self, pb, tmp_path):
        m1 = make_monitor(pb, '10.0.0.1')
        m2 = make_monitor(pb, '10.0.0.2')
        m3 = make_monitor(pb, '192.168.0.1')
        app = build_app(pb, tmp_path, [m1, m2, m3])
        self._prime(app, '10.0')
        assert 0 in app._search_results
        assert 1 in app._search_results
        assert 2 not in app._search_results

    def test_match_by_resolved_ip(self, pb, tmp_path):
        m = make_monitor(pb, 'myhost')
        m.resolved_ip = '192.168.1.5'
        app = build_app(pb, tmp_path, [m])
        self._prime(app, '192.168')
        assert 0 in app._search_results

    def test_match_by_resolved_hostname(self, pb, tmp_path):
        m = make_monitor(pb, '10.0.0.1')
        m.resolved_hostname = 'server.example.com'
        app = build_app(pb, tmp_path, [m])
        self._prime(app, 'example')
        assert 0 in app._search_results


# ===========================================================================
# _apply_search_result
# ===========================================================================

class TestApplySearchResult:

    def test_sets_highlighted_index(self, pb, tmp_path):
        m = make_monitor(pb, '10.0.0.1')
        app = build_app(pb, tmp_path, [m])
        app._search_mode = 'hosts'
        app._search_results = [0]
        app._apply_search_result(0)
        assert app.highlighted_index == 0

    def test_wraps_around(self, pb, tmp_path):
        m1 = make_monitor(pb, 'h1')
        m2 = make_monitor(pb, 'h2')
        app = build_app(pb, tmp_path, [m1, m2])
        app._search_mode = 'hosts'
        app._search_results = [0, 1]
        # raw_idx beyond bounds → wraps
        app._apply_search_result(5)
        assert app.highlighted_index in (0, 1)

    def test_empty_results_noop(self, pb, tmp_path):
        m = make_monitor(pb, 'h')
        app = build_app(pb, tmp_path, [m])
        app.highlighted_index = None
        app._search_mode = 'hosts'
        app._search_results = []
        app._apply_search_result(0)
        assert app.highlighted_index is None


# ===========================================================================
# _search_live_update
# ===========================================================================

class TestSearchLiveUpdate:

    def _setup_search(self, pb, tmp_path, layout, query):
        app = build_app(pb, tmp_path, layout)
        app._search_query = query
        app._search_mode = 'hosts'
        app._search_pre_highlighted = None
        app._search_pre_fold = {e: e.folded
                                 for e in app.entries if hasattr(e, 'folded')}
        app._search_auto_unfolded = set()
        app._search_idx = 0
        app._search_results = []
        app._update_search_results()
        return app

    def test_match_in_folded_section_unfolds_it(self, pb, tmp_path):
        s = make_section(pb, folded=True)
        m = make_monitor(pb, '10.0.0.1')
        app = self._setup_search(pb, tmp_path, [s, m], '10.0')
        app._search_live_update()
        assert s.folded is False

    def test_unmatched_section_stays_folded(self, pb, tmp_path):
        s1 = make_section(pb, 'A', level=1, folded=True)
        m1 = make_monitor(pb, '10.0.0.1')
        s2 = make_section(pb, 'B', level=1, folded=True)
        m2 = make_monitor(pb, '192.168.0.1')
        app = self._setup_search(pb, tmp_path, [s1, m1, s2, m2], '10.0')
        app._search_live_update()
        assert s1.folded is False   # s1 contains the match
        assert s2.folded is True    # s2 doesn't — stays folded

    def test_no_match_restores_highlighted_index(self, pb, tmp_path):
        m = make_monitor(pb, '10.0.0.1')
        app = self._setup_search(pb, tmp_path, [m], '')
        app._search_pre_highlighted = None
        app._search_results = []
        app._search_live_update()
        assert app.highlighted_index is None

    def test_auto_unfolded_sections_refold_on_new_query(self, pb, tmp_path):
        s = make_section(pb, folded=True)
        m = make_monitor(pb, '10.0.0.1')
        app = self._setup_search(pb, tmp_path, [s, m], '10.0')
        # First search: unfolds s
        app._search_live_update()
        assert s.folded is False

        # Change query to something that does NOT match → s should refold
        app._search_query = 'xyz'
        app._update_search_results()   # no matches
        app._search_live_update()
        assert s.folded is True
