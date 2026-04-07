"""Unit tests for per-host and global pause feature.

Tests cover:
- Monitor.pause() / unpause(): paused flag, _pause_event state, subprocess termination
- Application._get_pause_targets(): correct targets for host/section/no selection
- Application._apply_pause_toggle(): toggle semantics (pause if any active, unpause if all paused)
- _cmd_pause() with on/off/empty args
- _section_summary(): paused monitors excluded from ↑/↓/- counts; N⏸ segment added
"""

import threading
import pytest


# ---------------------------------------------------------------------------
# Monitor.pause() / unpause()
# ---------------------------------------------------------------------------

class TestMonitorPauseUnpause:
    """Monitor.pause() and unpause() manage paused flag and _pause_event correctly."""

    def test_initial_state_not_paused(self, pb):
        m = pb.PingMonitor("127.0.0.1")
        assert m.paused is False
        assert m._pause_event.is_set()

    def test_pause_sets_flag_and_clears_event(self, pb):
        m = pb.PingMonitor("127.0.0.1")
        m.pause()
        assert m.paused is True
        assert not m._pause_event.is_set()

    def test_unpause_clears_flag_and_sets_event(self, pb):
        m = pb.PingMonitor("127.0.0.1")
        m.pause()
        m.unpause()
        assert m.paused is False
        assert m._pause_event.is_set()

    def test_pause_terminates_proc(self, pb):
        """pause() calls terminate() on the active subprocess if present."""
        m = pb.PingMonitor("127.0.0.1")
        terminated = []

        class FakeProc:
            def terminate(self):
                terminated.append(True)

        m._proc = FakeProc()
        m.pause()
        assert terminated == [True]

    def test_stop_unblocks_paused_thread(self, pb):
        """stop() sets the pause_event so a blocked thread can exit."""
        m = pb.PingMonitor("127.0.0.1")
        m.pause()
        assert not m._pause_event.is_set()
        m.stop()
        assert m._pause_event.is_set()
        assert m.running is False

    def test_port_monitor_pause(self, pb):
        m = pb.PortMonitor("example.com", "80")
        m.pause()
        assert m.paused is True
        assert not m._pause_event.is_set()
        m.unpause()
        assert m.paused is False
        assert m._pause_event.is_set()


# ---------------------------------------------------------------------------
# Application._get_pause_targets()
# ---------------------------------------------------------------------------

class TestGetPauseTargets:
    """_get_pause_targets() returns the right monitors depending on selection."""

    def _make_app(self, pb):
        """Minimal Application with two hosts under a section (no file I/O)."""
        app = pb.Application.__new__(pb.Application)
        m_a = pb.PingMonitor("host-a")
        m_b = pb.PingMonitor("host-b")
        sec = pb.SectionLabel("Group", 1)
        app.entries  = [sec, m_a, m_b]
        app.monitors = [m_a, m_b]
        app.highlighted_index = None
        app.sort_by = 'none'
        return app

    def test_no_selection_returns_empty(self, pb):
        app = self._make_app(pb)
        assert app._get_pause_targets() == []

    def test_host_selected_returns_single(self, pb):
        app = self._make_app(pb)
        # entries: [SectionLabel(0), PingMonitor(host-a)(1), PingMonitor(host-b)(2)]
        app.highlighted_index = 1  # host-a
        targets = app._get_pause_targets()
        assert len(targets) == 1
        assert targets[0].host == "host-a"

    def test_section_selected_returns_all_under(self, pb):
        app = self._make_app(pb)
        app.highlighted_index = 0  # SectionLabel "Group"
        targets = app._get_pause_targets()
        assert len(targets) == 2
        hosts = {t.host for t in targets}
        assert hosts == {"host-a", "host-b"}


# ---------------------------------------------------------------------------
# Application._apply_pause_toggle()
# ---------------------------------------------------------------------------

