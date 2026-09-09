"""Regression tests for iterating the event log while a thread appends to it.

Reported as a crash out of the details overlay:

    File "ping-bulk", line 12930, in _draw_details_overlay
    RuntimeError: deque mutated during iteration

self.events is a deque, and add_event() appends from the state loop, the
clock-probe threads and the probe readers.  A Python-level 'for e in
self.events' in the drawing thread therefore races every event, and there were
three such loops: the details overlay, the display filter rebuild and the
':save' writer — the last inside a 'try/except OSError', which a RuntimeError
walks straight past.

Each test drives the real reader with a writer thread running, and asserts no
RuntimeError.  That is a race, so the assertion is only as good as its odds:
measured against the unfixed code, a Python-level loop failed 186 times in
7000 attempts, while list() of the same deque failed 0 times in 26000.  The
loop counts below are sized so the unfixed code fails essentially always.

Two of the three reproduce the original fault directly.  The overlay one is a
forward guard: the loop it replaced no longer exists to be raced, so against
the unfixed code it fails on the missing method rather than on the exception.
"""

import threading

import pytest


ROUNDS = 200


@pytest.fixture
def app(pb):
    a = pb.Application([('host', '10.0.0.1')])
    a._monitoring_started = True
    for i in range(2000):          # long enough that copying it takes a while
        a.add_event('10.0.0.1', f'filler {i}')
    return a


class _Hammer:
    """Appends events as fast as it can, the way the state loop does."""

    def __init__(self, app):
        self.app = app
        self._stop = threading.Event()
        self._t = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        i = 0
        while not self._stop.is_set():
            i += 1
            self.app.add_event('10.0.0.1', f'host down {i}')

    def __enter__(self):
        self._t.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._t.join(timeout=5)
        return False


def test_the_display_filter_rebuild_survives(app):
    """Runs every frame whenever an event below the current level arrives."""
    with _Hammer(app):
        for _ in range(ROUNDS):
            app._filtered_events_dirty = True
            app._get_filtered_events()


def test_the_details_overlay_survives(app):
    """The loop the crash came out of."""
    monitor = app.monitors[0]
    with _Hammer(app):
        for _ in range(ROUNDS):
            app._host_event_lines(monitor)


def test_saving_the_log_survives(app, tmp_path):
    """':save' iterated the deque inside a 'try/except OSError'.

    A RuntimeError is not an OSError, so it escaped the handler that exists to
    keep a failed save from killing anything.
    """
    out = tmp_path / 'log.txt'
    with _Hammer(app):
        for _ in range(5):         # each round writes a few thousand lines
            app.save_to_file(str(out))
    lines = out.read_text().splitlines()
    assert len(lines) > 100
    assert all(ln.startswith('#') or ln[:4].isdigit() for ln in lines), \
        'every written line must be a whole event line'


def test_the_snapshot_is_a_copy(app):
    """Appending after the snapshot must not change what the caller sees."""
    assert len(app.events) < app.log_size, \
        'the fixture must stay below the cap, or nothing here grows'
    before = app._events_snapshot()
    app.add_event('10.0.0.1', 'arrived later')
    assert len(app._events_snapshot()) == len(before) + 1
    assert 'arrived later' not in before[-1].text


def test_the_host_lines_still_select_by_name(app, pb):
    """The extraction must not have changed which lines are picked."""
    app.add_event('10.0.0.2', 'not this host')
    lines = app._host_event_lines(app.monitors[0])
    assert lines, 'the monitor has events of its own'
    assert all('10.0.0.2' not in ln for ln in lines)
