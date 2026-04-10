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
import pytest
from unittest.mock import patch


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
        """After binding, ':bindkey t' (no cmd) removes the binding."""
        app._cmd_bindkey('t :mux mtr')
        app._cmd_bindkey('t')
        keys = pb._parse_key_notation('t')
        binding, _ = app._key_trie.resolve(keys, set())
        assert binding is None
        assert any('unbound t' in e for e in app.events)

    def test_bindkey_list_empty(self, app):
        """':bindkey' with no user bindings logs 'no user key bindings'."""
        app.events.clear()
        app._cmd_bindkey()
        assert any('no user key bindings' in e for e in app.events)

    def test_bindkey_list_shows_user_bindings(self, app):
        """After binding, ':bindkey' lists it in events."""
        app._cmd_bindkey('t :mux mtr')
        app.events.clear()
        app._cmd_bindkey()
        assert any('t' in e and ':mux mtr' in e for e in app.events)

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
        """':bindkey --%h t :mux mtr' creates a context-aware binding."""
        app._cmd_bindkey('--%h t :mux mtr')
        keys = pb._parse_key_notation('t')
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
        """':bindkey --%s <Space>' unbinds only the section-context binding."""
        # Default Space has --%s :fold toggle and fallback :seen
        keys = pb._parse_key_notation('<Space>')
        r_section, _ = app._key_trie.resolve(keys, {'s'})
        assert r_section.commands == [':fold toggle']
        # Unbind only the section context
        app._cmd_bindkey('--%s <Space>')
        r_section, _ = app._key_trie.resolve(keys, {'s'})
        # Now falls back to :seen
        assert r_section.commands == [':seen']


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
        # Section context → fold toggle
        r, _ = app._key_trie.resolve(keys, {'s', 'H'})
        assert r.commands == [':fold toggle']
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
        """After binding a key, _save_config output contains :bindkey ..."""
        app, cfg = app_with_cfg
        app._cmd_bindkey('t :mux mtr')
        with patch.object(pb, '_config_path', return_value=cfg):
            success = app._save_config()
        assert success is True
        config_text = open(cfg).read()
        assert ':bindkey t :mux mtr' in config_text

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
        """After unbinding a default key, save output contains bare :bindkey <key>."""
        app, cfg = app_with_cfg
        # Unbind 'q' (a default binding)
        app._cmd_bindkey('q')
        with patch.object(pb, '_config_path', return_value=cfg):
            success = app._save_config()
        assert success is True
        config_text = open(cfg).read()
        # Should have ':bindkey q' (without a command) to unbind it
        lines = [line.strip() for line in config_text.splitlines()]
        assert ':bindkey q' in lines


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
