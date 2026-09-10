"""Unit tests for :mux and related features.

Covers:
  - _cmd_mux: kiosk whitelist (ssh/login allowed, others blocked), direction parsing,
    no-backend error, invalid direction
  - _cmd_mux_split: valid values, cycling, invalid value
  - _open_cmd_prefill: opens cmd mode with correct pre-fill
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app(pb, tmp_path):
    return _make_app(pb, tmp_path)


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
        cmd = shlex.join(tokens)
        # Mirrors Application._mux_pane_script: the pane shows the command
        # it runs as its first line, then holds if the command failed.
        script = (
            "printf '$ %s\\n' " + shlex.quote(cmd) + '; ' + cmd
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
        mock_backend.split.assert_called_once_with('v', self._held(['ssh', 'host']), focus=True)

    def test_explicit_v_flag(self, pb, tmp_path):
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('-v ssh host')
        mock_backend.split.assert_called_once_with('v', self._held(['ssh', 'host']), focus=True)

    def test_explicit_h_flag(self, pb, tmp_path):
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('-h ssh host')
        mock_backend.split.assert_called_once_with('h', self._held(['ssh', 'host']), focus=True)

    def test_window_flag(self, pb, tmp_path):
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('-w ssh host')
        mock_backend.new_window.assert_called_once_with(self._held(['ssh', 'host']), focus=True)
        mock_backend.split.assert_not_called()

    def test_mux_split_setting_used(self, pb, tmp_path):
        """The :set mux-split value is used as default direction."""
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        app.mux_split = 'h'
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('ssh host')
        mock_backend.split.assert_called_once_with('h', self._held(['ssh', 'host']), focus=True)

    def test_no_focus_split(self, pb, tmp_path):
        """--no-focus passes focus=False to backend.split."""
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('--no-focus ssh host')
        mock_backend.split.assert_called_once_with(
            'v', self._held(['ssh', 'host']), focus=False
        )

    def test_no_focus_window(self, pb, tmp_path):
        """--no-focus with -w passes focus=False to backend.new_window."""
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('-w --no-focus ssh host')
        mock_backend.new_window.assert_called_once_with(
            self._held(['ssh', 'host']), focus=False
        )
        mock_backend.split.assert_not_called()

    def test_no_focus_with_direction(self, pb, tmp_path):
        """--no-focus combined with -h direction."""
        app, mock_backend = self._app_with_mock_backend(pb, tmp_path)
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            app._cmd_mux('-h --no-focus mtr host')
        mock_backend.split.assert_called_once_with(
            'h', self._held(['mtr', 'host']), focus=False
        )

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
        assert app.prompt is not None
        assert app.prompt['type'] == 'mux_new_pane'
        # The argv should be captured in the prompt
        assert app.prompt['tokens'] == ['./ping-bulk', '-f', 'hosts.txt']

    def test_no_command_in_mux_adds_select_for_highlighted_host(self, pb, tmp_path):
        import sys
        app = _make_app(pb, tmp_path)
        app.highlighted_index = 0   # 127.0.0.1
        mock_backend = self._mock_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            with patch.object(sys, 'argv', ['./ping-bulk', '-f', 'hosts.txt']):
                app._cmd_mux('')
        assert app.prompt['type'] == 'mux_new_pane'
        assert '--select' in app.prompt['tokens']
        assert '127.0.0.1' in app.prompt['tokens']

    def test_no_command_in_mux_no_select_when_no_highlight(self, pb, tmp_path):
        import sys
        app = _make_app(pb, tmp_path)
        app.highlighted_index = None
        mock_backend = self._mock_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            with patch.object(sys, 'argv', ['./ping-bulk', '-f', 'hosts.txt']):
                app._cmd_mux('')
        assert '--select' not in app.prompt['tokens']

    def test_no_command_with_direction_flag_in_mux(self, pb, tmp_path):
        import sys
        app = _make_app(pb, tmp_path)
        mock_backend = self._mock_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            with patch.object(sys, 'argv', ['./ping-bulk', '-f', 'hosts.txt']):
                app._cmd_mux('-h')
        assert app.prompt['type'] == 'mux_new_pane'
        assert app.prompt['direction'] == 'h'

    def test_mux_new_pane_confirm_opens_split(self, pb, tmp_path):
        """Pressing Y/Enter in mux_new_pane prompt opens the split."""
        import sys
        app = _make_app(pb, tmp_path)
        mock_backend = self._mock_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            with patch.object(sys, 'argv', ['./ping-bulk', '-f', 'hosts.txt']):
                app._cmd_mux('')
        assert app.prompt['type'] == 'mux_new_pane'
        # Confirm with Enter
        app._handle_prompt_key(ord('\n'))
        assert app.prompt is None
        mock_backend.split.assert_called_once()
        shell_script = mock_backend.split.call_args[0][1][2]
        assert './ping-bulk' in shell_script

    def test_mux_new_pane_cancel_with_n(self, pb, tmp_path):
        """Pressing N in mux_new_pane prompt cancels without opening a pane."""
        import sys
        app = _make_app(pb, tmp_path)
        mock_backend = self._mock_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            with patch.object(sys, 'argv', ['./ping-bulk', '-f', 'hosts.txt']):
                app._cmd_mux('')
        app._handle_prompt_key(ord('n'))
        assert app.prompt is None
        mock_backend.split.assert_not_called()

    def test_mux_new_pane_cancel_with_esc(self, pb, tmp_path):
        """Pressing Esc in mux_new_pane prompt cancels without opening a pane."""
        import sys
        app = _make_app(pb, tmp_path)
        mock_backend = self._mock_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            with patch.object(sys, 'argv', ['./ping-bulk', '-f', 'hosts.txt']):
                app._cmd_mux('')
        app._handle_prompt_key(27)
        assert app.prompt is None
        mock_backend.split.assert_not_called()

    def test_mux_new_pane_kiosk_blocked(self, pb, tmp_path):
        """In kiosk mode, :mux without args is blocked (no prompt shown)."""
        import sys
        app = _make_app(pb, tmp_path)
        app.kiosk_mode = True
        mock_backend = self._mock_in_mux()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mock_backend}):
            with patch.object(sys, 'argv', ['./ping-bulk', '-f', 'hosts.txt']):
                app._cmd_mux('')
        assert app.prompt is None
        mock_backend.split.assert_not_called()


class TestNoFocusRelaunch:
    """--no-focus flag is preserved through the relaunch prompt."""

    def _mock_not_in_mux(self):
        m = MagicMock()
        m.is_inside.return_value = False
        m.available.return_value = True
        return m

    def test_no_focus_preserved_in_relaunch_pending_cmd(self, pb, tmp_path):
        """When not inside tmux, --no-focus must be kept in pending_cmd."""
        app = _make_app(pb, tmp_path)
        mux_backend = self._mock_not_in_mux()
        term_backend = MagicMock()   # separate object so 'backend is not terminal' works
        term_backend.is_inside.return_value = False
        term_backend.available.return_value = False
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mux_backend, 'screen': mux_backend,
                                            'terminal': term_backend}):
            app._cmd_mux('--no-focus mtr host')
        assert app.prompt is not None
        assert app.prompt['type'] == 'mux_relaunch'
        assert '--no-focus' in app.prompt['pending_cmd'], (
            f"--no-focus not in pending_cmd: {app.prompt['pending_cmd']!r}"
        )

    def test_direction_preserved_in_relaunch_pending_cmd(self, pb, tmp_path):
        """Explicit -h direction is re-injected into pending_cmd after relaunch."""
        app = _make_app(pb, tmp_path)
        mux_backend = self._mock_not_in_mux()
        term_backend = MagicMock()
        term_backend.is_inside.return_value = False
        term_backend.available.return_value = False
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mux_backend, 'screen': mux_backend,
                                            'terminal': term_backend}):
            app._cmd_mux('-h ssh host')
        assert app.prompt is not None
        assert '--split-h' in app.prompt['pending_cmd'], (
            f"--split-h not in pending_cmd: {app.prompt['pending_cmd']!r}"
        )

    def test_no_focus_and_direction_combined(self, pb, tmp_path):
        """-h --no-focus: both flags preserved in pending_cmd."""
        app = _make_app(pb, tmp_path)
        mux_backend = self._mock_not_in_mux()
        term_backend = MagicMock()
        term_backend.is_inside.return_value = False
        term_backend.available.return_value = False
        with patch.dict(pb._MUX_BACKENDS, {'tmux': mux_backend, 'screen': mux_backend,
                                            'terminal': term_backend}):
            app._cmd_mux('-h --no-focus mtr host')
        assert app.prompt is not None
        cmd = app.prompt['pending_cmd']
        assert '--split-h' in cmd, f"--split-h missing: {cmd!r}"
        assert '--no-focus' in cmd, f"--no-focus missing: {cmd!r}"


# ===========================================================================
# :mux --only
# ===========================================================================

class TestMuxOnly:
    """--only kills all other panes (tmux) or warns (screen/xterm)."""

    def _inside_backend(self):
        m = MagicMock()
        m.is_inside.return_value = True
        m.available.return_value = True
        return m

    def _outside_backend(self):
        m = MagicMock()
        m.is_inside.return_value = False
        m.available.return_value = True
        return m

    def test_only_calls_kill_others_on_tmux(self, pb, tmp_path):
        """--only calls kill_others() on the active tmux backend."""
        app = _make_app(pb, tmp_path)
        backend = self._inside_backend()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': backend, 'screen': backend,
                                            'terminal': MagicMock()}):
            app._cmd_mux('--only')
        backend.kill_others.assert_called_once()

    def test_only_not_in_mux_warns(self, pb, tmp_path):
        """--only outside a multiplexer session emits a warning event."""
        app = _make_app(pb, tmp_path)
        backend = self._outside_backend()
        with patch.dict(pb._MUX_BACKENDS, {'tmux': backend, 'screen': backend,
                                            'terminal': MagicMock()}):
            app._cmd_mux('--only')
        backend.kill_others.assert_not_called()
        assert any('--only' in e.text for e in app.events)

    def test_only_screen_emits_warning(self, pb, tmp_path):
        """kill_others() on ScreenBackend raises RuntimeError → shown as event."""
        app = _make_app(pb, tmp_path)
        backend = self._inside_backend()
        backend.kill_others.side_effect = RuntimeError(
            "screen: --only is not supported")
        with patch.dict(pb._MUX_BACKENDS, {'tmux': backend, 'screen': backend,
                                            'terminal': MagicMock()}):
            app._cmd_mux('--only')
        assert any('--only is not supported' in e.text for e in app.events)
