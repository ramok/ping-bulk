""":set autosave — write the config whenever a saved setting changes.

Off by default, because quietly rewriting a file somebody hand-edited is not
something to start doing unasked.  The generated first-run config names it
explicitly rather than leaving it commented, so the answer to "does this
program rewrite my file behind my back?" is in the file itself.

**What counts as a change is decided by comparing the rendered config**, not by
a list of which commands are persisted.  That list would be long — every
`:set`, plus `:layout`, `:log`, `:no-alarm`, `:relay-os`, `:prog-options` and
every user key binding — and would fall behind the next addition in silence.
"""

import os
import time

import pytest
from unittest.mock import patch


def _app(pb, tmp_path, started=True):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '10.0.0.1'), ('host', '10.0.0.2')])
    app._cfg = cfg
    if started:
        app._monitoring_started = True
        with patch.object(pb, '_config_path', return_value=cfg):
            app._config_on_disk = app._config_text()
    return app


def _run(pb, app, cmd):
    with patch.object(pb, '_config_path', return_value=app._cfg):
        app._dispatch_cmd(cmd)


class TestTheDefault:
    def test_it_is_off(self, pb, tmp_path):
        assert _app(pb, tmp_path).autosave is False

    def test_off_means_a_setting_change_writes_nothing(self, pb, tmp_path):
        app = _app(pb, tmp_path)
        before = open(app._cfg, encoding='utf-8').read()
        _run(pb, app, ':dns cycle')
        _run(pb, app, ':set sort latency')
        assert open(app._cfg, encoding='utf-8').read() == before

    def test_save_config_still_works_by_hand(self, pb, tmp_path):
        app = _app(pb, tmp_path)
        _run(pb, app, ':set sort latency')
        _run(pb, app, ':save-config')
        assert ':set sort latency' in open(app._cfg, encoding='utf-8').read()


class TestWhenItIsOn:
    @pytest.fixture
    def app(self, pb, tmp_path):
        a = _app(pb, tmp_path)
        _run(pb, a, ':set autosave on')
        return a

    def test_turning_it_on_saves_at_once(self, pb, tmp_path):
        """The setting that says "keep my settings" should not wait."""
        app = _app(pb, tmp_path)
        _run(pb, app, ':set sort latency')          # changed, not yet saved
        assert ':set sort latency' not in open(app._cfg, encoding='utf-8').read()
        _run(pb, app, ':set autosave on')
        assert ':set sort latency' in open(app._cfg, encoding='utf-8').read()

    def test_a_setting_change_is_written_immediately(self, pb, app):
        _run(pb, app, ':set sort name')
        assert ':set sort name' in open(app._cfg, encoding='utf-8').read()

    @pytest.mark.parametrize('cmd,expect', [
        (':dns cycle', ':set dns hostname'),   # the value, not the key:
        # ':set dns' alone matches the commented '# :set dns off' the
        # skeleton writes, so it passes even with autosave absent.
        (':set log-size 4321', ':set log-size 4321'),
        (':layout log', ':layout log'),
        (':no-alarm 10.0.0.*', ':no-alarm 10.0.0.*'),
        (':set late-grace 3', ':set late-grace 3'),
    ])
    def test_it_covers_more_than_set(self, pb, app, cmd, expect):
        """Not a list of commands — anything the config holds."""
        _run(pb, app, cmd)
        assert expect in open(app._cfg, encoding='utf-8').read(), cmd

    @pytest.mark.parametrize('cmd', [':seen', ':help', ':close', ':clear'])
    def test_a_command_that_persists_nothing_writes_nothing(self, pb, app, cmd):
        mtime = os.path.getmtime(app._cfg)
        time.sleep(0.01)
        _run(pb, app, cmd)
        assert os.path.getmtime(app._cfg) == mtime, cmd

    def test_an_unchanged_setting_writes_nothing(self, pb, app):
        """':set sort name' twice is one write, not two."""
        _run(pb, app, ':set sort name')
        mtime = os.path.getmtime(app._cfg)
        time.sleep(0.01)
        _run(pb, app, ':set sort name')
        assert os.path.getmtime(app._cfg) == mtime

    def test_it_round_trips(self, pb, app):
        _run(pb, app, ':set sort name')
        with patch.object(pb, '_config_path', return_value=app._cfg):
            fresh = pb.Application([('host', '10.0.0.1')])
        assert fresh.autosave is True
        assert fresh.sort_by == 'name'


class TestItDoesNotFireDuringStartup:
    def test_a_hosts_file_setting_is_not_written_to_the_user_config(self, pb,
                                                                    tmp_path):
        """Hosts-file settings belong to the file that declared them.

        _autosave is guarded on _monitoring_started, which is False while a
        config or hosts file is being read — otherwise opening somebody's
        hosts file would rewrite your own preferences.
        """
        app = _app(pb, tmp_path, started=False)
        app.autosave = True
        before = open(app._cfg, encoding='utf-8').read()
        _run(pb, app, ':set sort latency')          # as a file would
        assert open(app._cfg, encoding='utf-8').read() == before


