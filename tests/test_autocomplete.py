"""Unit tests for the ping-bulk command-line autocompleter.

Covers three layers of the completion system:

  _get_completions(text)
      Context-sensitive candidate list: command names when completing the
      first token, argument values when completing the second token, and an
      empty list for three or more tokens.

  Application._apply_completion(c, candidate)
      Static helper that replaces the rightmost partial token in the
      command-line buffer with the chosen candidate and moves the cursor to
      the end of the substituted text.

  Application._handle_cmd_key(key) — Tab / Shift+Tab paths
      The Tab key invokes _get_completions(), applies LCP (longest-common-prefix)
      when multiple candidates share a longer prefix than what is already typed,
      and opens a popup list.  Subsequent Tab presses cycle *forward* through the
      candidates (like Vim's wildmode=full).  Shift+Tab cycles *backward*.  When
      only one candidate exists it is applied immediately with a trailing space
      and no popup is shown.

No ping threads are started; the Application is built from a single
in-memory host entry with a mocked config path so the real user config is
never read or written.

Fixtures
--------
pb
    The ping-bulk module, imported once for the whole session via
    importlib.util (the script has no .py extension).

app (function-scoped)
    A fresh, non-running Application with self.cmd pre-opened and ready to
    accept keystrokes.
"""

import curses
import os
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helper: build a non-running Application with a temp config path
# ---------------------------------------------------------------------------

def _make_app(pb, tmp_path):
    """Return a non-running Application with a blank temp config."""
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, 'w') as f:
        f.write('')
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '127.0.0.1')])
    return app


def _open_cmd(app):
    """Open the command line (: mode) and return the cmd dict."""
    app.cmd = {
        'chars': [], 'cursor': 0,
        'hist_idx': -1, 'saved_line': '',
        'completions': [], 'comp_idx': -1, 'comp_prefix': '',
    }
    return app.cmd


def _set_text(app, text):
    """Set the command line text and position the cursor at the end."""
    app.cmd['chars'] = list(text)
    app.cmd['cursor'] = len(text)


# ---------------------------------------------------------------------------
# Fixture: fresh Application with cmd open
# ---------------------------------------------------------------------------

@pytest.fixture
def app(pb, tmp_path):
    """A non-running Application with the command line open and empty."""
    a = _make_app(pb, tmp_path)
    _open_cmd(a)
    return a


# ===========================================================================
# TestGetCompletions — _get_completions(text)
# ===========================================================================