class TestApplyPauseToggle:
    """_apply_pause_toggle() pauses if any active; unpauses if all paused."""

    def _monitors(self, pb, n=3):
        return [pb.PingMonitor(f"10.0.0.{i}") for i in range(n)]

    def test_all_running_pauses_all(self, pb):
        monitors = self._monitors(pb)
        app = pb.Application.__new__(pb.Application)
        app._apply_pause_toggle(monitors)
        assert all(m.paused for m in monitors)

    def test_all_paused_unpauses_all(self, pb):
        monitors = self._monitors(pb)
        for m in monitors:
            m.pause()
        app = pb.Application.__new__(pb.Application)
        app._apply_pause_toggle(monitors)
        assert all(not m.paused for m in monitors)

    def test_mixed_pauses_remaining(self, pb):
        monitors = self._monitors(pb, 3)
        monitors[0].pause()  # one already paused
        app = pb.Application.__new__(pb.Application)
        app._apply_pause_toggle(monitors)
        assert all(m.paused for m in monitors)

    def test_empty_list_is_noop(self, pb):
        app = pb.Application.__new__(pb.Application)
        app._apply_pause_toggle([])  # must not raise


# ---------------------------------------------------------------------------
# _cmd_pause() — on/off/toggle
# ---------------------------------------------------------------------------

class TestCmdPause:
    def _make_app(self, pb):
        app = pb.Application.__new__(pb.Application)
        app.monitors = [pb.PingMonitor(f"10.0.0.{i}") for i in range(2)]
        app.entries  = list(app.monitors)
        app.highlighted_index = None
        app.sort_by = 'none'
        app._monitoring_started = False
        return app

    def test_cmd_pause_on(self, pb):
        app = self._make_app(pb)
        app._cmd_pause('on')
        assert all(m.paused for m in app.monitors)

    def test_cmd_pause_off(self, pb):
        app = self._make_app(pb)
        app._cmd_pause('on')
        app._cmd_pause('off')
        assert all(not m.paused for m in app.monitors)

    def test_cmd_pause_toggle(self, pb):
        app = self._make_app(pb)
        app._cmd_pause('')
        assert all(m.paused for m in app.monitors)
        app._cmd_pause('')
        assert all(not m.paused for m in app.monitors)


# ---------------------------------------------------------------------------
# _section_summary() — paused count + exclusion from ↑/↓/-
# ---------------------------------------------------------------------------

class TestSectionSummaryPaused:
    """Paused monitors are excluded from ↑/↓/- badge segments; N⏸ added."""

    def _app(self, pb, n=3):
        app = pb.Application.__new__(pb.Application)
        app.monitors = [pb.PingMonitor(f"h{i}") for i in range(n)]
        app.entries  = list(app.monitors)
        app.highlighted_index = None
        app.sort_by = 'none'
        return app

    def test_no_paused_no_segment(self, pb):
        app = self._app(pb)
        for m in app.monitors:
            m.alive = True
        badge, _ = app._section_summary(app.monitors, 10, 0)
        texts = [t for t, _ in badge]
        assert '⏸' not in ''.join(texts)

    def test_paused_monitor_adds_segment(self, pb):
        app = self._app(pb)
        app.monitors[0].alive = True
        app.monitors[1].alive = True
        app.monitors[2].pause()
        app.monitors[2].alive = True   # alive state preserved after pause
        badge, _ = app._section_summary(app.monitors, 10, 0)
        texts = [t for t, _ in badge]
        joined = ''.join(texts)
        assert '⏸' in joined
        # paused count = 1
        assert '1⏸' in joined

    def test_paused_excluded_from_up_count(self, pb):
        app = self._app(pb)
        for m in app.monitors:
            m.alive = True
        app.monitors[0].pause()
        badge, _ = app._section_summary(app.monitors, 10, 0)
        texts = [t for t, _ in badge]
        joined = ''.join(texts)
        # Only 2 active-alive monitors should count as ↑
        assert '2↑' in joined
        assert '3↑' not in joined

    def test_all_paused_only_paused_segment(self, pb):
        app = self._app(pb)
        for m in app.monitors:
            m.pause()
        badge, _ = app._section_summary(app.monitors, 10, 0)
        texts = [t for t, _ in badge]
        joined = ''.join(texts)
        assert '3⏸' in joined
        assert '↑' not in joined
        assert '↓' not in joined

    def test_paused_badge_uses_cyan_color(self, pb):
        app = self._app(pb)
        app.monitors[0].pause()
        badge, _ = app._section_summary(app.monitors, 10, 0)
        paused_colors = [c for t, c in badge if '⏸' in t]
        assert paused_colors == [6]   # color_pair(6) = cyan
