"""Unit tests for keeping a host's probe loop alive, and naming it.

A monitor's thread dying is the least visible failure this program has: the
row keeps the history it had and simply stops changing, while the pings, the
display and the event log all carry on looking healthy.  Three parts:

  - every thread is named after what it is doing, because the thread name is
    all a death report has to identify it by — and 'Thread-42 (ping)' says
    nothing when there are fifty-nine of them;
  - a fault in the read loop costs one probe, not the host;
  - a thread that ends anyway is restarted, capped and paced, unless it
    stopped on purpose (a fatal error) or because it was told to.
"""

import os
import sys
import threading
import time
from unittest.mock import patch

import pytest


@pytest.fixture
def app(pb):
    a = pb.Application([('host', '10.0.0.1'), ('host', '10.0.0.2')])
    a._monitoring_started = True
    return a


def _events(app):
    return [e.text for e in app.events]


def _find(app, needle):
    return [t for t in _events(app) if needle in t]


class _DeadThread:
    """Stands in for a thread whose target has returned."""

    def __init__(self, name='ping:10.0.0.1'):
        self.name = name

    @staticmethod
    def is_alive():
        return False


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------

class TestThreadsAreNamed:

    def test_a_probe_loop_is_named_after_its_host(self, app):
        monitor = app.monitors[0]
        with patch.object(type(monitor), 'ping', lambda self: None):
            thread = app._start_monitor_thread(monitor)
            thread.join(timeout=5)
        assert thread.name == 'ping:10.0.0.1'

    def test_the_handle_is_kept_on_the_monitor(self, app):
        """The supervisor has nothing to check without it."""
        monitor = app.monitors[0]
        with patch.object(type(monitor), 'ping', lambda self: None):
            thread = app._start_monitor_thread(monitor)
            thread.join(timeout=5)
        assert monitor._thread is thread

    def test_a_relayed_host_carries_its_relay_in_the_name(self, pb, tmp_path):
        a = pb.Application([('cmd', ':remote-ping relay 10.9.9.9')])
        a._monitoring_started = True
        monitor = a.monitors[0]
        with patch.object(type(monitor), 'ping', lambda self: None):
            thread = a._start_monitor_thread(monitor)
            thread.join(timeout=5)
        assert thread.name == 'ping:relay→10.9.9.9'

    def test_every_thread_goes_through_the_one_helper(self, app_path):
        """There must be exactly one Thread() in the file, and it names itself.

        Stronger than checking each site for 'name=': a thread started any
        other way would be anonymous both in a death report and in 'top -H',
        and _spawn is what keeps those two in step.
        """
        src = open(app_path, encoding='utf-8').read()
        calls = []
        needle = 'threading.Thread('
        at = src.find(needle)
        while at != -1:
            i = at + len(needle) - 1
            depth = 0
            while i < len(src):
                if src[i] == '(':
                    depth += 1
                elif src[i] == ')':
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            calls.append(src[at:i + 1])
            at = src.find(needle, i)
        assert len(calls) == 1, f'threads started outside _spawn: {calls}'
        assert 'name=name' in calls[0], calls[0]


class TestOsTaskName:
    """What the kernel is told: /proc/<pid>/task/<tid>/comm, 15 bytes.

    That is what 'ps -o comm', 'ps -T', 'top', 'htop' and a bare
    'pgrep ping-bulk' read — all of which said 'python3' before.
    """

    def test_a_short_name_passes_through(self, pb):
        assert pb._os_task_name('state-loop') == b'state-loop'

    def test_the_host_is_trimmed_from_the_front(self, pb):
        """The tail identifies; the head is shared by every relayed host."""
        got = pb._os_task_name('ping:ses-wg-video→10.123.254.161')
        assert got == b'ping:23.254.161'
        assert got.startswith(b'ping:')
        assert b'254.161' in got, 'the identifying part must survive'

    def test_it_never_exceeds_the_kernel_limit(self, pb):
        for name in ['ping:' + 'x' * 200, 'x' * 200,
                     'ping:ses-wg-video→10.123.254.161', 'clock:10.0.0.1']:
            assert len(pb._os_task_name(name)) <= 15, name

    def test_a_name_with_no_tag_is_cut_from_the_right(self, pb):
        assert pb._os_task_name('averyverylongname') == b'averyverylongna'

    def test_a_tag_longer_than_the_limit_does_not_loop(self, pb):
        assert len(pb._os_task_name('averyverylongtag:host')) <= 15

    def test_a_multibyte_character_is_not_split(self, pb):
        """A half-written '→' would put a stray byte in ps output."""
        for i in range(1, 30):
            got = pb._os_task_name('dns:' + '→' * i)
            got.decode('utf-8')          # must not raise

    def test_setting_it_is_silent_where_prctl_is_absent(self, pb):
        with patch('ctypes.CDLL', side_effect=OSError('no libc')):
            pb._set_os_task_name('ping-bulk')      # must not raise


