"""Unit tests for :prog-options command."""

import os
import pytest
from unittest.mock import patch


def _make_app(pb, tmp_path):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '127.0.0.1')])
    app._monitoring_started = True
    return app


@pytest.fixture
def app(pb, tmp_path):
    return _make_app(pb, tmp_path)


class TestProgOptions:
    """Test :prog-options command."""

    def test_add_rule(self, app):
        """Adding a rule stores it in prog_options."""
        app._cmd_prog_options('ssh *.internal -o ProxyJump=gw')
        rules = app.prog_options.get('ssh', [])
        assert any(p == '*.internal' for p, _ in rules)

    def test_match_rule(self, app):
        """Matching returns options string."""
        app._cmd_prog_options('ssh *.internal -o ProxyJump=gw')
        disabled, opts = app._match_prog_options('ssh', 'host.internal')
        assert not disabled
        assert opts == '-o ProxyJump=gw'

    def test_no_match(self, app):
        """Non-matching host returns empty options."""
        app._cmd_prog_options('ssh *.internal -o ProxyJump=gw')
        disabled, opts = app._match_prog_options('ssh', 'host.external')
        assert not disabled
        assert opts == ''

    def test_disable_rule(self, app):
        """--disable rule returns disabled=True."""
        app._cmd_prog_options('ssh kiosk-* --disable')
        disabled, opts = app._match_prog_options('ssh', 'kiosk-1')
        assert disabled

    def test_last_match_wins(self, app):
        """Last matching rule wins."""
        app._cmd_prog_options('ssh * -o opt1')
        app._cmd_prog_options('ssh *.special -o opt2')
        disabled, opts = app._match_prog_options('ssh', 'host.special')
        assert opts == '-o opt2'

    def test_remove_rule(self, app):
        """Removing a rule by (prog, glob) clears it."""
        app._cmd_prog_options('ssh *.internal -o ProxyJump=gw')
        app._cmd_prog_options('ssh *.internal')
        rules = app.prog_options.get('ssh', [])
        assert not any(p == '*.internal' for p, _ in rules)

    def test_different_programs_independent(self, app):
        """Rules for different programs don't interfere."""
        app._cmd_prog_options('ssh *.internal -o ProxyJump=gw')
        app._cmd_prog_options('mtr *.slow --interval 2')
        _, ssh_opts = app._match_prog_options('ssh', 'host.internal')
        _, mtr_opts = app._match_prog_options('mtr', 'host.slow')
        assert ssh_opts == '-o ProxyJump=gw'
        assert mtr_opts == '--interval 2'

    def test_saveconfig_writes_rules(self, app, pb, tmp_path):
        """_save_config writes :prog-options lines."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        app._cmd_prog_options('ssh *.internal -o ProxyJump=gw')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        text = open(cfg).read()
        assert ':prog-options ssh *.internal -o ProxyJump=gw' in text

    def test_saveconfig_writes_disable(self, app, pb, tmp_path):
        """_save_config writes --disable rules."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        app._cmd_prog_options('ssh kiosk-* --disable')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        text = open(cfg).read()
        assert ':prog-options ssh kiosk-* --disable' in text
