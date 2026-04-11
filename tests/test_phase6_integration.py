"""Integration tests spanning multiple Phase 6 features.

Covers scenarios that exercise more than one feature together, where unit
tests in test_bindkey.py or test_prog_options.py would be insufficient.
"""

import os
import pytest
from unittest.mock import patch


def _make_app(pb, tmp_path):
    """Return an Application with a blank temp config and monitoring started."""
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '127.0.0.1')])
    app._monitoring_started = True
    return app, cfg


# ===========================================================================
# TestSaveconfigBothBindkeyAndProgOptions
# ===========================================================================

class TestSaveconfigBothBindkeyAndProgOptions:
    """Verify save → load round-trip preserves both :bindkey and :prog-options."""

    def test_roundtrip_bindkey_and_prog_options(self, pb, tmp_path):
        """Config saved with both a user binding and a prog-options rule.

        After reload both must be fully restored:
        - The user :bindkey entry is in the trie with origin='user'.
        - The :prog-options rule is present in prog_options.
        """
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()

        with patch.object(pb, '_config_path', return_value=cfg):
            app1 = pb.Application([('host', '127.0.0.1')])
        app1._monitoring_started = True
        app1._cmd_bindkey('t :mux mtr %i')
        app1._cmd_prog_options('ssh *.internal -o ProxyJump=gw')
        with patch.object(pb, '_config_path', return_value=cfg):
            app1._save_config()

        text = open(cfg).read()
        assert ':bind-key t :mux mtr %i' in text
        assert ':prog-options ssh *.internal -o ProxyJump=gw' in text

        with patch.object(pb, '_config_path', return_value=cfg):
            app2 = pb.Application([('host', '127.0.0.1')])

        # Binding restored
        keys = pb._parse_key_notation('t')
        binding, _ = app2._key_trie.resolve(keys, set())
        assert binding is not None
        assert binding.commands == [':mux mtr %i']
        assert binding.origin == 'user'

        # prog-options restored
        rules = app2.prog_options.get('ssh', [])
        assert ('*.internal', '-o ProxyJump=gw') in rules

    def test_roundtrip_bindkey_unbind_and_prog_options(self, pb, tmp_path):
        """An unbound default key plus a prog-options rule both survive round-trip."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()

        with patch.object(pb, '_config_path', return_value=cfg):
            app1 = pb.Application([('host', '127.0.0.1')])
        app1._monitoring_started = True
        # Unbind the default 'q' quit key and add a prog-options rule
        app1._cmd_bindkey('q')
        app1._cmd_prog_options('ssh kiosk-* --disable')
        with patch.object(pb, '_config_path', return_value=cfg):
            app1._save_config()

        with patch.object(pb, '_config_path', return_value=cfg):
            app2 = pb.Application([('host', '127.0.0.1')])

        # 'q' should be unbound (no user binding and default overridden)
        keys = pb._parse_key_notation('q')
        binding, _ = app2._key_trie.resolve(keys, set())
        # After an explicit unbind is saved and reloaded, the binding
        # should be absent (unbind removes it from the trie).
        assert binding is None

        # prog-options rule restored
        disabled, _ = app2._match_prog_options('ssh', 'kiosk-99')
        assert disabled
