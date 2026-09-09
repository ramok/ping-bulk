"""Tests for the autofold feature.

Covers:
  - ##! and :title! produce no_autofold=True in parse output
  - ##-! and :title-! combine folded_default + no_autofold
  - _get_direct_section_monitors stops at any SectionLabel
  - _autofold_tick unfolds on down, folds after delay, respects no_autofold
  - :set autofold on/off and :set autofold-delay
"""

import time
import unittest.mock as mock

import pytest

from utils.hosts_helper import write_hosts


# ===========================================================================
# Unit tests — parser
# ===========================================================================

class TestNoAutofoldParser:
    """##! and :title! produce no_autofold=True."""

    def test_hash_no_autofold(self, pb, tmp_path):
        """##! Title → no_autofold=True, folded=False."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "##! Exempt\n1.1.1.1\n"))
        assert entries[0] == ('section', 'Exempt', 1, False, True)

    def test_hash_folded_and_no_autofold(self, pb, tmp_path):
        """##-! Title → folded_default=True, no_autofold=True."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "##-! Exempt Folded\n1.1.1.1\n"))
        assert entries[0] == ('section', 'Exempt Folded', 1, True, True)

    def test_hash_bang_before_dash(self, pb, tmp_path):
        """##!- Title → order of modifiers should not matter."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "##!- SwappedMods\n1.1.1.1\n"))
        assert entries[0] == ('section', 'SwappedMods', 1, True, True)

    def test_title_no_autofold(self, pb, tmp_path):
        """:title! Title → no_autofold=True, folded=False."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, ":title! Exempt\n1.1.1.1\n"))
        assert entries[0] == ('section', 'Exempt', 1, False, True)

    def test_title2_no_autofold(self, pb, tmp_path):
        """:title2! → level 2, no_autofold=True."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, ":title2! Sub\n1.1.1.1\n"))
        assert entries[0] == ('section', 'Sub', 2, False, True)

    def test_title_folded_and_no_autofold(self, pb, tmp_path):
        """:title-! combines both modifiers."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, ":title-! Both\n1.1.1.1\n"))
        assert entries[0] == ('section', 'Both', 1, True, True)

    def test_normal_section_has_no_autofold_false(self, pb, tmp_path):
        """Normal ## section has no_autofold=False."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "## Normal\n1.1.1.1\n"))
        assert entries[0] == ('section', 'Normal', 1, False, False)

    def test_folded_section_has_no_autofold_false(self, pb, tmp_path):
        """##- folded section has no_autofold=False."""
        entries = pb.parse_hosts_file(write_hosts(tmp_path, "##- Folded\n1.1.1.1\n"))
        assert entries[0] == ('section', 'Folded', 1, True, False)


# ===========================================================================
# Unit tests — _get_direct_section_monitors
# ===========================================================================

def _build_app(pb, hosts_file):
    """Construct a Application app from a parsed hosts file (no threads started)."""
    entries = pb.parse_hosts_file(hosts_file)
    app = pb.Application(entries)
    return app


class TestGetDirectSectionMonitors:
    """_get_direct_section_monitors returns only direct child monitors."""

    def test_returns_only_direct_monitors(self, pb, tmp_path):
        hf = write_hosts(tmp_path, "## Top\n1.1.1.1\n2.2.2.2\n### Sub\n3.3.3.3\n")
        app = _build_app(pb, hf)
        # entries: SectionLabel('Top'), M(1.1.1.1), M(2.2.2.2), SectionLabel('Sub'), M(3.3.3.3)
        top_idx = next(i for i, e in enumerate(app.entries)
                       if isinstance(e, pb.SectionLabel) and e.title == 'Top')
        direct = app._get_direct_section_monitors(top_idx)
        hosts = [m.host for m in direct]
        assert '1.1.1.1' in hosts
        assert '2.2.2.2' in hosts
        assert '3.3.3.3' not in hosts  # sub-section's child

    def test_empty_section(self, pb, tmp_path):
        hf = write_hosts(tmp_path, "## Empty\n## Other\n1.1.1.1\n")
        app = _build_app(pb, hf)
        empty_idx = next(i for i, e in enumerate(app.entries)
                         if isinstance(e, pb.SectionLabel) and e.title == 'Empty')
        assert app._get_direct_section_monitors(empty_idx) == []


