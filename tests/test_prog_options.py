"""Unit tests for :prog-options command."""

import os
import shlex
import pytest
from unittest.mock import patch, MagicMock

from utils.hosts_helper import write_hosts


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

    def test_saveconfig_only_prog_options(self, app, pb, tmp_path):
        """_save_config writes :prog-options rules and nothing else for options."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        app._cmd_prog_options('ssh *.internal -o ProxyJump=gw')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        text = open(cfg).read()
        assert ':prog-options ssh *.internal' in text

    def test_roundtrip_options_rule(self, pb, tmp_path):
        """save → load round-trip preserves :prog-options rule with options."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()

        with patch.object(pb, '_config_path', return_value=cfg):
            app1 = pb.Application([('host', '127.0.0.1')])
        app1._monitoring_started = True
        app1._cmd_prog_options('ssh *.example.com -o StrictHostKeyChecking=no')
        with patch.object(pb, '_config_path', return_value=cfg):
            app1._save_config()

        with patch.object(pb, '_config_path', return_value=cfg):
            app2 = pb.Application([('host', '127.0.0.1')])

        rules = app2.prog_options.get('ssh', [])
        assert ('*.example.com', '-o StrictHostKeyChecking=no') in rules

    def test_roundtrip_disable_rule(self, pb, tmp_path):
        """save → load round-trip preserves :prog-options --disable rule."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()

        with patch.object(pb, '_config_path', return_value=cfg):
            app1 = pb.Application([('host', '127.0.0.1')])
        app1._monitoring_started = True
        app1._cmd_prog_options('ssh badhost --disable')
        with patch.object(pb, '_config_path', return_value=cfg):
            app1._save_config()

        with patch.object(pb, '_config_path', return_value=cfg):
            app2 = pb.Application([('host', '127.0.0.1')])

        rules = app2.prog_options.get('ssh', [])
        assert ('badhost', None) in rules
        disabled, _ = app2._match_prog_options('ssh', 'badhost')
        assert disabled

    def test_roundtrip_multiple_rules(self, pb, tmp_path):
        """save → load round-trip preserves multiple :prog-options rules."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()

        with patch.object(pb, '_config_path', return_value=cfg):
            app1 = pb.Application([('host', '127.0.0.1')])
        app1._monitoring_started = True
        app1._cmd_prog_options('ssh *.example.com -o StrictHostKeyChecking=no')
        app1._cmd_prog_options('ssh badhost --disable')
        with patch.object(pb, '_config_path', return_value=cfg):
            app1._save_config()

        with patch.object(pb, '_config_path', return_value=cfg):
            app2 = pb.Application([('host', '127.0.0.1')])

        ssh_rules = app2.prog_options.get('ssh', [])
        assert ('*.example.com', '-o StrictHostKeyChecking=no') in ssh_rules
        assert ('badhost', None) in ssh_rules

        _, opts = app2._match_prog_options('ssh', 'host.example.com')
        assert opts == '-o StrictHostKeyChecking=no'
        disabled, _ = app2._match_prog_options('ssh', 'badhost')
        assert disabled


# ===========================================================================
# :mux auto-injection of :prog-options from bindings
# ===========================================================================

def _make_app_with_monitor(pb, tmp_path, host='myhost', resolved_hostname='myhost'):
    """Return an app with one PingMonitor entry highlighted."""
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', host)])
    app._monitoring_started = True
    # Ensure there is a highlighted entry
    app.highlighted_index = 0
    # Set the resolved hostname on the monitor entry
    if app.entries:
        entry = app.entries[0]
        if isinstance(entry, pb.Monitor):
            entry.resolved_hostname = resolved_hostname
    return app


def _make_mock_backend():
    mock_backend = MagicMock()
    mock_backend.is_inside.return_value = True
    mock_backend.available.return_value = True
    return mock_backend


def _held(tokens):
    """Return the ['sh', '-c', ...] wrapper that _cmd_mux builds."""
    script = (
        shlex.join(tokens)
        + '; _rc=$?;'
          ' if [ "$_rc" -ne 0 ]; then'
          ' printf "\\n[process exited (code %s) — press Enter to close]\\n" "$_rc";'
          ' read _ignored; fi'
    )
    return ['sh', '-c', script]


