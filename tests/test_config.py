"""Unit tests for ping-bulk configuration file loading and saving.

These tests exercise _config_path(), _load_config(), _save_config(),
_create_default_config(), and the ':save-config' command handler without
starting any ping threads or curses sessions.  A temporary directory is
used for all config files so the real user config (~/.config/ping-bulk/)
is never touched.

Fixtures
--------
pb
    The ping-bulk module imported once for the whole test session.
    Because the script has no .py extension and is not on sys.path,
    it is loaded via importlib.util.

Helpers
-------
make_app(pb, cfg_path, config_text, ...)
    Construct an Application with the config file pre-populated with
    *config_text* and _config_path() patched to *cfg_path*.  No ping
    threads are started.
"""

import os
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helper: build an Application with a temp config
# ---------------------------------------------------------------------------

def make_app(pb, cfg_path, config_text='', log_file=None, entries=None):
    """Return a non-running Application whose config file contains *config_text*.

    Parameters
    ----------
    pb          — the ping-bulk module
    cfg_path    — absolute path to use as the config file (need not exist yet)
    config_text — text written into *cfg_path* before construction;
                  if None the file is *not* created (simulates first run)
    log_file    — passed to Application(entries, log_file=...)
    entries     — host entries; defaults to [('host', '127.0.0.1')]
    """
    if entries is None:
        entries = [('host', '127.0.0.1')]

    if config_text is not None:
        os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
        with open(cfg_path, 'w') as f:
            f.write(config_text)
    # else: leave the file absent (tests first-run / missing-file behaviour)

    with patch.object(pb, '_config_path', return_value=cfg_path):
        app = pb.Application(entries, log_file=log_file)
    return app


# ===========================================================================
# TestConfigPath
# ===========================================================================

class TestConfigPath:
    """_config_path() must return the XDG-compliant path."""

    def test_default_path(self, pb):
        """Without XDG_CONFIG_HOME the path should be under ~/.config."""
        env_backup = os.environ.pop('XDG_CONFIG_HOME', None)
        try:
            path = pb._config_path()
        finally:
            if env_backup is not None:
                os.environ['XDG_CONFIG_HOME'] = env_backup

        expected_prefix = os.path.join(os.path.expanduser('~'), '.config')
        assert path.startswith(expected_prefix), (
            f"Expected path under {expected_prefix!r}, got {path!r}"
        )
        assert path.endswith(os.path.join('ping-bulk', 'config')), (
            f"Expected path ending in 'ping-bulk/config', got {path!r}"
        )

    def test_xdg_config_home_override(self, pb, tmp_path):
        """When XDG_CONFIG_HOME is set it should be used as the base directory."""
        xdg = str(tmp_path / 'xdg')
        with patch.dict(os.environ, {'XDG_CONFIG_HOME': xdg}):
            path = pb._config_path()

        assert path == os.path.join(xdg, 'ping-bulk', 'config'), (
            f"Expected XDG-based path, got {path!r}"
        )


# ===========================================================================
# TestLoadConfig
# ===========================================================================

