"""Unit tests for custom stats columns (:set stats last,avg,stdev).

Covers:
  - Comma-list parsing → stats_custom set correctly
  - Clear with bare comma → stats_mode=0, stats_custom=None
  - Unknown name → event log error
  - cycle_stats includes custom slot
  - saveconfig emits correct format
  - Autocomplete: no comma → all names; comma → remaining excluding all/off
  - 'down' header → 'Up/Down'

No ping threads are started; state is set directly on attributes.
Real config file is never touched — _config_path() is patched to tmp dir.
"""

import os
import io
import pytest
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_app(pb, cfg_path, entries=None):
    if entries is None:
        entries = [('host', '127.0.0.1')]
    os.makedirs(os.path.dirname(cfg_path), exist_ok=True)
    with open(cfg_path, 'w') as f:
        f.write('')
    with patch.object(pb, '_config_path', return_value=cfg_path):
        app = pb.Application(entries, log_file=None)
    return app


def make_monitor(pb, host='127.0.0.1', **attrs):
    m = pb.PingMonitor(host)
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app(pb, tmp_path):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    return make_app(pb, cfg)


# ===========================================================================
# Parsing
# ===========================================================================

class TestCmdStatsParsing:
    """_cmd_stats() correctly parses comma lists and sets state."""

    def test_single_valid_stat_name(self, app, pb):
        """':set stats last' sets stats_custom=['Last'] and stats_mode=sentinel."""
        app._dispatch_cmd(':set stats last')
        assert app.stats_custom == ['Last'], app.stats_custom
        assert app.stats_mode == pb._CUSTOM_STATS_SENTINEL

    def test_comma_list_sets_custom(self, app, pb):
        """':set stats avg,stdev,loss%' sets custom list with canonical names."""
        app._dispatch_cmd(':set stats avg,stdev,loss%')
        assert app.stats_custom == ['Avg', 'StDev', 'Loss%'], app.stats_custom
        assert app.stats_mode == pb._CUSTOM_STATS_SENTINEL

    def test_case_insensitive(self, app, pb):
        """':set stats AVG,STDEV' is case-insensitive."""
        app._dispatch_cmd(':set stats AVG,STDEV')
        assert app.stats_custom == ['Avg', 'StDev']

    def test_bare_comma_clears_custom(self, app, pb):
        """':set stats ,' resets to off (stats_mode=0, stats_custom=None)."""
        app._dispatch_cmd(':set stats avg,stdev')
        assert app.stats_custom is not None
        app._dispatch_cmd(':set stats ,')
        assert app.stats_custom is None
        assert app.stats_mode == 0

    def test_all_not_valid_in_comma_list(self, app, pb):
        """':set stats avg,all' → event logged (unknown column), state unchanged."""
        app._monitoring_started = True
        initial_custom = app.stats_custom
        app._dispatch_cmd(':set stats avg,all')
        # 'all' is not in STAT_NAMES → cmd event logged, stats_custom unchanged
        events = [e for e in app.events if 'unknown' in e]
        assert events, "Expected event for 'all' in comma list"
        assert app.stats_custom == initial_custom

    def test_unknown_name_logs_error(self, app, pb):
        """':set stats bogus' logs a cmd event with 'unknown'."""
        app._monitoring_started = True
        app._dispatch_cmd(':set stats bogus')
        events = [e for e in app.events if 'unknown' in e]
        assert events, "Expected event for unknown stat name"

    def test_known_stats_mode_name_sets_mode(self, app, pb):
        """':set stats avg' (STATS_MODES name) sets stats_mode normally, clears custom."""
        app._dispatch_cmd(':set stats avg,stdev')  # first set custom
        assert app.stats_custom is not None
        app._dispatch_cmd(':set stats avg')  # avg is in STATS_MODES too
        # avg is both in STATS_MODES and STAT_NAMES; STATS_MODES takes priority
        assert app.stats_custom is None
        idx = [m.lower() for m in pb.STATS_MODES].index('avg')
        assert app.stats_mode == idx


# ===========================================================================
# Cycle stats
# ===========================================================================

class TestCycleStatsWithCustom:
    """cycle_stats() includes custom sentinel when stats_custom is set."""

    def test_cycle_length_extended_when_custom(self, app, pb):
        """With stats_custom set, cycling through all modes reaches the sentinel."""
        app._dispatch_cmd(':set stats last,avg')
        n_modes = len(pb.STATS_MODES)
        # Set back to 0 and cycle through all modes
        app.stats_mode = 0
        seen_sentinel = False
        for _ in range(n_modes + 2):
            app.cycle_stats(1)
            if app.stats_mode == pb._CUSTOM_STATS_SENTINEL:
                seen_sentinel = True
                break
        assert seen_sentinel, "cycle_stats should reach the custom sentinel"

    def test_cycle_from_sentinel_wraps_to_zero(self, app, pb):
        """After the custom sentinel, the next cycle step returns to off (0)."""
        app._dispatch_cmd(':set stats last,avg')
        app.stats_mode = pb._CUSTOM_STATS_SENTINEL
        app.cycle_stats(1)
        assert app.stats_mode == 0, f"Expected 0, got {app.stats_mode}"

    def test_no_custom_cycle_length_unchanged(self, app, pb):
        """Without custom stats, cycle stays within STATS_MODES."""
        app.stats_custom = None
        app.stats_mode = len(pb.STATS_MODES) - 1
        app.cycle_stats(1)
        assert app.stats_mode == 0


