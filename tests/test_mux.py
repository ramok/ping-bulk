"""Unit tests for :mux, :connect-options, _build_connect_cmd, and related features.

Covers:
  - _cmd_connect_options: add rule, disable rule ('-'), remove pattern, clear all
  - _build_connect_cmd: no rules, matching opts rule, matching disable rule,
    SshPingMonitor reuses ssh_args, kiosk mode injects isolation flags
  - _cmd_mux: kiosk whitelist (ssh/login allowed, others blocked), direction parsing,
    no-backend error, invalid direction
  - _cmd_mux_split: valid values, cycling, invalid value
  - _connect_to_highlighted: no selection, section highlighted, disabled host,
    no backend → prompt
  - _open_cmd_prefill: opens cmd mode with correct pre-fill
  - :connect-options in parse_hosts_file: emitted as ('cmd', ...) and dispatched
"""

import os
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(pb, tmp_path, entries=None):
    """Return a non-running Application with blank temp config."""
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, 'w') as f:
        f.write('')
    if entries is None:
        entries = [('host', '127.0.0.1')]
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application(entries)
    return app


def _make_app_with_rules(pb, tmp_path, rules):
    """Return app pre-loaded with connect_rules list."""
    app = _make_app(pb, tmp_path)
    app.connect_rules = list(rules)
    return app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app(pb, tmp_path):
    return _make_app(pb, tmp_path)


# ===========================================================================
# _cmd_connect_options
# ===========================================================================

class TestCmdConnectOptions:

    def test_add_rule(self, app):
        app._cmd_connect_options('*-router -l admin')
        assert app.connect_rules == [('*-router', '-l admin')]

    def test_add_disable_rule(self, app):
        """'-' as opts stores None (disabled)."""
        app._cmd_connect_options('1.1.1.1 -')
        assert app.connect_rules == [('1.1.1.1', None)]

    def test_add_multiple_rules(self, app):
        app._cmd_connect_options('*-router -l admin')
        app._cmd_connect_options('1.1.1.1 -')
        assert app.connect_rules == [('*-router', '-l admin'), ('1.1.1.1', None)]

    def test_replace_existing_pattern(self, app):
        """Adding a rule for a pattern that already exists replaces it."""
        app._cmd_connect_options('*-router -l admin')
        app._cmd_connect_options('*-router -l root')
        assert app.connect_rules == [('*-router', '-l root')]

    def test_remove_pattern(self, app):
        """Single-arg form removes that pattern's rule."""
        app._cmd_connect_options('*-router -l admin')
        app._cmd_connect_options('1.1.1.1 -')
        app._cmd_connect_options('1.1.1.1')  # remove
        assert app.connect_rules == [('*-router', '-l admin')]

    def test_clear_all(self, app):
        """No-arg form clears all rules."""
        app._cmd_connect_options('*-router -l admin')
        app._cmd_connect_options('1.1.1.1 -')
        app._cmd_connect_options('')
        assert app.connect_rules == []

    def test_clear_whitespace(self, app):
        """Whitespace-only arg also clears all rules."""
        app._cmd_connect_options('*-router -l admin')
        app._cmd_connect_options('   ')
        assert app.connect_rules == []


# ===========================================================================
# _build_connect_cmd
# ===========================================================================

