"""Unit tests for making a failing event-log write visible.

The streaming log opens, appends and closes on every event, and every failure
used to be swallowed:

    except OSError:
        pass  # silently ignore file write errors to avoid recursive events

So a log that stopped being written looked exactly like a log with nothing to
say.  Worse, only OSError was caught — a UnicodeEncodeError (a ValueError,
raised when the locale encoding cannot hold '→' or the banner's em dash) came
straight back out of add_event and killed its caller, which for the state loop
means every later host up/down event is lost for the rest of the run.

Covers:
  - a failing append is reported on screen, once, and does not raise
  - the report does not itself try to write the file
  - recovery is reported too
  - non-OSError failures are caught as well
  - ':log' with no argument reports whether the file is actually working
  - a dying thread names itself in the event log
"""

import os
import sys
import threading
from unittest.mock import patch

import pytest


@pytest.fixture
def hook_guard():
    """Put back whatever excepthook was installed — pytest has one of its own."""
    saved = threading.excepthook
    yield
    threading.excepthook = saved


def _events(app):
    return [e.text for e in app.events]


def _find(app, needle):
    return [t for t in _events(app) if needle in t]


@pytest.fixture
def app(pb):
    a = pb.Application([('host', '10.0.0.1'), ('host', '10.0.0.2')],
                       hosts_file='/opt/net/pb.hosts')
    a._monitoring_started = True
    return a


class TestFailureIsVisible:

    def test_a_failing_append_is_reported(self, app, tmp_path):
        """The path is a directory, so every open() for append fails."""
        app._cmd_log(str(tmp_path))          # a directory, not a file
        app.add_event('10.0.0.1', 'host down')
        assert _find(app, 'cannot write log file'), _events(app)

    def test_the_report_names_the_error(self, app, tmp_path):
        app._cmd_log(str(tmp_path))
        app.add_event('10.0.0.1', 'host down')
        line = _find(app, 'cannot write log file')[0]
        assert 'IsADirectoryError' in line, line
        assert str(tmp_path) in line

    def test_it_does_not_raise(self, app, tmp_path):
        """add_event runs in monitor threads and the state loop.

        An exception here used to travel up and kill whichever thread was
        reporting — the state loop being the expensive one to lose.
        """
        app._cmd_log(str(tmp_path))
        app.add_event('10.0.0.1', 'host down')   # must not raise

    def test_reported_only_once(self, app, tmp_path):
        """The failure repeats for every event; the complaint must not."""
        app._cmd_log(str(tmp_path))
        for i in range(20):
            app.add_event('10.0.0.1', f'event {i}')
        assert len(_find(app, 'cannot write log file')) == 1

    def test_a_non_oserror_is_caught_too(self, app, tmp_path):
        """'except OSError' let a UnicodeEncodeError through — a ValueError."""
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        with patch('builtins.open', side_effect=ValueError('bad encoding')):
            app.add_event('10.0.0.1', 'host down')   # must not raise
        assert _find(app, 'cannot write log file'), _events(app)
        assert 'ValueError' in _find(app, 'cannot write log file')[0]

    def test_the_report_itself_is_not_written_to_the_file(self, app, tmp_path):
        """Reporting through the broken file would recurse; it goes on screen."""
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'first')        # works
        calls = []
        real_open = open

        def flaky(path, *a, **kw):
            if str(path) == str(log):
                calls.append(path)
                raise OSError(28, 'No space left on device')
            return real_open(path, *a, **kw)

        with patch('builtins.open', side_effect=flaky):
            app.add_event('10.0.0.1', 'second')
        assert len(calls) == 1, 'the error report must not attempt a write'
        assert _find(app, 'cannot write log file')

    def test_recovery_is_reported(self, app, tmp_path):
        """A log that resumes after a gap must say so, or the gap is a mystery."""
        log = tmp_path / 'sub' / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'while broken')
        assert _find(app, 'cannot write log file')
        (tmp_path / 'sub').mkdir()
        app.add_event('10.0.0.1', 'after the fix')
        assert _find(app, 'log file writable again'), _events(app)
        assert 'after the fix' in log.read_text()

    def test_a_second_failure_is_reported_again_after_recovery(self, app, tmp_path):
        log = tmp_path / 'sub' / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'a')
        (tmp_path / 'sub').mkdir()
        app.add_event('10.0.0.1', 'b')
        log.unlink()
        os.rmdir(tmp_path / 'sub')
        app.add_event('10.0.0.1', 'c')
        assert len(_find(app, 'cannot write log file')) == 2


