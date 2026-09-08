"""Unit tests for the ping-bulk key binding infrastructure.

Tests cover:
  - _KeyTrie: prefix tree for key-code sequence lookups
  - _parse_key_notation() / _format_key_notation(): vim-like key notation parsing
  - _Binding: container for key binding metadata
  - :bindkey command: binding, unbinding, listing
  - Default bindings registration
  - Config save/load for user bindings

No ping threads are started; Application fixtures use a mocked config path
so the real user config is never read or written.
"""

import curses
import os
import shutil
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Fixtures — pb is provided by conftest.py
# ---------------------------------------------------------------------------

def _make_app(pb, tmp_path):
    """Return a non-running Application with a blank temp config."""
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, 'w') as f:
        f.write('')
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '127.0.0.1')])
    app._monitoring_started = True  # Enable event logging
    return app


@pytest.fixture
def app(pb, tmp_path):
    """Return a non-running Application with a blank temp config."""
    return _make_app(pb, tmp_path)


# ===========================================================================
# TestKeyTrie — prefix tree for multi-key sequences
# ===========================================================================

class TestKeyTrie:
    """Test _KeyTrie prefix-tree key binding storage."""

    def test_insert_and_lookup_single_key(self, pb):
        """Insert a single-key binding and verify resolve finds it."""
        trie = pb._KeyTrie()
        binding = pb._Binding([':quit'])
        trie.insert([ord('q')], binding)
        result, has_children = trie.resolve([ord('q')], set())
        assert result is binding
        assert not has_children

    def test_lookup_missing_key(self, pb):
        """Resolve of non-existent key returns (None, False)."""
        trie = pb._KeyTrie()
        result, has_children = trie.resolve([ord('x')], set())
        assert result is None
        assert not has_children

    def test_insert_multi_key_sequence(self, pb):
        """Insert a two-key sequence; verify prefix and full resolve."""
        trie = pb._KeyTrie()
        binding = pb._Binding([':fold za'])
        trie.insert([ord('z'), ord('a')], binding)
        # Prefix: 'z' alone has no binding but has children
        result_z, has_children_z = trie.resolve([ord('z')], set())
        assert result_z is None
        assert has_children_z
        # Full sequence: 'za' returns the binding
        result_za, has_children_za = trie.resolve([ord('z'), ord('a')], set())
        assert result_za is binding
        assert not has_children_za

    def test_remove_single_key(self, pb):
        """Remove a single-key binding; verify it's gone."""
        trie = pb._KeyTrie()
        binding = pb._Binding([':quit'])
        trie.insert([ord('q')], binding)
        removed = trie.remove([ord('q')])
        assert removed is True
        result, _ = trie.resolve([ord('q')], set())
        assert result is None

    def test_remove_prunes_empty_ancestors(self, pb):
        """Removing a leaf node prunes intermediate empty nodes."""
        trie = pb._KeyTrie()
        binding = pb._Binding([':fold za'])
        trie.insert([ord('z'), ord('a')], binding)
        removed = trie.remove([ord('z'), ord('a')])
        assert removed is True
        result_z, has_children_z = trie.resolve([ord('z')], set())
        assert result_z is None
        assert not has_children_z

    def test_remove_preserves_siblings(self, pb):
        """Removing one child doesn't affect siblings."""
        trie = pb._KeyTrie()
        binding_a = pb._Binding([':fold za'])
        binding_o = pb._Binding([':fold zo'])
        trie.insert([ord('z'), ord('a')], binding_a)
        trie.insert([ord('z'), ord('o')], binding_o)
        trie.remove([ord('z'), ord('a')])
        # 'z' prefix still exists (has 'zo' child)
        result_z, has_children_z = trie.resolve([ord('z')], set())
        assert result_z is None
        assert has_children_z
        # 'zo' still accessible
        result_zo, _ = trie.resolve([ord('z'), ord('o')], set())
        assert result_zo is binding_o

    def test_clear_subtree(self, pb):
        """clear_subtree removes all children but keeps own bindings."""
        trie = pb._KeyTrie()
        binding_z = pb._Binding([':something'])
        binding_za = pb._Binding([':fold za'])
        binding_zo = pb._Binding([':fold zo'])
        trie.insert([ord('z')], binding_z)
        trie.insert([ord('z'), ord('a')], binding_za)
        trie.insert([ord('z'), ord('o')], binding_zo)
        trie.clear_subtree([ord('z')])
        # 'z' binding still exists
        result_z, has_children = trie.resolve([ord('z')], set())
        assert result_z is binding_z
        assert not has_children
        # Children are gone
        result_za, _ = trie.resolve([ord('z'), ord('a')], set())
        assert result_za is None

    def test_iterate(self, pb):
        """__iter__ yields all (keys, binding) pairs sorted by key codes."""
        trie = pb._KeyTrie()
        binding_q = pb._Binding([':quit'])
        binding_za = pb._Binding([':fold za'])
        binding_zo = pb._Binding([':fold zo'])
        trie.insert([ord('q')], binding_q)
        trie.insert([ord('z'), ord('a')], binding_za)
        trie.insert([ord('z'), ord('o')], binding_zo)
        items = list(trie)
        assert len(items) == 3
        assert items[0] == ([ord('q')], binding_q)
        assert items[1] == ([ord('z'), ord('a')], binding_za)
        assert items[2] == ([ord('z'), ord('o')], binding_zo)

    def test_iterate_empty(self, pb):
        """Empty trie yields nothing."""
        trie = pb._KeyTrie()
        items = list(trie)
        assert items == []

    def test_remove_nonexistent_returns_false(self, pb):
        """Removing a non-existent key returns False."""
        trie = pb._KeyTrie()
        removed = trie.remove([ord('x')])
        assert removed is False

    def test_context_resolve_most_specific_wins(self, pb):
        """resolve() picks the most-specific matching context binding."""
        trie = pb._KeyTrie()
        b_default = pb._Binding([':seen'])
        b_host = pb._Binding([':nop'], context=frozenset('h'))
        b_section = pb._Binding([':fold toggle'], context=frozenset('s'))
        trie.insert([ord(' ')], b_default)
        trie.insert([ord(' ')], b_host)
        trie.insert([ord(' ')], b_section)
        # No context → fallback
        r, _ = trie.resolve([ord(' ')], set())
        assert r is b_default
        # Host selected → --%h binding
        r, _ = trie.resolve([ord(' ')], {'h', 'i'})
        assert r is b_host
        # Section selected → --%s binding
        r, _ = trie.resolve([ord(' ')], {'s', 'H'})
        assert r is b_section

    def test_context_fallback_to_unconditional(self, pb):
        """When no context binding matches, resolve falls back to None."""
        trie = pb._KeyTrie()
        b_default = pb._Binding([':quit'])
        trie.insert([ord('q')], b_default)
        # Even with context keys, unconditional binding matches
        r, _ = trie.resolve([ord('q')], {'h', 'i', 'p'})
        assert r is b_default


# ===========================================================================
# TestKeyNotation — parsing and formatting key notation
# ===========================================================================

class TestKeyNotation:
    """Test _parse_key_notation() and _format_key_notation()."""

    def test_parse_single_char(self, pb):
        """'a' parses to [97]."""
        result = pb._parse_key_notation('a')
        assert result == [ord('a')]

    def test_parse_multi_char_sequence(self, pb):
        """'za' parses to [122, 97]."""
        result = pb._parse_key_notation('za')
        assert result == [ord('z'), ord('a')]

    def test_parse_angle_bracket_cr(self, pb):
        """'<CR>' parses to KEY_ENTER."""
        result = pb._parse_key_notation('<CR>')
        assert result == [curses.KEY_ENTER]

    def test_parse_angle_bracket_esc(self, pb):
        """'<Esc>' parses to 27."""
        result = pb._parse_key_notation('<Esc>')
        assert result == [27]

    def test_parse_angle_bracket_space(self, pb):
        """'<Space>' parses to 32."""
        result = pb._parse_key_notation('<Space>')
        assert result == [ord(' ')]

    def test_parse_ctrl_letter(self, pb):
        """'<C-x>' parses to [24]."""
        result = pb._parse_key_notation('<C-x>')
        assert result == [24]

    def test_parse_ctrl_space(self, pb):
        """'<C-Space>' parses to [0]."""
        result = pb._parse_key_notation('<C-Space>')
        assert result == [0]

    def test_parse_arrows(self, pb):
        """Arrow keys parse to correct curses constants."""
        assert pb._parse_key_notation('<Up>') == [curses.KEY_UP]
        assert pb._parse_key_notation('<Down>') == [curses.KEY_DOWN]
        assert pb._parse_key_notation('<Left>') == [curses.KEY_LEFT]
        assert pb._parse_key_notation('<Right>') == [curses.KEY_RIGHT]

    def test_parse_page_keys(self, pb):
        """<PageUp>, <PgDn> parse to curses.KEY_PPAGE, KEY_NPAGE."""
        assert pb._parse_key_notation('<PageUp>') == [curses.KEY_PPAGE]
        assert pb._parse_key_notation('<PgDn>') == [curses.KEY_NPAGE]

    def test_parse_case_insensitive(self, pb):
        """'<cr>' is equivalent to '<CR>'."""
        assert pb._parse_key_notation('<cr>') == pb._parse_key_notation('<CR>')
        assert pb._parse_key_notation('<esc>') == pb._parse_key_notation('<Esc>')

    def test_parse_mixed(self, pb):
        """'z<CR>' parses to [ord('z'), KEY_ENTER]."""
        result = pb._parse_key_notation('z<CR>')
        assert result == [ord('z'), curses.KEY_ENTER]

    def test_parse_empty_raises(self, pb):
        """Empty string raises ValueError."""
        with pytest.raises(ValueError, match="empty key notation"):
            pb._parse_key_notation('')

    def test_parse_unknown_raises(self, pb):
        """Unknown angle-bracket token raises ValueError."""
        with pytest.raises(ValueError, match="unrecognized key notation"):
            pb._parse_key_notation('<INVALID>')

    def test_parse_unclosed_raises(self, pb):
        """Unclosed angle bracket raises ValueError."""
        with pytest.raises(ValueError, match="unclosed angle bracket"):
            pb._parse_key_notation('<Up')

    def test_format_single_char(self, pb):
        """[97] formats to 'a'."""
        result = pb._format_key_notation([ord('a')])
        assert result == 'a'

    def test_format_multi_key(self, pb):
        """[122, 97] formats to 'za'."""
        result = pb._format_key_notation([ord('z'), ord('a')])
        assert result == 'za'

    def test_format_special_keys(self, pb):
        """Special keys format to angle-bracket notation."""
        assert pb._format_key_notation([curses.KEY_ENTER]) == '<CR>'
        assert pb._format_key_notation([27]) == '<Esc>'
        assert pb._format_key_notation([ord(' ')]) == '<Space>'

    def test_format_ctrl_letter(self, pb):
        """[24] (Ctrl-X) formats to '<C-x>'."""
        result = pb._format_key_notation([24])
        assert result == '<C-x>'

    def test_format_unknown_hex(self, pb):
        """Unknown key code formats to hex notation."""
        result = pb._format_key_notation([9999])
        assert result == '<0x270F>'

    def test_roundtrip(self, pb):
        """Parse then format then parse should give same result."""
        notations = ['a', 'za', '<CR>', '<Esc>', '<C-x>', '<Up>', 'z<CR>']
        for notation in notations:
            codes = pb._parse_key_notation(notation)
            formatted = pb._format_key_notation(codes)
            codes_again = pb._parse_key_notation(formatted)
            assert codes == codes_again, f"Roundtrip failed for {notation!r}"


