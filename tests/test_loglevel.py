"""Unit tests for the log level system.

Covers:
  - EventEntry: level, category, text fields; string-delegation behaviour
  - _CATEGORY_LEVELS: category → level inference in add_event
  - add_event: explicit level= override
  - draw_events: display-time filtering by self.loglevel
  - _event_color_attr: colour selection per level/category
  - _cmd_loglevel: :set log-level command
  - -v / -q CLI flag level offset (via _parse_args-style test)
  - _save_config / config round-trip for log-level
"""

import os
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_app(pb, tmp_path, config=''):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, 'w') as f:
        f.write(config)
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '127.0.0.1')])
    return app, cfg


# ===========================================================================
# EventEntry
# ===========================================================================

class TestEventEntry:

    def test_fields(self, pb):
        e = pb.EventEntry(pb.LEVEL_INFO, 'cmd', 'timestamp   cmd   hello')
        assert e.level    == pb.LEVEL_INFO
        assert e.category == 'cmd'
        assert e.text     == 'timestamp   cmd   hello'

    def test_contains_delegates_to_text(self, pb):
        e = pb.EventEntry(pb.LEVEL_NORMAL, 'host', 'ts   myhost   host down')
        assert 'host down' in e
        assert 'xyz' not in e

    def test_lower_delegates_to_text(self, pb):
        e = pb.EventEntry(pb.LEVEL_NORMAL, 'cmd', 'ts   CMD   ERROR')
        assert 'error' in e.lower()

    def test_startswith_delegates_to_text(self, pb):
        e = pb.EventEntry(pb.LEVEL_INFO, 'cmd', '2026-')
        assert e.startswith('2026-')

    def test_eq_string(self, pb):
        e = pb.EventEntry(pb.LEVEL_QUIET, 'host', 'exact text')
        assert e == 'exact text'
        assert e != 'other text'

    def test_in_list_with_str(self, pb):
        e = pb.EventEntry(pb.LEVEL_QUIET, 'host', 'needle text')
        lst = [e]
        assert 'needle text' in lst   # uses e.__eq__(str)

    def test_str_returns_text(self, pb):
        e = pb.EventEntry(pb.LEVEL_DEBUG, 'bind-key', 'the text')
        assert str(e) == 'the text'


# ===========================================================================
# Level constants
# ===========================================================================

class TestLevelConstants:

    def test_levels_ordered(self, pb):
        assert pb.LEVEL_QUIET < pb.LEVEL_NORMAL < pb.LEVEL_INFO < pb.LEVEL_DEBUG

    def test_quiet_is_zero(self, pb):
        assert pb.LEVEL_QUIET == 0

    def test_debug_is_three(self, pb):
        assert pb.LEVEL_DEBUG == 3


# ===========================================================================
# Category level inference
# ===========================================================================