class TestMuxProgOptionsInjection:

    def test_opts_injected_from_binding(self, pb, tmp_path):
        """:mux ssh from binding with matching prog-options → opts injected."""
        app = _make_app_with_monitor(pb, tmp_path, host='myhost')
        app._cmd_prog_options('ssh myhost -o ProxyJump=gw')
        mock_backend = _make_mock_backend()
        app._mux_from_binding = True
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('ssh myhost')
        mock_backend.split.assert_called_once_with(
            'v', _held(['ssh', '-o', 'ProxyJump=gw', 'myhost']), focus=True
        )

    def test_disabled_from_binding_aborts(self, pb, tmp_path):
        """:mux ssh from binding with --disable → silently aborted."""
        app = _make_app_with_monitor(pb, tmp_path, host='kiosk-1')
        app._cmd_prog_options('ssh kiosk-* --disable')
        mock_backend = _make_mock_backend()
        app._mux_from_binding = True
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('ssh kiosk-1')
        mock_backend.split.assert_not_called()
        mock_backend.new_window.assert_not_called()

    def test_no_injection_when_not_from_binding(self, pb, tmp_path):
        """:mux ssh typed manually → prog-options NOT injected."""
        app = _make_app_with_monitor(pb, tmp_path, host='myhost')
        app._cmd_prog_options('ssh myhost -o ProxyJump=gw')
        mock_backend = _make_mock_backend()
        # _mux_from_binding is False (default)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('ssh myhost')
        mock_backend.split.assert_called_once_with(
            'v', _held(['ssh', 'myhost']), focus=True
        )

    def test_flag_reset_after_binding(self, pb, tmp_path):
        """_mux_from_binding is False again after _execute_binding returns."""
        app = _make_app_with_monitor(pb, tmp_path, host='myhost')
        # Simulate a binding that calls :mux ssh %h
        binding = pb._Binding(
            commands=[':mux ssh myhost'],
            edit_mode=False,
        )
        mock_backend = _make_mock_backend()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._execute_binding(binding)
        assert not app._mux_from_binding

    def test_r_expansion_with_prog_options_injection(self, pb, tmp_path):
        """:mux ssh %r with resolv_static + matching prog-options → opts injected with expanded %r.

        When a host has resolv_static=True the %r variable expands to the
        resolved IP.  prog-options match uses the display name (entry.host),
        so the rule must reference the display name.  The final mux command
        should contain both the injected opts and the resolved IP.
        """
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        with patch.object(pb, '_config_path', return_value=cfg):
            app = pb.Application([('host', 'label')])
        app._monitoring_started = True
        app.highlighted_index = 0
        entry = app.entries[0]
        entry.resolved_ip = '10.0.0.1'
        entry.resolv_static = True
        app._cmd_prog_options('ssh label -o StrictHostKeyChecking=no')
        binding = pb._Binding(commands=[':mux ssh %r'], edit_mode=False)
        mock_backend = _make_mock_backend()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._execute_binding(binding)
        mock_backend.split.assert_called_once_with(
            'v', _held(['ssh', '-o', 'StrictHostKeyChecking=no', '10.0.0.1']), focus=True
        )


# ===========================================================================
# :with prog-options / :end block form
# ===========================================================================

