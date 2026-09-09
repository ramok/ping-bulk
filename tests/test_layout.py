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

    def test_ctrl_l_is_bound_to_cycle(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('<C-l>'), set())
        assert binding is not None
        assert binding.commands == [':layout']

    def test_command_is_registered_and_completable(self, pb):
        assert 'layout' in pb._CMD_MAP
        assert pb._CMD_MAP['layout'].completable is True


class TestLayoutToggle:
    """`L` is a there-and-back peek at the log, not another cycle step."""

    def test_toggle_enters_log_from_all(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        app._cmd_layout('--toggle log')
        assert app.layout == 'log'

    def test_toggle_returns_to_all(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        app._cmd_layout('--toggle log')
        app._cmd_layout('--toggle log')
        assert app.layout == 'all'

    def test_toggle_returns_to_ping_not_all(self, pb, tmp_path):
        """It returns where you came from, not blindly to the default."""
        app, _ = _app(pb, tmp_path)
        app._cmd_layout('ping')
        app._cmd_layout('--toggle log')
        assert app.layout == 'log'
        app._cmd_layout('--toggle log')
        assert app.layout == 'ping'

    def test_toggle_defaults_to_log(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        app._cmd_layout('--toggle')
        assert app.layout == 'log'

    def test_toggle_works_for_any_mode(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        app._cmd_layout('--toggle ping')
        assert app.layout == 'ping'
        app._cmd_layout('--toggle ping')
        assert app.layout == 'all'

    def test_toggle_from_log_when_prev_is_also_log(self, pb, tmp_path):
        """Degenerate case must not strand the user on the same layout."""
        app, _ = _app(pb, tmp_path)
        app._cmd_layout('log')
        app._layout_prev = 'log'
        app._cmd_layout('--toggle log')
        assert app.layout == 'all'

    def test_toggle_rejects_unknown_mode(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        app._cmd_layout('--toggle bogus')
        assert app.layout == 'all'
        assert any('unknown mode' in e.text for e in app.events)

    def test_cycling_updates_the_return_target(self, pb, tmp_path):
        """After cycling, toggle must come back to the cycled-to layout."""
        app, _ = _app(pb, tmp_path)
        app._cmd_layout()                 # all -> ping
        assert app.layout == 'ping'
        app._cmd_layout('--toggle log')   # ping -> log
        app._cmd_layout('--toggle log')   # log -> ping
        assert app.layout == 'ping'

    def test_toggle_into_log_clears_selection(self, pb, tmp_path):
        app, _ = _app(pb, tmp_path)
        app.highlighted_index = 0
        app._cmd_layout('--toggle log')
        assert app.highlighted_index is None

    def test_l_is_bound_to_toggle(self, pb, tmp_path):
        """The plain key is the common action: peek at the log and back."""
        app, _ = _app(pb, tmp_path)
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('l'), set())
        assert binding is not None
        assert binding.commands == [':layout --toggle log']

    def test_capital_l_is_not_bound(self, pb, tmp_path):
        """L was the toggle before the swap; it must not linger."""
        app, _ = _app(pb, tmp_path)
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('L'), set())
        assert binding is None


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

    def test_l_key_toggles_log_and_back(self, app_path, check_integration_deps, tmp_path):
        sess = self._session(app_path, tmp_path, 'lay-key')
        try:
            sess.send_keys('l')          # -> log
            sess.wait_for('layout:log')
            sess.wait_for('Events')
            sess.send_keys('l')          # -> back to all
            sess.wait_for_absence('layout:')
        finally:
            sess.kill()

    def test_ctrl_l_cycles(self, app_path, check_integration_deps, tmp_path):
        sess = self._session(app_path, tmp_path, 'lay-cycle')
        try:
            sess.send_keys('C-l')        # -> ping
            sess.wait_for('layout:ping')
            sess.send_keys('C-l')        # -> log
            sess.wait_for('layout:log')
            sess.send_keys('C-l')        # -> all
            sess.wait_for_absence('layout:')
        finally:
            sess.kill()

    def test_events_header_shows_the_layout_hint(self, app_path, check_integration_deps, tmp_path):
        """The [l] label must say what the key will do from here."""
        sess = self._session(app_path, tmp_path, 'lay-hint')
        try:
            sess.send_keys('l')          # -> log, header visible
            sess.wait_for('Events')
            assert 'l back' in sess.capture_pane(), "log layout should offer 'back'"
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


class TestFoldedListReleasesItsRows:
    """Folding shortens the list, so the log must move up into the space.

    The host area used to be sized from the entry *count*, which folding does
    not change: a fully folded list left a screenful of blank rows between two
    section headers and the log — and on a short window pushed the log off the
    screen entirely, where 'l' was the only way to see any events at all.
    """

    HOSTS = ('## Group A\n' + '\n'.join(f'127.0.0.{i}' for i in range(1, 11))
             + '\n## Group B\n'
             + '\n'.join(f'127.0.0.{i}' for i in range(11, 21)) + '\n')

    def _session(self, app_path, tmp_path, name, height):
        from tmux_helper import TmuxSession
        hosts = tmp_path / 'folding.hosts'
        hosts.write_text(self.HOSTS)
        sess = TmuxSession(f'ping-bulk-test-{name}', width=120, height=height)
        sess.send_literal(f'python3 {app_path} -f {hosts}')
        sess.send_keys('Enter')
        sess.wait_for('DNS:', timeout=10)
        return sess

    @staticmethod
    def _row_of(screen, needle):
        for i, line in enumerate(screen.splitlines()):
            if line.startswith(needle):
                return i
        return None

    def test_log_follows_the_list_up(self, app_path, check_integration_deps, tmp_path):
        sess = self._session(app_path, tmp_path, 'fold-up', height=40)
        try:
            sess.wait_for('Events')
            before = self._row_of(sess.capture_pane(), 'Events')
            sess.send_keys('[')                     # :fold close-all
            sess.wait_for('[+] Group B')
            after = self._row_of(sess.capture_pane(), 'Events')
            assert after is not None
            assert after < before, f"log stayed at row {after} (was {before})"
            # header(1) + two section rows + one blank separator, and no
            # mode banner: each of those takes a host row, so a selection
            # (--select, say) would move this without anything being wrong.
            assert after == 4, f"expected the log right below the list, got {after}"
        finally:
            sess.kill()

    def test_no_blank_gap_is_left_behind(self, app_path, check_integration_deps, tmp_path):
        sess = self._session(app_path, tmp_path, 'fold-gap', height=40)
        try:
            sess.send_keys('[')
            sess.wait_for('[+] Group B')
            lines = sess.capture_pane().splitlines()
            events = self._row_of('\n'.join(lines), 'Events')
            blanks = [i for i in range(events) if not lines[i].strip()]
            assert len(blanks) == 1, f"blank rows above the log: {blanks}"
        finally:
            sess.kill()

    def test_a_short_window_gains_the_log_when_folded(self, app_path,
                                                      check_integration_deps, tmp_path):
        """The case that read as broken: 22 rows of list in a 14-row window."""
        sess = self._session(app_path, tmp_path, 'fold-short', height=14)
        try:
            assert 'Events' not in sess.capture_pane(), \
                'precondition: the unfolded list fills the window'
            sess.send_keys('[')
            sess.wait_for('Events')
        finally:
            sess.kill()

    def test_unfolding_gives_the_rows_back(self, app_path, check_integration_deps, tmp_path):
        sess = self._session(app_path, tmp_path, 'fold-back', height=40)
        try:
            sess.wait_for('Events')
            before = self._row_of(sess.capture_pane(), 'Events')
            sess.send_keys('[')
            sess.wait_for('[+] Group B')
            sess.send_keys(']')                     # :fold open-all
            sess.wait_for('[-] Group B')
            assert self._row_of(sess.capture_pane(), 'Events') == before
        finally:
            sess.kill()