class TestBuildConnectCmd:

    def test_no_rules_returns_plain_host(self, app):
        monitor = app.entries[0]  # 127.0.0.1
        disabled, cmd = app._build_connect_cmd(monitor)
        assert not disabled
        assert cmd == ['ssh', '127.0.0.1']

    def test_matching_opts_rule(self, app):
        app.connect_rules = [('127.*', '-l admin')]
        monitor = app.entries[0]
        disabled, cmd = app._build_connect_cmd(monitor)
        assert not disabled
        assert cmd == ['ssh', '127.0.0.1', '-l', 'admin']

    def test_matching_disable_rule(self, app):
        app.connect_rules = [('127.*', None)]
        monitor = app.entries[0]
        disabled, cmd = app._build_connect_cmd(monitor)
        assert disabled
        assert cmd == []

    def test_last_match_wins_enable_after_disable(self, app):
        """Enable rule after disable rule → not disabled."""
        app.connect_rules = [('127.*', None), ('127.0.0.1', '-l ops')]
        monitor = app.entries[0]
        disabled, cmd = app._build_connect_cmd(monitor)
        assert not disabled
        assert '-l' in cmd

    def test_last_match_wins_disable_after_enable(self, app):
        """Disable rule after enable rule → disabled."""
        app.connect_rules = [('127.0.0.1', '-l ops'), ('127.*', None)]
        monitor = app.entries[0]
        disabled, cmd = app._build_connect_cmd(monitor)
        assert disabled

    def test_no_match_returns_plain_host(self, app):
        app.connect_rules = [('10.*', '-l admin')]
        monitor = app.entries[0]
        disabled, cmd = app._build_connect_cmd(monitor)
        assert not disabled
        assert cmd == ['ssh', '127.0.0.1']

    def test_kiosk_mode_injects_isolation_flags(self, app):
        """_build_connect_cmd returns a clean command in kiosk mode; flags are
        injected later by _cmd_mux so the user cannot edit them."""
        app.kiosk_mode = True
        monitor = app.entries[0]
        disabled, cmd = app._build_connect_cmd(monitor)
        assert not disabled
        # No kiosk flags in the returned (user-editable) command
        assert '-F' not in cmd
        assert 'IdentityFile=none' not in cmd
        # Host still present
        assert '127.0.0.1' in cmd

    def test_kiosk_mode_with_matching_opts(self, app):
        """connect-options follow the host; kiosk flags are NOT in the prefill."""
        app.kiosk_mode = True
        app.connect_rules = [('127.*', '-l admin')]
        monitor = app.entries[0]
        disabled, cmd = app._build_connect_cmd(monitor)
        assert not disabled
        # -l admin follows the host; no kiosk isolation flags
        host_idx = cmd.index('127.0.0.1')
        l_idx = cmd.index('-l')
        assert host_idx < l_idx
        assert '-F' not in cmd


# ===========================================================================
# _cmd_mux_split
# ===========================================================================

class TestCmdMuxSplit:

    def test_set_valid_value(self, app):
        app._cmd_mux_split('h')
        assert app.mux_split == 'h'

    def test_set_window(self, app):
        app._cmd_mux_split('window')
        assert app.mux_split == 'window'

    def test_cycle_no_arg(self, app):
        app.mux_split = 'v'
        app._cmd_mux_split('')
        assert app.mux_split == 'h'
        app._cmd_mux_split('')
        assert app.mux_split == 'window'
        app._cmd_mux_split('')
        assert app.mux_split == 'v'

    def test_invalid_value_ignored(self, app):
        app.mux_split = 'v'
        app._cmd_mux_split('diagonal')
        assert app.mux_split == 'v'


# ===========================================================================
# _cmd_mux — kiosk whitelist
# ===========================================================================