class TestLogStateReport:
    """':log' has to answer "is it broken, or just quiet?"."""

    def test_counts_the_lines_written(self, app, tmp_path):
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))          # itself logs 'logging to: …'
        before = app._log_lines_written
        for i in range(3):
            app.add_event('10.0.0.1', f'event {i}')
        app._cmd_log('')
        assert f'{before + 3} lines written' in _find(app, 'active log file')[-1]

    def test_reports_the_file_size(self, app, tmp_path):
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'x')
        app._cmd_log('')
        assert 'bytes' in _find(app, 'active log file')[-1]

    def test_reports_a_failure(self, app, tmp_path):
        app._cmd_log(str(tmp_path))
        app.add_event('10.0.0.1', 'x')
        app._cmd_log('')
        line = _find(app, 'active log file')[-1]
        assert 'last write FAILED' in line, line
        assert 'IsADirectoryError' in line

    def test_no_log_file_says_so(self, app):
        app._cmd_log('')
        assert _find(app, 'no log file active')

    def test_a_quiet_log_looks_healthy(self, app, tmp_path):
        """The point of the count: nothing wrong, nothing to say."""
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'x')
        app._cmd_log('')
        assert 'FAILED' not in _find(app, 'active log file')[-1]


class TestDyingThreadIsVisible:
    """A daemon thread's traceback goes to stderr, which curses paints over.

    check_state_changes is the only producer of host up/down events, so losing
    it stops the event log while the pings, the history and the UI carry on
    looking healthy — the report that started this.
    """

    @pytest.mark.filterwarnings('ignore::pytest.PytestUnhandledThreadExceptionWarning')
    def test_a_thread_death_reaches_the_event_log(self, app, pb, hook_guard):
        app._install_thread_excepthook()
        def boom():
            raise RuntimeError('cannot start new thread')
        t = threading.Thread(target=boom, name='pb-test-thread')
        t.start()
        t.join()
        assert _find(app, 'thread pb-test-thread died'), _events(app)
        assert _find(app, 'cannot start new thread')

    @pytest.mark.filterwarnings('ignore::pytest.PytestUnhandledThreadExceptionWarning')
    def test_it_reaches_the_log_file_too(self, app, tmp_path, hook_guard):
        """On screen is not enough: the file is what gets read afterwards."""
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app._install_thread_excepthook()

        def boom():
            raise RuntimeError('state loop equivalent')
        t = threading.Thread(target=boom, name='pb-file')
        t.start()
        t.join()
        assert 'thread pb-file died' in log.read_text(), log.read_text()

    @pytest.mark.filterwarnings('ignore::pytest.PytestUnhandledThreadExceptionWarning')
    def test_the_traceback_is_kept_at_debug_level(self, app, pb, hook_guard):
        app._install_thread_excepthook()
        def boom():
            raise ValueError('x')
        t = threading.Thread(target=boom, name='pb-tb')
        t.start()
        t.join()
        tb = [e for e in app.events if 'Traceback' in e.text]
        assert tb, _events(app)
        assert tb[0].level == pb.LEVEL_DEBUG

    @pytest.mark.filterwarnings('ignore::pytest.PytestUnhandledThreadExceptionWarning')
    def test_a_system_exit_is_not_an_error(self, app, hook_guard):
        app._install_thread_excepthook()
        t = threading.Thread(target=lambda: (_ for _ in ()).throw(SystemExit),
                             name='pb-exit')
        t.start()
        t.join()
        assert not _find(app, 'died')
        # Positive control: the hook is installed and does report a real fault,
        # so the absence above is a decision and not a hook that never ran.
        def boom():
            raise RuntimeError('control')
        c = threading.Thread(target=boom, name='pb-control')
        c.start()
        c.join()
        assert _find(app, 'thread pb-control died'), _events(app)