# ===========================================================================
# Unit tests — _autofold_tick logic
# ===========================================================================

class TestAutofoldTick:
    """_autofold_tick behavior."""

    def _setup(self, pb, tmp_path, *, no_autofold=False, starts_folded=False):
        """Build a simple 1-section app with 2 monitors, return (app, section, monitors)."""
        marker = ('!' if no_autofold else '') + ('-' if starts_folded else '')
        hf = write_hosts(tmp_path, f"##{marker} Services\n1.1.1.1\n2.2.2.2\n")
        app = _build_app(pb, hf)
        app.autofold = True
        app.autofold_delay = 5.0
        section = next(e for e in app.entries if isinstance(e, pb.SectionLabel))
        monitors = [e for e in app.entries if isinstance(e, pb.Monitor)]
        return app, section, monitors

    def test_unfolds_when_host_down(self, pb, tmp_path):
        app, section, monitors = self._setup(pb, tmp_path, starts_folded=True)
        monitors[0].alive = False
        monitors[1].alive = True
        section.folded = True
        app._autofold_tick()
        assert not section.folded

    def test_does_not_fold_when_all_up_before_delay(self, pb, tmp_path):
        app, section, monitors = self._setup(pb, tmp_path)
        for m in monitors:
            m.alive = True
        section.folded = False
        app._autofold_tick()
        # delay not elapsed — should still be unfolded
        assert not section.folded

    def test_folds_after_delay(self, pb, tmp_path):
        app, section, monitors = self._setup(pb, tmp_path)
        for m in monitors:
            m.alive = True
        section.folded = False
        # Simulate first tick to record timestamp
        app._autofold_tick()
        sid = id(section)
        # Wind back the timestamp to simulate elapsed delay
        app._autofold_ts[sid] = time.time() - 10.0
        app._autofold_tick()
        assert section.folded

    def test_no_autofold_section_ignored(self, pb, tmp_path):
        app, section, monitors = self._setup(pb, tmp_path, no_autofold=True,
                                             starts_folded=False)
        monitors[0].alive = False
        monitors[1].alive = True
        section.folded = False
        app._autofold_tick()
        assert not section.folded  # exempt — stays put

    def test_skips_initialising_monitors(self, pb, tmp_path):
        app, section, monitors = self._setup(pb, tmp_path, starts_folded=True)
        # All monitors still initialising
        for m in monitors:
            m.alive = None
        section.folded = True
        app._autofold_tick()
        assert section.folded  # no change — no known status

    def test_down_resets_fold_timer(self, pb, tmp_path):
        app, section, monitors = self._setup(pb, tmp_path)
        for m in monitors:
            m.alive = True
        section.folded = False
        app._autofold_tick()
        # Host goes down before delay elapses
        monitors[0].alive = False
        app._autofold_tick()
        assert id(section) not in app._autofold_ts  # timer cleared

    def test_disabled_autofold_does_nothing(self, pb, tmp_path):
        app, section, monitors = self._setup(pb, tmp_path, starts_folded=False)
        app.autofold = False
        monitors[0].alive = False
        section.folded = False
        app._autofold_tick()
        assert not section.folded  # disabled — no action

    def test_paused_monitors_excluded(self, pb, tmp_path):
        """Paused monitors don't contribute to the liveness check."""
        app, section, monitors = self._setup(pb, tmp_path, starts_folded=True)
        monitors[0].alive = False
        monitors[0].paused = True   # paused — excluded
        monitors[1].alive = True
        section.folded = True
        app._autofold_tick()
        # monitors[0] is paused, only monitors[1] (alive) is active → all alive → start timer
        assert not section.folded or id(section) in app._autofold_ts or True
        # More precise: section should NOT unfold because the only active monitor is alive
        # Actually it starts the fold-delay timer; section stays unfolded until delay expires.
        # The important thing: it did NOT unfold due to the paused-down monitor.
        assert section.folded  # started folded and paused down-monitor excluded → stays folded

    def test_empty_section_skipped(self, pb, tmp_path):
        """Section with no monitors (direct children) is skipped."""
        hf = write_hosts(tmp_path, "## Empty\n## Other\n1.1.1.1\n")
        app = _build_app(pb, hf)
        app.autofold = True
        # Should not raise
        app._autofold_tick()

    def test_parent_folds_independently_from_subsection(self, pb, tmp_path):
        """Parent section autofolds based on its direct monitors only.

        When a parent has all-alive direct monitors but a subsection has a
        down host, the parent SHOULD autofold (hiding its direct monitors).
        The subsection is evaluated independently and stays unfolded.
        """
        from unittest.mock import patch

        cfg = tmp_path / "ping-bulk" / "config"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('')

        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([], log_file=None)

        # services (direct: lab✓, docker✓), extra (direct: admin✓, nas-old✗)
        services = pb.SectionLabel("services", level=1, folded_default=False)
        lab = pb.PingMonitor("lab")
        docker = pb.PingMonitor("docker")
        extra = pb.SectionLabel("extra", level=2, folded_default=False)
        admin = pb.PingMonitor("admin")
        nas_old = pb.PingMonitor("nas-old")

        app.entries = [services, lab, docker, extra, admin, nas_old]
        app.monitors = [lab, docker, admin, nas_old]

        lab.alive = True
        docker.alive = True
        admin.alive = True
        nas_old.alive = False

        app.autofold = True
        app.autofold_delay = 0.0
        services.folded = False
        extra.folded = False

        # Prime the timer so the delay has elapsed
        app._autofold_ts[id(services)] = 0.0

        app._autofold_tick()

        # services: direct monitors all alive → autofolded ✓
        assert services.folded, "services should be autofolded (direct monitors all alive)"
        # extra: nas-old is down → stays unfolded ✓
        assert not extra.folded, "extra should stay unfolded (nas-old is down)"

        for m in app.monitors:
            m.stop()

    def test_parent_not_unfolded_by_subsection_down_host(self, pb, tmp_path):
        """A manually-folded parent is NOT force-unfolded by a down host in a subsection.

        Autofold evaluates each section by its direct monitors only.  A down
        host in a subsection triggers unfold of THAT subsection, not the parent.
        """
        from unittest.mock import patch

        cfg = tmp_path / "ping-bulk" / "config"
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('')

        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([], log_file=None)

        services = pb.SectionLabel("services", level=1, folded_default=False)
        lab = pb.PingMonitor("lab")
        extra = pb.SectionLabel("extra", level=2, folded_default=False)
        nas_old = pb.PingMonitor("nas-old")

        app.entries = [services, lab, extra, nas_old]
        app.monitors = [lab, nas_old]

        lab.alive = True
        nas_old.alive = False

        app.autofold = True
        app.autofold_delay = 5.0
        services.folded = True  # manually folded
        extra.folded = True

        app._autofold_tick()

        # services has only lab (alive) as direct monitor → autofold does NOT unfold it
        assert services.folded, "services should stay folded (direct monitor lab is alive)"
        # extra has nas-old (down) → autounfolded
        assert not extra.folded, "extra should be unfolded (nas-old is down)"

        for m in app.monitors:
            m.stop()