class TestCategoryLevels:

    def test_host_event_is_quiet(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.add_event('10.0.0.1', 'host down')
        e = list(app.events)[-1]
        assert e.level == pb.LEVEL_QUIET

    def test_cmd_event_is_info(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.add_event('cmd', 'fold: missing action argument')
        e = list(app.events)[-1]
        assert e.level == pb.LEVEL_INFO

    def test_bind_key_event_is_debug(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.add_event('bind-key', 't → :mux mtr %i')
        e = list(app.events)[-1]
        assert e.level == pb.LEVEL_DEBUG

    def test_warn_event_is_normal(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.add_event('warn', 'something wrong')
        e = list(app.events)[-1]
        assert e.level == pb.LEVEL_NORMAL

    def test_resolv_event_is_normal(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.add_event('resolv', 'no monitor matched')
        e = list(app.events)[-1]
        assert e.level == pb.LEVEL_NORMAL

    def test_explicit_level_overrides(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.add_event('cmd', 'some msg', level=pb.LEVEL_DEBUG)
        e = list(app.events)[-1]
        assert e.level == pb.LEVEL_DEBUG

    def test_host_error_is_normal(self, pb, tmp_path):
        """Monitor process errors use explicit level=LEVEL_NORMAL."""
        app, _ = _make_app(pb, tmp_path)
        app.add_event('10.0.0.1', 'error: unreachable', level=pb.LEVEL_NORMAL)
        e = list(app.events)[-1]
        assert e.level == pb.LEVEL_NORMAL

    def test_seen_marker_is_quiet(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.mark_seen()
        e = list(app.events)[-1]
        assert e.level == pb.LEVEL_QUIET
        assert e.category == 'seen'

    def test_seen_marker_reaches_filtered_list(self, pb, tmp_path):
        """mark_seen must sync the cached filtered list, or it never renders.

        draw_events reads _get_filtered_events(); appending only to
        self.events left the marker invisible at every loglevel.
        """
        app, _ = _make_app(pb, tmp_path)
        before = len(app._get_filtered_events())  # prime the cache as the UI does
        app.mark_seen()
        after = app._get_filtered_events()
        assert len(after) == before + 1
        assert after[-1].category == 'seen'

    def test_seen_marker_visible_at_every_loglevel(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        for lvl in (pb.LEVEL_QUIET, pb.LEVEL_NORMAL, pb.LEVEL_INFO, pb.LEVEL_DEBUG):
            app.loglevel = lvl
            app._filtered_events_dirty = True
            before = len(app._get_filtered_events())
            app.mark_seen()
            assert len(app._get_filtered_events()) == before + 1, f"level {lvl}"


# ===========================================================================
# draw_events filtering
# ===========================================================================

class TestDrawEventsFiltering:

    def _add_entries(self, pb, app):
        app.add_event('10.0.0.1', 'host down')                           # QUIET
        app.add_event('resolv', 'no monitor matched')                     # NORMAL
        app.add_event('cmd', 'fold toggled')                              # INFO
        app.add_event('bind-key', 't → :mux mtr %i')                     # DEBUG

    def _visible(self, pb, app):
        """Return list of texts visible at current loglevel."""
        return [e.text for e in app.events if e.level <= app.loglevel]

    def test_default_loglevel_is_normal(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        assert app.loglevel == pb.LEVEL_NORMAL

    def test_quiet_hides_warn_and_info(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        self._add_entries(pb, app)
        app.loglevel = pb.LEVEL_QUIET
        visible = self._visible(pb, app)
        assert any('host down' in t for t in visible)
        assert not any('no monitor matched' in t for t in visible)
        assert not any('fold toggled' in t for t in visible)
        assert not any('mux mtr' in t for t in visible)

    def test_normal_shows_warn_hides_info(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        self._add_entries(pb, app)
        app.loglevel = pb.LEVEL_NORMAL
        visible = self._visible(pb, app)
        assert any('host down' in t for t in visible)
        assert any('no monitor matched' in t for t in visible)
        assert not any('fold toggled' in t for t in visible)
        assert not any('mux mtr' in t for t in visible)

    def test_info_shows_cmd_hides_debug(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        self._add_entries(pb, app)
        app.loglevel = pb.LEVEL_INFO
        visible = self._visible(pb, app)
        assert any('fold toggled' in t for t in visible)
        assert not any('mux mtr' in t for t in visible)

    def test_debug_shows_all(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        self._add_entries(pb, app)
        app.loglevel = pb.LEVEL_DEBUG
        visible = self._visible(pb, app)
        assert any('mux mtr' in t for t in visible)

    def test_switch_level_reveals_history(self, pb, tmp_path):
        """Switching loglevel up reveals previously hidden entries."""
        app, _ = _make_app(pb, tmp_path)
        app.add_event('cmd', 'some cmd output')
        app.loglevel = pb.LEVEL_NORMAL
        assert not any('some cmd output' in t for t in self._visible(pb, app))
        app.loglevel = pb.LEVEL_INFO
        assert any('some cmd output' in t for t in self._visible(pb, app))


# ===========================================================================
# _event_color_attr
# ===========================================================================

class TestEventColorAttr:

    def _entry(self, pb, level, category, msg='some msg'):
        text = f'ts   {category}   {msg}'
        return pb.EventEntry(level, category, text)

    def test_debug_gets_dim(self, pb):
        import curses
        e = self._entry(pb, pb.LEVEL_DEBUG, 'bind-key', 't → :mux')
        assert pb._event_color_attr(e) == curses.A_DIM

    def test_quiet_gets_no_color(self, pb):
        e = self._entry(pb, pb.LEVEL_QUIET, '10.0.0.1', 'host down')
        assert pb._event_color_attr(e) == 0

    def test_info_gets_no_color(self, pb):
        e = self._entry(pb, pb.LEVEL_INFO, 'cmd', 'fold toggled')
        assert pb._event_color_attr(e) == 0

    def test_normal_error_gets_red(self, pb):
        # Use side_effect so we can distinguish color pair numbers
        with patch('curses.color_pair', side_effect=lambda n: n):
            e = self._entry(pb, pb.LEVEL_NORMAL, 'save', 'error: disk full')
            assert pb._event_color_attr(e) == 2   # pair 2 = red

    def test_normal_error_msg_gets_red(self, pb):
        with patch('curses.color_pair', side_effect=lambda n: n):
            e = self._entry(pb, pb.LEVEL_NORMAL, '10.0.0.1', 'error: unreachable')
            assert pb._event_color_attr(e) == 2

    def test_normal_warning_gets_yellow(self, pb):
        with patch('curses.color_pair', side_effect=lambda n: n):
            e = self._entry(pb, pb.LEVEL_NORMAL, 'resolv', 'no monitor matched')
            assert pb._event_color_attr(e) == 3   # pair 3 = yellow


# ===========================================================================
# :set log-level command
# ===========================================================================

class TestCmdLoglevel:

    def test_set_quiet(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set log-level quiet')
        assert app.loglevel == pb.LEVEL_QUIET

    def test_set_info(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set log-level info')
        assert app.loglevel == pb.LEVEL_INFO

    def test_set_debug(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set log-level debug')
        assert app.loglevel == pb.LEVEL_DEBUG

    def test_set_normal(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.loglevel = pb.LEVEL_DEBUG
        app._dispatch_cmd(':set log-level normal')
        assert app.loglevel == pb.LEVEL_NORMAL

    def test_invalid_value_logs_error(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set log-level verbose')
        assert any('unknown value' in e for e in app.events)

    def test_no_args_opens_settings_overlay(self, pb, tmp_path):
        """:set log-level with no argument opens settings overlay focused on 'log-level'."""
        app, _ = _make_app(pb, tmp_path)
        app.loglevel = pb.LEVEL_INFO
        app._dispatch_cmd(':set log-level')
        assert app.help_open and app.help_show_settings
        assert app.help_search == 'log-level'

    def test_set_resets_log_offset(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.log_offset = 10
        app._dispatch_cmd(':set log-level quiet')
        assert app.log_offset == 0


# ===========================================================================
# Config save/load round-trip
# ===========================================================================

class TestLogLevelConfig:

    def test_saved_to_config(self, pb, tmp_path):
        app, cfg = _make_app(pb, tmp_path)
        app.loglevel = pb.LEVEL_INFO
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        with open(cfg) as f:
            text = f.read()
        assert ':set log-level info' in text

    def test_loaded_from_config(self, pb, tmp_path):
        app, cfg = _make_app(pb, tmp_path, ':set log-level debug\n')
        assert app.loglevel == pb.LEVEL_DEBUG

    def test_default_level_not_changed_if_absent(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path, '')
        assert app.loglevel == pb.LEVEL_NORMAL


# ===========================================================================
# CLI -v / -q flag offset
# ===========================================================================

class TestLogLevelCliFlags:
    """Test that -v/-q correctly offset the base log level."""

    def _apply(self, pb, log_level=None, verbose=0, quiet=0):
        """Simulate what main() does when applying CLI args."""
        level_names = {'quiet': pb.LEVEL_QUIET, 'normal': pb.LEVEL_NORMAL,
                       'info': pb.LEVEL_INFO, 'debug': pb.LEVEL_DEBUG}
        base = level_names.get(log_level, pb.LEVEL_NORMAL)
        return max(pb.LEVEL_QUIET, min(pb.LEVEL_DEBUG, base + verbose - quiet))

    def test_default_is_normal(self, pb):
        assert self._apply(pb) == pb.LEVEL_NORMAL

    def test_v_gives_info(self, pb):
        assert self._apply(pb, verbose=1) == pb.LEVEL_INFO

    def test_vv_gives_debug(self, pb):
        assert self._apply(pb, verbose=2) == pb.LEVEL_DEBUG

    def test_vvv_clamped_at_debug(self, pb):
        assert self._apply(pb, verbose=10) == pb.LEVEL_DEBUG

    def test_q_gives_quiet(self, pb):
        assert self._apply(pb, quiet=1) == pb.LEVEL_QUIET

    def test_qq_clamped_at_quiet(self, pb):
        assert self._apply(pb, quiet=10) == pb.LEVEL_QUIET

    def test_explicit_log_level_plus_v(self, pb):
        assert self._apply(pb, log_level='quiet', verbose=1) == pb.LEVEL_NORMAL

    def test_explicit_log_level_minus_q(self, pb):
        assert self._apply(pb, log_level='info', quiet=1) == pb.LEVEL_NORMAL


# ===========================================================================
# :save — write buffered event log to a file
# ===========================================================================

class TestSaveCommand:

    def test_save_command_is_registered(self, pb):
        """:save must be reachable — _open_prompt_save had no callers before."""
        assert 'save' in pb._CMD_MAP
        assert pb._CMD_MAP['save'].action == '_open_prompt_save'

    def test_w_key_is_bound_to_save(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('W'), set())
        assert binding is not None
        assert ':save' in binding.commands

    def test_save_with_filename_writes_log(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.add_event('cmd', 'hello world')
        target = tmp_path / 'out.log'
        app._open_prompt_save(str(target))
        assert target.exists()
        assert 'hello world' in target.read_text()
        assert app.prompt is None      # direct write, no prompt

    def test_save_without_args_opens_prompt(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app._open_prompt_save()
        assert app.prompt is not None
        assert app.prompt['type'] == 'save'

    def test_save_prompt_prefills_active_log_file(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.log_file = '/tmp/existing.log'
        app._open_prompt_save()
        assert ''.join(app.prompt['chars']) == '/tmp/existing.log'

    def test_save_writes_all_levels(self, pb, tmp_path):
        """The saved file ignores loglevel filtering — users grep it."""
        app, _ = _make_app(pb, tmp_path)
        app.loglevel = pb.LEVEL_QUIET
        app.add_event('bind-key', 'debug detail', level=pb.LEVEL_DEBUG)
        target = tmp_path / 'all.log'
        app._open_prompt_save(str(target))
        assert 'debug detail' in target.read_text()

    def test_save_via_dispatch_cmd(self, pb, tmp_path):
        """':save <file>' through the normal command dispatcher."""
        app, _ = _make_app(pb, tmp_path)
        app.add_event('cmd', 'dispatched')
        target = tmp_path / 'dispatch.log'
        app._dispatch_cmd(f':save {target}')
        assert target.exists()
        assert 'dispatched' in target.read_text()


# ===========================================================================
# :save follow semantics — snapshot by default, stream only on request
# ===========================================================================

ENTER = ord('\n')
ESC   = 27


class TestSaveFollowFlow:
    """Writing a snapshot must not silently redirect future logging.

    :save used to set log_file as a side effect, so asking for one file
    quietly moved the live log there too.
    """

    def test_plain_save_does_not_start_following(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.add_event('cmd', 'hello')
        target = tmp_path / 'snap.log'
        app._open_prompt_save(str(target))
        assert target.exists()
        assert app.log_file is None, "snapshot must not become the streaming log"

    def test_follow_flag_starts_following(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.add_event('cmd', 'hello')
        target = tmp_path / 'follow.log'
        app._open_prompt_save(f'--follow {str(target)}')
        assert target.exists()
        assert app.log_file == str(target)

    def test_new_file_asks_write_or_follow(self, pb, tmp_path):
        """A new filename skips truncate/append and goes straight to the choice."""
        app, _ = _make_app(pb, tmp_path)
        app._open_prompt_save()
        app.prompt['chars'] = list(str(tmp_path / 'new.log'))
        app._handle_prompt_key(ENTER)
        assert app.prompt['type'] == 'save_follow'
        assert app.prompt['append'] is False

    def test_existing_file_asks_truncate_then_follow(self, pb, tmp_path):
        target = tmp_path / 'exists.log'
        target.write_text('old\n')
        app, _ = _make_app(pb, tmp_path)
        app._open_prompt_save()
        app.prompt['chars'] = list(str(target))
        app._handle_prompt_key(ENTER)
        assert app.prompt['type'] == 'save_confirm'
        app._handle_prompt_key(ord('a'))          # append
        assert app.prompt['type'] == 'save_follow'
        assert app.prompt['append'] is True

    def test_w_writes_without_following(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.add_event('cmd', 'payload')
        target = tmp_path / 'once.log'
        app._open_prompt_save()
        app.prompt['chars'] = list(str(target))
        app._handle_prompt_key(ENTER)
        app._handle_prompt_key(ord('w'))
        assert app.prompt is None
        assert 'payload' in target.read_text()
        assert app.log_file is None

    def test_f_writes_and_follows(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app.add_event('cmd', 'payload')
        target = tmp_path / 'tail.log'
        app._open_prompt_save()
        app.prompt['chars'] = list(str(target))
        app._handle_prompt_key(ENTER)
        app._handle_prompt_key(ord('f'))
        assert app.prompt is None
        assert 'payload' in target.read_text()
        assert app.log_file == str(target)

    def test_following_captures_later_events(self, pb, tmp_path):
        """After [f], a new event must land in the file."""
        app, _ = _make_app(pb, tmp_path)
        target = tmp_path / 'live.log'
        app._open_prompt_save()
        app.prompt['chars'] = list(str(target))
        app._handle_prompt_key(ENTER)
        app._handle_prompt_key(ord('f'))
        app.add_event('cmd', 'arrived-later')
        assert 'arrived-later' in target.read_text()

    def test_escape_at_follow_step_writes_nothing(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        target = tmp_path / 'cancelled.log'
        app._open_prompt_save()
        app.prompt['chars'] = list(str(target))
        app._handle_prompt_key(ENTER)
        app._handle_prompt_key(ESC)
        assert app.prompt is None
        assert not target.exists()
        assert app.log_file is None

    def test_append_preserves_existing_content(self, pb, tmp_path):
        target = tmp_path / 'grow.log'
        target.write_text('previous\n')
        app, _ = _make_app(pb, tmp_path)
        app.add_event('cmd', 'fresh')
        app._open_prompt_save()
        app.prompt['chars'] = list(str(target))
        app._handle_prompt_key(ENTER)
        app._handle_prompt_key(ord('a'))
        app._handle_prompt_key(ord('w'))
        body = target.read_text()
        assert 'previous' in body and 'fresh' in body

    def test_truncate_replaces_existing_content(self, pb, tmp_path):
        target = tmp_path / 'wipe.log'
        target.write_text('previous\n')
        app, _ = _make_app(pb, tmp_path)
        app.add_event('cmd', 'fresh')
        app._open_prompt_save()
        app.prompt['chars'] = list(str(target))
        app._handle_prompt_key(ENTER)
        app._handle_prompt_key(ord('t'))
        app._handle_prompt_key(ord('w'))
        body = target.read_text()
        assert 'previous' not in body and 'fresh' in body


# ===========================================================================
# Save prompt: path completion and directory rejection
# ===========================================================================

TAB  = ord('\t')


class TestSavePromptCompletion:
    """The filename prompt completes paths, like the ':' command line does."""

    def _open(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app._open_prompt_save()
        app.prompt['chars'] = []
        return app

    def test_unique_match_is_applied(self, pb, tmp_path):
        (tmp_path / 'only.log').write_text('')
        app = self._open(pb, tmp_path)
        app.prompt['chars'] = list(str(tmp_path / 'on'))
        app._handle_prompt_key(TAB)
        assert ''.join(app.prompt['chars']) == str(tmp_path / 'only.log')
        assert app.prompt['completions'] == [], "unique match needs no popup"

    def test_multiple_matches_fill_common_prefix(self, pb, tmp_path):
        (tmp_path / 'alpha.log').write_text('')
        (tmp_path / 'alpha2.log').write_text('')
        app = self._open(pb, tmp_path)
        app.prompt['chars'] = list(str(tmp_path / 'a'))
        app._handle_prompt_key(TAB)
        assert ''.join(app.prompt['chars']) == str(tmp_path / 'alpha')
        assert len(app.prompt['completions']) == 2, "popup should stay open"

    def test_further_tabs_cycle_forward(self, pb, tmp_path):
        (tmp_path / 'alpha.log').write_text('')
        (tmp_path / 'alpha2.log').write_text('')
        app = self._open(pb, tmp_path)
        app.prompt['chars'] = list(str(tmp_path / 'a'))
        app._handle_prompt_key(TAB)          # LCP
        app._handle_prompt_key(TAB)          # first candidate
        first = ''.join(app.prompt['chars'])
        app._handle_prompt_key(TAB)          # second candidate
        second = ''.join(app.prompt['chars'])
        assert first != second
        assert {first, second} == {str(tmp_path / 'alpha.log'),
                                   str(tmp_path / 'alpha2.log')}

    def test_shift_tab_cycles_backward(self, pb, tmp_path):
        (tmp_path / 'alpha.log').write_text('')
        (tmp_path / 'alpha2.log').write_text('')
        app = self._open(pb, tmp_path)
        app.prompt['chars'] = list(str(tmp_path / 'a'))
        app._handle_prompt_key(TAB)
        app._handle_prompt_key(TAB)
        forward = ''.join(app.prompt['chars'])
        app._handle_prompt_key(TAB)
        app._handle_prompt_key(pb.curses.KEY_BTAB)
        assert ''.join(app.prompt['chars']) == forward

    def test_directory_candidate_keeps_trailing_slash(self, pb, tmp_path):
        """So the next Tab can descend into it."""
        (tmp_path / 'sub').mkdir()
        app = self._open(pb, tmp_path)
        app.prompt['chars'] = list(str(tmp_path / 'su'))
        app._handle_prompt_key(TAB)
        assert ''.join(app.prompt['chars']).endswith('/')

    def test_typing_invalidates_stale_candidates(self, pb, tmp_path):
        (tmp_path / 'alpha.log').write_text('')
        (tmp_path / 'alpha2.log').write_text('')
        app = self._open(pb, tmp_path)
        app.prompt['chars'] = list(str(tmp_path / 'a'))
        app._handle_prompt_key(TAB)
        assert app.prompt['completions']
        app._handle_prompt_key(ord('x'))
        assert app.prompt['completions'] == []

    def test_backspace_invalidates_stale_candidates(self, pb, tmp_path):
        (tmp_path / 'alpha.log').write_text('')
        (tmp_path / 'alpha2.log').write_text('')
        app = self._open(pb, tmp_path)
        app.prompt['chars'] = list(str(tmp_path / 'a'))
        app._handle_prompt_key(TAB)
        assert app.prompt['completions']
        app._handle_prompt_key(127)
        assert app.prompt['completions'] == []

    def test_no_match_leaves_buffer_alone(self, pb, tmp_path):
        app = self._open(pb, tmp_path)
        typed = str(tmp_path / 'nothing-here')
        app.prompt['chars'] = list(typed)
        app._handle_prompt_key(TAB)
        assert ''.join(app.prompt['chars']) == typed


class TestSavePromptDirectoryRejected:
    """A directory exists but is not writable as a log file."""

    def test_directory_does_not_advance_to_truncate_prompt(self, pb, tmp_path):
        """os.path.exists() is true for a dir, so it used to ask truncate/append."""
        app, _ = _make_app(pb, tmp_path)
        app._open_prompt_save()
        app.prompt['chars'] = list(str(tmp_path))
        app._handle_prompt_key(ENTER)
        assert app.prompt is not None, "prompt should stay open"
        assert app.prompt['type'] == 'save', "must not become save_confirm"

    def test_directory_reports_a_clear_error(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app._open_prompt_save()
        app.prompt['chars'] = list(str(tmp_path))
        app._handle_prompt_key(ENTER)
        assert any('is a directory' in e.text for e in app.events)

    def test_dot_is_rejected(self, pb, tmp_path):
        app, _ = _make_app(pb, tmp_path)
        app._open_prompt_save()
        app.prompt['chars'] = ['.']
        app._handle_prompt_key(ENTER)
        assert app.prompt['type'] == 'save'
        assert any('is a directory' in e.text for e in app.events)

    def test_directory_arg_to_command_is_rejected(self, pb, tmp_path):
        """':save <dir>' must not attempt the write either."""
        app, _ = _make_app(pb, tmp_path)
        app._open_prompt_save(str(tmp_path))
        assert any('is a directory' in e.text for e in app.events)
        assert app.log_file is None