# ===========================================================================
# TestBinding — _Binding container
# ===========================================================================

class TestBinding:
    """Test _Binding container for key binding metadata."""

    def test_binding_creation(self, pb):
        """Create a binding with commands, edit_mode, key_notation, origin."""
        binding = pb._Binding(
            [':set dns hostname', ':set stats down'],
            edit_mode=True,
            key_notation='<C-d>',
            origin='user'
        )
        assert binding.commands == [':set dns hostname', ':set stats down']
        assert binding.edit_mode is True
        assert binding.key_notation == '<C-d>'
        assert binding.origin == 'user'

    def test_binding_default_origin(self, pb):
        """Default origin is 'default'."""
        binding = pb._Binding([':quit'])
        assert binding.origin == 'default'

    def test_binding_repr(self, pb):
        """__repr__ produces readable output."""
        binding = pb._Binding([':quit', ':clear'], edit_mode=False,
                              key_notation='q', origin='default')
        r = repr(binding)
        assert 'q' in r
        assert 'exec' in r
        assert ':quit' in r and ':clear' in r


# ===========================================================================
# TestBindkeyCommand — :bindkey command
# ===========================================================================

class TestBindkeyCommand:
    """Test :bindkey command for binding, unbinding, listing."""

    def test_bindkey_bind_key(self, app, pb):
        """':bindkey t :mux mtr' creates a binding."""
        app._cmd_bindkey('t :mux mtr')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.commands == [':mux mtr']
        assert binding.origin == 'user'
        assert binding.key_notation == 't'

    def test_bindkey_unbind_key(self, app, pb):
        """After binding, ':unbind-key t' removes the binding."""
        app._cmd_bindkey('t :mux mtr')
        app._last_cmd_name = 'unbind-key'
        app._cmd_bindkey('t')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None
        assert any('unbound t' in e for e in app.events)

    def test_bindkey_list_empty(self, app):
        """':bindkey' with no user bindings opens help overlay in [A] mode."""
        app._cmd_bindkey()
        assert app.help_open
        assert app.help_show_all is True

    def test_bindkey_list_shows_user_bindings(self, app):
        """After binding, ':bindkey' opens help overlay in [A] mode."""
        app._cmd_bindkey('t :mux mtr')
        app._cmd_bindkey()
        assert app.help_open
        assert app.help_show_all is True

    def test_bindkey_multi_command(self, app, pb):
        """':bindkey t :set stats down \\; :set dns hostname' creates multi-cmd binding."""
        app._cmd_bindkey(r't :set stats down \; :set dns hostname')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.commands == [':set stats down', ':set dns hostname']

    def test_bindkey_edit_mode(self, app, pb):
        """':bindkey t :mux mtr %h...' sets edit_mode=True."""
        app._cmd_bindkey('t :mux mtr %h...')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.edit_mode is True
        assert binding.commands == [':mux mtr %h']

    def test_bindkey_overrides_default(self, app, pb):
        """Binding 'q' to something else replaces the default :quit binding."""
        keys_q = pb._parse_key_notation('q')
        binding_before, _ = app._key_trie.resolve(keys_q, set())
        assert binding_before.commands == [':quit']
        assert binding_before.origin == 'default'
        app._cmd_bindkey('q :help')
        binding_after, _ = app._key_trie.resolve(keys_q, set())
        assert binding_after.commands == [':help']
        assert binding_after.origin == 'user'

    def test_bindkey_multi_key_sequence(self, app, pb):
        """':bindkey gt :select first' binds 'g' then 't' sequence."""
        app._cmd_bindkey('gt :select first')
        keys_gt = pb._parse_key_notation('gt')
        binding, _ = app._key_trie.resolve(keys_gt, set())
        assert binding is not None
        assert binding.commands == [':select first']
        keys_g = pb._parse_key_notation('g')
        binding_g, has_children_g = app._key_trie.resolve(keys_g, set())
        assert binding_g is None
        assert has_children_g

    def test_bindkey_context_flag(self, app, pb):
        """':bindkey --%h y :mux mtr' creates a context-aware binding."""
        app._cmd_bindkey('--%h y :mux mtr')
        keys = pb._parse_key_notation('y')
        # Without host context → no match (no unconditional fallback)
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None
        # With host context → match
        binding, _ = app._key_trie.resolve(keys, {'h', 'i'})
        assert binding is not None
        assert binding.commands == [':mux mtr']
        assert binding.context == frozenset({'h'})

    def test_bindkey_context_with_fallback(self, app, pb):
        """Context binding coexists with unconditional fallback."""
        app._cmd_bindkey('--%s t :fold toggle')
        app._cmd_bindkey('t :seen')
        keys = pb._parse_key_notation('t')
        # Section context → context binding wins
        r, _ = app._key_trie.resolve(keys, {'s', 'H'})
        assert r.commands == [':fold toggle']
        # No context → fallback
        r, _ = app._key_trie.resolve(keys, set())
        assert r.commands == [':seen']
        # Host context → fallback (no --%h binding)
        r, _ = app._key_trie.resolve(keys, {'h', 'i'})
        assert r.commands == [':seen']

    def test_bindkey_context_unbind(self, app, pb):
        """':unbind-key --%s <Space>' unbinds only the section-context binding."""
        # Default Space has --%s :fold toggle-recursive --if-hosts, and :seen
        keys = pb._parse_key_notation('<Space>')
        r_section, _ = app._key_trie.resolve(keys, {'s'})
        assert r_section.commands == [':fold toggle-recursive --if-hosts']
        # Unbind only the section context
        app._last_cmd_name = 'unbind-key'
        app._cmd_bindkey('--%s <Space>')
        r_section, _ = app._key_trie.resolve(keys, {'s'})
        # Now falls back to :seen
        assert r_section.commands == [':seen']


# ===========================================================================
# TestMultiModeBindings — comma-separated --mode values
# ===========================================================================

