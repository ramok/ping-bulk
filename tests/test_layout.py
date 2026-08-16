"""Unit tests for the :layout command (all / ping / log).

'log' exists because the host list takes the space it needs and the event log
only gets the leftover — with a long host list the log is squeezed to nothing
and there was no way to see it.
"""

import os
import pytest
from unittest.mock import patch


def _app(pb, tmp_path, config=''):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, 'w') as f:
        f.write(config)
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '127.0.0.1')])
    return app, cfg


class TestLayoutCommand:

    def test_default_is_all(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        assert app.layout == 'all'

    @pytest.mark.parametrize('mode', ['all', 'ping', 'log'])
    def test_set_each_mode(self, pb, tmp_path, mode):
        app, _ = _app(pb, tmp_path)
        app._cmd_layout(mode)
        assert app.layout == mode

    def test_case_insensitive(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        app._cmd_layout('LOG')
        assert app.layout == 'log'

    def test_no_arg_cycles_in_order(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        seen = []
        for _ in range(4):
            app._cmd_layout()
            seen.append(app.layout)
        assert seen == ['ping', 'log', 'all', 'ping']

    def test_unknown_mode_rejected_and_state_kept(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        app._cmd_layout('log')
        app._cmd_layout('bogus')
        assert app.layout == 'log'
        assert any('unknown mode' in e.text for e in app.events)

    def test_log_layout_clears_host_selection(self, pb, tmp_path):
        """With the host list hidden, arrows should scroll the log instead."""
        app, _ = _app(pb, tmp_path)
        app.highlighted_index = 0
        app._cmd_layout('log')
        assert app.highlighted_index is None

    def test_other_layouts_keep_selection(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        app.highlighted_index = 0
        app._cmd_layout('ping')
        assert app.highlighted_index == 0

    def test_l_key_is_bound_to_layout(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('l'), set())
        assert binding is not None
        assert ':layout' in binding.commands

    def test_command_is_registered_and_completable(self, pb):
        assert 'layout' in pb._CMD_MAP
        assert pb._CMD_MAP['layout'].completable is True


class TestLayoutPersistence:

    def test_default_not_written_to_config(self, pb, tmp_path):
        """'all' is the default, so it need not clutter the config."""
        app, cfg = _app(pb, tmp_path)
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        assert ':layout' not in open(cfg).read()

    @pytest.mark.parametrize('mode', ['ping', 'log'])
    def test_non_default_is_written(self, pb, tmp_path, mode):
        app, cfg = _app(pb, tmp_path)
        app._cmd_layout(mode)
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        assert f':layout {mode}' in open(cfg).read()

    def test_config_round_trip(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path, config=':layout log\n')
        assert app.layout == 'log'


class TestLayoutRendering:
    """Drives a real process — the point of 'log' is what reaches the screen."""

    HOSTS = '\n'.join(f'127.0.0.{i}' for i in range(1, 26)) + '\n'

    def _session(self, app_path, tmp_path, name, height=20):
        from tmux_helper import TmuxSession
        hosts = tmp_path / 'many.hosts'
        hosts.write_text(self.HOSTS)
        sess = TmuxSession(f'ping-bulk-test-{name}', width=120, height=height)
        sess.send_literal(f'python3 {app_path} -f {hosts}')
        sess.send_keys('Enter')
        sess.wait_for('DNS:', timeout=10)
        return sess

    def test_long_host_list_hides_the_log(self, app_path, check_integration_deps, tmp_path):
        """The situation 'log' exists to rescue: no room left for the log."""
        sess = self._session(app_path, tmp_path, 'lay-squeeze')
        try:
            assert 'Events' not in sess.capture_pane()
        finally:
            sess.kill()

    def test_log_layout_reveals_the_log(self, app_path, check_integration_deps, tmp_path):
        sess = self._session(app_path, tmp_path, 'lay-log')
        try:
            sess.send_keys(':', 'l', 'a', 'y', 'o', 'u', 't', ' ', 'l', 'o', 'g', 'Enter')
            sess.wait_for('Events')
            content = sess.capture_pane()
            # The log header must be the top row — nothing above it means the
            # host list is gone.  (Host IPs still appear inside log messages,
            # so their presence in the pane proves nothing.)
            first = next(l for l in content.splitlines() if l.strip())
            assert first.startswith('Events'), f"log not at top; got {first!r}"
            assert 'layout:log' in content, "status bar should show the mode"
        finally:
            sess.kill()

    def test_l_key_cycles_to_log(self, app_path, check_integration_deps, tmp_path):
        sess = self._session(app_path, tmp_path, 'lay-key')
        try:
            sess.send_keys('l')          # -> ping
            sess.wait_for('layout:ping')
            sess.send_keys('l')          # -> log
            sess.wait_for('layout:log')
            sess.wait_for('Events')
            sess.send_keys('l')          # -> all
            sess.wait_for_absence('layout:')
        finally:
            sess.kill()

    def test_default_layout_shows_no_indicator(self, app_path, check_integration_deps, tmp_path):
        sess = self._session(app_path, tmp_path, 'lay-default')
        try:
            assert 'layout:' not in sess.capture_pane()
        finally:
            sess.kill()