@pytest.mark.skipif(os.geteuid() == 0,
                    reason='root ignores directory permissions, so the write '
                           'cannot be made to fail this way')
class TestAFailedSaveIsNotSilent:
    """Believing settings are kept when they are not is the worst outcome.

    ``_save_config`` reports under category 'config', which is LEVEL_INFO and
    therefore invisible at the default level.  With autosave on, every command
    retries — measured, 24 failed writes in 25 commands, none of them visible
    — which is both a silent data loss and the flood the previous commit
    existed to stop.  So: said once, and said again only when it recovers.
    """

    @pytest.fixture
    def app(self, pb, tmp_path):
        a = _app(pb, tmp_path)
        _run(pb, a, ':set autosave on')
        return a

    def test_the_first_failure_is_reported(self, pb, app):
        os.chmod(os.path.dirname(app._cfg), 0o555)
        try:
            app._status_msg = None
            n = len(app.events)
            _run(pb, app, ':set log-size 4321')
            shown = [e.text for e in list(app.events)[n:]
                     if e.level <= app.loglevel]
            assert len(shown) == 1, shown
            assert 'not being saved' in shown[0]
            assert app._status_msg
        finally:
            os.chmod(os.path.dirname(app._cfg), 0o755)

    def test_it_is_not_repeated_for_every_command(self, pb, app):
        os.chmod(os.path.dirname(app._cfg), 0o555)
        try:
            n = len(app.events)
            for i in range(25):
                _run(pb, app, ':set log-size %d' % (5000 + i))
            shown = [e.text for e in list(app.events)[n:]
                     if e.level <= app.loglevel]
            assert len(shown) == 1, len(shown)
        finally:
            os.chmod(os.path.dirname(app._cfg), 0o755)

    def test_recovery_is_reported_too(self, pb, app):
        os.chmod(os.path.dirname(app._cfg), 0o555)
        try:
            _run(pb, app, ':set log-size 4321')
        finally:
            os.chmod(os.path.dirname(app._cfg), 0o755)
        n = len(app.events)
        _run(pb, app, ':set log-size 8765')
        shown = [e.text for e in list(app.events)[n:]
                 if e.level <= app.loglevel]
        assert any('saving again' in t for t in shown), shown
        assert ':set log-size 8765' in open(app._cfg, encoding='utf-8').read()

    def test_the_existing_config_is_not_destroyed_by_a_failed_save(self, pb,
                                                                   app):
        """A truncating write would leave an empty file; this one must not."""
        before = open(app._cfg, encoding='utf-8').read()
        assert before
        os.chmod(os.path.dirname(app._cfg), 0o555)
        try:
            _run(pb, app, ':set log-size 4321')
        finally:
            os.chmod(os.path.dirname(app._cfg), 0o755)
        assert open(app._cfg, encoding='utf-8').read() == before


class TestTheGeneratedConfig:
    def test_a_first_run_names_the_setting(self, pb, tmp_path):
        app = _app(pb, tmp_path, started=False)
        assert ':set autosave off' in open(app._cfg, encoding='utf-8').read()

    def test_it_is_not_created_when_one_exists(self, pb, tmp_path):
        cfg = tmp_path / 'ping-bulk' / 'config'
        os.makedirs(str(cfg.parent), exist_ok=True)
        cfg.write_text('# mine\n:set sort latency\n', encoding='utf-8')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([('host', '10.0.0.1')])
        assert cfg.read_text(encoding='utf-8') == '# mine\n:set sort latency\n'
        assert app.sort_by == 'latency'


class TestTheParameterFollowsTheHouseRule:
    """AGENTS.md §11: bare reports, cycle steps, anything else is a value."""

    def test_bare_reports_and_changes_nothing(self, pb, tmp_path):
        app = _app(pb, tmp_path)
        _run(pb, app, ':set autosave')
        assert app.autosave is False
        assert app._status_msg and 'autosave' in app._status_msg['text']

    def test_cycle_steps(self, pb, tmp_path):
        app = _app(pb, tmp_path)
        _run(pb, app, ':set autosave cycle')
        assert app.autosave is True
        _run(pb, app, ':set autosave cycle')
        assert app.autosave is False

    def test_a_bad_value_is_refused_visibly(self, pb, tmp_path):
        app = _app(pb, tmp_path)
        app._status_msg = None
        n = len(app.events)
        _run(pb, app, ':set autosave yes')
        assert app.autosave is False
        assert [e for e in list(app.events)[n:] if e.level <= app.loglevel]
        assert app._status_msg