class TestCmdMuxKiosk:

    def _app_in_backend(self, pb, tmp_path):
        """App with a mock TmuxBackend that is 'inside' tmux."""
        app = _make_app(pb, tmp_path)
        app.kiosk_mode = True
        # Inject a mock backend into the module-level dict
        mock_backend = MagicMock()
        mock_backend.is_inside.return_value = True
        mock_backend.available.return_value = True
        return app, mock_backend

    def test_ssh_allowed_in_kiosk(self, pb, tmp_path):
        app, mock_backend = self._app_in_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('ssh 10.0.0.1')
        mock_backend.split.assert_called_once()

    def test_login_allowed_in_kiosk(self, pb, tmp_path):
        app, mock_backend = self._app_in_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('login')
        mock_backend.split.assert_called_once()

    def test_bash_blocked_in_kiosk(self, pb, tmp_path):
        app, mock_backend = self._app_in_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('bash')
        mock_backend.split.assert_not_called()

    def test_arbitrary_cmd_blocked_in_kiosk(self, pb, tmp_path):
        app, mock_backend = self._app_in_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('htop')
        mock_backend.split.assert_not_called()

    def test_ssh_not_blocked_outside_kiosk(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app.kiosk_mode = False
        mock_backend = MagicMock()
        mock_backend.is_inside.return_value = True
        mock_backend.available.return_value = True
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('bash')
        mock_backend.split.assert_called_once()


# ===========================================================================
# _cmd_mux — direction flags and no-backend error
# ===========================================================================

class TestCmdMuxDirection:

    def _app_with_mock_backend(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        mock_backend = MagicMock()
        mock_backend.is_inside.return_value = True
        mock_backend.available.return_value = True
        return app, mock_backend

    @staticmethod
    def _held(tokens):
        """Return the ['sh', '-c', ...] wrapper that _cmd_mux builds."""
        import shlex
        script = (
            shlex.join(tokens)
            + '; _rc=$?;'
              ' if [ "$_rc" -ne 0 ]; then'
              ' printf "\\n[process exited (code %s) — press Enter to close]\\n" "$_rc";'
              ' read _ignored; fi'
        )
        return ['sh', '-c', script]

    def test_default_split_direction(self, pb, tmp_path):
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('ssh host')
        mock_backend.split.assert_called_once_with('v', self._held(['ssh', 'host']))

    def test_explicit_v_flag(self, pb, tmp_path):
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('-v ssh host')
        mock_backend.split.assert_called_once_with('v', self._held(['ssh', 'host']))

    def test_explicit_h_flag(self, pb, tmp_path):
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('-h ssh host')
        mock_backend.split.assert_called_once_with('h', self._held(['ssh', 'host']))

    def test_window_flag(self, pb, tmp_path):
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('-w ssh host')
        mock_backend.new_window.assert_called_once_with(self._held(['ssh', 'host']))
        mock_backend.split.assert_not_called()

    def test_mux_split_setting_used(self, pb, tmp_path):
        """The :set mux-split value is used as default direction."""
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        app.mux_split = 'h'
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('ssh host')
        mock_backend.split.assert_called_once_with('h', self._held(['ssh', 'host']))

    def test_no_backend_logs_error(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        mock_none = MagicMock()
        mock_none.is_inside.return_value = False
        mock_none.available.return_value = False
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_none, 'screen': mock_none,
                                            'terminal': mock_none}):
            before = len(app.events)
            app._cmd_mux('ssh host')
        assert len(app.events) > before

    def test_empty_command_no_mux_opens_relaunch_prompt(self, pb, tmp_path):
        """No-command :mux when not inside any mux → relaunch prompt."""
        app = _make_app(pb, tmp_path)
        mock_none = MagicMock()
        mock_none.is_inside.return_value = False
        mock_none.available.return_value = False
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_none, 'screen': mock_none,
                                            'terminal': mock_none}):
            app._cmd_mux('')
        assert app.prompt is not None
        assert app.prompt['type'] == 'mux_relaunch'


# ===========================================================================
# _open_cmd_prefill
# ===========================================================================

class TestOpenCmdPrefill:

    def test_text_is_set(self, app):
        app._open_cmd_prefill('mux ssh 10.0.0.1')
        assert ''.join(app.cmd['chars']) == 'mux ssh 10.0.0.1'

    def test_cursor_at_end(self, app):
        app._open_cmd_prefill('mux ssh 10.0.0.1')
        assert app.cmd['cursor'] == len('mux ssh 10.0.0.1')

    def test_empty_prefill(self, app):
        app._open_cmd_prefill('')
        assert app.cmd['chars'] == []
        assert app.cmd['cursor'] == 0


# ===========================================================================
# _connect_to_highlighted
# ===========================================================================