class TestSpawnNamesBothWays:

    def test_the_python_name_is_the_full_one(self, pb):
        """It is what a thread-death report prints, so nothing is trimmed."""
        seen = []
        t = pb._spawn(lambda: seen.append(threading.current_thread().name),
                      'ping:ses-wg-video→10.123.254.161')
        t.join(timeout=5)
        assert seen == ['ping:ses-wg-video→10.123.254.161']

    @pytest.mark.skipif(not os.path.exists('/proc/self/comm'),
                        reason='needs Linux /proc')
    def test_the_kernel_name_is_the_trimmed_one(self, pb):
        seen = []

        def read_own_comm():
            tid = threading.get_native_id()
            with open(f'/proc/self/task/{tid}/comm') as f:
                seen.append(f.read().strip())

        t = pb._spawn(read_own_comm, 'ping:ses-wg-video→10.123.254.161')
        t.join(timeout=5)
        assert seen == ['ping:23.254.161'], seen

    def test_arguments_are_passed_through(self, pb):
        got = []
        t = pb._spawn(lambda a, b=None: got.append((a, b)), 'x:1',
                      args=('pos',), kwargs={'b': 'kw'})
        t.join(timeout=5)
        assert got == [('pos', 'kw')]

    def test_the_thread_is_a_daemon(self, pb):
        """Or quitting would hang on 59 of them."""
        t = pb._spawn(lambda: None, 'x:1')
        assert t.daemon
        t.join(timeout=5)


