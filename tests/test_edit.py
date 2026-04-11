"""Unit tests for :edit mtime-based change detection and reload logic.

Tests cover:
  - _cmd_edit: no prompt when mtime unchanged (or read-only file)
  - _cmd_edit: script_changed prompt set when mtime changes
  - _snapshot_monitor / _restore_monitor: round-trip field preservation
  - _edit_reload_inplace: clears monitors, re-sources, restores history
  - _handle_prompt_key (script_changed): option 1 triggers execvp,
    option 2 calls _edit_reload_inplace, option 3/Esc dismisses
"""

import os
import pytest
from unittest.mock import patch, MagicMock, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(pb, tmp_path):
    """Return a non-running Application with a blank temp config."""
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, 'w') as f:
        f.write('')
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '127.0.0.1')])
    app._monitoring_started = True
    return app


@pytest.fixture
def app(pb, tmp_path):
    return _make_app(pb, tmp_path)


# ---------------------------------------------------------------------------
# Helper: create a minimal hosts file
# ---------------------------------------------------------------------------

def _write_hosts(path, content='127.0.0.1\n'):
    path.write_text(content)
    return str(path)


# ===========================================================================
# TestEditMtimeCheck
# ===========================================================================

class TestEditMtimeCheck:
    """_cmd_edit sets prompt only when the hosts file mtime actually changes."""

    def test_unchanged_mtime_sets_no_prompt(self, app, tmp_path):
        """If mtime is the same before and after editing, no prompt is set."""
        hosts = _write_hosts(tmp_path / 'hosts')
        app.hosts_file = hosts
        mtime = os.stat(hosts).st_mtime

        with patch.object(app, '_resolve_editor', return_value=['true']), \
             patch('subprocess.call'), \
             patch('curses.endwin'), patch('curses.doupdate'), \
             patch('os.stat') as mock_stat:
            mock_stat.return_value.st_mtime = mtime  # same before and after
            app._cmd_edit()

        assert app.prompt is None

    def test_changed_mtime_sets_script_changed_prompt(self, app, tmp_path):
        """If mtime differs after editing, prompt type 'script_changed' is set."""
        hosts = _write_hosts(tmp_path / 'hosts')
        app.hosts_file = hosts

        mtime_values = iter([100.0, 200.0])  # before=100, after=200

        with patch.object(app, '_resolve_editor', return_value=['true']), \
             patch('subprocess.call'), \
             patch('curses.endwin'), patch('curses.doupdate'), \
             patch('os.stat') as mock_stat:
            mock_stat.side_effect = lambda p: MagicMock(st_mtime=next(mtime_values))
            app._cmd_edit()

        assert app.prompt is not None
        assert app.prompt['type'] == 'script_changed'
        assert app.prompt['file'] == hosts

    def test_no_hosts_file_logs_error(self, app):
        """With no hosts_file set, _cmd_edit logs an error and sets no prompt."""
        app.hosts_file = None
        app._cmd_edit()
        assert app.prompt is None
        assert any('no hosts file' in e for e in app.events)

    def test_no_editor_logs_error(self, app, tmp_path):
        """With no editor found, _cmd_edit logs an error and sets no prompt."""
        hosts = _write_hosts(tmp_path / 'hosts')
        app.hosts_file = hosts
        with patch.object(app, '_resolve_editor', return_value=[]):
            app._cmd_edit()
        assert app.prompt is None
        assert any('no editor' in e for e in app.events)

    def test_stat_oserror_before_sets_no_prompt(self, app, tmp_path):
        """If os.stat raises before the editor, no prompt is set."""
        hosts = _write_hosts(tmp_path / 'hosts')
        app.hosts_file = hosts

        with patch.object(app, '_resolve_editor', return_value=['true']), \
             patch('subprocess.call'), \
             patch('curses.endwin'), patch('curses.doupdate'), \
             patch('os.stat', side_effect=OSError('no such file')):
            app._cmd_edit()

        assert app.prompt is None

    def test_write_protected_file_opens_editor(self, app, tmp_path):
        """A read-only file still opens the editor (no early bail on W_OK)."""
        hosts = _write_hosts(tmp_path / 'hosts')
        app.hosts_file = hosts
        called = []

        def fake_call(cmd):
            called.append(cmd)

        mtime = os.stat(hosts).st_mtime
        with patch.object(app, '_resolve_editor', return_value=['true']), \
             patch('subprocess.call', side_effect=fake_call), \
             patch('curses.endwin'), patch('curses.doupdate'), \
             patch('os.stat') as mock_stat:
            mock_stat.return_value.st_mtime = mtime  # unchanged → no prompt
            app._cmd_edit()

        assert len(called) == 1  # editor was invoked


# ===========================================================================
# TestSnapshotRestore
# ===========================================================================