class TestGetCompletions:
    """Tests for Application._get_completions(text)."""

    # ── First token: command name completion ─────────────────────────────

    def test_empty_text_returns_all_completable_commands(self, app, pb):
        """Empty input must return all completable command names."""
        result = app._get_completions('')
        # All names in CMD_REGISTRY where completable=True should be present.
        completable = {
            name
            for cmd in pb.CMD_REGISTRY
            for name in cmd.names
            if cmd.completable
        }
        assert set(result) == completable, (
            f"Expected all completable names, got {sorted(result)}"
        )

    def test_partial_prefix_s_filters_to_matching_commands(self, app):
        """'s' prefix must match all completable commands starting with 's'."""
        result = app._get_completions('s')
        assert set(result) == {'saveconfig', 'screen', 'scroll-history', 'scroll-log',
                                'scroll-overlay', 'seen', 'select', 'set', 'sort',
                                'source', 'ssh', 'stats', 'sync-history'}, (
            f"Unexpected results for 's': {sorted(result)}"
        )

    def test_exact_command_returns_itself(self, app):
        """Typing the full command name 'log' must match only 'log' (log-size is :set only)."""
        result = app._get_completions('log')
        assert result == ['log'], f"Expected ['log'], got {result}"

    def test_colon_prefix_stripped_before_matching(self, app):
        """A leading ':' must be stripped; ':lo' must resolve the same as 'lo'."""
        with_colon    = app._get_completions(':lo')
        without_colon = app._get_completions('lo')
        assert with_colon == without_colon, (
            f"Mismatch: ':lo'→{with_colon}  'lo'→{without_colon}"
        )

    def test_no_match_returns_empty(self, app):
        """An unrecognised prefix must return an empty list."""
        result = app._get_completions('zzz')
        assert result == [], f"Expected [], got {result}"

    def test_prefix_h_returns_history_hist_help(self, app):
        """'h' must match history, hist, and help."""
        result = app._get_completions('h')
        assert set(result) == {'history', 'hist', 'help'}, (
            f"Unexpected results for 'h': {sorted(result)}"
        )

    def test_prefix_hi_returns_history_and_hist(self, app):
        """'hi' must match history and hist (help does not start with 'hi')."""
        result = app._get_completions('hi')
        assert set(result) == {'history', 'hist'}, (
            f"Unexpected results for 'hi': {sorted(result)}"
        )

    def test_non_completable_ssh_begin_not_returned(self, app):
        """ssh-begin and ssh-end are marked completable=False and must be excluded."""
        result = app._get_completions('')
        assert 'ssh-begin' not in result, "'ssh-begin' should be excluded from completions"
        assert 'ssh-end'   not in result, "'ssh-end' should be excluded from completions"

    def test_result_is_sorted(self, app):
        """Completions for the first token must be returned in sorted order."""
        result = app._get_completions('s')
        assert result == sorted(result), f"Completions are not sorted: {result}"

    # ── Second token: argument value completion ───────────────────────────

    def test_dns_with_trailing_space_returns_all_dns_modes(self, app, pb):
        """'dns ' must return the full list of DNS mode names."""
        result = app._get_completions('dns ')
        expected = [m.lower() for m in pb.DNS_MODES]
        assert result == expected, (
            f"Expected dns modes {expected}, got {result}"
        )

    def test_dns_partial_arg_h_returns_hostname(self, app):
        """'dns h' must return only 'hostname'."""
        result = app._get_completions('dns h')
        assert result == ['hostname'], f"Expected ['hostname'], got {result}"

    def test_dns_partial_arg_no_match_returns_empty(self, app):
        """'dns zzz' must return an empty list."""
        result = app._get_completions('dns zzz')
        assert result == [], f"Expected [], got {result}"

    def test_stats_with_trailing_space_returns_all_stats_modes(self, app, pb):
        """'stats ' must return all STATS_MODES plus extra stat aliases (lowercased)."""
        result = app._get_completions('stats ')
        expected = sorted(set(m.lower() for m in pb.STATS_MODES) | set(pb.STAT_NAMES.keys()))
        assert result == expected, (
            f"Expected stats modes {expected}, got {result}"
        )

    def test_sort_with_trailing_space_returns_all_sort_modes(self, app):
        """'sort ' must return all four sort mode names."""
        result = app._get_completions('sort ')
        assert set(result) == {'none', 'name', 'status', 'latency'}, (
            f"Unexpected sort completions: {result}"
        )

    def test_history_with_trailing_space_returns_all_history_modes(self, app, pb):
        """'history ' must return the full list of HISTORY_MODES (lowercased)."""
        result = app._get_completions('history ')
        expected = [m.lower() for m in pb.HISTORY_MODES]
        assert result == expected, (
            f"Expected history modes {expected}, got {result}"
        )

    def test_log_with_trailing_space_includes_off(self, app):
        """'log ' must include the static keyword 'off' among its completions."""
        result = app._get_completions('log ')
        assert 'off' in result, f"'off' not found in 'log ' completions: {result}"

    def test_log_arg_off_prefix_returns_off(self, app):
        """'log o' must return 'off' (matches the 'off' static keyword)."""
        result = app._get_completions('log o')
        assert 'off' in result, f"'off' not found in 'log o' completions: {result}"

    def test_log_arg_uppercase_prefix_case_insensitive(self, app):
        """'log O' must still match 'off' (case-insensitive keyword check)."""
        result = app._get_completions('log O')
        assert 'off' in result, f"'off' not found in 'log O' completions: {result}"

    def test_three_tokens_returns_empty(self, app):
        """Three tokens (completed second arg + trailing space) must return []."""
        result = app._get_completions('dns off extra')
        assert result == [], f"Expected [] for three tokens, got {result}"

    def test_two_complete_tokens_with_trailing_space_returns_empty(self, app):
        """'dns off ' (two tokens + trailing space = start of 3rd) must return []."""
        result = app._get_completions('dns off ')
        assert result == [], (
            f"Expected [] for 'dns off ' (3rd-token position), got {result}"
        )

    def test_unknown_command_second_token_returns_empty(self, app):
        """Unknown command 'zzz ' has no registered arg choices → empty list."""
        result = app._get_completions('zzz ')
        assert result == [], f"Expected [] for unknown command arg, got {result}"