class TestConnectToHighlighted:

    def test_no_selection_logs_message(self, app):
        app.highlighted_index = None
        before = len(app.events)
        app._connect_to_highlighted()
        assert len(app.events) > before

    def test_section_highlighted_logs_message(self, pb, tmp_path):
        """Highlighting a section header should not open cmd mode."""
        app = _make_app(pb, tmp_path, entries=[
            ('section', 'Group', 1, False),
            ('host', '10.0.0.1'),
        ])
        app.highlighted_index = 0  # SectionLabel
        before = len(app.events)
        app._connect_to_highlighted()
        assert len(app.events) > before
        assert app.cmd is None

    def test_disabled_host_logs_message(self, pb, tmp_path):
        """Connect-disabled host should flash a message, not open cmd mode."""
        app = _make_app(pb, tmp_path, entries=[('host', '1.1.1.1')])
        app.connect_rules = [('1.1.1.1', None)]
        app.highlighted_index = 0
        before = len(app.events)
        app._connect_to_highlighted()
        assert len(app.events) > before
        assert app.cmd is None

    def test_no_backend_opens_prompt(self, pb, tmp_path):
        """When not in a multiplexer, a mux_relaunch prompt is opened."""
        app = _make_app(pb, tmp_path)
        app.highlighted_index = 0
        mock_none = MagicMock()
        mock_none.is_inside.return_value = False
        mock_none.available.return_value = False
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_none, 'screen': mock_none,
                                            'terminal': mock_none}):
            app._connect_to_highlighted()
        assert app.prompt is not None
        assert app.prompt['type'] == 'mux_relaunch'

    def test_connected_host_opens_cmd_prefill(self, pb, tmp_path):
        """When backend is available, cmd mode opens with ssh prefill."""
        app = _make_app(pb, tmp_path)
        app.highlighted_index = 0
        mock_backend = MagicMock()
        mock_backend.is_inside.return_value = True
        mock_backend.available.return_value = True
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._connect_to_highlighted()
        assert app.cmd is not None
        prefill = ''.join(app.cmd['chars'])
        assert prefill.startswith('mux ssh')
        assert '127.0.0.1' in prefill

    def test_connect_options_opts_in_prefill(self, pb, tmp_path):
        """connect-options SSH flags appear in the pre-filled command."""
        app = _make_app(pb, tmp_path)
        app.connect_rules = [('127.*', '-l admin')]
        app.highlighted_index = 0
        mock_backend = MagicMock()
        mock_backend.is_inside.return_value = True
        mock_backend.available.return_value = True
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._connect_to_highlighted()
        prefill = ''.join(app.cmd['chars'])
        assert '-l' in prefill
        assert 'admin' in prefill


# ===========================================================================
# :connect-options in parse_hosts_file → dispatched at init
# ===========================================================================

class TestConnectOptionsInHostsFile:

    def test_parsed_and_applied(self, pb, tmp_path):
        """':connect-options' in hosts file is dispatched at Application init."""
        hosts_file = tmp_path / 'hosts.txt'
        hosts_file.write_text(
            ':connect-options *-router -l admin\n'
            ':connect-options 1.1.1.1 -\n'
            '127.0.0.1\n'
        )
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        with patch.object(pb, '_config_path', return_value=cfg):
            entries = pb.parse_hosts_file(str(hosts_file))
            app = pb.Application(entries)
        assert ('*-router', '-l admin') in app.connect_rules
        assert ('1.1.1.1', None) in app.connect_rules


# ===========================================================================
# _session_name_from_hosts_file
# ===========================================================================

class TestSessionNameFromHostsFile:

    def test_simple_name(self, pb):
        assert pb._session_name_from_hosts_file('hosts') == 'hosts'

    def test_dashes_replaced(self, pb):
        assert pb._session_name_from_hosts_file('ping-bulk.evo-lan') == 'ping_bulk_evo_lan'

    def test_dots_replaced(self, pb):
        assert pb._session_name_from_hosts_file('hosts.txt') == 'hosts_txt'

    def test_with_directory_prefix(self, pb):
        assert pb._session_name_from_hosts_file('/etc/ping-bulk/office.lan') == 'office_lan'

    def test_none_falls_back(self, pb):
        assert pb._session_name_from_hosts_file(None) == 'ping_bulk'

    def test_empty_string_falls_back(self, pb):
        assert pb._session_name_from_hosts_file('') == 'ping_bulk'


# ===========================================================================
# TmuxBackend.relaunch_cmd / ScreenBackend.relaunch_cmd
# ===========================================================================