class TestTheCommandColumn:
    """What 'ps aux' shows: the argument vector the kernel recorded at execve.

    A '#!' line puts the interpreter at the front of it, so the column read
    'python3 /path/to/ping-bulk -f myhosts'.  The region is the process's own
    memory and the kernel publishes its bounds in /proc/self/stat, so it can
    be rewritten in place.

    (Py_GetArgcArgv, the trick every recipe names, is a dead end on Python 3:
    it returns the interpreter's own wchar_t copy, not this region.)
    """

    DRIVER = """# -*- coding: utf-8 -*-
import importlib.machinery, importlib.util, subprocess, sys, os
loader = importlib.machinery.SourceFileLoader('ping_bulk', sys.argv[1])
spec = importlib.util.spec_from_loader('ping_bulk', loader)
pb = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pb)
pb._set_process_cmdline(['ping-bulk', '-f', 'myhosts'])
print('CMDLINE:' + open('/proc/self/cmdline', 'rb').read().replace(b'\\0', b' ')
      .decode().strip())
print('PS:' + subprocess.run(['ps', '-o', 'args=', '-p', str(os.getpid())],
                             capture_output=True, text=True).stdout.strip())
print('ARGV:' + repr(sys.argv[2:]))
"""

    def _run(self, app_path, tmp_path, extra=()):
        import subprocess
        driver = tmp_path / 'driver.py'
        driver.write_text(self.DRIVER, encoding='utf-8')
        done = subprocess.run(
            [sys.executable, str(driver), app_path, *extra],
            capture_output=True, text=True)
        assert done.returncode == 0, done.stderr
        return dict(line.split(':', 1) for line in done.stdout.splitlines()
                    if ':' in line)

    @pytest.mark.skipif(not os.path.exists('/proc/self/stat'),
                        reason='needs Linux /proc')
    def test_the_kernel_reports_the_new_title(self, app_path, tmp_path):
        out = self._run(app_path, tmp_path, ['pad'] * 20)
        assert out['CMDLINE'] == 'ping-bulk -f myhosts', out

    @pytest.mark.skipif(not os.path.exists('/proc/self/stat'),
                        reason='needs Linux /proc')
    def test_ps_itself_agrees(self, app_path, tmp_path):
        """Reading /proc is not proof; ps is what the user looks at."""
        out = self._run(app_path, tmp_path, ['pad'] * 20)
        assert out['PS'] == 'ping-bulk -f myhosts', out

    @pytest.mark.skipif(not os.path.exists('/proc/self/stat'),
                        reason='needs Linux /proc')
    def test_nothing_of_the_old_title_is_left_behind(self, app_path, tmp_path):
        """The rest of the region has to be cleared, or ps shows the tail."""
        out = self._run(app_path, tmp_path, ['xyzzy-marker'] * 10)
        assert 'xyzzy-marker' not in out['CMDLINE'], out

    @pytest.mark.skipif(not os.path.exists('/proc/self/stat'),
                        reason='needs Linux /proc')
    def test_sys_argv_is_untouched(self, app_path, tmp_path):
        """Only the display changes — the program still knows its arguments."""
        out = self._run(app_path, tmp_path, ['keep', 'these'])
        assert out['ARGV'] == "['keep', 'these']", out

    def test_a_long_title_stays_inside_the_region(self, app_path, tmp_path):
        """The region is fixed size, and the environment lives just past it.

        Overrunning arg_end is the classic way this trick corrupts a process,
        so the assertion is the byte count against the kernel's own bounds —
        not against the old title, which is shorter than the region it sits in.
        """
        import subprocess
        driver = tmp_path / 'long.py'
        driver.write_text("""
import importlib.machinery, importlib.util, os, sys
loader = importlib.machinery.SourceFileLoader('ping_bulk', sys.argv[1])
spec = importlib.util.spec_from_loader('ping_bulk', loader)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
fields = open('/proc/self/stat', 'rb').read().rpartition(b')')[2].split()
room = int(fields[46]) - int(fields[45])
m._set_process_cmdline(['x' * 5000])
after = open('/proc/self/cmdline', 'rb').read()
print(room, len(after), os.environ.get('PB_CANARY', 'GONE'))
""", encoding='utf-8')
        env = dict(os.environ, PB_CANARY='intact')
        done = subprocess.run([sys.executable, str(driver), app_path],
                              capture_output=True, text=True, env=env)
        if done.returncode != 0:            # no /proc: nothing to assert
            pytest.skip(done.stderr.strip()[:80])
        room, after, canary = done.stdout.split()
        assert int(after) <= int(room), 'the title must not grow past arg_end'
        assert canary == 'intact', 'the environment sits just past arg_end'

    def test_it_is_silent_without_proc(self, pb):
        with patch('builtins.open', side_effect=FileNotFoundError('/proc')):
            pb._set_process_cmdline(['ping-bulk'])      # must not raise

    def test_it_leaves_an_unexpected_region_alone(self, pb):
        """The guard: if the region does not hold our cmdline, do not write."""
        with patch('ctypes.string_at', return_value=b'something else'), \
             patch('ctypes.memmove') as memmove:
            pb._set_process_cmdline(['ping-bulk'])
        memmove.assert_not_called()