class TestProgOptionsBlock:
    """Parser-level tests for :with prog-options / :end."""

    def test_basic_block(self, pb, tmp_path):
        """:with prog-options block emits :prog-options commands."""
        content = (
            ":with prog-options ssh\n"
            "  *-router -l admin\n"
            "  *-switch -l root\n"
            ":end\n"
            "1.2.3.4\n"
        )
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [e[1] for e in entries if e[0] == 'cmd']
        assert any(':prog-options ssh *-router -l admin' in c for c in cmds)
        assert any(':prog-options ssh *-switch -l root' in c for c in cmds)
        assert ('host', '1.2.3.4') in entries

    def test_block_disable(self, pb, tmp_path):
        """:with prog-options block supports --disable lines."""
        content = (
            ":with prog-options mtr\n"
            "  bad-host --disable\n"
            ":end\n"
        )
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [e[1] for e in entries if e[0] == 'cmd']
        assert any(':prog-options mtr bad-host --disable' in c for c in cmds)

    def test_block_no_prog_name_is_error(self, pb, tmp_path):
        """:with prog-options with no program name emits an error."""
        content = ":with prog-options\n  * -l admin\n:end\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [e for e in entries if e[0] == 'error']
        assert errors, "expected an error for missing program name"

    def test_end_without_begin_is_error(self, pb, tmp_path):
        """:end without matching begin emits an error."""
        content = ":end\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [e for e in entries if e[0] == 'error']
        assert errors

    def test_block_applied_to_app(self, pb, tmp_path):
        """Block form rules are applied when Application loads the hosts file."""
        cfg = str(tmp_path / 'config')
        open(cfg, 'w').close()
        content = (
            ":with prog-options ssh\n"
            "  *.internal -o ProxyJump=bastion\n"
            ":end\n"
            "127.0.0.1\n"
        )
        hosts_file = write_hosts(tmp_path, content)
        entries = pb.parse_hosts_file(hosts_file)
        with patch.object(pb, '_config_path', return_value=cfg):
            app = pb.Application(entries)
        disabled, opts = app._match_prog_options('ssh', 'host.internal')
        assert not disabled
        assert opts == '-o ProxyJump=bastion'

    def test_block_multiple_programs(self, pb, tmp_path):
        """Multiple :with prog-options blocks for different programs work independently."""
        content = (
            ":with prog-options ssh\n"
            "  *.internal -l admin\n"
            ":end\n"
            ":with prog-options mtr\n"
            "  slow-host --interval 2\n"
            ":end\n"
        )
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [e[1] for e in entries if e[0] == 'cmd']
        assert any(':prog-options ssh *.internal -l admin' in c for c in cmds)
        assert any(':prog-options mtr slow-host --interval 2' in c for c in cmds)

    def test_block_in_for_loop(self, pb, tmp_path):
        """:with prog-options inside :for loop applies back-references."""
        content = (
            ":for {router,switch}\n"
            ":with prog-options ssh\n"
            "  $1 -l admin\n"
            ":end\n"
            ":end\n"
        )
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        cmds = [e[1] for e in entries if e[0] == 'cmd']
        assert any(':prog-options ssh router -l admin' in c for c in cmds)
        assert any(':prog-options ssh switch -l admin' in c for c in cmds)

    def test_interactive_with_shows_error(self, app):
        """:with called interactively emits an error event."""
        app._cmd_with('prog-options ssh')
        events = [e for e in app.events if 'with' in e.text]
        assert events

    def test_end_closes_with_block(self, pb, tmp_path):
        """:end correctly closes a :with block; hosts after it are parsed normally."""
        content = (
            ":with prog-options ssh\n"
            "  *-router -l admin\n"
            ":end\n"
            "1.1.1.1\n"
        )
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [e for e in entries if e[0] == 'error']
        assert not errors, f"expected no errors for valid :end closer; got {errors!r}"
        hosts = [e[1] for e in entries if e[0] == 'host']
        assert any('1.1.1.1' in h for h in hosts), "host after :end should be parsed"

    def test_unknown_cmd_inside_with_is_error(self, pb, tmp_path):
        """Any unrecognised command inside :with prog-options block is an error; hosts after still appear."""
        content = (
            ":with prog-options ssh\n"
            "  *-cam --disable\n"
            ":foobar\n"
            "10.0.0.1\n"
        )
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [e for e in entries if e[0] == 'error']
        assert any('foobar' in e[1] for e in errors), "expected error mentioning the bad command"
        hosts = [e[1] for e in entries if e[0] == 'host']
        assert any('10.0.0.1' in h for h in hosts), "host after error should still be parsed"

    def test_unclosed_with_at_eof_is_error(self, pb, tmp_path):
        """:with block not closed at EOF emits an error."""
        content = ":with prog-options ssh\n  *-router -l admin\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [e for e in entries if e[0] == 'error']
        assert errors, "expected an error for unclosed :with block at EOF"
        assert 'missing :end' in errors[0][1]
