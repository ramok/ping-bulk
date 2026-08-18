"""Unit tests for the event-log file: path resolution and -l precedence.

Covers:
  - _resolve_path expands a leading '~' and leaves everything else alone
  - ':log ~/pb.log' actually writes (it used to fail silently in open())
  - '-l' beats a ':log' in the hosts file and in the config file
  - ':log' typed interactively beats '-l'
  - hosts_file / kiosk_mode are set before startup commands are dispatched

The '~' cases matter because a failing open() in the append path is swallowed
by design (an error event there would recurse), so a bad path produced no
diagnostic at all — the log was simply empty forever.
"""

import os
import pathlib

from utils.hosts_helper import write_hosts


# ---------------------------------------------------------------------------
# _resolve_path
# ---------------------------------------------------------------------------

class TestResolvePath:

    def test_tilde_expands_to_home(self, pb):
        assert pb._resolve_path('~/pb.log') == os.path.join(
            os.path.expanduser('~'), 'pb.log')

    def test_absolute_path_unchanged(self, pb):
        assert pb._resolve_path('/var/log/pb.log') == '/var/log/pb.log'

    def test_relative_path_unchanged(self, pb):
        assert pb._resolve_path('pb.log') == 'pb.log'

    def test_empty_path_unchanged(self, pb):
        assert pb._resolve_path('') == ''

    def test_dollar_is_not_expanded(self, pb, monkeypatch):
        """'$' is resolved at parse time; a second pass would use other rules."""
        monkeypatch.setenv('PB_TEST_DIR', '/tmp')
        assert pb._resolve_path('$PB_TEST_DIR/pb.log') == '$PB_TEST_DIR/pb.log'

    def test_tilde_only(self, pb):
        assert pb._resolve_path('~') == os.path.expanduser('~')


class TestLogPathIsResolved:

    def test_tilde_log_path_is_stored_expanded(self, pb, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        app = pb.Application([('host', '127.0.0.1')])
        app._monitoring_started = True
        app._cmd_log('~/pb.log')
        assert app.log_file == str(tmp_path / 'pb.log')

    def test_tilde_log_path_actually_writes(self, pb, tmp_path, monkeypatch):
        """The regression: open('~/pb.log') raised and the error was swallowed."""
        monkeypatch.setenv('HOME', str(tmp_path))
        app = pb.Application([('host', '127.0.0.1')])
        app._monitoring_started = True
        app._cmd_log('~/pb.log')
        app.add_event('test', 'hello')
        assert (tmp_path / 'pb.log').exists(), "log file was never created"
        assert 'hello' in (tmp_path / 'pb.log').read_text()

    def test_save_follow_resolves_tilde(self, pb, tmp_path, monkeypatch):
        """':save --follow' sets the streaming path too, and used to skip '~'."""
        monkeypatch.setenv('HOME', str(tmp_path))
        app = pb.Application([('host', '127.0.0.1')])
        app._monitoring_started = True
        app._open_prompt_save('--follow ~/saved.log')
        assert app.log_file == str(tmp_path / 'saved.log')
        app.add_event('test', 'after-follow')
        assert 'after-follow' in (tmp_path / 'saved.log').read_text()

    def test_save_resolves_tilde(self, pb, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        app = pb.Application([('host', '127.0.0.1')])
        app._monitoring_started = True
        app.add_event('test', 'snapshot-me')
        app._open_prompt_save('~/snapshot.log')
        assert (tmp_path / 'snapshot.log').exists()
        assert 'snapshot-me' in (tmp_path / 'snapshot.log').read_text()

    def test_source_resolves_tilde(self, pb, tmp_path, monkeypatch):
        monkeypatch.setenv('HOME', str(tmp_path))
        (tmp_path / 'extra.hosts').write_text('10.9.9.9\n')
        app = pb.Application([('host', '127.0.0.1')])
        app._monitoring_started = True
        app._cmd_source('~/extra.hosts')
        assert '10.9.9.9' in [m.host for m in app.monitors]


# ---------------------------------------------------------------------------
# -l / --log-file precedence
# ---------------------------------------------------------------------------

class TestLogFilePrecedence:

    def test_cli_beats_hosts_file(self, pb):
        app = pb.Application([('cmd', ':log /tmp/from-script.log'),
                              ('host', '127.0.0.1')],
                             log_file='/tmp/from-cli.log')
        assert app.log_file == '/tmp/from-cli.log'

    def test_hosts_file_applies_without_cli_flag(self, pb):
        app = pb.Application([('cmd', ':log /tmp/from-script.log'),
                              ('host', '127.0.0.1')])
        assert app.log_file == '/tmp/from-script.log'

    def test_skipped_startup_log_is_reported(self, pb):
        app = pb.Application([('cmd', ':log /tmp/from-script.log')],
                             log_file='/tmp/from-cli.log')
        assert any(e.category == 'log' and '/tmp/from-cli.log' in e.text
                   for e in app.events), \
            "the ignored ':log' should leave a trace in the event log"

    def test_interactive_log_beats_cli_flag(self, pb):
        app = pb.Application([('host', '127.0.0.1')],
                             log_file='/tmp/from-cli.log')
        app._monitoring_started = True          # as after start_monitoring()
        app._cmd_log('/tmp/typed.log')
        assert app.log_file == '/tmp/typed.log'

    def test_interactive_log_off_beats_cli_flag(self, pb):
        app = pb.Application([('host', '127.0.0.1')],
                             log_file='/tmp/from-cli.log')
        app._monitoring_started = True
        app._cmd_log('off')
        assert app.log_file is None


# ---------------------------------------------------------------------------
# Constructor ordering
# ---------------------------------------------------------------------------

class TestConstructorContext:
    """hosts_file / kiosk_mode must be known while 'cmd' entries are dispatched.

    Both are proved through kiosk path checks, which read the pair during that
    dispatch.  Asserting the attributes directly would only pin the keyword
    arguments; a startup ':edit' would be the other reader, but it launches an
    editor, so it is not usable from a unit test.
    """

    def test_kiosk_mode_applies_to_startup_log_command(self, pb, tmp_path):
        """In kiosk mode a startup ':log' outside the allowed roots is refused.

        Before hosts_file/kiosk_mode moved into the constructor, kiosk_mode was
        still False during this dispatch, so the path check never ran.
        """
        # Not tmp_path: that lives under /tmp/, which kiosk mode allows.
        denied = '/var/tmp/pb-kiosk-denied.log'
        app = pb.Application([('cmd', f':log {denied}')],
                             hosts_file='/etc/ping-bulk/hosts',
                             kiosk_mode=True)
        assert app.log_file != denied

    def test_kiosk_mode_allows_log_beside_hosts_file(self, pb, tmp_path):
        """The 'directory containing the hosts file' prefix must be reachable.

        The hosts file deliberately lives outside /tmp/, or the test would pass
        on that prefix alone and stay green if the hosts-dir rule were deleted.
        (pytest's tmp_path is under /tmp/, hence /var/tmp/ here.)
        """
        outside = pathlib.Path('/var/tmp') / f'pb-kiosk-{os.getpid()}'
        outside.mkdir(parents=True, exist_ok=True)
        try:
            hosts = outside / 'hosts.txt'
            hosts.write_text('127.0.0.1\n')
            allowed = str(outside / 'beside.log')
            app = pb.Application([('cmd', f':log {allowed}')],
                                 hosts_file=str(hosts), kiosk_mode=True)
            assert app.log_file == allowed
        finally:
            for f in outside.iterdir():
                f.unlink()
            outside.rmdir()