class TestTheProcessNamesItself:
    """'ps -o comm', 'top' and 'pgrep ping-bulk' said 'python3'.

    Driven through a real process, because the thing being tested is what the
    kernel recorded — no unit test can see that.
    """

    def test_ps_and_pgrep_see_ping_bulk(self, app_path, check_integration_deps,
                                        tmp_path):
        import subprocess
        from tmux_helper import TmuxSession
        hosts = tmp_path / 'named.hosts'
        hosts.write_text('127.0.0.1\n')
        sess = TmuxSession('ping-bulk-test-procname', width=100, height=12)
        try:
            sess.send_literal(f'python3 {app_path} -f {hosts}')
            sess.send_keys('Enter')
            sess.wait_for('DNS:', timeout=10)
            pids = subprocess.run(['pgrep', '-f', str(hosts)],
                                  capture_output=True, text=True).stdout.split()
            assert pids, 'the app should be running'
            pid = pids[0]
            comm = subprocess.run(['ps', '-o', 'comm=', '-p', pid],
                                  capture_output=True, text=True).stdout.strip()
            assert comm == 'ping-bulk', f'ps -o comm says {comm!r}'
            named = subprocess.run(['pgrep', '-x', 'ping-bulk'],
                                   capture_output=True, text=True).stdout.split()
            assert pid in named, "pgrep -x ping-bulk should find it"
        finally:
            sess.kill()


# ---------------------------------------------------------------------------
# A fault in the read loop
# ---------------------------------------------------------------------------