class TestRelaunchCmd:

    def test_tmux_session_name_from_hosts_file(self, pb):
        backend = pb.TmuxBackend()
        cmd = backend.relaunch_cmd(['./ping-bulk', '-f', 'sensor-station'],
                                   hosts_file='sensor-station')
        # session name is the 4th token after 'new -As <name>'
        new_idx = cmd.index('new')
        assert cmd[new_idx + 1] == '-As'
        assert cmd[new_idx + 2] == 'sensor_station'

    def test_tmux_session_name_with_dashes_and_dots(self, pb):
        backend = pb.TmuxBackend()
        cmd = backend.relaunch_cmd(['./ping-bulk', '-f', 'ping-bulk.evo-lan'],
                                   hosts_file='ping-bulk.evo-lan')
        new_idx = cmd.index('new')
        assert cmd[new_idx + 2] == 'ping_bulk_evo_lan'

    def test_tmux_session_name_fallback_when_no_hosts_file(self, pb):
        backend = pb.TmuxBackend()
        cmd = backend.relaunch_cmd(['./ping-bulk', '8.8.8.8'])
        new_idx = cmd.index('new')
        assert cmd[new_idx + 2] == 'ping_bulk'

    def test_screen_session_name_from_hosts_file(self, pb):
        backend = pb.ScreenBackend()
        cmd = backend.relaunch_cmd(['./ping-bulk', '-f', 'my-hosts.txt'],
                                   hosts_file='my-hosts.txt')
        s_idx = cmd.index('-S')
        assert cmd[s_idx + 1] == 'my_hosts_txt'

    def test_screen_session_name_fallback(self, pb):
        backend = pb.ScreenBackend()
        cmd = backend.relaunch_cmd(['./ping-bulk', '8.8.8.8'])
        s_idx = cmd.index('-S')
        assert cmd[s_idx + 1] == 'ping_bulk'


# ===========================================================================
# _cmd_mux — no command (self-relaunch)
# ===========================================================================

class TestCmdMuxNoCommand:

    def _mock_in_mux(self):
        mock = MagicMock()
        mock.is_inside.return_value = True
        mock.available.return_value = True
        return mock

    def _mock_not_in_mux(self):
        mock = MagicMock()
        mock.is_inside.return_value = False
        mock.available.return_value = False
        return mock

    def test_no_command_not_in_mux_sets_relaunch_prompt(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        none_backend = self._mock_not_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': none_backend, 'screen': none_backend,
                                            'terminal': none_backend}):
            app._cmd_mux('')
        assert app.prompt is not None
        assert app.prompt['type'] == 'mux_relaunch'
        # No pending_cmd: the relaunch IS the goal, no follow-up command
        assert not app.prompt.get('pending_cmd')

    def test_no_command_in_mux_opens_split_with_argv(self, pb, tmp_path):
        import sys
        app = _make_app(pb, tmp_path)
        mock_backend = self._mock_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            with patch.object(sys, 'argv', ['./ping-bulk', '-f', 'hosts.txt']):
                app._cmd_mux('')
        mock_backend.split.assert_called_once()
        # _cmd_mux wraps tokens in ['sh', '-c', '<script>']
        shell_script = mock_backend.split.call_args[0][1][2]
        assert './ping-bulk' in shell_script
        assert '-f' in shell_script
        assert 'hosts.txt' in shell_script

    def test_no_command_in_mux_adds_select_for_highlighted_host(self, pb, tmp_path):
        import sys
        app = _make_app(pb, tmp_path)
        app.highlighted_index = 0   # 127.0.0.1
        mock_backend = self._mock_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            with patch.object(sys, 'argv', ['./ping-bulk', '-f', 'hosts.txt']):
                app._cmd_mux('')
        shell_script = mock_backend.split.call_args[0][1][2]
        assert '--select' in shell_script
        assert '127.0.0.1' in shell_script

    def test_no_command_in_mux_no_select_when_no_highlight(self, pb, tmp_path):
        import sys
        app = _make_app(pb, tmp_path)
        app.highlighted_index = None
        mock_backend = self._mock_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            with patch.object(sys, 'argv', ['./ping-bulk', '-f', 'hosts.txt']):
                app._cmd_mux('')
        shell_script = mock_backend.split.call_args[0][1][2]
        assert '--select' not in shell_script

    def test_no_command_with_direction_flag_in_mux(self, pb, tmp_path):
        import sys
        app = _make_app(pb, tmp_path)
        mock_backend = self._mock_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            with patch.object(sys, 'argv', ['./ping-bulk', '-f', 'hosts.txt']):
                app._cmd_mux('-h')
        mock_backend.split.assert_called_once()
        direction = mock_backend.split.call_args[0][0]
        assert direction == 'h'