# ===========================================================================
# Saveconfig
# ===========================================================================

class TestSaveconfigCustom:
    """_cmd_saveconfig emits correct format for custom stats."""

    def _capture_saveconfig(self, app, tmp_path):
        cfg = str(tmp_path / 'saved_config')
        with patch.object(type(app).__module__ and app, '_config_path',
                          return_value=cfg) if False else \
             patch('builtins.open', create=True) as _:
            # Use real file approach
            pass
        # Write via real _cmd_saveconfig to a temp file
        with patch.object(
            __import__('importlib').util.find_spec('builtins') or object(), 'x', None
        ) if False else io.StringIO() as buf:
            pass
        return cfg

    def test_saveconfig_emits_custom_format(self, app, pb, tmp_path):
        """saveconfig writes ':set stats last,avg' for custom mode."""
        app._dispatch_cmd(':set stats last,avg')
        cfg_file = str(tmp_path / 'test_config')
        with patch.object(pb, '_config_path', return_value=cfg_file):
            app._dispatch_cmd(':saveconfig')
        content = open(cfg_file).read()
        assert ':set stats last,avg' in content, (
            f"Expected ':set stats last,avg' in saveconfig, got:\n{content}"
        )

    def test_saveconfig_standard_mode_unchanged(self, app, pb, tmp_path):
        """saveconfig writes ':set stats Avg' (canonical form) for STATS_MODES mode."""
        app._dispatch_cmd(':set stats avg')
        # avg is in STATS_MODES → standard mode, stats_custom=None
        assert app.stats_custom is None
        cfg_file = str(tmp_path / 'test_config2')
        with patch.object(pb, '_config_path', return_value=cfg_file):
            app._dispatch_cmd(':saveconfig')
        content = open(cfg_file).read()
        assert ':set stats Avg' in content, (
            f"Expected ':set stats Avg' in saveconfig, got:\n{content}"
        )

    def test_saveconfig_off_mode(self, app, pb, tmp_path):
        """saveconfig writes ':set stats off' when stats is off."""
        app.stats_mode = 0
        app.stats_custom = None
        cfg_file = str(tmp_path / 'test_config3')
        with patch.object(pb, '_config_path', return_value=cfg_file):
            app._dispatch_cmd(':saveconfig')
        content = open(cfg_file).read()
        assert ':set stats off' in content, (
            f"Expected ':set stats off' in saveconfig, got:\n{content}"
        )


# ===========================================================================
# Autocomplete
# ===========================================================================

class TestCustomStatsAutocomplete:
    """_complete_stats_arg() returns context-sensitive completions."""

    def test_no_comma_returns_all_names(self, app, pb):
        """No comma in prefix: all STATS_MODES + STAT_NAMES returned."""
        result = app._complete_stats_arg('')
        expected = sorted(
            set(m.lower() for m in pb.STATS_MODES) | set(pb.STAT_NAMES.keys())
        )
        assert result == expected, result

    def test_no_comma_prefix_filtered(self, app, pb):
        """Prefix 'av' → only 'avg'."""
        result = app._complete_stats_arg('av')
        assert result == ['avg'], result

    def test_comma_excludes_all_and_off(self, app, pb):
        """Comma present: 'all' and 'off' are excluded."""
        result = app._complete_stats_arg('avg,')
        candidates = [c.split(',')[-1] for c in result]
        assert 'all' not in candidates, result
        assert 'off' not in candidates, result

    def test_comma_excludes_already_used(self, app, pb):
        """Comma present: already-used names are excluded."""
        result = app._complete_stats_arg('avg,')
        candidates = [c.split(',')[-1] for c in result]
        assert 'avg' not in candidates, result

    def test_comma_prefix_filter(self, app, pb):
        """After comma, typed prefix filters candidates."""
        result = app._complete_stats_arg('avg,st')
        # 'stdev' should be there, nothing else starting with 'st'
        candidates = [c.split(',')[-1] for c in result]
        assert 'stdev' in candidates, result
        for c in candidates:
            assert c.startswith('st'), f"Unexpected: {c}"

    def test_comma_returns_full_replacement(self, app, pb):
        """Comma completions return the full prefix + candidate."""
        result = app._complete_stats_arg('avg,')
        for r in result:
            assert r.startswith('avg,'), f"Missing prefix in: {r}"


# ===========================================================================
# Header strings
# ===========================================================================

class TestStatHeaders:
    """_STAT_HEADER maps canonical names to the correct header strings."""

    def test_down_header_is_up_down(self, pb):
        assert pb._STAT_HEADER['Down'] == 'Up/Down'

    def test_last_header_is_ms(self, pb):
        assert pb._STAT_HEADER['Last'] == 'ms'

    def test_loss_pct_header(self, pb):
        assert pb._STAT_HEADER['Loss%'] == 'Loss%'

    def test_all_canonical_names_in_header(self, pb):
        for canonical in pb.STAT_NAMES.values():
            assert canonical in pb._STAT_HEADER, (
                f"Missing header for canonical name '{canonical}'"
            )