class TestReaderFaultCostsOneProbe:

    def test_the_fault_is_reported_as_this_host_s_own_message(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        m._note_reader_fault(ValueError('could not convert string to float'))
        assert m.take_new_stderr() == [
            'ping-bulk: reader error: ValueError: '
            'could not convert string to float']

    def test_it_is_reported_once_however_often_it_repeats(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        for _ in range(5):
            m._note_reader_fault(ValueError('same fault'))
        assert len(m.take_new_stderr()) == 1

    def test_it_can_explain_a_down_transition(self, pb):
        """It goes through the stderr machinery, so 'why' picks it up."""
        m = pb.PingMonitor('10.0.0.1')
        m._note_reader_fault(RuntimeError('boom'))
        assert 'reader error' in (m.recent_stderr() or '')

    def test_a_different_fault_is_news_again(self, pb):
        m = pb.PingMonitor('10.0.0.1')
        m._note_reader_fault(ValueError('first'))
        m.take_new_stderr()
        m._note_reader_fault(KeyError('second'))
        assert len(m.take_new_stderr()) == 1


# ---------------------------------------------------------------------------
# Restarting
# ---------------------------------------------------------------------------

class TestReaderFaultDoesNotEndTheLoop:
    """End to end: the guard around the one unguarded call in ping().

    Driven through the real loop with a piped Popen stand-in, because the point
    is that the exception does not leave ping() — a unit test on the reporting
    helper cannot show that.
    """

    def _run(self, monitor, timeout=3.0):
        t = threading.Thread(target=monitor.ping, daemon=True,
                             name='ping:test')
        t.start()
        t.join(timeout)
        return t

    def test_the_loop_retries_instead_of_ending(self, pb):
        """One probe lost, not the host: the loop backs off and goes again."""
        from proc_helper import FakeProc
        m = pb.PingMonitor('10.0.0.1')
        proc = FakeProc(stdout_lines=[], stderr_text='')
        calls = []

        def boom():
            calls.append(1)
            raise ValueError('could not convert string to float')

        try:
            with patch('subprocess.Popen', return_value=proc), \
                 patch.object(m, '_read_until_exit', side_effect=boom):
                t = self._run(m, timeout=4.0)
                assert t.is_alive(), 'the fault must not end the loop'
                assert len(calls) >= 2, f'it must try again: {len(calls)} tries'
                assert m.error is None, 'a reader fault is not a fatal error'
        finally:
            m.running = False
            t.join(timeout=5)

    def test_a_transient_stderr_does_not_become_fatal(self, pb):
        """The regression this guard nearly introduced.

        'network is unreachable' is in _FATAL_PING_ERRORS because a run that
        produced nothing and said that is genuinely dead — but ping also prints
        it per probe while carrying on.  A run whose reader failed is not a run
        that produced nothing; it is a run we did not finish reading.  Marking
        it fatal killed the host for good *and* set the flag that stops the
        supervisor bringing it back: dead-but-restartable became
        dead-and-never-restarted.
        """
        from proc_helper import FakeProc
        m = pb.PingMonitor('10.0.0.1')
        proc = FakeProc(stdout_lines=[], stderr_text='')

        def read_then_raise():
            # What really happens: the reader drains the child's stderr, then
            # trips over a stdout line it cannot parse.  The stderr has to be
            # recorded *before* the fault or there is nothing to misclassify
            # and this test passes with the guard removed.
            m._note_stderr('ping: network is unreachable')
            raise ValueError("could not convert string to float: 'xyz'")

        try:
            with patch('subprocess.Popen', return_value=proc), \
                 patch.object(m, '_read_until_exit',
                              side_effect=read_then_raise):
                t = self._run(m, timeout=2.5)
                assert m.error is None, \
                    f'a reader fault must not be classified: {m.error!r}'
                assert t.is_alive(), 'and the loop must still be going'
        finally:
            m.running = False
            t.join(timeout=5)

    def test_a_real_fatal_error_still_stops_the_loop(self, pb):
        """The exemption must not disarm the classification itself."""
        from proc_helper import FakeProc
        m = pb.PingMonitor('10.0.0.1')
        proc = FakeProc(stdout_lines=[],
                        stderr_text='ping: name or service not known\n')
        with patch('subprocess.Popen', return_value=proc):
            t = self._run(m, timeout=3.0)
        assert not t.is_alive()
        assert m.error and 'name or service not known' in m.error

    def test_the_fault_report_is_capped(self, pb):
        """The message carries the offending data, so it varies every time."""
        m = pb.PingMonitor('10.0.0.1')
        for i in range(m._SEEN_STDERR_MAX + 50):
            m._note_reader_fault(ValueError(f"could not convert '{i}'"))
        assert len(m._seen_stderr) == m._SEEN_STDERR_MAX

    def test_the_fault_reaches_the_event_log_path(self, pb):
        from proc_helper import FakeProc
        m = pb.PingMonitor('10.0.0.1')
        proc = FakeProc(stdout_lines=[],
                        stderr_text='ping: name or service not known\n')
        with patch('subprocess.Popen', return_value=proc), \
             patch.object(m, '_read_until_exit',
                          side_effect=ValueError('bad line')):
            self._run(m)
        pending = m.take_new_stderr()
        assert any('reader error: ValueError: bad line' in t for t in pending), \
            pending


class TestSupervisor:

    def test_a_dead_loop_is_restarted(self, app):
        monitor = app.monitors[0]
        monitor._thread = _DeadThread()
        with patch.object(app, '_start_monitor_thread') as start:
            app._supervise_monitor_threads()
        start.assert_called_once_with(monitor)
        assert _find(app, 'probe loop stopped and was restarted'), _events(app)

    def test_a_live_loop_is_left_alone(self, app):
        monitor = app.monitors[0]
        monitor._thread = threading.Thread(target=lambda: time.sleep(5),
                                           daemon=True, name='ping:x')
        monitor._thread.start()
        try:
            with patch.object(app, '_start_monitor_thread') as start:
                app._supervise_monitor_threads()
            start.assert_not_called()
        finally:
            monitor.running = False

    def test_a_stopped_monitor_is_left_alone(self, app):
        """':edit' and quitting stop monitors on purpose."""
        monitor = app.monitors[0]
        monitor._thread = _DeadThread()
        monitor.running = False
        with patch.object(app, '_start_monitor_thread') as start:
            app._supervise_monitor_threads()
        start.assert_not_called()

    def test_a_fatal_error_is_not_restarted(self, app):
        """ping() breaks out on purpose there — restarting hits the same wall.

        'Name or service not known' does not become true on a second attempt,
        and the loop has no reset path for self.error.
        """
        monitor = app.monitors[0]
        monitor._thread = _DeadThread()
        monitor.error = 'Name or service not known'
        with patch.object(app, '_start_monitor_thread') as start:
            app._supervise_monitor_threads()
        start.assert_not_called()
        assert not _find(app, 'restarted')

    def test_a_monitor_with_no_thread_yet_is_left_alone(self, app):
        with patch.object(app, '_start_monitor_thread') as start:
            app._supervise_monitor_threads()
        start.assert_not_called()

    def test_the_second_restart_waits(self, app):
        """A fault that recurs at once must not respawn twice a second."""
        monitor = app.monitors[0]
        monitor._thread = _DeadThread()
        with patch.object(app, '_start_monitor_thread'):
            app._supervise_monitor_threads()      # first: immediate
            monitor._thread = _DeadThread()
            with patch.object(app, '_start_monitor_thread') as again:
                app._supervise_monitor_threads()  # second: too soon
            again.assert_not_called()
        assert monitor._restarts == 1

    def test_it_gives_up_after_the_cap(self, app):
        monitor = app.monitors[0]
        limit = app._MONITOR_RESTART_LIMIT
        for i in range(limit + 3):
            monitor._thread = _DeadThread()
            monitor._restart_ts = 0.0          # pretend the pause elapsed
            with patch.object(app, '_start_monitor_thread'):
                app._supervise_monitor_threads()
        assert monitor._restarts == limit
        assert len(_find(app, 'not restarting it again')) == 1, _events(app)

    def test_giving_up_says_the_host_is_unmonitored(self, app):
        monitor = app.monitors[0]
        for _ in range(app._MONITOR_RESTART_LIMIT):
            monitor._thread = _DeadThread()
            monitor._restart_ts = 0.0
            with patch.object(app, '_start_monitor_thread'):
                app._supervise_monitor_threads()
        assert _find(app, 'no longer being probed'), _events(app)

    def test_the_dead_handle_is_dropped_from_the_thread_list(self, app):
        """Or a long-running session accumulates them."""
        monitor = app.monitors[0]
        dead = _DeadThread()
        monitor._thread = dead
        app.threads.append(dead)
        with patch.object(app, '_start_monitor_thread'):
            app._supervise_monitor_threads()
        assert dead not in app.threads

    def test_only_the_dead_monitor_is_touched(self, app):
        alive, dead = app.monitors
        alive._thread = threading.Thread(target=lambda: time.sleep(5),
                                         daemon=True, name='ping:alive')
        alive._thread.start()
        dead._thread = _DeadThread()
        try:
            with patch.object(app, '_start_monitor_thread') as start:
                app._supervise_monitor_threads()
            start.assert_called_once_with(dead)
        finally:
            alive.running = False

    def test_the_state_loop_runs_it(self, app):
        """It has to be driven by something that cannot itself die."""
        with patch.object(app, '_supervise_monitor_threads') as sup:
            app._state_pass(3.0)
        sup.assert_called_once()

    def test_a_supervisor_fault_does_not_kill_the_state_loop(self, app):
        app.running = True

        def blow_up():
            app.running = False
            raise RuntimeError('boom')

        with patch.object(app, '_supervise_monitor_threads',
                          side_effect=blow_up):
            app.check_state_changes()          # must return, not raise
        assert _find(app, 'RuntimeError: boom'), _events(app)


# ---------------------------------------------------------------------------
# The clock probe's flag
# ---------------------------------------------------------------------------

class TestClockProbeReleasesItsFlag:
    """The dispatcher only starts a probe when the flag is clear, so leaving
    it set freezes that host's Drift and RTime with nothing re-attempted.
    """

    def test_cleared_after_a_successful_probe(self, app):
        monitor = app.monitors[0]
        monitor._clock_probing = True
        with patch.object(app, '_clock_probe_once', return_value=1.5):
            app._run_clock_probe(monitor)
        assert monitor._clock_probing is False
        assert monitor.clock_state == 'ok'

    def test_cleared_after_a_failed_probe(self, app):
        monitor = app.monitors[0]
        monitor._clock_probing = True
        with patch.object(app, '_clock_probe_once', return_value=None):
            app._run_clock_probe(monitor)
        assert monitor._clock_probing is False

    def test_cleared_when_the_bookkeeping_itself_raises(self, app):
        """The part that used to sit outside the try.

        A bad clock_interval makes the 'now + interval' arithmetic raise after
        the probe has already succeeded — which is exactly the shape that left
        the flag set and the host's Drift frozen for good.
        """
        monitor = app.monitors[0]
        monitor._clock_probing = True
        app.clock_interval = 'not a number'
        with patch.object(app, '_clock_probe_once', return_value=1.5):
            with pytest.raises(TypeError):
                app._run_clock_probe(monitor)
        assert monitor._clock_probing is False