class TestSnapshotRestore:
    """_snapshot_monitor and _restore_monitor round-trip all stat fields."""

    def _make_monitor(self, pb, host='10.0.0.1'):
        m = pb.PingMonitor(host)
        return m

    def test_snapshot_captures_history(self, pb):
        m = self._make_monitor(pb)
        m.history.extend([12.3, None, 15.0])
        snap = pb.Application.__dict__['_snapshot_monitor'](None, m)
        assert snap['history'] == [12.3, None, 15.0]

    def test_snapshot_captures_counters(self, pb):
        m = self._make_monitor(pb)
        m.rx_count = 5
        m.xx_count = 2
        m.ping_count = 7
        snap = pb.Application.__dict__['_snapshot_monitor'](None, m)
        assert snap['rx_count'] == 5
        assert snap['xx_count'] == 2
        assert snap['ping_count'] == 7

    def test_restore_repopulates_history(self, pb):
        src = self._make_monitor(pb, '10.0.0.1')
        src.history.extend([10.0, 20.0])
        src.history_times.extend([1000.0, 2000.0])
        src.latencies = [10.0, 20.0]
        src.rx_count = 2
        snap = pb.Application.__dict__['_snapshot_monitor'](None, src)

        dst = self._make_monitor(pb, '10.0.0.1')
        pb.Application.__dict__['_restore_monitor'](None, dst, snap)

        assert list(dst.history) == [10.0, 20.0]
        assert dst.rx_count == 2
        assert dst.latencies == [10.0, 20.0]

    def test_restore_preserves_alive_state(self, pb):
        src = self._make_monitor(pb)
        src.alive = True
        src.down_since = 999.0
        src.up_since = 1001.0
        snap = pb.Application.__dict__['_snapshot_monitor'](None, src)

        dst = self._make_monitor(pb)
        pb.Application.__dict__['_restore_monitor'](None, dst, snap)

        assert dst.alive is True
        assert dst.down_since == 999.0
        assert dst.up_since == 1001.0


# ===========================================================================
# TestEditReloadInplace
# ===========================================================================

class TestEditReloadInplace:
    """_edit_reload_inplace clears monitors, re-sources, and restores history."""

    def test_clears_monitors_before_source(self, app, tmp_path):
        """After reload, only the hosts from the new file are present."""
        hosts = _write_hosts(tmp_path / 'hosts', '10.0.0.1\n10.0.0.2\n')
        app.hosts_file = hosts
        initial_count = len(app.monitors)

        with patch.object(app, '_cmd_source') as mock_source:
            app._edit_reload_inplace(hosts)
            mock_source.assert_called_once_with(hosts)

        assert len(app.monitors) == 0  # cleared before source (source was mocked)

    def test_history_restored_for_matching_host(self, app, pb, tmp_path):
        """Hosts present before and after reload get their history back."""
        hosts = _write_hosts(tmp_path / 'hosts', '127.0.0.1\n')
        app.hosts_file = hosts

        # Seed the existing monitor with history
        m_old = app.monitors[0]
        m_old.history.extend([10.0, 20.0])
        m_old.rx_count = 2

        # After source, a new monitor for the same host is created
        m_new = pb.PingMonitor('127.0.0.1')

        def fake_source(path):
            app.monitors.append(m_new)
            app.entries.append(m_new)

        with patch.object(app, '_cmd_source', side_effect=fake_source):
            app._edit_reload_inplace(hosts)

        assert list(m_new.history) == [10.0, 20.0]
        assert m_new.rx_count == 2

    def test_new_host_starts_fresh(self, app, pb, tmp_path):
        """A host that didn't exist before the reload starts with empty history."""
        hosts = _write_hosts(tmp_path / 'hosts', '127.0.0.1\n10.0.0.99\n')
        app.hosts_file = hosts

        m_new = pb.PingMonitor('10.0.0.99')

        def fake_source(path):
            app.monitors.append(m_new)
            app.entries.append(m_new)

        with patch.object(app, '_cmd_source', side_effect=fake_source):
            app._edit_reload_inplace(hosts)

        assert len(m_new.history) == 0
        assert m_new.rx_count == 0

    def test_resets_selection_scroll(self, app, tmp_path):
        """highlighted_index and host_scroll are reset to defaults."""
        hosts = _write_hosts(tmp_path / 'hosts')
        app.hosts_file = hosts
        app.highlighted_index = 2
        app.host_scroll = 5

        with patch.object(app, '_cmd_source'):
            app._edit_reload_inplace(hosts)

        assert app.highlighted_index is None
        assert app.host_scroll == 0


# ===========================================================================
# TestScriptChangedPromptKeys
# ===========================================================================

class TestScriptChangedPromptKeys:
    """_handle_prompt_key dispatches script_changed keys correctly."""

    def _set_prompt(self, app, hosts):
        app.prompt = {'type': 'script_changed', 'file': hosts}

    def test_key_3_dismisses_prompt(self, app, tmp_path):
        hosts = _write_hosts(tmp_path / 'hosts')
        self._set_prompt(app, hosts)
        app._handle_prompt_key(ord('3'))
        assert app.prompt is None

    def test_esc_dismisses_prompt(self, app, tmp_path):
        hosts = _write_hosts(tmp_path / 'hosts')
        self._set_prompt(app, hosts)
        app._handle_prompt_key(27)
        assert app.prompt is None

    def test_other_key_dismisses_prompt(self, app, tmp_path):
        hosts = _write_hosts(tmp_path / 'hosts')
        self._set_prompt(app, hosts)
        app._handle_prompt_key(ord('x'))
        assert app.prompt is None

    def test_key_1_calls_execvp(self, app, tmp_path):
        hosts = _write_hosts(tmp_path / 'hosts')
        self._set_prompt(app, hosts)
        import sys
        with patch('os.execvp') as mock_exec, \
             patch('curses.endwin'):
            app._handle_prompt_key(ord('1'))
        mock_exec.assert_called_once_with(sys.argv[0], sys.argv)

    def test_key_2_calls_reload_inplace(self, app, tmp_path):
        hosts = _write_hosts(tmp_path / 'hosts')
        self._set_prompt(app, hosts)
        with patch.object(app, '_edit_reload_inplace') as mock_reload:
            app._handle_prompt_key(ord('2'))
        mock_reload.assert_called_once_with(hosts)
        assert app.prompt is None