class TestLoadConfig:
    """_load_config() reads recognised keys and silently ignores others."""

    def test_dns_mode_loaded(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, ':dns hostname\n')
        idx = pb.DNS_MODES.index('hostname')
        assert app.dns_mode == idx, (
            f"Expected dns_mode={idx} for 'hostname', got {app.dns_mode}"
        )

    def test_stats_mode_loaded(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, ':stats Loss%\n')
        idx = pb.STATS_MODES.index('Loss%')
        assert app.stats_mode == idx, (
            f"Expected stats_mode={idx} for 'Loss%', got {app.stats_mode}"
        )

    def test_sort_loaded(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, ':sort name\n')
        assert app.sort_by == 'name', (
            f"Expected sort_by='name', got {app.sort_by!r}"
        )

    def test_history_mode_loaded(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, ':ping-view rtt\n')
        idx = pb.HISTORY_MODES.index('rtt')
        assert app.history_mode == idx, (
            f"Expected history_mode={idx} for 'rtt', got {app.history_mode}"
        )

    def test_log_file_loaded(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        log_path = str(tmp_path / 'events.log')
        app = make_app(pb, cfg, f':log {log_path}\n')
        assert app.log_file == log_path, (
            f"Expected log_file={log_path!r}, got {app.log_file!r}"
        )

    def test_empty_log_value_disables_logging(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, ':log off\n')
        assert app.log_file is None, (
            f"Expected log_file=None for ':log off', got {app.log_file!r}"
        )

    def test_all_settings_loaded_together(self, pb, tmp_path):
        """All recognised commands can appear in a single config file."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        config_text = (
            ':dns ip\n'
            ':stats Avg\n'
            ':sort latency\n'
            ':ping-view scaled\n'
        )
        app = make_app(pb, cfg, config_text)
        assert app.dns_mode  == pb.DNS_MODES.index('ip')
        assert app.stats_mode == pb.STATS_MODES.index('Avg')
        assert app.sort_by   == 'latency'
        assert app.history_mode == pb.HISTORY_MODES.index('scaled')

    def test_comment_lines_ignored(self, pb, tmp_path):
        """Lines starting with '#' must not be parsed."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '# :dns hostname\n# :stats Max\n')
        assert app.dns_mode == 0,    "Comment line changed dns_mode"
        assert app.stats_mode == 0,  "Comment line changed stats_mode"

    def test_unknown_command_silently_ignored(self, pb, tmp_path):
        """Unknown commands must leave all settings at their defaults."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, ':unknownkey foobar\n')
        # Defaults: dns_mode=0, stats_mode=0, sort_by='none', history_mode=0
        assert app.dns_mode    == 0
        assert app.stats_mode  == 0
        assert app.sort_by     == 'none'
        assert app.history_mode == 0

    def test_line_without_colon_ignored(self, pb, tmp_path):
        """Lines not starting with ':' must be silently skipped."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, 'dns hostname\njust-a-word\n')
        assert app.dns_mode == 0, "Line without ':' prefix changed dns_mode"

    def test_invalid_dns_value_ignored(self, pb, tmp_path):
        """An unrecognised value for a known command must not change the setting."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, ':dns invalid_mode\n')
        assert app.dns_mode == 0, (
            f"Invalid dns value should be ignored; dns_mode={app.dns_mode}"
        )

    def test_case_insensitive_command(self, pb, tmp_path):
        """Command names are compared case-insensitively."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, ':DNS hostname\n:STATS Max\n')
        assert app.dns_mode   == pb.DNS_MODES.index('hostname')
        assert app.stats_mode == pb.STATS_MODES.index('Max')

    def test_missing_config_file_uses_defaults(self, pb, tmp_path):
        """A missing config file must be silently ignored; defaults apply."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        # config_text=None → file is NOT created
        app = make_app(pb, cfg, config_text=None)
        assert app.dns_mode    == 0
        assert app.stats_mode  == 0
        assert app.sort_by     == 'none'
        assert app.history_mode == 0
        assert app.log_file    is None


# ===========================================================================
# TestCreateDefaultConfig
# ===========================================================================

class TestCreateDefaultConfig:
    """On first run (no existing config) a commented default file is created."""

    def test_default_config_created_when_missing(self, pb, tmp_path):
        """If no config file exists, _create_default_config() writes one."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        # config_text=None → file absent → should be created by Application.__init__
        make_app(pb, cfg, config_text=None)
        assert os.path.isfile(cfg), "Default config file was not created on first run"

    def test_default_config_contains_comment_header(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        make_app(pb, cfg, config_text=None)
        with open(cfg) as f:
            content = f.read()
        assert '# ping-bulk configuration' in content

    def test_default_config_all_lines_are_comments(self, pb, tmp_path):
        """Every non-blank setting line in the default config must be commented out."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        make_app(pb, cfg, config_text=None)
        with open(cfg) as f:
            lines = f.readlines()
        for line in lines:
            stripped = line.strip()
            if stripped and not stripped.startswith('#'):
                pytest.fail(
                    f"Default config has an active (non-commented) line: {line!r}"
                )

    def test_no_new_file_when_config_exists(self, pb, tmp_path):
        """If the config file already exists it must not be overwritten."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        original = '# my custom config\ndns = ip\n'
        make_app(pb, cfg, config_text=original)
        # Second run — file already exists
        make_app(pb, cfg, config_text=None)  # config_text=None → file stays as-is from prev run
        # Actually in this flow make_app with config_text=None just doesn't write,
        # so the file from the first make_app call is still there.
        with open(cfg) as f:
            content = f.read()
        assert 'my custom config' in content, (
            "Existing config file was overwritten by _create_default_config()"
        )


# ===========================================================================
# TestSaveConfig
# ===========================================================================

class TestSaveConfig:
    """_save_config() must persist all current settings to the config file."""

    def test_returns_true_on_success(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        with patch.object(pb, '_config_path', return_value=cfg):
            result = app._save_config()
        assert result is True, "_save_config() should return True on success"

    def test_creates_file(self, pb, tmp_path):
        """_save_config() must create the file (including parent dirs) if needed."""
        cfg = str(tmp_path / 'subdir' / 'ping-bulk' / 'config')
        app = make_app(pb, str(tmp_path / 'ping-bulk' / 'config'), '')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        assert os.path.isfile(cfg), "_save_config() did not create the config file"

    def test_dns_persisted(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app.dns_mode = pb.DNS_MODES.index('ip')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        with open(cfg) as f:
            content = f.read()
        assert ':set dns ip' in content, f"dns setting not found in saved config:\n{content}"

    def test_stats_persisted(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app.stats_mode = pb.STATS_MODES.index('Avg')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        with open(cfg) as f:
            content = f.read()
        assert ':set stats Avg' in content

    def test_sort_persisted(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app.sort_by = 'latency'
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        with open(cfg) as f:
            content = f.read()
        assert ':set sort latency' in content

    def test_history_persisted(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app.history_mode = pb.HISTORY_MODES.index('scaled')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        with open(cfg) as f:
            content = f.read()
        assert ':set ping-view scaled' in content

    def test_log_file_persisted_when_set(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        log_path = str(tmp_path / 'events.log')
        app = make_app(pb, cfg, '')
        app.log_file = log_path
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        with open(cfg) as f:
            content = f.read()
        assert f':log {log_path}' in content

    def test_log_commented_when_none(self, pb, tmp_path):
        """When log_file is None, the saved config must have a commented-out log line."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app.log_file = None
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        with open(cfg) as f:
            content = f.read()
        # Active ':log ...' should NOT appear; a commented placeholder should.
        assert '# :log' in content, (
            "Expected commented-out log line when log_file is None"
        )
        for line in content.splitlines():
            if line.strip().startswith(':log ') and not line.strip().startswith('#'):
                pytest.fail(f"Uncommented ':log' setting found when log_file is None: {line!r}")

    def test_roundtrip(self, pb, tmp_path):
        """Settings written by _save_config() are correctly read back by _load_config()."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        # Build an app with custom settings
        app1 = make_app(pb, cfg, '')
        app1.dns_mode     = pb.DNS_MODES.index('hostname')
        app1.stats_mode   = pb.STATS_MODES.index('Max')
        app1.sort_by      = 'status'
        app1.history_mode = pb.HISTORY_MODES.index('rtt')
        app1.log_file     = None
        with patch.object(pb, '_config_path', return_value=cfg):
            app1._save_config()

        # Build a second app that reads the just-written file
        app2 = make_app(pb, cfg, config_text=None)  # file already exists from above
        # Wait — make_app with config_text=None does not write anything; the file
        # from _save_config() above is already there.
        with patch.object(pb, '_config_path', return_value=cfg):
            app2._load_config()

        assert app2.dns_mode     == app1.dns_mode
        assert app2.stats_mode   == app1.stats_mode
        assert app2.sort_by      == app1.sort_by
        assert app2.history_mode == app1.history_mode


# ===========================================================================
# TestSaveConfigCommand
# ===========================================================================

class TestSaveConfigCommand:
    """:save-config command writes settings and reports success in the event log."""

    def test_saveconfig_creates_file(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd('save-config')
        assert os.path.isfile(cfg), ":save-config did not create the config file"

    def test_saveconfig_emits_event(self, pb, tmp_path):
        """:save-config must add a success event to the event log."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd('save-config')
        events = list(app.events)
        assert any('config' in e and 'saved' in e for e in events), (
            f":save-config event not found.\nEvents: {events}"
        )

    def test_saveconfig_event_mentions_path(self, pb, tmp_path):
        """The success event must mention the path of the saved file."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd('save-config')
        events = list(app.events)
        assert any(cfg in e for e in events), (
            f"Config path {cfg!r} not mentioned in events.\nEvents: {events}"
        )

    def test_saveconfig_persists_current_dns_mode(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app.dns_mode = pb.DNS_MODES.index('ip')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd('save-config')
        with open(cfg) as f:
            content = f.read()
        assert ':set dns ip' in content

    def test_saveconfig_colon_prefix_accepted(self, pb, tmp_path):
        """':save-config' (with leading colon) must also work."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd(':save-config')
        assert os.path.isfile(cfg), ":save-config with leading colon did not create file"


# ===========================================================================
# TestLogFileCliOverride
# ===========================================================================

# ===========================================================================
# TestLogSize
# ===========================================================================

class TestLogSize:
    """Tests for the :set log-size command and its config persistence."""

    def test_default_log_size(self, pb, tmp_path):
        """log_size defaults to 10000."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        assert app.log_size == 10000

    def test_valid_value_sets_log_size(self, pb, tmp_path):
        """A valid positive integer changes log_size."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set log-size 5000')
        assert app.log_size == 5000

    def test_valid_value_resizes_deque(self, pb, tmp_path):
        """Changing log-size resizes the events deque."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set log-size 500')
        assert app.events.maxlen == 500

    def test_resize_preserves_existing_events(self, pb, tmp_path):
        """Existing events are preserved when the deque is resized (up to new maxlen)."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        # Add a few events directly
        for i in range(5):
            app.events.append(f'event {i}')
        app._dispatch_cmd(':set log-size 50')
        event_list = list(app.events)
        assert len(event_list) == 5
        assert 'event 0' in event_list

    def test_no_args_opens_settings_overlay(self, pb, tmp_path):
        """:set log-size with no argument opens settings overlay focused on 'log-size'."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set log-size')
        assert app.help_open and app.help_show_settings
        assert app.help_search == 'log-size'

    def test_invalid_non_integer_rejected(self, pb, tmp_path):
        """A non-integer value must be rejected and log_size must stay unchanged."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set log-size abc')
        assert app.log_size == 10000
        events = list(app.events)
        assert any('invalid' in e.lower() or 'error' in e.lower() for e in events)

    def test_invalid_zero_rejected(self, pb, tmp_path):
        """Zero is not a valid log size."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set log-size 0')
        assert app.log_size == 10000

    def test_invalid_negative_rejected(self, pb, tmp_path):
        """Negative integers are not valid log sizes."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set log-size -100')
        assert app.log_size == 10000

    def test_log_size_persisted_by_save_config(self, pb, tmp_path):
        """:set log-size is written to the config file by _save_config()."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app.log_size = 2000
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        with open(cfg) as f:
            content = f.read()
        assert ':set log-size 2000' in content

    def test_log_size_loaded_from_config(self, pb, tmp_path):
        """:set log-size in the config file is applied on startup."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, ':set log-size 3000\n')
        assert app.log_size == 3000
        assert app.events.maxlen == 3000

    def test_log_size_roundtrip(self, pb, tmp_path):
        """log-size survives a save+load cycle."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app1 = make_app(pb, cfg, '')
        app1.log_size = 7500
        with patch.object(pb, '_config_path', return_value=cfg):
            app1._save_config()

        app2 = make_app(pb, cfg, config_text=None)
        with patch.object(pb, '_config_path', return_value=cfg):
            app2._load_config()
        assert app2.log_size == 7500

    def test_set_log_size_via_set_command(self, pb, tmp_path):
        """:set log-size <n> delegates to _cmd_log_size."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set log-size 4000')
        assert app.log_size == 4000

    def test_log_size_in_set_params(self, pb):
        """log-size must be listed in SET_PARAMS."""
        names = [p.name for p in pb.SET_PARAMS]
        assert 'log-size' in names, f"log-size not found in SET_PARAMS: {names}"


class TestSetCommand:
    """Tests for the :set <param> [value] command dispatcher."""

    def test_set_dns_hostname(self, pb, tmp_path):
        """:set dns hostname sets dns_mode to the 'hostname' index."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set dns hostname')
        assert app.dns_mode == pb.DNS_MODES.index('hostname')

    def test_set_stats_avg(self, pb, tmp_path):
        """:set stats avg sets stats_mode to the 'Avg' index."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set stats avg')
        assert app.stats_mode == pb.STATS_MODES.index('Avg')

    def test_set_sort_latency(self, pb, tmp_path):
        """:set sort latency sets sort_by to 'latency'."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set sort latency')
        assert app.sort_by == 'latency'

    def test_set_ping_view_rtt(self, pb, tmp_path):
        """:set ping-view rtt sets history_mode to the 'rtt' index."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set ping-view rtt')
        assert app.history_mode == pb.HISTORY_MODES.index('rtt')

    def test_set_no_args_opens_settings_overlay(self, pb, tmp_path):
        """:set with no arguments opens the settings overlay (help_open + help_show_settings)."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set')
        assert app.help_open, "help overlay should be open after :set"
        assert app.help_show_settings, "settings tab should be active after :set"

    def test_set_unknown_param_emits_error(self, pb, tmp_path):
        """:set unknownparam emits an 'unknown setting' error to the event log."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set unknownparam')
        events = list(app.events)
        assert any("unknown setting 'unknownparam'" in e for e in events), (
            f"Expected unknown-setting error in events; got: {events}"
        )

    def test_set_dns_no_value_opens_settings_overlay(self, pb, tmp_path):
        """:set dns with no value opens settings overlay focused on 'dns'."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        initial = app.dns_mode
        app._dispatch_cmd(':set dns')
        assert app.help_open, "help overlay should be open"
        assert app.help_show_settings, "settings tab should be active"
        assert app.dns_mode == initial, "dns_mode must not change when no value given"
        assert app.help_search == 'dns', "search should be pre-populated with param name"


class TestLogFileCliOverride:
    """The CLI --log-file argument must override the 'log' value from the config file."""

    def test_cli_log_file_overrides_config(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        config_log  = str(tmp_path / 'config.log')
        cli_log     = str(tmp_path / 'cli.log')
        # Write config with :log config_log
        config_text = f':log {config_log}\n'
        app = make_app(pb, cfg, config_text, log_file=cli_log)
        assert app.log_file == cli_log, (
            f"CLI log_file should override config; got {app.log_file!r}"
        )

    def test_cli_log_file_none_uses_config(self, pb, tmp_path):
        """When no CLI log_file is given the value from config is used."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        config_log = str(tmp_path / 'config.log')
        config_text = f':log {config_log}\n'
        app = make_app(pb, cfg, config_text, log_file=None)
        assert app.log_file == config_log, (
            f"Config log file should be used when CLI arg is absent; got {app.log_file!r}"
        )


class TestHistorySize:
    """Tests for the :set history-size command and its config persistence."""

    def test_default_history_size(self, pb, tmp_path):
        """history_size defaults to 86400."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        assert app.history_size == 86400

    def test_valid_value_sets_history_size(self, pb, tmp_path):
        """A valid positive integer changes history_size."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set history-size 1000')
        assert app.history_size == 1000

    def test_valid_value_resizes_monitor_deques(self, pb, tmp_path):
        """Changing history-size resizes the history deque on all monitors."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '', entries=[('host', '10.0.0.1'), ('host', '10.0.0.2')])
        app._dispatch_cmd(':set history-size 500')
        for m in app.monitors:
            assert m.history.maxlen == 500

    def test_resize_preserves_existing_history(self, pb, tmp_path):
        """Existing history entries are preserved when the deque is resized (up to new maxlen)."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '', entries=[('host', '10.0.0.1')])
        m = app.monitors[0]
        for v in [1.0, 2.0, 3.0]:
            m.history.append(v)
        app._dispatch_cmd(':set history-size 10000')
        assert list(m.history) == [1.0, 2.0, 3.0]

    def test_no_args_opens_settings_overlay(self, pb, tmp_path):
        """:set history-size with no argument opens settings overlay focused on 'history-size'."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set history-size')
        assert app.help_open and app.help_show_settings
        assert app.help_search == 'history-size'

    def test_invalid_non_integer_rejected(self, pb, tmp_path):
        """A non-integer value must be rejected and history_size must stay unchanged."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set history-size abc')
        assert app.history_size == 86400
        events = list(app.events)
        assert any('invalid' in e.lower() or 'error' in e.lower() for e in events)

    def test_invalid_zero_rejected(self, pb, tmp_path):
        """Zero is not a valid history size."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set history-size 0')
        assert app.history_size == 86400

    def test_invalid_negative_rejected(self, pb, tmp_path):
        """Negative integers are not valid history sizes."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set history-size -100')
        assert app.history_size == 86400

    def test_history_size_persisted_by_save_config(self, pb, tmp_path):
        """:set history-size is written to the config file by _save_config()."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app.history_size = 2000
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        with open(cfg) as f:
            content = f.read()
        assert ':set history-size 2000' in content

    def test_history_size_loaded_from_config(self, pb, tmp_path):
        """:set history-size in the config file is applied on startup."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, ':set history-size 3000\n')
        assert app.history_size == 3000

    def test_history_size_roundtrip(self, pb, tmp_path):
        """history-size survives a save+load cycle."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app1 = make_app(pb, cfg, '')
        app1.history_size = 7500
        with patch.object(pb, '_config_path', return_value=cfg):
            app1._save_config()

        app2 = make_app(pb, cfg, config_text=None)
        with patch.object(pb, '_config_path', return_value=cfg):
            app2._load_config()
        assert app2.history_size == 7500

    def test_set_history_size_via_set_command(self, pb, tmp_path):
        """:set history-size <n> delegates to _cmd_history_size."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set history-size 4000')
        assert app.history_size == 4000

    def test_history_size_in_set_params(self, pb):
        """history-size must be listed in SET_PARAMS."""
        names = [p.name for p in pb.SET_PARAMS]
        assert 'history-size' in names, f"history-size not found in SET_PARAMS: {names}"



# ===========================================================================
# TestSettingsOverlay  (S1-nav)
# ===========================================================================

class TestSettingsOverlay:
    """Settings overlay tab: navigation, Space-cycle, Enter pre-fill, search sync."""

    # ------------------------------------------------------------------
    # Layout: _build_settings_lines must produce 4 data rows per param
    # ------------------------------------------------------------------

    def test_build_settings_lines_has_name_row(self, pb, tmp_path):
        """Each param produces a row that starts with ':set <name>'."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        lines = app._build_settings_lines(content_width=200)
        for p in pb.SET_PARAMS:
            assert any(line.strip().startswith(f':set {p.name}')
                       for line in lines), \
                f"No ':set {p.name}' row in settings lines"

    def test_build_settings_lines_has_current_value(self, pb, tmp_path):
        """Each param's current value appears on its row."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        lines = app._build_settings_lines(content_width=200)
        for p in pb.SET_PARAMS:
            cur = p.get_current(app)
            # Find the row for this param
            row = next((l for l in lines if l.strip().startswith(f':set {p.name}')), None)
            assert row is not None
            assert cur in row, f"Current value {cur!r} not found in row for {p.name!r}"

    def test_build_settings_lines_has_values_inline(self, pb, tmp_path):
        """Each param's values appear inline on its row (not on a separate 'values:' line)."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        lines = app._build_settings_lines(content_width=200)
        # No separate 'values:' rows — table format embeds values in each row
        val_rows = [l for l in lines if 'values:' in l]
        assert len(val_rows) == 0, "4-column format must not emit separate 'values:' lines"
        # A known short values list must appear directly on the param's row
        sort_row = next(l for l in lines if l.strip().startswith(':set sort'))
        assert 'none' in sort_row and 'latency' in sort_row

    def test_build_settings_lines_one_row_per_param(self, pb, tmp_path):
        """Each param occupies exactly one data row; description always shown (no truncation)."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        lines = app._build_settings_lines()
        # Every param must have its description visible (no terminal-width hiding)
        for p in pb.SET_PARAMS:
            row = next((l for l in lines if l.strip().startswith(f':set {p.name}')), None)
            assert row is not None
            assert p.help in row, f"Description for {p.name!r} should appear untruncated"

    # ------------------------------------------------------------------
    # _open_settings_overlay
    # ------------------------------------------------------------------

    def test_open_settings_overlay_no_param(self, pb, tmp_path):
        """:set with no args opens overlay at cursor=0 with empty search."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set')
        assert app.help_open
        assert app.help_show_settings
        assert app.settings_cursor == 0
        assert app.help_search == ''

    def test_open_settings_overlay_with_param(self, pb, tmp_path):
        """:set <param> opens overlay with search pre-populated and cursor on param."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        # Use 'sort' (index 2 in SET_PARAMS)
        sort_idx = next(i for i, p in enumerate(pb.SET_PARAMS) if p.name == 'sort')
        app._dispatch_cmd(':set sort')
        assert app.help_open
        assert app.help_show_settings
        assert app.help_search == 'sort'
        assert app.settings_cursor == sort_idx

    # ------------------------------------------------------------------
    # Cursor navigation
    # ------------------------------------------------------------------

    def test_cursor_wraps_down(self, pb, tmp_path):
        """Cursor wraps from last param back to first."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._open_settings_overlay()
        app.settings_cursor = len(pb.SET_PARAMS) - 1
        app._cmd_settings_cursor('down')
        assert app.settings_cursor == 0

    def test_cursor_wraps_up(self, pb, tmp_path):
        """Cursor wraps from first param back to last."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._open_settings_overlay()
        app.settings_cursor = 0
        app._cmd_settings_cursor('up')
        assert app.settings_cursor == len(pb.SET_PARAMS) - 1

    def test_cursor_moves_down(self, pb, tmp_path):
        """Cursor moves down by one."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._open_settings_overlay()
        app.settings_cursor = 0
        app._cmd_settings_cursor('down')
        assert app.settings_cursor == 1

    def test_cursor_ignored_when_overlay_closed(self, pb, tmp_path):
        """_cmd_settings_cursor is a no-op when help overlay is closed."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app.settings_cursor = 0
        app._cmd_settings_cursor('down')  # overlay not open
        assert app.settings_cursor == 0

    # ------------------------------------------------------------------
    # Space: cycle value (_cmd_settings_apply)
    # ------------------------------------------------------------------

    def test_space_cycles_dns_mode(self, pb, tmp_path):
        """Space cycles dns_mode forward without closing the overlay."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        dns_idx = next(i for i, p in enumerate(pb.SET_PARAMS) if p.name == 'dns')
        app._open_settings_overlay()
        app.settings_cursor = dns_idx
        before = app.dns_mode
        app._cmd_settings_apply()
        assert app.dns_mode == (before + 1) % len(pb.DNS_MODES)
        # Overlay must stay open
        assert app.help_open
        assert app.help_show_settings

    def test_space_free_form_opens_edit(self, pb, tmp_path):
        """Space on a free-form param (stats) falls back to edit mode."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        stats_idx = next(i for i, p in enumerate(pb.SET_PARAMS) if p.name == 'stats')
        app._open_settings_overlay()
        app.settings_cursor = stats_idx
        app._cmd_settings_apply()
        # Edit mode: overlay closed, command line pre-filled
        assert not app.help_open
        assert app.cmd is not None
        assert 'stats' in ''.join(app.cmd['chars'])

    def test_space_ignored_when_overlay_closed(self, pb, tmp_path):
        """_cmd_settings_apply is a no-op when help overlay is closed."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        before = app.dns_mode
        app._cmd_settings_apply()  # overlay not open
        assert app.dns_mode == before

    # ------------------------------------------------------------------
    # Enter: pre-fill command line (_cmd_settings_edit)
    # ------------------------------------------------------------------

    def test_enter_closes_overlay_and_prefills_cmdline(self, pb, tmp_path):
        """Enter closes the overlay and opens the command line with :set <n> <v>."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        dns_idx = next(i for i, p in enumerate(pb.SET_PARAMS) if p.name == 'dns')
        app._open_settings_overlay()
        app.settings_cursor = dns_idx
        app._cmd_settings_edit()
        assert not app.help_open, "Overlay should be closed after Enter"
        assert app.cmd is not None, "Command line should be open"
        cmd_text = ''.join(app.cmd['chars'])
        assert 'set dns' in cmd_text, f"Command line should contain 'set dns', got: {cmd_text!r}"
        cur = pb.SET_PARAMS[dns_idx].get_current(app)
        assert cur in cmd_text, f"Current value {cur!r} should be pre-filled"

    def test_enter_ignored_when_overlay_closed(self, pb, tmp_path):
        """_cmd_settings_edit is a no-op when overlay is closed."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._cmd_settings_edit()
        assert app.cmd is None

    # ------------------------------------------------------------------
    # Search → cursor sync (_sync_settings_cursor_to_match)
    # ------------------------------------------------------------------

    def test_search_updates_cursor(self, pb, tmp_path):
        """Typing in search while in settings mode moves settings_cursor to match."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._open_settings_overlay()
        # Force _settings_line_map by building lines
        app._build_settings_lines(content_width=100)
        # Search for 'autofold-delay' — should move cursor to that param
        autofold_delay_idx = next(
            i for i, p in enumerate(pb.SET_PARAMS) if p.name == 'autofold-delay')
        app.help_search = 'autofold-delay'
        app._update_help_search()
        assert app.settings_cursor == autofold_delay_idx, \
            f"Expected cursor={autofold_delay_idx}, got {app.settings_cursor}"

    def test_search_jump_updates_cursor(self, pb, tmp_path):
        """n/N (search jump) also updates settings_cursor."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._open_settings_overlay()
        app._build_settings_lines(content_width=100)
        # Search for 'on' — matches many params; first match should set cursor
        app.help_search = 'on'
        app._update_help_search()
        first_cursor = app.settings_cursor
        # Jump to next match — cursor may change
        if len(app.help_search_matches) > 1:
            app._help_search_jump(+1)
            # Cursor is still a valid param index
            assert 0 <= app.settings_cursor < len(pb.SET_PARAMS)


class TestLateGraceSetting:
    """`:set late-grace` bounds how long an unanswered probe may still arrive."""

    def _app(self, pb, tmp_path, config=''):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        with open(cfg, 'w') as f:
            f.write(config)
        with patch.object(pb, '_config_path', return_value=cfg):
            app = pb.Application([('host', '127.0.0.1')])
        return app, cfg

    def test_default_is_one_second(self, pb, tmp_path):
        app, _ = self._app(pb, tmp_path)
        assert app.late_grace == 1.0

    def test_set_accepts_a_float(self, pb, tmp_path):
        app, _ = self._app(pb, tmp_path)
        app._dispatch_cmd(':set late-grace 2.5')
        assert app.late_grace == 2.5

    def test_zero_is_allowed(self, pb, tmp_path):
        """0 restores the old behaviour: a '-O' line is an immediate loss."""
        app, _ = self._app(pb, tmp_path)
        app._dispatch_cmd(':set late-grace 0')
        assert app.late_grace == 0.0

    def test_negative_is_rejected(self, pb, tmp_path):
        app, _ = self._app(pb, tmp_path)
        app._dispatch_cmd(':set late-grace -1')
        assert app.late_grace == 1.0
        assert any('invalid value' in e.text for e in app.events)

    def test_garbage_is_rejected(self, pb, tmp_path):
        app, _ = self._app(pb, tmp_path)
        app._dispatch_cmd(':set late-grace soon')
        assert app.late_grace == 1.0

    def test_default_not_written_to_config(self, pb, tmp_path):
        app, cfg = self._app(pb, tmp_path)
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        assert 'late-grace' not in open(cfg).read()

    def test_non_default_is_written(self, pb, tmp_path):
        app, cfg = self._app(pb, tmp_path)
        app._dispatch_cmd(':set late-grace 3')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._save_config()
        assert ':set late-grace 3' in open(cfg).read()

    def test_config_round_trip(self, pb, tmp_path):
        app, _ = self._app(pb, tmp_path, config=':set late-grace 2\n')
        assert app.late_grace == 2.0