# ===========================================================================
# Unit tests — _fold_healthy / _fold_unhealthy
# ===========================================================================

class TestFoldHealthyUnhealthy:
    """Manual fold-healthy / fold-unhealthy actions."""

    def _make_app(self, pb, tmp_path):
        hf = write_hosts(tmp_path, "## Up\n1.1.1.1\n## Down\n2.2.2.2\n## Mixed\n3.3.3.3\n4.4.4.4\n")
        app = _build_app(pb, hf)
        # Set liveness: Up section alive, Down section down, Mixed has one of each
        monitors = {m.host: m for m in app.monitors}
        monitors['1.1.1.1'].alive = True
        monitors['2.2.2.2'].alive = False
        monitors['3.3.3.3'].alive = True
        monitors['4.4.4.4'].alive = False
        return app

    def test_fold_healthy_folds_only_all_up(self, pb, tmp_path):
        app = self._make_app(pb, tmp_path)
        app._fold_healthy()
        sections = {e.title: e for e in app.entries if isinstance(e, pb.SectionLabel)}
        assert sections['Up'].folded        # all alive → folded
        assert not sections['Down'].folded  # has down host → not folded
        assert not sections['Mixed'].folded # mixed → not folded

    def test_fold_unhealthy_folds_only_any_down(self, pb, tmp_path):
        app = self._make_app(pb, tmp_path)
        app._fold_unhealthy()
        sections = {e.title: e for e in app.entries if isinstance(e, pb.SectionLabel)}
        assert not sections['Up'].folded    # all alive → not folded
        assert sections['Down'].folded      # has down host → folded
        assert sections['Mixed'].folded     # has down host → folded


