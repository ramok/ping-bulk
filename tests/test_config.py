"""Unit tests for ping-bulk configuration file loading and saving.

These tests exercise _config_path(), _load_config(), _save_config(),
_create_default_config(), and the ':saveconfig' command handler without
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

import importlib.machinery
import importlib.util
import os
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Module import
# ---------------------------------------------------------------------------

@pytest.fixture(scope='session')
def pb(app_path):
    """The ping-bulk module, imported once for the whole test session.

    spec_from_file_location() returns None for extension-less scripts, so we
    construct the spec explicitly via SourceFileLoader.
    """
    loader = importlib.machinery.SourceFileLoader('ping_bulk', app_path)
    spec = importlib.util.spec_from_loader('ping_bulk', loader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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
    """:saveconfig command writes settings and reports success in the event log."""

    def test_saveconfig_creates_file(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd('saveconfig')
        assert os.path.isfile(cfg), ":saveconfig did not create the config file"

    def test_saveconfig_emits_event(self, pb, tmp_path):
        """:saveconfig must add a success event to the event log."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd('saveconfig')
        events = list(app.events)
        assert any('config' in e and 'saved' in e for e in events), (
            f":saveconfig event not found.\nEvents: {events}"
        )

    def test_saveconfig_event_mentions_path(self, pb, tmp_path):
        """The success event must mention the path of the saved file."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd('saveconfig')
        events = list(app.events)
        assert any(cfg in e for e in events), (
            f"Config path {cfg!r} not mentioned in events.\nEvents: {events}"
        )

    def test_saveconfig_persists_current_dns_mode(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app.dns_mode = pb.DNS_MODES.index('ip')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd('saveconfig')
        with open(cfg) as f:
            content = f.read()
        assert ':set dns ip' in content

    def test_saveconfig_colon_prefix_accepted(self, pb, tmp_path):
        """':saveconfig' (with leading colon) must also work."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd(':saveconfig')
        assert os.path.isfile(cfg), ":saveconfig with leading colon did not create file"


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

    def test_no_args_shows_current_size(self, pb, tmp_path):
        """Calling :set log-size with no argument reports the current size in the event log."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set log-size')
        events = list(app.events)
        assert any('10000' in e for e in events), (
            f"Current log size not reported in events: {events}"
        )

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

    def test_set_no_args_emits_usage(self, pb, tmp_path):
        """:set with no arguments emits a usage error to the event log."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set')
        events = list(app.events)
        assert any('set:' in e and 'usage' in e for e in events), (
            f"Expected usage error in events; got: {events}"
        )

    def test_set_unknown_param_emits_error(self, pb, tmp_path):
        """:set unknownparam emits an 'unknown setting' error to the event log."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set unknownparam')
        events = list(app.events)
        assert any("unknown setting 'unknownparam'" in e for e in events), (
            f"Expected unknown-setting error in events; got: {events}"
        )

    def test_set_dns_no_value_cycles_forward(self, pb, tmp_path):
        """:set dns with no value cycles dns_mode forward by one step."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        initial = app.dns_mode
        app._dispatch_cmd(':set dns')
        assert app.dns_mode == (initial + 1) % len(pb.DNS_MODES)


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

    def test_no_args_shows_current_size(self, pb, tmp_path):
        """Calling :set history-size with no argument reports the current size in the event log."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = make_app(pb, cfg, '')
        app._dispatch_cmd(':set history-size')
        events = list(app.events)
        assert any('86400' in e for e in events), (
            f"Current history size not reported in events: {events}"
        )

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

