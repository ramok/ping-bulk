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
    cmd = shlex.join(tokens)
    # Mirrors Application._mux_pane_script: the pane shows the command it
    # runs as its first line, then holds if the command failed.
    script = (
        "printf '$ %s\\n' " + shlex.quote(cmd) + '; ' + cmd
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

    def test_unclosed_with_at_eof_is_silent(self, pb, tmp_path):
        """:with block not closed at EOF is silently accepted (EOF = implicit :end)."""
        content = ":with prog-options ssh\n  *-router -l admin\n"
        entries = pb.parse_hosts_file(write_hosts(tmp_path, content))
        errors = [e for e in entries if e[0] == 'error']
        warns  = [e for e in entries if e[0] == 'warn']
        assert not errors, "unclosed :with at EOF should NOT emit an error"
        assert not warns,  "unclosed :with at EOF should NOT emit a warning"


class TestProgOptionsForRelayedHosts:
    """Patterns must match the target of a relayed host, not its display name.

    A ':with remote-ping <relay>' host is shown as 'relay→target', which no
    sensible glob matches, and its resolved_hostname is unset — so rules like
    '*-router -l admin' silently never fired for anything behind a relay.
    """

    def _relayed(self, pb, app, target, alias=None, relay='gw.example.com'):
        if alias:
            app.hosts_map[alias] = (target, alias)
            app.hosts_map[target] = (target, alias)
        m = pb.SshPingMonitor([relay], target, hosts_map=app.hosts_map)
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        return m

    def test_pattern_matches_the_resolv_alias(self, app, pb):
        app._cmd_prog_options('ssh *-router -l admin')
        m = self._relayed(pb, app, '10.111.1.1', alias='tent-router')
        disabled, opts = app._match_prog_options('ssh', *app._prog_match_names(m))
        assert not disabled
        assert opts == '-l admin'

    def test_pattern_matches_the_target_address(self, app, pb):
        app._cmd_prog_options('ssh 10.111.* -l dev')
        m = self._relayed(pb, app, '10.111.1.5')
        _, opts = app._match_prog_options('ssh', *app._prog_match_names(m))
        assert opts == '-l dev'

    def test_disable_applies_to_relayed_hosts(self, app, pb):
        """'*-cam* --disable' must hide connect for a relayed camera too."""
        app._cmd_prog_options('ssh *-cam* --disable')
        m = self._relayed(pb, app, '10.123.1.20', alias='sh1-cam1')
        disabled, _ = app._match_prog_options('ssh', *app._prog_match_names(m))
        assert disabled

    def test_composite_display_name_is_not_the_subject(self, app, pb):
        """A rule naming the relay no longer leaks onto the hosts behind it."""
        app._cmd_prog_options('ssh gw.example.com -l relayuser')
        m = self._relayed(pb, app, '10.111.1.1', alias='tent-router')
        _, opts = app._match_prog_options('ssh', *app._prog_match_names(m))
        assert opts == '', \
            'options for the relay must not be applied to the target'

    def test_plain_monitor_still_matches_on_its_own_name(self, app, pb):
        app._cmd_prog_options('ssh *.internal -l admin')
        m = pb.PingMonitor('box.internal')
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        _, opts = app._match_prog_options('ssh', *app._prog_match_names(m))
        assert opts == '-l admin'

    def test_plain_monitor_resolv_alias_still_matches(self, app, pb):
        app._cmd_prog_options('ssh *-router -l admin')
        m = pb.PingMonitor('10.0.0.1')
        m.resolved_hostname = 'core-router'
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        _, opts = app._match_prog_options('ssh', *app._prog_match_names(m))
        assert opts == '-l admin'

    def test_non_monitor_entry_yields_empty_names(self, app, pb):
        """SectionLabel / None must not raise, and must not match a bare name."""
        assert app._prog_match_names(pb.SectionLabel('Group', 1, False, False)) \
            == ('', '')
        assert app._prog_match_names(None) == ('', '')

    def test_injected_into_the_mux_command(self, app, pb):
        """End to end: the -l lands in the actual ssh command for a relayed host."""
        app._cmd_prog_options('ssh *-router -l admin')
        self._relayed(pb, app, '10.111.1.1', alias='tent-router')
        backend = MagicMock()
        backend.is_inside.return_value = True
        backend.available.return_value = True
        with patch.dict(pb._MUX_BACKENDS, {'tmux': backend}):
            app._mux_from_binding = True
            app._cmd_mux('ssh -J gw.example.com 10.111.1.1')
        backend.split.assert_called_once()
        # split(direction, command); the command is wrapped in sh -c '...'
        launched = ' '.join(backend.split.call_args[0][1])
        assert 'ssh -l admin -J gw.example.com 10.111.1.1' in launched, launched


class TestExactPatternBeatsGlob:
    """A rule naming one host exactly wins over a glob, whatever the order.

    Ordering alone used to decide, so this silently gave 'tent-router' the
    '-l admin' meant for every other router:

        tent-router  -l root
        *-router     -l admin

    Writing the specific rule last worked, but only until the next glob was
    appended — which is what made ordering the wrong mechanism.
    """

    def _rules(self, app, *rules):
        for r in rules:
            app._cmd_prog_options('ssh ' + r)
        return app

    def test_exact_before_glob(self, app):
        self._rules(app, 'tent-router -l root', '*-router -l admin')
        assert app._match_prog_options('ssh', 'tent-router') == (False, '-l root')

    def test_exact_after_glob(self, app):
        self._rules(app, '*-router -l admin', 'tent-router -l root')
        assert app._match_prog_options('ssh', 'tent-router') == (False, '-l root')

    def test_glob_still_covers_other_hosts(self, app):
        self._rules(app, 'tent-router -l root', '*-router -l admin')
        assert app._match_prog_options('ssh', 'sh1-router') == (False, '-l admin')

    def test_a_later_glob_cannot_steal_an_exact_host(self, app):
        """The case the ordering workaround could not survive."""
        self._rules(app, '*-router -l admin', 'tent-router -l root',
                    '*-rout* -l dev')
        assert app._match_prog_options('ssh', 'tent-router') == (False, '-l root')
        assert app._match_prog_options('ssh', 'sh1-router') == (False, '-l dev')

    def test_last_exact_wins_among_exacts(self, app):
        """Ordering still decides between rules of the same kind."""
        self._rules(app, 'tent-router -l root', 'tent-router -l dev')
        assert app._match_prog_options('ssh', 'tent-router') == (False, '-l dev')

    def test_last_glob_wins_among_globs(self, app):
        self._rules(app, '*-router -l admin', '*-rout* -l dev')
        assert app._match_prog_options('ssh', 'sh1-router') == (False, '-l dev')

    def test_exact_overrides_a_glob_disable(self, app):
        self._rules(app, '*-cam* --disable', 'sh1-cam1 -l admin')
        assert app._match_prog_options('ssh', 'sh1-cam1') == (False, '-l admin')

    def test_exact_disable_overrides_a_glob_opts(self, app):
        self._rules(app, '* -l admin', 'restricted.example.com --disable')
        assert app._match_prog_options('ssh', 'restricted.example.com') == (True, '')

    def test_no_match_is_unchanged(self, app):
        self._rules(app, '*-router -l admin')
        assert app._match_prog_options('ssh', 'unrelated') == (False, '')

    def test_exact_match_on_the_resolved_name(self, app):
        """Whether the pattern is a glob is what ranks it, not which name matched."""
        self._rules(app, '*-router -l admin', 'tent-router -l root')
        assert app._match_prog_options('ssh', '10.111.1.1', 'tent-router') == \
            (False, '-l root')


class TestIsGlob:

    @pytest.mark.parametrize('pattern', ['*-router', 'sh?-router', 'sh[12]-router',
                                         '*', 'a*b'])
    def test_glob_patterns(self, pb, pattern):
        assert pb._is_glob(pattern) is True

    @pytest.mark.parametrize('pattern', ['tent-router', '10.0.0.1',
                                         'host.example.com', 'a-b_c'])
    def test_literal_patterns(self, pb, pattern):
        assert pb._is_glob(pattern) is False


class TestConnectChain:
    """The chain that reaches a relayed host, composed from stored hops.

    ping-bulk holds the jump hosts as a list (read out of the directive once,
    when the monitor is built) and composes ssh options from it.  Taking
    options apart again is what this replaced, and it was wrong three ways:
    it missed '-o ProxyJump=', it dropped the port from a bracketed IPv6
    hop, and it rewrote a two-user chain that ssh accepts.
    """

    def _chain(self, pb, ssh_args, target):
        return pb.SshPingMonitor(ssh_args, target).connect_chain()

    def test_ordinary_relayed_host(self, pb):
        """The relay is the last hop and the target is the destination."""
        assert self._chain(pb, ['-J', 'outer', 'admin@relay'], '10.111.1.1') \
            == (['outer', 'admin@relay'], '10.111.1.1')

    def test_relay_monitored_as_its_own_host(self, pb):
        """ssh refuses a destination that is one of its hops, so the chain
        stops before it and keeps the login the relay is already reached
        with."""
        assert self._chain(pb, ['-J', 'outer', 'admin@relay'], 'relay') \
            == (['outer'], 'admin@relay')

    def test_relay_as_own_host_without_outer_hops(self, pb):
        """Nothing left to jump through: the caller drops '-J' entirely."""
        assert self._chain(pb, ['admin@relay'], 'relay') \
            == ([], 'admin@relay')

    @pytest.mark.parametrize('flags', [
        ['-o', 'ProxyJump=outer'],
        ['-oProxyJump=outer'],
        ['-J', 'outer'],
    ])
    def test_every_proxyjump_spelling_is_read(self, pb, flags):
        assert self._chain(pb, flags + ['admin@relay'], 'relay') \
            == (['outer'], 'admin@relay')

    def test_kiosk_pane_does_not_echo_the_command(self, app, pb):
        """The kiosk argv carries the key-isolation flags injected so the
        user cannot see or change them, down to the key's path."""
        app.kiosk_mode = True
        script = app._mux_pane_script(['ssh', '-i', '/etc/pb/key', 'host'])
        assert 'printf \'$ ' not in script
        assert '/etc/pb/key' in script, "the command itself still runs"

    def test_pane_echoes_the_command_normally(self, app, pb):
        script = app._mux_pane_script(['ssh', '-J', 'a,b', 'c'])
        assert script.startswith("printf '$ %s\\n' 'ssh -J a,b c'; ")

    @pytest.mark.parametrize('hop,target', [
        ('h:2222', 'h'),
        ('[2001:db8::1]:2222', '[2001:db8::1]'),
    ])
    def test_a_differing_port_is_a_different_endpoint(self, pb, hop, target):
        """ssh accepts '-J h:2222 h'; both port spellings must compare."""
        hops, dest = self._chain(pb, ['-J', hop, 'relay'], target)
        assert hops == [hop, 'relay'] and dest == target

    def test_same_ipv6_endpoint_collapses(self, pb):
        assert self._chain(pb, ['-J', 'outer', '[2001:db8::1]'],
                           '[2001:db8::1]') == (['outer'], '[2001:db8::1]')

    @pytest.mark.parametrize('order', ['before', 'after'])
    def test_alias_and_address_are_one_host(self, app, pb, order):
        """A ':resolv' written after the ':remote-ping' leaves the relay
        under its alias while the target is already an address; compared
        literally the two look unrelated and the loop slips through."""
        resolv = ':resolv 10.123.254.2 proxmox'
        directive = 'admin@proxmox 10.123.254.2'
        if order == 'before':
            app._dispatch_cmd(resolv)
            app._cmd_remote_ping(directive)
        else:
            app._cmd_remote_ping(directive)
            app._dispatch_cmd(resolv)
        hops, dest = app.monitors[-1].connect_chain()
        assert hops == []
        assert dest in ('admin@proxmox', 'admin@10.123.254.2')

    def test_connect_preview_for_the_relay_itself(self, app, pb):
        """End to end: 'c', 'C' and the Connect: line all read this chain."""
        app.hosts_map['proxmox'] = ('10.123.254.2', 'proxmox')
        app.hosts_map['10.123.254.2'] = ('10.123.254.2', 'proxmox')
        app._cmd_prog_options('ssh proxmox -l admin')
        app._cmd_remote_ping('-J 217.160.7.176 admin@10.123.254.2 10.123.254.2')
        m = app.monitors[-1]
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        assert app._connect_preview(m) == \
            'ssh -l admin -J 217.160.7.176 admin@10.123.254.2'

    def test_connect_preview_for_a_host_behind_the_relay(self, app, pb):
        app._cmd_remote_ping('-J 217.160.7.176 admin@10.123.254.2 10.111.1.1')
        m = app.monitors[-1]
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        assert app._connect_preview(m) == \
            'ssh -J 217.160.7.176,admin@10.123.254.2 10.111.1.1'

    def test_relay_as_own_host_with_no_hops_drops_the_option(self, app, pb):
        """With no hops left there is no '%d', so the plain 'ssh %r' binding
        takes over — a '-J' with an empty value would be rejected by ssh."""
        app._cmd_remote_ping('admin@10.123.254.2 10.123.254.2')
        m = app.monitors[-1]
        app.entries.append(m)
        app.highlighted_index = len(app.entries) - 1
        assert app._connect_preview(m) == 'ssh admin@10.123.254.2'