# ===========================================================================
# TestApplyCompletion — Application._apply_completion(c, candidate)
# ===========================================================================

class TestApplyCompletion:
    """Tests for the static method Application._apply_completion(c, candidate)."""

    def _make_cmd(self, text):
        """Create a minimal cmd dict with the given text and cursor at end."""
        return {'chars': list(text), 'cursor': len(text)}

    def test_replace_only_token(self, app):
        """Partial first token 'lo' + candidate 'log' → chars become 'log'."""
        c = self._make_cmd('lo')
        app._apply_completion(c, 'log')
        assert ''.join(c['chars']) == 'log'

    def test_replace_second_token_after_space(self, app):
        """'dns ho' + candidate 'hostname' → 'dns hostname'."""
        c = self._make_cmd('dns ho')
        app._apply_completion(c, 'hostname')
        assert ''.join(c['chars']) == 'dns hostname'

    def test_replace_empty_second_token_after_trailing_space(self, app):
        """'dns ' (trailing space, empty second token) + candidate → 'dns hostname'."""
        c = self._make_cmd('dns ')
        app._apply_completion(c, 'hostname')
        assert ''.join(c['chars']) == 'dns hostname'

    def test_cursor_moved_to_end_of_new_text(self, app):
        """After applying a completion the cursor must be at len(new_text)."""
        c = self._make_cmd('lo')
        app._apply_completion(c, 'log')
        assert c['cursor'] == len('log')

    def test_cursor_moved_to_end_with_prefix(self, app):
        """Cursor after 'dns hostname' must be 12 (len('dns hostname'))."""
        c = self._make_cmd('dns ho')
        app._apply_completion(c, 'hostname')
        assert c['cursor'] == len('dns hostname')

    def test_apply_to_empty_text(self, app):
        """Applying a candidate to an empty buffer must set chars to the candidate."""
        c = self._make_cmd('')
        app._apply_completion(c, 'log')
        assert ''.join(c['chars']) == 'log'
        assert c['cursor'] == len('log')

    def test_prefix_before_last_space_preserved(self, app):
        """Only the token after the last space is replaced; earlier tokens are kept."""
        c = self._make_cmd('dns host')
        app._apply_completion(c, 'hostname')
        result = ''.join(c['chars'])
        assert result.startswith('dns '), f"Prefix 'dns ' was not preserved: {result!r}"
        assert result == 'dns hostname'

    def test_full_candidate_replaces_identical_token(self, app):
        """Applying 'log' to 'log' (exact match) must keep the text as 'log'."""
        c = self._make_cmd('log')
        app._apply_completion(c, 'log')
        assert ''.join(c['chars']) == 'log'
        assert c['cursor'] == len('log')


# ===========================================================================
# TestTabHandling — Tab key path in _handle_cmd_key
# ===========================================================================

