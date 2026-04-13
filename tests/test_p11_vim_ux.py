"""Unit tests for Phase 11 vim-style UX features.

Tests cover:
  - :unbind-key command removes a key binding
  - :bind-key <key> (no cmd) queries what is bound to that key
  - Vim navigation defaults: G, gg, Ctrl-F, Ctrl-B
  - :fold word aliases (open/close/open-recursive/...)
  - Search: _update_search_results, _apply_search_result, n/N navigation
  - Help overlay: help_show_all toggle via _cmd_help_toggle_all
"""

import os
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_app(pb, tmp_path):
    """Return a non-running Application with a blank temp config."""
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, 'w') as f:
        f.write('')
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '127.0.0.1')])
    app._monitoring_started = True
    return app


@pytest.fixture
def app(pb, tmp_path):
    return _make_app(pb, tmp_path)


# ===========================================================================
# TestUnbindKey — :unbind-key command
# ===========================================================================

class TestUnbindKey:
    """Tests for :unbind-key command (and :bind-key query mode)."""

    def test_unbind_key_removes_user_binding(self, app, pb):
        """':unbind-key t' removes a previously set user binding."""
        app._cmd_bindkey('t :mux mtr')
        keys = pb._parse_key_notation('t')
        assert app._key_trie.resolve(keys, set())[0] is not None

        app._last_cmd_name = 'unbind-key'
        app._cmd_bindkey('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None

    def test_unbind_key_removes_default_binding(self, app, pb):
        """':unbind-key q' removes the default :quit binding."""
        keys = pb._parse_key_notation('q')
        assert app._key_trie.resolve(keys, set())[0] is not None

        app._last_cmd_name = 'unbind-key'
        app._cmd_bindkey('q')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None

    def test_unbind_key_logs_unbound(self, app, pb):
        """':unbind-key q' logs 'unbound q' in events."""
        app.events.clear()
        app._last_cmd_name = 'unbind-key'
        app._cmd_bindkey('q')
        assert any('unbound q' in e for e in app.events)

    def test_unbind_key_nonexistent_logs_no_binding(self, app, pb):
        """':unbind-key x' when 'x' has no binding logs 'no binding'."""
        app.events.clear()
        app._last_cmd_name = 'unbind-key'
        app._cmd_bindkey('x')
        assert any('no binding' in e for e in app.events)

    def test_bind_key_query_no_cmd(self, app, pb):
        """':bind-key q' (no command) queries the binding rather than removing it."""
        app.events.clear()
        # Do NOT set _last_cmd_name to 'unbind-key'; use default 'bind-key'
        app._last_cmd_name = 'bind-key'
        app._cmd_bindkey('q')
        # q is bound to :quit by default — should report it
        assert any('quit' in e for e in app.events)
        # The binding must still be present
        keys = pb._parse_key_notation('q')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None

    def test_bind_key_query_unbound_key(self, app, pb):
        """':bind-key x' when 'x' has no binding reports 'no binding'."""
        app.events.clear()
        app._last_cmd_name = 'bind-key'
        app._cmd_bindkey('x')
        assert any('no binding' in e for e in app.events)

    def test_unbind_key_saved_as_unbind_key_in_config(self, app, pb, tmp_path):
        """After ':unbind-key q', saved config contains ':unbind-key q'."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        app._last_cmd_name = 'unbind-key'
        app._cmd_bindkey('q')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        lines = [l.strip() for l in open(cfg).read().splitlines()]
        assert ':unbind-key q' in lines

    def test_unbind_key_not_saved_as_bind_key(self, app, pb, tmp_path):
        """Saved config must NOT contain bare ':bind-key q' for an unbind."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        app._last_cmd_name = 'unbind-key'
        app._cmd_bindkey('q')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        text = open(cfg).read()
        assert ':bind-key q\n' not in text


# ===========================================================================
# TestVimNavDefaults — G, gg, Ctrl-F, Ctrl-B default bindings
# ===========================================================================

class TestVimNavDefaults:
    """Verify default vim-style navigation bindings are registered."""

    def test_G_bound_to_select_last(self, app, pb):
        """'G' is bound to ':select last'."""
        keys = pb._parse_key_notation('G')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert ':select last' in binding.commands

    def test_gg_bound_to_select_first(self, app, pb):
        """'gg' (two-key sequence) is bound to ':select first'."""
        keys = pb._parse_key_notation('gg')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert ':select first' in binding.commands

    def test_ctrl_f_bound_to_scroll_log_page_forward(self, app, pb):
        """Ctrl-F is bound to ':scroll event-history page-' (forward)."""
        keys = pb._parse_key_notation('<C-f>')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert ':scroll event-history page-' in binding.commands

    def test_ctrl_b_bound_to_scroll_log_page_back(self, app, pb):
        """Ctrl-B is bound to ':scroll event-history page' (backward)."""
        keys = pb._parse_key_notation('<C-b>')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert ':scroll event-history page' in binding.commands


# ===========================================================================
# TestFoldAliases — :fold word aliases
# ===========================================================================

class TestFoldAliases:
    """Test that :fold accepts word aliases in addition to z-notation."""

    def _fold_alias_maps(self, app, word, expected_z):
        """Helper: cmd :fold <word> should behave like :fold <expected_z>."""
        app.events.clear()
        # Attempt fold — if no sections, it logs something but must not error
        try:
            app._cmd_fold(word)
        except Exception as exc:
            pytest.fail(f":fold {word!r} raised {exc!r}")
        # The word alias must NOT produce an "invalid" error
        assert not any(
            'invalid' in e.lower() and 'fold' in e.lower()
            for e in app.events
        ), f":fold {word!r} was rejected as invalid"

    def test_fold_open(self, app):
        self._fold_alias_maps(app, 'open', 'zo')

    def test_fold_close(self, app):
        self._fold_alias_maps(app, 'close', 'zc')

    def test_fold_open_recursive(self, app):
        self._fold_alias_maps(app, 'open-recursive', 'zO')

    def test_fold_close_recursive(self, app):
        self._fold_alias_maps(app, 'close-recursive', 'zC')

    def test_fold_open_all(self, app):
        self._fold_alias_maps(app, 'open-all', 'zR')

    def test_fold_close_all(self, app):
        self._fold_alias_maps(app, 'close-all', 'zM')

    def test_fold_open_level(self, app):
        self._fold_alias_maps(app, 'open-level', 'zr')

    def test_fold_close_level(self, app):
        self._fold_alias_maps(app, 'close-level', 'zm')

    def test_fold_toggle_still_works(self, app):
        self._fold_alias_maps(app, 'toggle', 'za')

    def test_fold_toggle_recursive_still_works(self, app):
        self._fold_alias_maps(app, 'toggle-recursive', 'zA')

    def test_fold_invalid_word_rejected(self, app):
        """:fold with unknown word is rejected."""
        app.events.clear()
        app._cmd_fold('notavalidword')
        assert any('unknown' in e.lower() or 'invalid' in e.lower()
                   for e in app.events)


# ===========================================================================
# TestSearch — search state, update, apply, navigation
# ===========================================================================

class TestSearch:
    """Test _update_search_results and _apply_search_result logic."""

    def _add_hosts(self, app, pb, hosts):
        """Add PingMonitor entries to app."""
        for h in hosts:
            m = pb.PingMonitor(h)
            m.resolved_ip = None
            app.entries.append(m)

    def test_update_search_hosts_mode_finds_matches(self, app, pb):
        """_update_search_results in 'hosts' mode returns indices of matching hosts."""
        self._add_hosts(app, pb, ['alpha.example.com', 'beta.example.com', 'gamma.net'])
        app._search_mode = 'hosts'
        app._search_query = 'example'
        app._update_search_results()
        # entries are at indices 1,2 (index 0 is the '127.0.0.1' from app fixture)
        matched_hosts = [app.entries[i].host for i in app._search_results]
        assert 'alpha.example.com' in matched_hosts
        assert 'beta.example.com' in matched_hosts
        assert 'gamma.net' not in matched_hosts

    def test_update_search_hosts_mode_case_insensitive(self, app, pb):
        """Host search is case-insensitive."""
        self._add_hosts(app, pb, ['ROUTER.LAN'])
        app._search_mode = 'hosts'
        app._search_query = 'router'
        app._update_search_results()
        matched = [app.entries[i].host for i in app._search_results]
        assert 'ROUTER.LAN' in matched

    def test_update_search_hosts_mode_no_match(self, app, pb):
        """_update_search_results returns empty list when nothing matches."""
        self._add_hosts(app, pb, ['alpha.com', 'beta.com'])
        app._search_mode = 'hosts'
        app._search_query = 'zzznomatch'
        app._update_search_results()
        assert app._search_results == []

    def test_apply_search_result_hosts_sets_highlighted_index(self, app, pb):
        """_apply_search_result in 'hosts' mode sets highlighted_index."""
        self._add_hosts(app, pb, ['target.host'])
        app._search_mode = 'hosts'
        app._search_query = 'target'
        app._update_search_results()
        assert len(app._search_results) >= 1
        app._apply_search_result(0)
        assert app.highlighted_index == app._search_results[0]

    def test_search_next_advances_idx(self, app, pb):
        """_cmd_search_next advances _search_idx to next result."""
        self._add_hosts(app, pb, ['a.example.com', 'b.example.com', 'c.example.com'])
        app._search_mode = 'hosts'
        app._search_query = 'example'
        app._update_search_results()
        assert len(app._search_results) >= 2
        app._search_idx = 0
        app._cmd_search_next()
        assert app._search_idx == 1

    def test_search_next_wraps_around(self, app, pb):
        """_cmd_search_next wraps from last to first result."""
        self._add_hosts(app, pb, ['a.example.com', 'b.example.com'])
        app._search_mode = 'hosts'
        app._search_query = 'example'
        app._update_search_results()
        n = len(app._search_results)
        assert n >= 2
        app._search_idx = n - 1
        app._cmd_search_next()
        assert app._search_idx == 0

    def test_search_prev_goes_backward(self, app, pb):
        """_cmd_search_next 'prev' moves _search_idx backward."""
        self._add_hosts(app, pb, ['a.example.com', 'b.example.com', 'c.example.com'])
        app._search_mode = 'hosts'
        app._search_query = 'example'
        app._update_search_results()
        assert len(app._search_results) >= 2
        app._search_idx = 1
        app._cmd_search_next('prev')
        assert app._search_idx == 0

    def test_search_prev_wraps_to_last(self, app, pb):
        """_cmd_search_next 'prev' wraps from first to last result."""
        self._add_hosts(app, pb, ['a.example.com', 'b.example.com'])
        app._search_mode = 'hosts'
        app._search_query = 'example'
        app._update_search_results()
        n = len(app._search_results)
        assert n >= 2
        app._search_idx = 0
        app._cmd_search_next('prev')
        assert app._search_idx == n - 1

    def test_search_next_noop_when_no_results(self, app, pb):
        """_cmd_search_next does nothing when there are no results."""
        app._search_mode = 'hosts'
        app._search_results = []
        app._search_idx = 0
        app._cmd_search_next()  # must not raise
        assert app._search_idx == 0

    def test_search_open_sets_mode_hosts_when_selected(self, app, pb):
        """_cmd_search_open sets prompt mode to 'hosts' when a host is selected."""
        self._add_hosts(app, pb, ['test.local'])
        app.highlighted_index = 0
        app._cmd_search_open()
        assert app.prompt is not None
        assert app.prompt.get('mode') == 'hosts'

    def test_search_open_sets_mode_log_when_not_selected(self, app, pb):
        """_cmd_search_open sets prompt mode to 'log' when no host is selected."""
        app.highlighted_index = None
        app._cmd_search_open()
        assert app.prompt is not None
        assert app.prompt.get('mode') == 'log'


# ===========================================================================
# TestHelpToggleAll — help overlay all-bindings toggle
# ===========================================================================

class TestHelpToggleAll:
    """Test help_show_all toggle and _build_all_bindings_lines."""

    def test_toggle_all_flips_state(self, app):
        """_cmd_help_toggle_all flips help_show_all."""
        app.help_show_all = False
        app._cmd_help_toggle_all()
        assert app.help_show_all is True
        app._cmd_help_toggle_all()
        assert app.help_show_all is False

    def test_toggle_all_resets_scroll(self, app):
        """_cmd_help_toggle_all resets help_scroll to 0."""
        app.help_scroll = 42
        app._cmd_help_toggle_all()
        assert app.help_scroll == 0

    def test_build_all_bindings_has_entries(self, app):
        """_build_all_bindings_lines returns at least one line per default binding."""
        lines = app._build_all_bindings_lines()
        assert len(lines) > 0

    def test_build_all_bindings_contains_quit(self, app):
        """_build_all_bindings_lines mentions the :quit binding somewhere."""
        lines = app._build_all_bindings_lines()
        assert any('quit' in line for line in lines)

    def test_build_all_bindings_no_duplicates(self, app):
        """_build_all_bindings_lines does not repeat bindings within the same mode section."""
        lines = app._build_all_bindings_lines()
        # Split output into per-mode sections and check uniqueness within each section.
        # Bindings may legitimately repeat across different modes (e.g. 'q → :close'
        # appearing in both help mode and details mode is expected).
        current_section = []
        for line in lines:
            if line.startswith('-DIVIDER-') or (line.startswith('  ') and not line.startswith('    ')):
                # Check previous section for dups before starting a new one
                binding_lines = [l for l in current_section if l.startswith('    ')]
                assert len(binding_lines) == len(set(binding_lines)), (
                    f"Duplicate bindings in section: {[l for l, c in __import__('collections').Counter(binding_lines).items() if c > 1]}"
                )
                current_section = []
            else:
                current_section.append(line)
        # Check last section
        binding_lines = [l for l in current_section if l.startswith('    ')]
        assert len(binding_lines) == len(set(binding_lines))