class TestMultiModeBindings:
    """Test --mode with comma-separated mode lists."""

    @staticmethod
    def _resolve(app, key_code, mode):
        """Resolve a single-key binding in the given mode via trie."""
        return app._key_trie.resolve([key_code], set(), mode=mode)[0]

    def test_multi_mode_registers_in_each(self, app, pb):
        """--mode help,details registers the binding in both mode tables."""
        app._cmd_bindkey('--mode help,details q :close')
        key_code = ord('q')
        assert self._resolve(app, key_code, 'help') is not None
        assert self._resolve(app, key_code, 'details') is not None

    def test_multi_mode_same_binding_object(self, app, pb):
        """A single binding object is shared across all specified modes."""
        app._cmd_bindkey('--mode help,details q :close')
        key_code = ord('q')
        b_help = self._resolve(app, key_code, 'help')
        b_details = self._resolve(app, key_code, 'details')
        assert b_help is b_details

    def test_multi_mode_commands(self, app, pb):
        """Binding commands are correct for multi-mode."""
        app._cmd_bindkey('--mode help,details q :close')
        b = self._resolve(app, ord('q'), 'help')
        assert b.commands == [':close']

    def test_multi_mode_three_modes(self, app, pb):
        """Three modes can be specified at once."""
        app._cmd_bindkey('--mode help,details,command q :close')
        key_code = ord('q')
        assert self._resolve(app, key_code, 'help') is not None
        assert self._resolve(app, key_code, 'details') is not None
        assert self._resolve(app, key_code, 'command') is not None

    def test_multi_mode_with_desc(self, app, pb):
        """--desc is applied to the shared binding object."""
        app._cmd_bindkey('--mode help,details --desc "Close overlay" q :close')
        b = self._resolve(app, ord('q'), 'help')
        assert b.desc == 'Close overlay'

    def test_multi_mode_unbind_each(self, app, pb):
        """Unbinding with multi-mode removes from each mode table."""
        app._cmd_bindkey('--mode help,details q :close')
        app._last_cmd_name = 'unbind-key'
        app._cmd_bindkey('--mode help,details q')
        assert self._resolve(app, ord('q'), 'help') is None
        assert self._resolve(app, ord('q'), 'details') is None

    def test_multi_mode_query_each(self, app, pb):
        """Query with multi-mode reports for each mode."""
        app._cmd_bindkey('--mode help,details q :close')
        app._cmd_bindkey('--mode help,details q')  # query
        event_texts = [e.text for e in app.events]
        assert any('--mode help' in t and '→' in t for t in event_texts)
        assert any('--mode details' in t and '→' in t for t in event_texts)

    def test_normal_combined_with_other_modes(self, app, pb):
        """'normal' can be combined with other modes."""
        app._cmd_bindkey('--mode normal,help t :close')
        # Registered in help mode
        assert self._resolve(app, ord('t'), 'help') is not None
        # Also registered in normal mode
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('t'), set())
        assert binding is not None and binding.origin == 'user'

    def test_invalid_mode_in_list_rejected(self, app, pb):
        """An invalid mode name in the comma list is rejected."""
        app._cmd_bindkey('--mode help,badmode t :close')
        b = self._resolve(app, ord('t'), 'help')
        assert b is None or b.origin != 'user'
        assert any("unknown mode" in e.text for e in app.events)

    def test_single_mode_unchanged(self, app, pb):
        """Single --mode value still works as before."""
        app._cmd_bindkey('--mode help t :close')
        assert self._resolve(app, ord('t'), 'help') is not None
        # Not registered in details mode as user binding
        b_details = self._resolve(app, ord('t'), 'details')
        assert b_details is None or b_details.origin != 'user'


# ===========================================================================
# TestDefaultBindings — verify default bindings are registered
# ===========================================================================

class TestDefaultBindings:
    """Test that default bindings are registered correctly."""

    def test_default_quit_bound(self, app, pb):
        """'q' is bound to ':quit'."""
        keys = pb._parse_key_notation('q')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.commands == [':quit']
        assert binding.origin == 'default'

    def test_default_z_sequences(self, app, pb):
        """'za' is bound to ':fold za'."""
        keys = pb._parse_key_notation('za')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.commands == [':fold za']
        assert binding.origin == 'default'

    def test_default_arrows(self, app, pb):
        """'<Up>' is bound to ':select up'."""
        keys = pb._parse_key_notation('<Up>')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.commands == [':select up']
        assert binding.origin == 'default'

    def test_default_cr_bound(self, app, pb):
        """'<CR>' is bound to ':details'."""
        keys = pb._parse_key_notation('<CR>')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.commands == [':details']
        assert binding.origin == 'default'

    def test_default_space_context_aware(self, app, pb):
        """Space has context-aware bindings: fold for sections, seen for fallback."""
        keys = pb._parse_key_notation('<Space>')
        # Section context → recursive fold toggle, skipping pure containers
        r, _ = app._key_trie.resolve(keys, {'s', 'H'})
        assert r.commands == [':fold toggle-recursive --if-hosts']
        # No context → seen
        r, _ = app._key_trie.resolve(keys, set())
        assert r.commands == [':seen']
        # Host context → falls back to seen
        r, _ = app._key_trie.resolve(keys, {'h', 'i'})
        assert r.commands == [':seen']


# ===========================================================================
# TestSaveConfigBindings — config persistence
# ===========================================================================