class TestTabHandling:
    """Tests for the Tab-key completion path inside _handle_cmd_key."""

    TAB       = ord('\t')
    SHIFT_TAB = curses.KEY_BTAB

    # ── Unique match ─────────────────────────────────────────────────────

    def test_unique_match_applies_candidate(self, app):
        """Single candidate: Tab must apply it into the chars buffer."""
        _set_text(app, 'lo')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text.startswith('log'), (
            f"Expected text starting with 'log', got {text!r}"
        )

    def test_unique_match_appends_trailing_space(self, app):
        """Single candidate: Tab must append a trailing space after the command."""
        _set_text(app, 'save')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'saveconfig ', f"Expected 'saveconfig ' (with trailing space), got {text!r}"

    def test_unique_match_no_popup(self, app):
        """Single candidate: the completion popup must be cleared (no list needed)."""
        _set_text(app, 'save')
        app._handle_cmd_key(self.TAB)
        assert app.cmd['completions'] == [], (
            f"Expected empty completions after unique match, got {app.cmd['completions']}"
        )

    def test_unique_match_cursor_at_end(self, app):
        """Single candidate: cursor must be placed after the trailing space."""
        _set_text(app, 'lo')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert app.cmd['cursor'] == len(text), (
            f"Expected cursor={len(text)}, got {app.cmd['cursor']}"
        )

    def test_unique_match_directory_no_trailing_space(self, app, tmp_path):
        """Single candidate ending with '/': no trailing space must be added."""
        # Create a temp sub-directory so filesystem completion returns a dir entry.
        subdir = tmp_path / 'mysubdir'
        subdir.mkdir()
        prefix = str(tmp_path) + '/mysu'
        _set_text(app, f'log {prefix}')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        # The completed text must end with '/' (directory) and no extra space.
        assert text.endswith('/'), (
            f"Expected trailing '/' for directory completion, got {text!r}"
        )
        assert not text.endswith('/ '), (
            f"Directory completion must not append a space, got {text!r}"
        )

    # ── Multiple matches: LCP extension ──────────────────────────────────

    def test_lcp_extends_partial_token(self, app):
        """'hi' has candidates history+hist; LCP='hist' extends the typed 'hi'."""
        _set_text(app, 'hi')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'hist', (
            f"Expected LCP 'hist' applied to 'hi', got {text!r}"
        )

    def test_lcp_does_not_append_space_for_multiple_matches(self, app):
        """LCP extension for multiple matches must not append a trailing space."""
        _set_text(app, 'hi')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert not text.endswith(' '), (
            f"LCP extension must not add a trailing space for multiple matches: {text!r}"
        )

    def test_lcp_popup_remains_open_after_extension(self, app):
        """After LCP extends the token, the completion popup must remain visible."""
        _set_text(app, 'hi')
        app._handle_cmd_key(self.TAB)
        assert app.cmd['completions'], (
            "Popup completions must stay populated after an LCP extension"
        )

    def test_lcp_popup_contains_all_candidates(self, app):
        """The popup must list all matching candidates after LCP extension."""
        _set_text(app, 'hi')
        app._handle_cmd_key(self.TAB)
        assert set(app.cmd['completions']) == {'history', 'hist'}, (
            f"Expected {{history, hist}} in popup, got {app.cmd['completions']}"
        )

    # ── Multiple matches: no LCP extension ───────────────────────────────

    def test_no_lcp_extension_text_unchanged(self, app):
        """'h' (history/hist/help): LCP='h' gives no extension; text stays 'h'."""
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'h', (
            f"Expected text unchanged at 'h' (no LCP extension), got {text!r}"
        )

    def test_no_lcp_extension_popup_contains_candidates(self, app):
        """When LCP gives no extension the popup must still list all candidates."""
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)
        assert set(app.cmd['completions']) == {'history', 'hist', 'help'}, (
            f"Expected {{history, hist, help}} in popup, got {app.cmd['completions']}"
        )

    def test_no_lcp_extension_comp_idx_minus_one(self, app):
        """comp_idx must stay -1 (no highlighted selection) for a popup list."""
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)
        assert app.cmd['comp_idx'] == -1, (
            f"Expected comp_idx=-1 (no selection), got {app.cmd['comp_idx']}"
        )

    # ── No match ─────────────────────────────────────────────────────────

    def test_no_match_text_unchanged(self, app):
        """Tab on an unrecognised prefix must not alter the command buffer."""
        _set_text(app, 'zzz')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'zzz', f"Expected 'zzz' unchanged, got {text!r}"

    def test_no_match_completions_empty(self, app):
        """Tab on an unrecognised prefix must leave completions empty."""
        _set_text(app, 'zzz')
        app._handle_cmd_key(self.TAB)
        assert app.cmd['completions'] == [], (
            f"Expected empty completions for no match, got {app.cmd['completions']}"
        )

    # ── Tab cycling (forward, wildmode=full) ─────────────────────────────

    def test_second_tab_with_popup_open_text_unchanged(self, app):
        """A second Tab while the popup is open cycles forward to the first candidate."""
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)   # opens popup, comp_idx=-1, text='h'
        first_candidate = app.cmd['completions'][0]
        app._handle_cmd_key(self.TAB)   # second Tab — cycles to first candidate
        text = ''.join(app.cmd['chars'])
        assert text == first_candidate, (
            f"Expected text={first_candidate!r} (first candidate) after second Tab, "
            f"got {text!r}"
        )

    def test_second_tab_with_popup_open_comp_idx_unchanged(self, app):
        """A second Tab while the popup is open must advance comp_idx to 0."""
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)
        app._handle_cmd_key(self.TAB)
        assert app.cmd['comp_idx'] == 0, (
            f"Expected comp_idx=0 after second Tab, got {app.cmd['comp_idx']}"
        )

    def test_second_tab_popup_completions_unchanged(self, app):
        """A second Tab while the popup is open must not alter the candidate list."""
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)
        completions_after_first = list(app.cmd['completions'])
        app._handle_cmd_key(self.TAB)
        assert app.cmd['completions'] == completions_after_first, (
            "Second Tab changed the completions list"
        )

    def test_third_tab_cycles_to_second_candidate(self, app):
        """A third Tab must advance comp_idx to 1 and apply the second candidate.

        Completions for 'h' = ['help', 'hist', 'history'] (sorted).
        Tab×1: popup opens, comp_idx=-1, text='h' (LCP='h', no extension).
        Tab×2: comp_idx=0, text='help'.
        Tab×3: comp_idx=1, text='hist'.
        """
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)   # Tab×1 — opens popup, comp_idx=-1
        app._handle_cmd_key(self.TAB)   # Tab×2 — comp_idx=0, text='help'
        app._handle_cmd_key(self.TAB)   # Tab×3 — comp_idx=1, text='hist'
        assert app.cmd['comp_idx'] == 1, (
            f"Expected comp_idx=1 after third Tab, got {app.cmd['comp_idx']}"
        )
        text = ''.join(app.cmd['chars'])
        assert text == 'hist', (
            f"Expected text='hist' after third Tab, got {text!r}"
        )

    def test_tab_wraps_from_last_to_first(self, app):
        """After cycling through all candidates a further Tab wraps back to first.

        Completions for 'h' = ['help', 'hist', 'history'] (sorted, n=3).
        Tab×1: popup opens, comp_idx=-1.
        Tab×2: comp_idx=0 ('help').
        Tab×3: comp_idx=1 ('hist').
        Tab×4: comp_idx=2 ('history').
        Tab×5: wraps → comp_idx=0 ('help').
        """
        _set_text(app, 'h')
        for _ in range(5):
            app._handle_cmd_key(self.TAB)
        assert app.cmd['comp_idx'] == 0, (
            f"Expected comp_idx=0 after wrap-around, got {app.cmd['comp_idx']}"
        )
        text = ''.join(app.cmd['chars'])
        assert text == 'help', (
            f"Expected text='help' after wrap-around, got {text!r}"
        )

    # ── Non-Tab key clears popup ──────────────────────────────────────────

    def test_non_tab_key_clears_completions(self, app):
        """Pressing any non-Tab key must clear the completion popup."""
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)   # open popup
        assert app.cmd['completions']   # sanity: popup is open

        # Press a printable key — it should clear the popup.
        app._handle_cmd_key(ord('i'))
        assert app.cmd['completions'] == [], (
            f"Expected popup cleared after non-Tab key, got {app.cmd['completions']}"
        )
        assert app.cmd['comp_idx'] == -1, (
            f"Expected comp_idx=-1 after non-Tab key, got {app.cmd['comp_idx']}"
        )

    def test_non_tab_key_inserts_character(self, app):
        """Pressing a printable key after a Tab clears the popup and inserts the char."""
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)
        app._handle_cmd_key(ord('e'))   # should clear popup and insert 'e'
        text = ''.join(app.cmd['chars'])
        assert text.endswith('e'), (
            f"Expected text to end with 'e' after key press, got {text!r}"
        )

    # ── Shift+Tab cycling (backward) ─────────────────────────────────────

    def test_shift_tab_no_popup_opens_popup_and_wraps_to_last(self, app):
        """Shift+Tab with no open popup must open it and wrap to the last candidate.

        Completions for 'h' = ['help', 'hist', 'history'] (sorted, n=3).
        Shift+Tab wrap rule: (n-1) if idx <= 0.
        comp_idx starts at -1 → wraps to 2 → text='history'.
        """
        _set_text(app, 'h')
        app._handle_cmd_key(self.SHIFT_TAB)
        assert app.cmd['comp_idx'] == 2, (
            f"Expected comp_idx=2 (last candidate) after cold Shift+Tab, "
            f"got {app.cmd['comp_idx']}"
        )
        text = ''.join(app.cmd['chars'])
        assert text == 'history', (
            f"Expected text='history' after cold Shift+Tab, got {text!r}"
        )

    def test_shift_tab_popup_open_at_minus_one_wraps_to_last(self, app):
        """Shift+Tab while popup is open with comp_idx=-1 must wrap to last candidate.

        Tab×1: popup opens, comp_idx=-1, text='h' (LCP no extension).
        Shift+Tab: comp_idx=-1 → wraps to 2 → text='history'.
        """
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)           # Tab×1: popup, comp_idx=-1
        app._handle_cmd_key(self.SHIFT_TAB)     # Shift+Tab: wraps to last
        assert app.cmd['comp_idx'] == 2, (
            f"Expected comp_idx=2 after Tab×1 + Shift+Tab, got {app.cmd['comp_idx']}"
        )
        text = ''.join(app.cmd['chars'])
        assert text == 'history', (
            f"Expected text='history' after Tab×1 + Shift+Tab, got {text!r}"
        )

    def test_shift_tab_from_comp_idx_zero_wraps_to_last(self, app):
        """Shift+Tab when comp_idx=0 must wrap backward to the last candidate.

        Tab×2: comp_idx=0, text='help'.
        Shift+Tab: comp_idx=0 → (n-1) = 2 → text='history'.
        """
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)           # Tab×1: popup, comp_idx=-1
        app._handle_cmd_key(self.TAB)           # Tab×2: comp_idx=0, text='help'
        app._handle_cmd_key(self.SHIFT_TAB)     # Shift+Tab: 0 → wraps to 2
        assert app.cmd['comp_idx'] == 2, (
            f"Expected comp_idx=2 after Tab×2 + Shift+Tab, got {app.cmd['comp_idx']}"
        )
        text = ''.join(app.cmd['chars'])
        assert text == 'history', (
            f"Expected text='history' after Tab×2 + Shift+Tab, got {text!r}"
        )

    def test_shift_tab_from_comp_idx_one_goes_to_zero(self, app):
        """Shift+Tab when comp_idx=1 must step back to 0.

        Tab×3: comp_idx=1, text='hist'.
        Shift+Tab: comp_idx=1 → 0 → text='help'.
        """
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)           # Tab×1: popup, comp_idx=-1
        app._handle_cmd_key(self.TAB)           # Tab×2: comp_idx=0
        app._handle_cmd_key(self.TAB)           # Tab×3: comp_idx=1, text='hist'
        app._handle_cmd_key(self.SHIFT_TAB)     # Shift+Tab: 1 → 0
        assert app.cmd['comp_idx'] == 0, (
            f"Expected comp_idx=0 after Tab×3 + Shift+Tab, got {app.cmd['comp_idx']}"
        )
        text = ''.join(app.cmd['chars'])
        assert text == 'help', (
            f"Expected text='help' after Tab×3 + Shift+Tab, got {text!r}"
        )

    def test_shift_tab_from_comp_idx_two_goes_to_one(self, app):
        """Shift+Tab when comp_idx=2 must step back to 1.

        Tab×4: comp_idx=2, text='history'.
        Shift+Tab: comp_idx=2 → 1 → text='hist'.
        """
        _set_text(app, 'h')
        app._handle_cmd_key(self.TAB)           # Tab×1: popup, comp_idx=-1
        app._handle_cmd_key(self.TAB)           # Tab×2: comp_idx=0
        app._handle_cmd_key(self.TAB)           # Tab×3: comp_idx=1
        app._handle_cmd_key(self.TAB)           # Tab×4: comp_idx=2, text='history'
        app._handle_cmd_key(self.SHIFT_TAB)     # Shift+Tab: 2 → 1
        assert app.cmd['comp_idx'] == 1, (
            f"Expected comp_idx=1 after Tab×4 + Shift+Tab, got {app.cmd['comp_idx']}"
        )
        text = ''.join(app.cmd['chars'])
        assert text == 'hist', (
            f"Expected text='hist' after Tab×4 + Shift+Tab, got {text!r}"
        )

    def test_shift_tab_unique_match_applies_with_trailing_space(self, app):
        """Shift+Tab on a unique match must apply it immediately with a trailing space.

        'save' has a single completion: 'saveconfig'.
        Shift+Tab must behave identically to Tab for a unique match:
        apply 'saveconfig' + trailing space, clear the popup.
        """
        _set_text(app, 'save')
        app._handle_cmd_key(self.SHIFT_TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'saveconfig ', (
            f"Expected 'saveconfig ' (with trailing space) after Shift+Tab unique match, "
            f"got {text!r}"
        )
        assert app.cmd['completions'] == [], (
            f"Expected completions cleared after unique Shift+Tab match, "
            f"got {app.cmd['completions']}"
        )

    # ── Argument completions via Tab ──────────────────────────────────────

    def test_tab_completes_dns_arg(self, app):
        """'dns h' + Tab → unique match 'hostname' applied with trailing space."""
        _set_text(app, 'dns h')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'dns hostname ', (
            f"Expected 'dns hostname ' after Tab, got {text!r}"
        )

    def test_tab_with_full_command_and_trailing_space_completes_arg(self, app):
        """'dns ' + Tab with a unique arg match applies the completion."""
        # 'dns o' → unique 'off'
        _set_text(app, 'dns o')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'dns off ', (
            f"Expected 'dns off ' after Tab, got {text!r}"
        )

    def test_tab_arg_no_match_leaves_text_unchanged(self, app):
        """'dns zzz' + Tab → no arg matches, text unchanged."""
        _set_text(app, 'dns zzz')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'dns zzz', (
            f"Expected 'dns zzz' unchanged, got {text!r}"
        )

    # ── :set <param> <value> completions ─────────────────────────────────

    def test_set_param_value_all_completions(self, app, pb):
        """':set stats ' + Tab → popup lists all stats modes and stat name aliases."""
        _set_text(app, 'set stats ')
        app._handle_cmd_key(self.TAB)
        expected = set(m.lower() for m in pb.STATS_MODES) | set(pb.STAT_NAMES.keys())
        assert set(app.cmd['completions']) == expected, (
            f"Expected all stats modes {expected}, got {app.cmd['completions']}"
        )

    def test_set_param_value_prefix_filter(self, app):
        """':set stats lo' + Tab → unique match 'loss%' applied with trailing space."""
        _set_text(app, 'set stats lo')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'set stats loss% ', (
            f"Expected 'set stats loss% ' after Tab, got {text!r}"
        )

    def test_set_param_value_prefix_filter_avg(self, app):
        """':set stats av' + Tab → unique match 'avg' applied with trailing space.

        'a' alone matches both 'avg' and 'all'; 'av' is the shortest unambiguous prefix.
        """
        _set_text(app, 'set stats av')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'set stats avg ', (
            f"Expected 'set stats avg ' after Tab, got {text!r}"
        )

    def test_set_param_value_no_completion_after_complete_value(self, app):
        """':set stats loss% ' (trailing space = 4th token) + Tab → no completions."""
        _set_text(app, 'set stats loss% ')
        app._handle_cmd_key(self.TAB)
        assert app.cmd['completions'] == [], (
            f"Expected no completions beyond 3 tokens, got {app.cmd['completions']}"
        )
        text = ''.join(app.cmd['chars'])
        assert text == 'set stats loss% ', (
            f"Expected text unchanged, got {text!r}"
        )

    def test_set_param_value_dns_hostname(self, app):
        """':set dns h' + Tab → unique match 'hostname' applied with trailing space."""
        _set_text(app, 'set dns h')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'set dns hostname ', (
            f"Expected 'set dns hostname ' after Tab, got {text!r}"
        )

    def test_set_param_value_unknown_param_no_completions(self, app):
        """':set zzz v' + Tab → unknown param, no completions."""
        _set_text(app, 'set zzz v')
        app._handle_cmd_key(self.TAB)
        assert app.cmd['completions'] == [], (
            f"Expected no completions for unknown :set param, got {app.cmd['completions']}"
        )

    def test_set_param_value_no_match_text_unchanged(self, app):
        """':set stats zzz' + Tab → no value matches, text unchanged."""
        _set_text(app, 'set stats zzz')
        app._handle_cmd_key(self.TAB)
        text = ''.join(app.cmd['chars'])
        assert text == 'set stats zzz', (
            f"Expected 'set stats zzz' unchanged, got {text!r}"
        )