class TestStateLoopSurvives:
    """One bad monitor must not cost the other 58 their events."""

    def test_a_raising_monitor_does_not_stop_the_sweep(self, app, pb):
        """The other 58 hosts must still get their events in the same sweep.

        Patching the *instance*, not the class: both monitors are PingMonitor,
        so a class patch takes out the good one too and the test passes with
        the per-monitor guard deleted.
        """
        bad, good = app.monitors
        good.alive = True          # ready to produce 'host starts up'
        with patch.object(bad, '_expire_pending',
                          side_effect=RuntimeError('boom')):
            app._state_pass(3.0)   # the one failing sweep
        assert _find(app, 'host starts up'), _events(app)
        assert _find(app, 'RuntimeError: boom'), 'the fault must be reported'

    def test_the_monitor_error_is_reported_once(self, app):
        bad = app.monitors[0]
        with patch.object(bad, '_expire_pending',
                          side_effect=RuntimeError('boom')):
            for _ in range(5):
                app._state_pass(3.0)
        hits = _find(app, 'reported once')
        assert len(hits) == 1, hits

    def test_the_report_names_the_host(self, app):
        bad = app.monitors[0]
        with patch.object(bad, '_expire_pending',
                          side_effect=RuntimeError('boom')):
            app._state_pass(3.0)
        assert _find(app, '10.0.0.1'), _events(app)

    def test_an_error_outside_the_monitor_loop_is_caught(self, app):
        """check_state_changes must survive anything, not just monitor faults.

        Drives the real loop for one iteration — without the guard the
        exception comes back out of the call below, which is what killed the
        thread in the field.
        """
        app.running = True

        def blow_up(_secs):
            app.running = False      # so the loop ends after this iteration
            raise RuntimeError('boom')

        with patch.object(app, '_state_pass', side_effect=blow_up):
            app.check_state_changes()          # must return, not raise
        assert _find(app, 'state loop: RuntimeError: boom'), _events(app)

    def test_a_second_kind_of_fault_is_reported_again(self, app):
        """Reported once per (site, exception type) — a new fault is news."""
        bad = app.monitors[0]
        for exc in (RuntimeError('boom'), ValueError('other')):
            with patch.object(bad, '_expire_pending', side_effect=exc):
                for _ in range(3):
                    app._state_pass(3.0)
        assert len(_find(app, 'reported once')) == 2, _events(app)


class TestNonUtf8Locale:
    """The log file must not depend on the locale it was started with.

    open(path, 'a') uses locale.getpreferredencoding().  Under LANG=C that is
    ASCII, and the session banner's em dash — plus every relayed host's '→' —
    raises UnicodeEncodeError.  Being a ValueError it slipped past the old
    'except OSError', came back out of add_event, and killed the caller: for
    the state loop, every host up/down event for the rest of the run.

    Measured before the fix: 'UnicodeEncodeError: ... \\u2014', log file 0 bytes.
    A service unit with no LANG= is all it takes.
    """

    SCRIPT = """# -*- coding: utf-8 -*-
import importlib.machinery, importlib.util, os, sys
loader = importlib.machinery.SourceFileLoader('ping_bulk', sys.argv[1])
spec = importlib.util.spec_from_loader('ping_bulk', loader)
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)
app = pb.Application([('host', '10.0.0.1')], hosts_file='/x/pb.hosts')
app._monitoring_started = True
app.log_file = sys.argv[2]
app.add_event('ses-wg-video → 10.123.1.1', 'host down')
print(os.path.getsize(sys.argv[2]))
"""

    def _run(self, app_path, tmp_path):
        import subprocess
        log = tmp_path / 'ascii.log'
        # The driver goes in a file, not '-c': an ASCII command line cannot
        # carry the '→' the test is about.
        driver = tmp_path / 'driver.py'
        driver.write_text(self.SCRIPT, encoding='utf-8')
        env = dict(os.environ, LC_ALL='C', PYTHONUTF8='0',
                   PYTHONCOERCECLOCALE='0')
        env.pop('LANG', None)
        env.pop('LC_CTYPE', None)
        return subprocess.run(
            [sys.executable, str(driver), app_path, str(log)],
            capture_output=True, text=True, env=env), log

    def test_the_event_is_written_under_an_ascii_locale(self, app_path, tmp_path):
        done, log = self._run(app_path, tmp_path)
        assert done.returncode == 0, done.stderr
        assert int(done.stdout.strip()) > 0, 'nothing reached the file'

    def test_the_non_ascii_name_survives_as_utf8(self, app_path, tmp_path):
        """errors='replace' is the fallback, not the normal path."""
        done, log = self._run(app_path, tmp_path)
        assert done.returncode == 0, done.stderr
        text = log.read_text(encoding='utf-8')
        assert 'ses-wg-video → 10.123.1.1' in text, text
        assert '###### log started' in text