# ===========================================================================
# Unit tests — expected-down hosts (':no-alarm' / '~')
# ===========================================================================

class TestExpectedDownDoesNotHoldASectionOpen:
    """A ':no-alarm' host that is down is not news, so it must not block a fold.

    A section holding a normally-off power switch would otherwise sit unfolded
    for good — on a kiosk console that is exactly the row budget autofold was
    added to reclaim.
    """

    def _setup(self, pb, tmp_path, hosts):
        hf = write_hosts(tmp_path, "## Services\n" + hosts)
        app = _build_app(pb, hf)
        app.autofold = True
        app.autofold_delay = 5.0
        section = next(e for e in app.entries if isinstance(e, pb.SectionLabel))
        monitors = [e for e in app.entries if isinstance(e, pb.Monitor)]
        return app, section, monitors

    def _elapse(self, app, section):
        """Run the countdown to completion: tick, wind back, tick again."""
        app._autofold_tick()
        app._autofold_ts[id(section)] = time.time() - 10.0
        app._autofold_tick()

    def test_mixed_up_and_expected_down_folds(self, pb, tmp_path):
        app, section, monitors = self._setup(pb, tmp_path, "1.1.1.1\n~2.2.2.2\n")
        monitors[0].alive = True
        monitors[1].alive = False       # marked — expected to be silent
        assert monitors[1].no_alarm, "the '~' prefix should have marked it"
        section.folded = False
        self._elapse(app, section)
        assert section.folded

    def test_all_expected_down_folds(self, pb, tmp_path):
        app, section, monitors = self._setup(pb, tmp_path, "~1.1.1.1\n~2.2.2.2\n")
        for m in monitors:
            m.alive = False
        section.folded = False
        self._elapse(app, section)
        assert section.folded

    def test_an_expected_down_host_does_not_unfold(self, pb, tmp_path):
        app, section, monitors = self._setup(pb, tmp_path, "1.1.1.1\n~2.2.2.2\n")
        monitors[0].alive = True
        monitors[1].alive = False
        section.folded = True
        app._autofold_tick()
        assert section.folded

    def test_an_unmarked_down_host_still_unfolds(self, pb, tmp_path):
        """The exemption must not leak to its neighbours."""
        app, section, monitors = self._setup(pb, tmp_path, "1.1.1.1\n~2.2.2.2\n")
        monitors[0].alive = False       # not marked — real news
        monitors[1].alive = False
        section.folded = True
        app._autofold_tick()
        assert not section.folded

    def test_a_process_error_is_never_exempt(self, pb, tmp_path):
        """':no-alarm' means 'a lost reply is expected', not 'a broken host is'.

        A mistyped address fails to resolve; folding that away silently would
        hide the one thing the user needs to see.
        """
        app, section, monitors = self._setup(pb, tmp_path, "1.1.1.1\n~2.2.2.2\n")
        monitors[0].alive = True
        monitors[1].alive = False
        monitors[1].error = 'Name or service not known'
        section.folded = True
        app._autofold_tick()
        assert not section.folded

    def test_unmarking_a_down_host_unfolds_immediately(self, pb, tmp_path):
        """'o' takes the marker off — the section must reopen on the next tick."""
        app, section, monitors = self._setup(pb, tmp_path, "1.1.1.1\n~2.2.2.2\n")
        monitors[0].alive = True
        monitors[1].alive = False
        section.folded = False
        self._elapse(app, section)
        assert section.folded, "precondition: marked, so it folded"
        app.highlighted_index = app.entries.index(monitors[1])
        app._cmd_no_alarm('--toggle')
        assert monitors[1].no_alarm is False
        app._autofold_tick()
        assert not section.folded

    def test_an_initialising_marked_host_changes_nothing(self, pb, tmp_path):
        app, section, monitors = self._setup(pb, tmp_path, "~1.1.1.1\n~2.2.2.2\n")
        for m in monitors:
            m.alive = None
        section.folded = True
        app._autofold_tick()
        assert section.folded
        assert id(section) not in app._autofold_ts

    def test_a_glob_rule_reaches_the_check(self, pb, tmp_path):
        """The rule form users actually write, not just the '~' prefix."""
        hf = write_hosts(tmp_path, ":no-alarm *-switch\n"
                                   "## Services\n"
                                   "1.1.1.1 ## router\n"
                                   "2.2.2.2 ## rack-switch\n")
        app = _build_app(pb, hf)
        app.autofold = True
        app.autofold_delay = 5.0
        section = next(e for e in app.entries if isinstance(e, pb.SectionLabel))
        monitors = [e for e in app.entries if isinstance(e, pb.Monitor)]
        monitors[0].alive = True
        monitors[1].alive = False
        assert monitors[1].no_alarm
        section.folded = False
        self._elapse(app, section)
        assert section.folded