class TestSaveConfigBindings:
    """Test that _save_config includes/excludes bindings correctly."""

    @pytest.fixture
    def app_with_cfg(self, pb, tmp_path):
        """Return (app, cfg_path) with _config_path patched for the whole test."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        with patch.object(pb, '_config_path', return_value=cfg):
            app = pb.Application([('host', '127.0.0.1')])
            app._monitoring_started = True
            yield app, cfg

    def test_saveconfig_includes_user_bindings(self, app_with_cfg, pb):
        """After binding a key, _save_config output contains :bind-key ..."""
        app, cfg = app_with_cfg
        app._cmd_bindkey('t :mux mtr')
        with patch.object(pb, '_config_path', return_value=cfg):
            success = app._save_config()
        assert success is True
        config_text = open(cfg).read()
        assert ':bind-key t :mux mtr' in config_text

    def test_saveconfig_excludes_default_bindings(self, app_with_cfg, pb):
        """Default bindings are not in save output."""
        app, cfg = app_with_cfg
        with patch.object(pb, '_config_path', return_value=cfg):
            success = app._save_config()
        assert success is True
        config_text = open(cfg).read()
        # Default binding like 'q :quit' should NOT be in config
        assert ':bindkey q :quit' not in config_text

    def test_saveconfig_includes_unbinds(self, app_with_cfg, pb):
        """After unbinding a default key, save output contains ':unbind-key <key>'."""
        app, cfg = app_with_cfg
        # Unbind 'q' (a default binding) via :unbind-key
        app._last_cmd_name = 'unbind-key'
        app._cmd_bindkey('q')
        with patch.object(pb, '_config_path', return_value=cfg):
            success = app._save_config()
        assert success is True
        config_text = open(cfg).read()
        # Should have ':unbind-key q' to unbind it
        lines = [line.strip() for line in config_text.splitlines()]
        assert ':unbind-key q' in lines


# ===========================================================================
# TestBindingContext — _binding_context() and %h resolv_static behaviour
# ===========================================================================

class TestBindingContext:
    """Test that _binding_context() builds the correct variable dict,
    especially the %h resolv_static → IP substitution."""

    def _make_ping_monitor(self, pb, host, resolved_ip=None, resolv_static=False):
        m = pb.PingMonitor(host)
        m.resolved_ip = resolved_ip
        m.resolv_static = resolv_static
        return m

    def test_h_uses_host_always(self, app, pb):
        """%h always returns entry.host regardless of :resolv mapping."""
        m = self._make_ping_monitor(pb, 'sensor-hub-1', resolved_ip='10.0.0.1',
                                    resolv_static=True)
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['h'] == 'sensor-hub-1', (
            "%h should always be the display name; use %i for the IP"
        )

    def test_h_uses_host_without_resolv(self, app, pb):
        """%h returns entry.host when no :resolv mapping and no resolved_ip."""
        m = self._make_ping_monitor(pb, 'myhost.local')
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['h'] == 'myhost.local'

    def test_i_set_when_resolv_static(self, app, pb):
        """%i is the resolved_ip when resolv_static; use %i for network tools."""
        m = self._make_ping_monitor(pb, 'sensor-hub-1', resolved_ip='10.0.0.1',
                                    resolv_static=True)
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx.get('i') == '10.0.0.1'

    def test_i_set_when_dns_resolved(self, app, pb):
        """%i is set for DNS-resolved IPs too (not only :resolv static)."""
        m = self._make_ping_monitor(pb, 'myhost.local', resolved_ip='192.168.1.5',
                                    resolv_static=False)
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx.get('i') == '192.168.1.5'

    def test_i_expansion_for_mtr(self, app, pb):
        """End-to-end: ':mux mtr %i' expands to resolved_ip (replaces old %h usage)."""
        m = self._make_ping_monitor(pb, 'label-only', resolved_ip='10.1.2.3',
                                    resolv_static=True)
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        app._cmd_bindkey('t :mux mtr %i')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        cmds, warning = app._expand_binding_commands(binding.commands)
        assert warning is None
        assert cmds == [':mux mtr 10.1.2.3']

    # ── %r variable ──────────────────────────────────────────────────────────

    def test_r_uses_host_for_plain_monitor(self, app, pb):
        """%r falls back to host when no :resolv static mapping."""
        m = self._make_ping_monitor(pb, 'myhost.example.com')
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['r'] == 'myhost.example.com'

    def test_r_uses_ip_when_resolv_static(self, app, pb):
        """%r returns the resolved_ip when resolv_static is set."""
        m = self._make_ping_monitor(pb, 'label', resolved_ip='10.0.0.1',
                                    resolv_static=True)
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['r'] == '10.0.0.1'

    def test_r_not_affected_by_dns_resolved(self, app, pb):
        """%r stays as host when resolved_ip comes from DNS (not :resolv)."""
        m = self._make_ping_monitor(pb, 'myhost.local', resolved_ip='192.168.1.5',
                                    resolv_static=False)
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['r'] == 'myhost.local'

    def test_r_for_port_monitor_no_resolv_static(self, app, pb):
        """%r for PortMonitor without resolv_static uses _ping_host."""
        m = pb.PortMonitor('web.example.com', '80')
        m.resolved_ip = '93.184.216.34'
        m.resolv_static = False
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['r'] == 'web.example.com'

    def test_r_for_port_monitor_with_resolv_static(self, app, pb):
        """%r for PortMonitor with resolv_static=True uses resolved_ip."""
        m = pb.PortMonitor('web.example.com', '80')
        m.resolved_ip = '93.184.216.34'
        m.resolv_static = True
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['r'] == '93.184.216.34'

    # ── %d variable ──────────────────────────────────────────────────────────

    def test_d_set_for_ssh_monitor(self, app, pb):
        """%d is the SSH destination for SshPingMonitor entries."""
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], ping_host='localhost')
        m.resolved_ip = None
        m.resolv_static = False
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['d'] == 'user@remote'

    def test_d_not_set_for_plain_monitor(self, app, pb):
        """%d is absent for plain PingMonitor entries."""
        m = self._make_ping_monitor(pb, 'myhost.local')
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert 'd' not in ctx

    # ── %j variable ──────────────────────────────────────────────────────────

    def test_j_is_jump_host_list(self, app, pb):
        """%j holds jump host list from -J flag."""
        m = pb.SshPingMonitor(['-J', 'bastion', 'user@remote'], ping_host='localhost')
        m.resolved_ip = None
        m.resolv_static = False
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['j'] == ['bastion']

    def test_j_not_set_when_no_jumps(self, app, pb):
        """%j is absent when SshPingMonitor has no -J flags."""
        m = pb.SshPingMonitor(['user@remote'], ping_host='localhost')
        m.resolved_ip = None
        m.resolv_static = False
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert 'j' not in ctx

    def test_j_multiple_jump_hosts(self, app, pb):
        """%j holds multiple comma-separated jump hosts from -J flag."""
        m = pb.SshPingMonitor(['-J', 'gw1,gw2', 'user@remote'], ping_host='localhost')
        m.resolved_ip = None
        m.resolv_static = False
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['j'] == ['gw1', 'gw2']

    # ── %H and %R variables ───────────────────────────────────────────────────

    def _make_section(self, app, pb, title='Servers', level=1):
        """Append a SectionLabel to app.entries and return it."""
        s = pb.SectionLabel(title, level=level)
        app.entries.append(s)
        return s

    def test_R_equals_H_for_plain_monitors(self, app, pb):
        """%R equals %H when no host has resolv_static set."""
        self._make_section(app, pb)
        for host in ('alpha', 'beta', 'gamma'):
            app.entries.append(self._make_ping_monitor(pb, host))
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['H'] == ['alpha', 'beta', 'gamma']
        assert ctx['R'] == ctx['H'], "%R should equal %H when no resolv_static"

    def test_R_uses_ip_for_resolv_static_host(self, app, pb):
        """%R returns resolved_ip for the host that has resolv_static=True."""
        self._make_section(app, pb)
        app.entries.append(self._make_ping_monitor(pb, 'alpha'))
        app.entries.append(
            self._make_ping_monitor(pb, 'beta', resolved_ip='10.0.0.2', resolv_static=True))
        app.entries.append(self._make_ping_monitor(pb, 'gamma'))
        app.highlighted_index = len(app.entries) - 1
        ctx = app._binding_context()
        assert ctx['H'] == ['alpha', 'beta', 'gamma']
        assert ctx['R'] == ['alpha', '10.0.0.2', 'gamma']

    def test_R_comma_join(self, app, pb):
        """%{R:,} joins connectable targets with commas."""
        self._make_section(app, pb)
        app.entries.append(self._make_ping_monitor(pb, 'host1'))
        app.entries.append(
            self._make_ping_monitor(pb, 'host2', resolved_ip='192.168.1.1', resolv_static=True))
        app.highlighted_index = len(app.entries) - 1
        cmds, warning = app._expand_binding_commands(['ping %{R:,}'])
        assert warning is None
        assert cmds == ['ping host1,192.168.1.1']



# ===========================================================================
# TestConditionalExpansion — %{var?template} syntax
# ===========================================================================

class TestConditionalExpansion:
    """Test %{var?template} conditional expansion."""

    def _make_ping_entry(self, pb, app, host, resolved_ip=None):
        m = pb.PingMonitor(host)
        m.resolved_ip = resolved_ip
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        return m

    def _make_ssh_entry(self, pb, app, ssh_args, ping_host='localhost'):
        m = pb.SshPingMonitor(ssh_args, ping_host=ping_host)
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        return m

    def _expand(self, app, command):
        """Expand a single command string and return (result, warning)."""
        cmds, warning = app._expand_binding_commands([command])
        return cmds[0], warning

    def test_conditional_expands_when_var_set(self, app, pb):
        """%{j?-J %j} expands to '-J bastion' when j is present."""
        self._make_ssh_entry(pb, app, ['-J', 'bastion', 'user@remote'], ping_host='localhost')
        result, warning = self._expand(app, '%{j?-J %j}')
        assert warning is None
        assert result == '-J bastion'

    def test_conditional_empty_when_var_missing(self, app, pb):
        """%{j?-J %j} expands to '' when j is absent (plain PingMonitor)."""
        self._make_ping_entry(pb, app, 'myhost.local')
        result, warning = self._expand(app, '%{j?-J %j}')
        assert warning is None
        assert result == ''

    def test_conditional_empty_when_inner_var_missing(self, app, pb):
        """%{j?-J %x} expands to '' when j is present but %x is not in ctx."""
        self._make_ssh_entry(pb, app, ['-J', 'bastion', 'user@remote'], ping_host='localhost')
        result, warning = self._expand(app, '%{j?-J %x}')
        assert warning is None
        assert result == ''

    def test_conditional_multiple_in_command(self, app, pb):
        """%{j?-J %j} %h expands with both conditional and regular vars."""
        m = self._make_ssh_entry(pb, app, ['-J', 'bastion', 'user@remote'], ping_host='localhost')
        m.host = 'myhost'
        result, warning = self._expand(app, '%{j?-J %j} %h')
        assert warning is None
        assert result == '-J bastion myhost'

    def test_conditional_wraps_literal_text(self, app, pb):
        """%{h?host=%h} expands to 'host=myhost' when h is present."""
        self._make_ping_entry(pb, app, 'myhost')
        result, warning = self._expand(app, '%{h?host=%h}')
        assert warning is None
        assert result == 'host=myhost'

    def test_conditional_var_present_but_inner_missing(self, app, pb):
        """%{h?host=%h path=%x} → '' because %x is missing."""
        self._make_ping_entry(pb, app, 'myhost')
        result, warning = self._expand(app, '%{h?host=%h path=%x}')
        assert warning is None
        assert result == ''

    def test_no_conditional_passthrough(self, app, pb):
        """Commands without %{?} still expand normally."""
        self._make_ping_entry(pb, app, 'myhost', resolved_ip='10.0.0.1')
        result, warning = self._expand(app, 'ping %h %i')
        assert warning is None
        assert result == 'ping myhost 10.0.0.1'

    def test_conditional_sep_expansion_in_template(self, app, pb):
        """%{j?-J %{j:,}} works when j is a list (multi-hop jumps)."""
        m = self._make_ssh_entry(pb, app, ['bastion'], ping_host='localhost')
        # Simulate companion task: j is a list of jump hosts
        ctx = app._binding_context()
        ctx['j'] = ['bastion', 'gw2']
        result = app._expand_conditional('%{j?-J %{j:,}}', ctx)
        assert result == '-J bastion,gw2'

    def test_conditional_sep_syntax_missing_inner_var(self, app, pb):
        """%{j?-J %{x:,}} → '' when j is set but %x (sep syntax) is missing."""
        # j is present (SSH monitor with a jump host) but %x has no value;
        # the nested %{x:,} raises _BindingVarMissing inside the conditional
        # template, so the whole block collapses to the empty string.
        self._make_ssh_entry(pb, app, ['-J', 'bastion', 'user@remote'], ping_host='localhost')
        result, warning = self._expand(app, '%{j?-J %{x:,}}')
        assert warning is None
        assert result == ''


# ===========================================================================
# TestDefaultCBinding — default 'c' key uses :mux ssh with %r/%d/%j
# ===========================================================================

class TestDefaultCBinding:
    """Verify the default 'c' binding expands via %r/%d/%j instead of :connect."""

    def _make_ping_entry(self, pb, app, host, resolved_ip=None, resolv_static=False):
        m = pb.PingMonitor(host)
        m.resolved_ip = resolved_ip
        m.resolv_static = resolv_static
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        return m

    def _make_ssh_entry(self, pb, app, ssh_args, ping_host='localhost'):
        m = pb.SshPingMonitor(ssh_args, ping_host=ping_host)
        m.resolved_ip = None
        m.resolv_static = False
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        return m

    def _resolve_c_binding(self, app, pb):
        """Resolve the 'c' key binding against the current app context."""
        ctx_keys = set(app._binding_context().keys())
        keys = pb._parse_key_notation('c')
        binding, _ = app._key_trie.resolve(keys, ctx_keys)
        return binding

    def test_c_default_not_connect(self, app, pb):
        """Default 'c' binding must not be ':connect'."""
        self._make_ping_entry(pb, app, 'myhost')
        binding = self._resolve_c_binding(app, pb)
        assert binding is not None
        assert ':connect' not in binding.commands

    def test_c_plain_host_expands_to_ssh_r(self, app, pb):
        """For PingMonitor, 'c' expands to ':mux ssh <host>'."""
        self._make_ping_entry(pb, app, 'myhost.example.com')
        binding = self._resolve_c_binding(app, pb)
        assert binding is not None
        cmds, warning = app._expand_binding_commands(binding.commands)
        assert warning is None
        assert cmds == [':mux ssh myhost.example.com']

    def test_c_plain_host_resolv_static_uses_ip(self, app, pb):
        """For PingMonitor with :resolv, 'c' expands to ':mux ssh <resolved_ip>'."""
        self._make_ping_entry(pb, app, 'label', resolved_ip='10.0.0.5', resolv_static=True)
        binding = self._resolve_c_binding(app, pb)
        assert binding is not None
        cmds, warning = app._expand_binding_commands(binding.commands)
        assert warning is None
        assert cmds == [':mux ssh 10.0.0.5']

    def test_c_ssh_monitor_with_jump_chains_relay_after_jump(self, app, pb):
        """The relay is appended to the jump chain; the monitored host is the target."""
        self._make_ssh_entry(pb, app, ['-J', 'bastion', 'user@remote'])
        binding = self._resolve_c_binding(app, pb)
        assert binding is not None
        cmds, warning = app._expand_binding_commands(binding.commands)
        assert warning is None
        assert cmds == [':mux ssh -J bastion,user@remote localhost']

    def test_c_ssh_monitor_no_jump_jumps_via_the_relay(self, app, pb):
        """With no extra jumps the relay itself is the only -J hop."""
        self._make_ssh_entry(pb, app, ['user@remote'])
        binding = self._resolve_c_binding(app, pb)
        assert binding is not None
        cmds, warning = app._expand_binding_commands(binding.commands)
        assert warning is None
        assert cmds == [':mux ssh -J user@remote localhost']

    def test_c_ssh_monitor_multi_jump_uses_one_comma_list(self, app, pb):
        """All hops land in a single -J list.

        Repeating the flag would look right but not work: ssh keeps the first
        value of a repeated option, so '-J gw1 -J gw2' silently ignores gw2.
        """
        self._make_ssh_entry(pb, app, ['-J', 'gw1', '-J', 'gw2', 'user@remote'])
        binding = self._resolve_c_binding(app, pb)
        assert binding is not None
        cmds, warning = app._expand_binding_commands(binding.commands)
        assert warning is None
        assert cmds == [':mux ssh -J gw1,gw2,user@remote localhost']

    def test_c_ssh_context_guard_wins_over_fallback(self, app, pb):
        """Context-guarded --%d binding beats the plain fallback for SSH monitors."""
        self._make_ssh_entry(pb, app, ['-J', 'bastion', 'user@remote'])
        binding = self._resolve_c_binding(app, pb)
        # The SSH binding has context={'d'} (non-None) — it must win
        assert binding is not None
        assert binding.context is not None and 'd' in binding.context

    def test_c_plain_monitor_d_context_guard_inactive(self, app, pb):
        """For plain PingMonitor 'd' is absent; only the fallback 'c' binding fires."""
        self._make_ping_entry(pb, app, 'myhost')
        ctx_keys = set(app._binding_context().keys())
        assert 'd' not in ctx_keys
        keys = pb._parse_key_notation('c')
        binding, _ = app._key_trie.resolve(keys, ctx_keys)
        assert binding is not None
        # The resolved binding must be the unconditional fallback (no 'd' guard)
        assert binding.context is None or 'd' not in binding.context


# ===========================================================================
# TestScrollDirectionArgs — trailing-dash direction convention (8a)
# ===========================================================================

class TestScrollDirectionArgs:
    """scroll ping-history and scroll event-history accept trailing-dash reverse direction."""

    def test_scroll_history_half_forward(self, app):
        app.scroll_history = lambda d: setattr(app, '_last_delta', d)
        app._visible_ping_length = 100
        app._cmd_scroll('ping-history half')
        assert app._last_delta == 50

    def test_scroll_history_half_dash_reverse(self, app):
        app.scroll_history = lambda d: setattr(app, '_last_delta', d)
        app._visible_ping_length = 100
        app._cmd_scroll('ping-history half-')
        assert app._last_delta == -50

    def test_scroll_history_legacy_minus_half_invalid(self, app):
        """-half is no longer valid; treated as invalid arg."""
        app.scroll_history = lambda d: setattr(app, '_last_delta', d)
        app._visible_ping_length = 100
        app._cmd_scroll('ping-history -half')
        assert not hasattr(app, '_last_delta')

    def test_scroll_history_full_dash(self, app):
        app.scroll_history = lambda d: setattr(app, '_last_delta', d)
        app._visible_ping_length = 40
        app._cmd_scroll('ping-history full-')
        assert app._last_delta == -40

    def test_scroll_log_page_dash(self, app):
        app.scroll_log = lambda d: setattr(app, '_last_log_delta', d)
        app._log_page_size = 20
        app._cmd_scroll('event-history page-')
        assert app._last_log_delta == -20

    def test_scroll_log_legacy_minus_page_invalid(self, app):
        """-page is no longer valid; treated as invalid arg."""
        app.scroll_log = lambda d: setattr(app, '_last_log_delta', d)
        app._log_page_size = 20
        app._cmd_scroll('event-history -page')
        assert not hasattr(app, '_last_log_delta')


# ===========================================================================
# TestModeFlag — --mode on :bind-key (8e)
# ===========================================================================

class TestModeFlag:
    """--mode stores bindings in the trie for non-normal modes."""

    @staticmethod
    def _resolve(app, key_code, mode):
        return app._key_trie.resolve([key_code], set(), mode=mode)[0]

    def test_default_help_mode_bindings_exist(self, app, pb):
        """Default help-mode bindings for q, Esc, Up, Down are registered."""
        import curses
        assert self._resolve(app, ord('q'), 'help') is not None
        assert self._resolve(app, 27, 'help') is not None    # Esc
        assert self._resolve(app, curses.KEY_UP, 'help') is not None
        assert self._resolve(app, curses.KEY_DOWN, 'help') is not None

    def test_default_details_mode_bindings_exist(self, app, pb):
        """Default details-mode bindings for q, Esc, Up, Down are registered."""
        import curses
        assert self._resolve(app, ord('q'), 'details') is not None
        assert self._resolve(app, 27, 'details') is not None
        assert self._resolve(app, curses.KEY_UP, 'details') is not None

    def test_user_help_mode_binding(self, app, pb):
        """--mode help stores binding accessible via trie for help mode."""
        app._cmd_bindkey('--mode help h :help')
        b = self._resolve(app, ord('h'), 'help')
        assert b is not None
        assert b.commands == [':help']
        assert b.mode == 'help'

    def test_user_details_mode_binding(self, app, pb):
        """--mode details stores binding accessible via trie for details mode."""
        app._cmd_bindkey('--mode details i :ping-view')
        assert self._resolve(app, ord('i'), 'details') is not None

    def test_mode_binding_not_in_main_trie(self, app, pb):
        """A --mode help binding does NOT appear in the main key trie."""
        app._cmd_bindkey('--mode help x :help')
        keys = pb._parse_key_notation('x')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None or all(':help' not in c for c in binding.commands)

    def test_dispatch_mode_key_executes_command(self, app, pb):
        """_dispatch_mode_key finds and runs help-mode binding."""
        executed = []
        original = app._dispatch_cmd
        app._dispatch_cmd = lambda cmd: executed.append(cmd)
        app._cmd_bindkey('--mode help h :help')
        result = app._dispatch_mode_key('help', ord('h'))
        assert result is True
        assert any("help" in cmd for cmd in executed)
        app._dispatch_cmd = original

    def test_dispatch_mode_key_returns_false_for_unbound(self, app, pb):
        """_dispatch_mode_key returns False when no binding exists for the key."""
        result = app._dispatch_mode_key('help', ord('Z'))
        assert result is False

    def test_cmd_close_closes_help(self, app, pb):
        """:close sets help_open=False and _current_mode='normal'."""
        app.help_open = True
        app._current_mode = 'help'
        app._cmd_close()
        assert app.help_open is False
        assert app._current_mode == 'normal'

    def test_cmd_close_closes_details(self, app, pb):
        """:close sets details_open=False and clears details_monitor."""
        import unittest.mock as mock
        app.details_open = True
        app.details_monitor = mock.MagicMock()
        app._current_mode = 'details'
        app._cmd_close()
        assert app.details_open is False
        assert app.details_monitor is None
        assert app._current_mode == 'normal'

    def test_scroll_overlay_help(self, app, pb):
        """:scroll-overlay up/down adjusts help_scroll."""
        app.help_open = True
        app.help_scroll = 5
        app._cmd_scroll_overlay('up')
        assert app.help_scroll == 4
        app._cmd_scroll_overlay('down')
        assert app.help_scroll == 5
        app._cmd_scroll_overlay('page')
        assert app.help_scroll == 15
        app._cmd_scroll_overlay('page-')
        assert app.help_scroll == 5

    def test_scroll_overlay_clamped_at_zero(self, app, pb):
        """:scroll-overlay page- from scroll=3 clamps at 0."""
        app.help_open = True
        app.help_scroll = 3
        app._cmd_scroll_overlay('page-')
        assert app.help_scroll == 0


# ===========================================================================
# TestDescFlag — --desc on :bind-key (8h)
# ===========================================================================

class TestDescFlag:
    """--desc stores description text on _Binding."""

    def test_desc_stored_on_binding(self, app, pb):
        """--desc text is stored as binding.desc."""
        app._cmd_bindkey('--desc "Connect via MTR" t :mux mtr %i')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.desc == 'Connect via MTR'

    def test_desc_empty_by_default(self, app, pb):
        """Bindings without --desc have empty desc."""
        app._cmd_bindkey('t :mux mtr')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding.desc == ''

    def test_desc_shown_in_listing(self, app, pb):
        """bind-key listing shows desc text alongside binding."""
        app._cmd_bindkey('--desc "MTR trace" t :mux mtr')
        app._cmd_bindkey()
        events = [e for e in app.events if 'MTR trace' in e]
        assert events, "desc text not shown in listing"

    def test_desc_with_mode(self, app, pb):
        """--mode and --desc can be combined."""
        app._cmd_bindkey('--mode help --desc "Show help" h :help')
        b = app._key_trie.resolve([ord('h')], set(), mode='help')[0]
        assert b is not None
        assert b.desc == 'Show help'


# ===========================================================================
# TestHintFlag — --hint on :bind-key (8h2)
# ===========================================================================

class TestHintFlag:
    """--hint stores hint text on _Binding and appears in menu bar collection."""

    def test_hint_stored_on_binding(self, app, pb):
        """--hint text is stored as binding.hint."""
        app._cmd_bindkey('--hint "[t]ool" t :mux mtr')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.hint == '[t]ool'

    def test_hint_empty_by_default(self, app, pb):
        """Bindings without --hint have empty hint."""
        app._cmd_bindkey('t :mux mtr')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding.hint == ''

    def test_default_action_hints_present(self, app, pb):
        """Default bindings for q and ? carry hint text; C is shown in Events header."""
        hints = [b.hint for _, b in app._key_trie if b.hint]
        assert any('[q]uit' in h for h in hints), "q binding missing [q]uit hint"
        assert any('[?]' in h for h in hints), "? binding missing hint"
        # C (clear log) moved to Events header — no trie hint expected
        assert not any('[C]lear' in h for h in hints), "C should not have trie hint"

    def test_user_hint_collected_for_menu(self, app, pb):
        """User-defined --hint binding shows up when iterating trie for menu."""
        app._cmd_bindkey('--hint "[m]tr" m :mux mtr')
        all_hints = [b.hint for _, b in app._key_trie if b.hint]
        assert '[m]tr' in all_hints

    def test_desc_and_hint_combined(self, app, pb):
        """--desc and --hint can both be set on one binding."""
        app._cmd_bindkey('--desc "Run MTR" --hint "[m]tr" m :mux mtr')
        keys = pb._parse_key_notation('m')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding.desc == 'Run MTR'
        assert binding.hint == '[m]tr'


# ---------------------------------------------------------------------------
# Conditional binding flags: --if-cmd / --if-sh
# ---------------------------------------------------------------------------

class TestConditionalBindings:
    """Test --if-cmd and --if-sh flags for conditional key binding."""

    def test_if_cmd_present_binds(self, app, pb):
        """--if-cmd with a program that exists → binding is registered."""
        # 'python3' is always in PATH during tests
        app._cmd_bindkey('--if-cmd python3 t :quit')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.commands == [':quit']

    def test_if_cmd_missing_skips(self, app, pb):
        """--if-cmd with a nonexistent program → binding is skipped."""
        app._cmd_bindkey('--if-cmd zzz_no_such_program_999 y :quit')
        keys = pb._parse_key_notation('y')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None

    def test_if_cmd_missing_logs_event(self, app, pb):
        """Skipped --if-cmd logs an info-level event."""
        app._cmd_bindkey('--if-cmd zzz_no_such_program_999 t :quit')
        matching = [e for e in app.events
                    if 'zzz_no_such_program_999' in e.text
                    and 'not in PATH' in e.text]
        assert len(matching) == 1
        assert matching[0].level == pb.LEVEL_INFO

    def test_if_cmd_multiple_all_pass(self, app, pb):
        """Multiple --if-cmd flags: binding registered when all pass."""
        app._cmd_bindkey('--if-cmd python3 --if-cmd sh t :quit')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None

    def test_if_cmd_multiple_one_fails(self, app, pb):
        """Multiple --if-cmd flags: first failure skips the binding."""
        app._cmd_bindkey(
            '--if-cmd python3 --if-cmd zzz_no_such_program_999 y :quit')
        keys = pb._parse_key_notation('y')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None

    def test_if_sh_true_binds(self, app, pb):
        """--if-sh with a true condition → binding is registered."""
        app._cmd_bindkey('--if-sh "true" t :quit')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None

    def test_if_sh_false_skips(self, app, pb):
        """--if-sh with a false condition → binding is skipped."""
        app._cmd_bindkey('--if-sh "false" y :quit')
        keys = pb._parse_key_notation('y')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None

    def test_if_sh_false_logs_event(self, app, pb):
        """Skipped --if-sh logs an info-level event."""
        app._cmd_bindkey('--if-sh "false" t :quit')
        matching = [e for e in app.events
                    if '--if-sh failed' in e.text]
        assert len(matching) == 1
        assert matching[0].level == pb.LEVEL_INFO

    def test_if_sh_quoted_command(self, app, pb):
        """--if-sh with a quoted multi-word command."""
        app._cmd_bindkey('--if-sh "test 1 = 1" t :quit')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None

    def test_if_sh_kiosk_blocked(self, app, pb):
        """--if-sh is blocked in kiosk mode."""
        app.kiosk_mode = True
        app._loading_file = True  # even during file loading
        app._cmd_bindkey('--if-sh "true" y :quit')
        keys = pb._parse_key_notation('y')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None
        matching = [e for e in app.events
                    if 'kiosk' in e.text and '--if-sh' in e.text]
        assert len(matching) == 1

    def test_if_cmd_kiosk_allowed(self, app, pb):
        """--if-cmd is allowed in kiosk mode (during file loading)."""
        app.kiosk_mode = True
        app._loading_file = True
        app._cmd_bindkey('--if-cmd python3 t :quit')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None

    def test_if_cmd_with_context_flags(self, app, pb):
        """--if-cmd combined with --%h context flag."""
        app._cmd_bindkey('--if-cmd python3 --%h y :quit')
        keys = pb._parse_key_notation('y')
        # With no context vars, shouldn't resolve
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None
        # With 'h' context var, should resolve
        binding, _ = app._key_trie.resolve(keys, {'h'})
        assert binding is not None

    def test_if_cmd_with_mode(self, app, pb):
        """--if-cmd combined with --mode help."""
        app._cmd_bindkey('--if-cmd python3 --mode help t :quit')
        assert app._key_trie.resolve([ord('t')], set(), mode='help')[0] is not None

    def test_if_cmd_missing_with_mode(self, app, pb):
        """--if-cmd missing combined with --mode: mode binding not created."""
        app._cmd_bindkey(
            '--if-cmd zzz_no_such_program_999 --mode help t :quit')
        assert app._key_trie.resolve([ord('t')], set(), mode='help')[0] is None

    def test_if_cmd_with_desc_hint(self, app, pb):
        """--if-cmd combined with --desc and --hint."""
        app._cmd_bindkey(
            '--if-cmd python3 --desc "Run tool" --hint "[t]ool" t :quit')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.desc == 'Run tool'
        assert binding.hint == '[t]ool'

    def test_if_cmd_and_if_sh_combined(self, app, pb):
        """Both --if-cmd and --if-sh can be used together."""
        app._cmd_bindkey('--if-cmd python3 --if-sh "true" t :quit')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is not None

    def test_if_cmd_pass_if_sh_fail(self, app, pb):
        """--if-cmd passes but --if-sh fails → binding skipped."""
        app._cmd_bindkey('--if-cmd python3 --if-sh "false" y :quit')
        keys = pb._parse_key_notation('y')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None


# ===========================================================================
# TestDefaultCBindingForRelayHosts — 'c' on a :remote-ping host
# ===========================================================================

class TestDefaultCBindingForRelayHosts:
    """'c' must open a shell on the selected host, not on its relay.

    ping-bulk monitors a ':with remote-ping <relay>' host by running ping on
    the relay, so reaching the host itself means jumping through the relay.
    The binding used to expand to 'ssh <relay>', which landed on the relay and
    dropped the selected host from the command altogether.
    """

    def _relay_monitor(self, pb, ssh_args, ping_host):
        return pb.SshPingMonitor(ssh_args, ping_host)

    def _expand_c(self, app, pb, monitor, context={'d'}):
        app.entries.append(monitor)
        app.highlighted_index = len(app.entries) - 1
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('c'), context)
        assert binding is not None, "'c' should be bound in this context"
        cmds, warning = app._expand_binding_commands(binding.commands)
        assert warning is None, warning
        return cmds[0]

    def test_destination_is_the_host_not_the_relay(self, app, pb):
        m = self._relay_monitor(pb, ['ses-wg-video'], '10.111.1.1')
        assert self._expand_c(app, pb, m) == ':mux ssh -J ses-wg-video 10.111.1.1'

    def test_existing_jump_hosts_come_before_the_relay(self, app, pb):
        m = self._relay_monitor(pb, ['-J', 'relay1', 'ses-wg-video'], '10.111.1.99')
        assert self._expand_c(app, pb, m) == \
            ':mux ssh -J relay1,ses-wg-video 10.111.1.99'

    def test_multi_hop_uses_one_comma_separated_flag(self, app, pb):
        """ssh keeps the first value of a repeated option, so '-J a -J b' drops b."""
        m = self._relay_monitor(pb, ['-J', 'r1,r2', 'ses-wg-video'], '10.111.1.77')
        expanded = self._expand_c(app, pb, m)
        assert expanded == ':mux ssh -J r1,r2,ses-wg-video 10.111.1.77'
        assert expanded.count('-J') == 1, \
            "repeated -J flags are silently collapsed by ssh to the first one"

    def test_plain_host_still_connects_directly(self, app, pb):
        """A host with no relay has no %d context and uses the simple form."""
        m = pb.PingMonitor('plain.example.com')
        assert self._expand_c(app, pb, m, context=set()) == \
            ':mux ssh plain.example.com'


class TestUserBindingBeatsDefaultOnTie:
    """An explicit user binding must win over an equally specific default.

    A default guarded on --%d and a user binding guarded on --%h both match a
    relayed host.  Insertion order used to decide, so defaults always won and
    adding one could silently take a key away from the user's own config.
    """

    def test_user_context_binding_wins_over_default(self, app, pb):
        app._cmd_bindkey('--%h c :mux echo mine')
        m = pb.SshPingMonitor(['gw.example.com'], '10.0.0.1')
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = set(app._binding_context().keys())
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('c'), ctx)
        assert binding.origin == 'user'
        assert binding.commands == [':mux echo mine']

    def test_more_specific_default_still_wins(self, app, pb):
        """Specificity is still checked first; origin only breaks ties.

        'c' has a --%d default, which outranks an unguarded user binding.
        """
        app._cmd_bindkey('c :mux echo unguarded')
        m = pb.SshPingMonitor(['gw.example.com'], '10.0.0.1')
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = set(app._binding_context().keys())
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('c'), ctx)
        assert binding.origin == 'default', \
            'a --%d default is more specific than an unguarded user binding'

    def test_user_binding_wins_for_plain_host_too(self, app, pb):
        app._cmd_bindkey('--%h c :mux echo mine')
        m = pb.PingMonitor('host.example.com')
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = set(app._binding_context().keys())
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('c'), ctx)
        assert binding.commands == [':mux echo mine']


# ===========================================================================
# TestRelayPrefix — running a host-directed command where the host is reachable
# ===========================================================================

class TestRelayPrefix:
    """A host behind a relay is reachable only from that relay.

    So a tool aimed at it (mtr, traceroute, iperf3, curl, …) has no route to it
    locally and must run on the relay.  The decision is read off the variables
    the binding used, which keeps it program-agnostic — there is no list of
    known tools anywhere in the code.
    """

    def _relayed(self, app, pb, ssh_args=('relay',), target='10.0.0.1'):
        m = pb.SshPingMonitor(list(ssh_args), target)
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        return m

    def _prefix_for(self, app, template):
        used = set()
        app._expand_binding_commands([template], used=used)
        return app._relay_prefix_for(used)

    # ── which commands get wrapped ───────────────────────────────────────────

    def test_host_directed_command_runs_on_the_relay(self, app, pb):
        self._relayed(app, pb)
        assert self._prefix_for(app, ':mux mtr %r') == ['ssh', '-t', 'relay']

    def test_percent_h_also_counts_as_host_directed(self, app, pb):
        self._relayed(app, pb)
        assert self._prefix_for(app, ':mux traceroute %h') == ['ssh', '-t', 'relay']

    def test_percent_i_also_counts_as_host_directed(self, app, pb):
        self._relayed(app, pb)
        assert self._prefix_for(app, ':mux iperf3 -c %i') == ['ssh', '-t', 'relay']

    def test_relay_aware_binding_is_left_alone(self, app, pb):
        """A binding naming %d handles the relay itself, as 'c' does."""
        self._relayed(app, pb)
        assert self._prefix_for(app, ':mux ssh -J %d %r') == []

    def test_command_not_about_the_host_stays_local(self, app, pb):
        """':mux man ping-bulk' from the help overlay must not be wrapped."""
        self._relayed(app, pb)
        assert self._prefix_for(app, ':mux man ping-bulk') == []

    def test_section_variable_only_stays_local(self, app, pb):
        self._relayed(app, pb)
        assert self._prefix_for(app, ':mux echo %s') == []

    def test_plain_host_stays_local(self, app, pb):
        m = pb.PingMonitor('host.example.com')
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        assert self._prefix_for(app, ':mux mtr %r') == []

    def test_nothing_selected_stays_local(self, app, pb):
        app.highlighted_index = None
        assert app._relay_prefix_for({'r'}) == []

    # ── how the prefix is built ──────────────────────────────────────────────

    def test_jump_hosts_precede_the_relay_in_one_list(self, app, pb):
        """We log in *to* the relay, so the -J chain stops before it."""
        self._relayed(app, pb, ssh_args=('-J', 'a', '-J', 'b', 'relay'))
        assert self._prefix_for(app, ':mux mtr %r') == \
            ['ssh', '-t', '-J', 'a,b', 'relay']

    def test_tty_is_requested(self, app, pb):
        """Interactive tools need a tty on the far side."""
        self._relayed(app, pb)
        assert '-t' in self._prefix_for(app, ':mux mtr %r')

    # ── end to end, including :prog-options ──────────────────────────────────

    def _launch(self, app, pb, template):
        used = set()
        cmds, warning = app._expand_binding_commands([template], used=used)
        assert warning is None, warning
        backend = MagicMock()
        backend.is_inside.return_value = True
        backend.available.return_value = True
        with patch.dict(pb._MUX_BACKENDS, {'tmux': backend}):
            app._mux_from_binding = True
            app._mux_relay_prefix = app._relay_prefix_for(used)
            try:
                app._cmd_mux(cmds[0][len(':mux '):])
            finally:
                app._mux_from_binding = False
                app._mux_relay_prefix = None
        if not backend.split.called:
            return None
        return ' '.join(backend.split.call_args[0][1])

    def test_wrapped_command_is_launched(self, app, pb):
        self._relayed(app, pb)
        assert 'ssh -t relay mtr 10.0.0.1' in self._launch(app, pb, ':mux mtr %r')

    def test_relay_gets_its_own_ssh_options_not_the_targets(self, app, pb):
        """The login lands on the relay, so the relay's -l applies to it.

        The target's own rule must not be used for the relay hop — that was the
        bug that made a hand-written relay binding log in as the wrong user.
        """
        app._cmd_prog_options('ssh relay -l relayuser')
        app._cmd_prog_options('ssh 10.0.0.* -l targetuser')
        self._relayed(app, pb)
        launched = self._launch(app, pb, ':mux mtr %r')
        assert 'ssh -l relayuser -t relay' in launched, launched
        assert 'targetuser' not in launched, launched

    def test_wrapped_program_still_gets_its_own_rules(self, app, pb):
        """The program acts on the target, so its rules match the target."""
        app._cmd_prog_options('mtr 10.0.0.* -4')
        self._relayed(app, pb)
        launched = self._launch(app, pb, ':mux mtr %r')
        assert 'mtr -4 10.0.0.1' in launched, launched

    def test_disabled_program_is_not_run_at_all(self, app, pb):
        app._cmd_prog_options('mtr 10.0.0.* --disable')
        self._relayed(app, pb)
        assert self._launch(app, pb, ':mux mtr %r') is None

    def test_disabled_relay_ssh_refuses_and_explains(self, app, pb):
        """No way in means no run; say so rather than launching something odd."""
        app._cmd_prog_options('ssh relay --disable')
        self._relayed(app, pb)
        assert self._launch(app, pb, ':mux mtr %r') is None
        assert any('relay is disabled' in e.text for e in app.events), \
            [e.text for e in app.events]


class TestDefaultTBinding:
    """'t' is a default only when mtr is installed, via _b(if_cmd=...)."""

    @pytest.mark.skipif(not shutil.which('mtr'), reason='mtr not installed')
    def test_t_is_bound_when_mtr_present(self, app, pb):
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('t'), {'h', 'r'})
        assert binding is not None
        assert binding.commands == [':mux mtr %r']

    def test_default_is_skipped_when_the_program_is_absent(self, app, pb):
        """The gate is the generic _b(if_cmd=...), not a per-program check.

        Re-registers the defaults with nothing on PATH: every if_cmd-gated
        default drops out, while ungated ones such as 'q' stay.
        """
        fresh = pb._KeyTrie()
        with patch.object(app, '_key_trie', fresh), \
                patch.object(pb.shutil, 'which', return_value=None):
            app._register_default_bindings()
        assert fresh.resolve(pb._parse_key_notation('t'), {'h', 'r'})[0] is None
        assert fresh.resolve(pb._parse_key_notation('q'), set())[0] is not None


# ===========================================================================
# TestContextFlagPercentI — '--%i' was never a valid guard
# ===========================================================================

class TestContextFlagPercentI:
    """'i' was missing from _BINDING_CONTEXT_VARS since guards were introduced.

    Every other per-host variable could be guarded on, so '--%i t :mux mtr %i'
    looked reasonable, was rejected, and the rejection sat at 'info' — below
    the default log level.
    """

    def test_percent_i_is_accepted(self, app, pb):
        app._cmd_bindkey('--%i y :mux mtr %i')
        m = pb.PingMonitor('10.0.0.1')
        m.resolved_ip = '10.0.0.1'
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = set(app._binding_context().keys())
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('y'), ctx)
        assert binding is not None
        assert binding.commands == [':mux mtr %i']

    def test_percent_i_guard_does_not_match_without_an_ip(self, app, pb):
        """The guard is what it says: no resolved IP means the key is inert."""
        app._cmd_bindkey('--%i y :mux mtr %i')
        m = pb.PingMonitor('unresolved.example.com')
        m.resolved_ip = None
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        ctx = set(app._binding_context().keys())
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('y'), ctx)
        assert binding is None

    @pytest.mark.parametrize('flag', ['--%h', '--%i', '--%r', '--%d',
                                      '--%s', '--%p', '--%j'])
    def test_every_context_variable_is_guardable(self, app, pb, flag):
        app._cmd_bindkey(f'{flag} y :quit')
        bindings, _ = app._key_trie.lookup(pb._parse_key_notation('y'))
        assert bindings.get('normal'), f'{flag} was rejected'

    def test_unknown_flag_is_still_rejected(self, app, pb):
        app._cmd_bindkey('--%zz y :quit')
        bindings, _ = app._key_trie.lookup(pb._parse_key_notation('y'))
        assert not bindings.get('normal')

    def test_rejection_is_visible_at_the_default_loglevel(self, app, pb):
        """A hosts-file line that did nothing must not be reported below it."""
        app._monitoring_started = False
        app._cmd_bindkey('--%zz y :quit')
        visible = [e for e in app.events if e.level <= pb.LEVEL_NORMAL]
        assert any('unknown context flag --%zz' in e.text for e in visible), \
            [e.text for e in app.events]

    def test_percent_i_is_offered_in_completion(self, app, pb):
        flags = pb._CMD_MAP['bind-key'].flags
        assert '--%i' in flags, flags


# ===========================================================================
# TestConnectPreview — the details overlay's 'Connect:' line
# ===========================================================================

class TestConnectPreview:
    """'Connect:' previews what 'c' would run, so it must not be rebuilt.

    It used to construct its own string from monitor.host, which for a relayed
    host is the composite display label ('relay→target', arrow included) — not
    a usable ssh target — and it omitted the -J relay hop.  It also ignored a
    rebound 'c' entirely.
    """

    def _select(self, app, monitor):
        app.entries.append(monitor)
        app.highlighted_index = len(app.entries) - 1
        return monitor

    def _real_c(self, app, pb):
        """What pressing 'c' actually launches, as a command string."""
        binding, _ = app._key_trie.resolve(
            pb._parse_key_notation('c'), set(app._binding_context().keys()))
        assert binding is not None
        backend = MagicMock()
        backend.is_inside.return_value = True
        backend.available.return_value = True
        with patch.dict(pb._MUX_BACKENDS, {'tmux': backend}):
            app._execute_binding(binding)
        if not backend.split.called:
            return None
        launched = ' '.join(backend.split.call_args[0][1])
        return launched.replace('sh -c ', '').split(';')[0].strip()

    # ── preview matches reality ─────────────────────────────────────────────

    def test_plain_host_matches(self, app, pb):
        m = self._select(app, pb.PingMonitor('10.0.0.1'))
        assert app._connect_preview(m) == self._real_c(app, pb)

    def test_relayed_host_matches(self, app, pb):
        m = self._select(app, pb.SshPingMonitor(['relay'], '10.1.2.3'))
        assert app._connect_preview(m) == self._real_c(app, pb)

    def test_relayed_host_shows_the_jump_not_the_label(self, app, pb):
        """The old preview named 'relay→target', which ssh cannot resolve."""
        m = self._select(app, pb.SshPingMonitor(['relay'], '10.1.2.3'))
        preview = app._connect_preview(m)
        assert preview == 'ssh -J relay 10.1.2.3', preview
        assert '→' not in preview

    def test_prog_options_are_shown(self, app, pb):
        app._cmd_prog_options('ssh *-router -l admin')
        m = self._select(app, pb.PingMonitor('core-router'))
        assert app._connect_preview(m) == 'ssh -l admin core-router'
        assert app._connect_preview(m) == self._real_c(app, pb)

    def test_relayed_host_with_prog_options_matches(self, app, pb):
        app._cmd_prog_options('ssh 10.1.* -l dev')
        m = self._select(app, pb.SshPingMonitor(['relay'], '10.1.2.3'))
        assert app._connect_preview(m) == self._real_c(app, pb)

    def test_resolv_static_target_matches(self, app, pb):
        m = pb.PingMonitor('label')
        m.resolved_ip = '10.0.0.5'
        m.resolv_static = True
        self._select(app, m)
        assert app._connect_preview(m) == self._real_c(app, pb)

    # ── disabled ────────────────────────────────────────────────────────────

    def test_disabled_returns_none(self, app, pb):
        app._cmd_prog_options('ssh *-cam* --disable')
        m = self._select(app, pb.PingMonitor('sh1-cam1'))
        assert app._connect_preview(m) is None

    def test_disabled_relayed_host_returns_none(self, app, pb):
        app._cmd_prog_options('ssh 10.1.* --disable')
        m = self._select(app, pb.SshPingMonitor(['relay'], '10.1.2.3'))
        assert app._connect_preview(m) is None

    # ── a rebound 'c' is followed ───────────────────────────────────────────

    def test_rebound_c_is_previewed(self, app, pb):
        """The old preview showed the built-in form whatever 'c' was bound to."""
        app._cmd_bindkey('c :mux ssh -l myuser %r')
        m = self._select(app, pb.PingMonitor('10.0.0.1'))
        assert app._connect_preview(m) == 'ssh -l myuser 10.0.0.1'
        assert app._connect_preview(m) == self._real_c(app, pb)

    def test_rebound_c_with_prog_options_matches(self, app, pb):
        app._cmd_bindkey('c :mux ssh -l myuser %r')
        app._cmd_prog_options('ssh 10.0.0.1 -o Compression=yes')
        m = self._select(app, pb.PingMonitor('10.0.0.1'))
        assert app._connect_preview(m) == self._real_c(app, pb)

    def test_multi_command_binding_is_shown_joined(self, app, pb):
        app._cmd_bindkey(r'c :mux ssh %r \; :mux echo hi')
        m = self._select(app, pb.PingMonitor('10.0.0.1'))
        assert app._connect_preview(m) == 'ssh 10.0.0.1 ; echo hi'

    def test_split_flags_are_not_shown(self, app, pb):
        """'-v' selects the pane direction; it is not part of the command."""
        app._cmd_bindkey('c :mux -v ssh %r')
        m = self._select(app, pb.PingMonitor('10.0.0.1'))
        assert app._connect_preview(m) == 'ssh 10.0.0.1'

    def test_non_mux_binding_is_shown_as_written(self, app, pb):
        app._cmd_bindkey('c :select down')
        m = self._select(app, pb.PingMonitor('10.0.0.1'))
        assert app._connect_preview(m) == 'select down'

    def test_unbound_c_returns_none(self, app, pb):
        app._last_cmd_name = 'unbind-key'
        app._cmd_bindkey('c')
        app._last_cmd_name = None
        m = self._select(app, pb.PingMonitor('10.0.0.1'))
        assert app._connect_preview(m) is None


# ===========================================================================
# TestEditModeConnect — 'C' hands you the command instead of running it
# ===========================================================================

class TestEditModeConnect:
    """'c' connects; 'C' pre-fills the same command for editing.

    Not Ctrl-Shift-C: a terminal sends byte 3 for that exactly as it does for
    Ctrl-C, so the two cannot be distinguished, and it is the emulator's own
    copy shortcut.  'X' took over clearing the event log.
    """

    def _select(self, app, monitor):
        app.entries.append(monitor)
        app.highlighted_index = len(app.entries) - 1
        return monitor

    def _press(self, app, pb, key):
        app.cmd = None
        binding, _ = app._key_trie.resolve(
            pb._parse_key_notation(key), set(app._binding_context().keys()))
        assert binding is not None, f'{key} is unbound'
        app._execute_binding(binding)
        return ''.join(app.cmd['chars']) if app.cmd else None

    def test_c_upper_prefills_and_does_not_run(self, app, pb):
        self._select(app, pb.PingMonitor('10.0.0.1'))
        backend = MagicMock()
        backend.is_inside.return_value = True
        backend.available.return_value = True
        with patch.dict(pb._MUX_BACKENDS, {'tmux': backend}):
            text = self._press(app, pb, 'C')
        assert text == 'mux ssh 10.0.0.1'
        backend.split.assert_not_called()

    def test_cursor_sits_at_the_end_for_editing(self, app, pb):
        self._select(app, pb.PingMonitor('10.0.0.1'))
        self._press(app, pb, 'C')
        assert app.cmd['cursor'] == len(app.cmd['chars'])

    def test_prefill_includes_prog_options(self, app, pb):
        """Edit mode skips :mux's injection, so the pre-fill has to carry it."""
        app._cmd_prog_options('ssh *-router -l admin')
        self._select(app, pb.PingMonitor('core-router'))
        assert self._press(app, pb, 'C') == 'mux ssh -l admin core-router'

    def test_prefill_includes_the_relay_hop(self, app, pb):
        self._select(app, pb.SshPingMonitor(['relay'], '10.1.2.3'))
        assert self._press(app, pb, 'C') == 'mux ssh -J relay 10.1.2.3'

    def test_prefill_matches_what_c_would_run(self, app, pb):
        app._cmd_prog_options('ssh 10.1.* -l dev')
        m = self._select(app, pb.SshPingMonitor(['relay'], '10.1.2.3'))
        assert self._press(app, pb, 'C') == f'mux {app._connect_preview(m)}'

    def test_disabled_host_prefills_nothing(self, app, pb):
        app._cmd_prog_options('ssh *-cam* --disable')
        self._select(app, pb.PingMonitor('sh1-cam1'))
        assert self._press(app, pb, 'C') is None

    def test_disabled_host_says_why(self, app, pb):
        app._cmd_prog_options('ssh *-cam* --disable')
        self._select(app, pb.PingMonitor('sh1-cam1'))
        self._press(app, pb, 'C')
        assert any('disabled for this host' in e.text for e in app.events)

    def test_lowercase_c_still_runs_immediately(self, app, pb):
        self._select(app, pb.PingMonitor('10.0.0.1'))
        backend = MagicMock()
        backend.is_inside.return_value = True
        backend.available.return_value = True
        with patch.dict(pb._MUX_BACKENDS, {'tmux': backend}):
            binding, _ = app._key_trie.resolve(
                pb._parse_key_notation('c'),
                set(app._binding_context().keys()))
            app._execute_binding(binding)
        backend.split.assert_called_once()
        assert app.cmd is None

    def test_x_now_clears_the_event_log(self, app, pb):
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('X'), set())
        assert binding is not None
        assert binding.commands == [':clear --confirm']

    def test_c_is_no_longer_clear(self, app, pb):
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('C'), set())
        assert ':clear --confirm' not in binding.commands

    def test_ctrl_shift_c_is_not_a_key(self, pb):
        """Kept out of the defaults because a terminal cannot send it."""
        with pytest.raises(ValueError):
            pb._parse_key_notation('<C-S-c>')