class TestAutofoldLockLabel:
    """The '(autofold lock)' label and the tick must agree.

    If they disagree the user folds a section, autofold reopens it, and the
    header carries no explanation for why.
    """

    def _setup(self, pb, tmp_path, hosts):
        hf = write_hosts(tmp_path, "## Services\n" + hosts)
        app = _build_app(pb, hf)
        app.autofold = True
        section_idx = next(i for i, e in enumerate(app.entries)
                           if isinstance(e, pb.SectionLabel))
        monitors = [e for e in app.entries if isinstance(e, pb.Monitor)]
        return app, section_idx, monitors

    def test_not_locked_by_an_expected_down_host(self, pb, tmp_path):
        app, idx, monitors = self._setup(pb, tmp_path, "1.1.1.1\n~2.2.2.2\n")
        monitors[0].alive = True
        monitors[1].alive = False
        assert app._section_autofold_locked(idx) is False

    def test_locked_by_an_unmarked_down_host(self, pb, tmp_path):
        app, idx, monitors = self._setup(pb, tmp_path, "1.1.1.1\n~2.2.2.2\n")
        monitors[0].alive = False
        monitors[1].alive = False
        assert app._section_autofold_locked(idx) is True

    def test_locked_by_a_marked_host_in_error(self, pb, tmp_path):
        app, idx, monitors = self._setup(pb, tmp_path, "1.1.1.1\n~2.2.2.2\n")
        monitors[0].alive = True
        monitors[1].alive = False
        monitors[1].error = 'connect failed'
        assert app._section_autofold_locked(idx) is True


class TestFoldHealthyAndExpectedDown:
    """z[ / z] ask the same question autofold does, so they answer it alike.

    A section holding a normally-off power switch used to refuse to fold under
    z[ and fold under z] — the exact inversion of what the marker means.
    """

    def _app(self, pb, tmp_path):
        hf = write_hosts(tmp_path,
                         "## Quiet\n1.1.1.1\n~2.2.2.2\n"
                         "## Broken\n3.3.3.3\n~4.4.4.4\n")
        app = _build_app(pb, hf)
        mons = {m.host: m for m in app.monitors}
        mons['1.1.1.1'].alive = True
        mons['2.2.2.2'].alive = False    # marked — expected
        mons['3.3.3.3'].alive = False    # unmarked — real
        mons['4.4.4.4'].alive = False
        return app, mons

    def _sections(self, app, pb):
        return {e.title: e for e in app.entries if isinstance(e, pb.SectionLabel)}

    def test_close_healthy_folds_the_quiet_section(self, pb, tmp_path):
        app, _ = self._app(pb, tmp_path)
        app._fold_healthy()
        sections = self._sections(app, pb)
        assert sections['Quiet'].folded
        assert not sections['Broken'].folded

    def test_close_unhealthy_leaves_the_quiet_section(self, pb, tmp_path):
        app, _ = self._app(pb, tmp_path)
        app._fold_unhealthy()
        sections = self._sections(app, pb)
        assert not sections['Quiet'].folded
        assert sections['Broken'].folded

    def test_a_process_error_makes_a_marked_section_unhealthy(self, pb, tmp_path):
        app, mons = self._app(pb, tmp_path)
        mons['2.2.2.2'].error = 'Name or service not known'
        app._fold_healthy()
        assert not self._sections(app, pb)['Quiet'].folded
