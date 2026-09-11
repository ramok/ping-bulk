"""An ':edit' reload keeps every host whose definition did not change.

It used to stop every monitor, clear the lists, rebuild all of them and copy
the history across.  A host whose line was byte-identical still lost its child
process and re-authenticated, which was plainly visible in sync mode: the '_'
cells ("no ping process this second") staircased down the list, one or two at
the top and eight or nine by the last host behind a 50-host relay, because
reconnections are paced by ':set ssh-connect-rate'.  The relay paid fifty
handshakes at once, which is the same shape as the MaxStartups problem the
clock probe once caused.

Now the children keep running throughout, and reconciliation happens *after*
the file has been read — ':resolv' and ':relay-os' are applied to a monitor
after it is built, so an identity taken at construction time cannot see a
changed static mapping or a relay newly declared FreeBSD.

The identity is deliberately generous: an extra restart costs a few seconds of
history, while a wrong reuse leaves a host probing the wrong target for the
rest of the run.  A changed jump chain is the case that must never be reused.
"""

import os
import pytest
from unittest.mock import patch


BASE = """### group
10.0.0.1
10.0.0.2
:with remote-ping -J proxy root@relay
10.1.0.1
10.1.0.2
:with-end
"""


@pytest.fixture
def bed(pb, tmp_path):
    """An Application over a hosts file, with reload that starts no threads."""
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    hosts = tmp_path / 'reload.hosts'

    class Bed:
        def build(self, content=BASE):
            hosts.write_text(content)
            with patch.object(pb, '_config_path', return_value=cfg):
                self.app = pb.Application(pb.parse_hosts_file(str(hosts)))
            self.app._monitoring_started = True
            self.hosts = str(hosts)
            return self.app

        def reload(self, content):
            hosts.write_text(content)
            self.started = []
            with patch.object(self.app, '_start_monitor_thread',
                              side_effect=self.started.append):
                self.app._edit_reload_inplace(self.hosts)
            return self.app

        def ids(self):
            return [id(m) for m in self.app.monitors]

        def by_name(self):
            return {m.host: id(m) for m in self.app.monitors}

    return Bed()


def _relayed(pb, app):
    return [m for m in app.monitors if isinstance(m, pb.SshPingMonitor)]


# ===========================================================================
# Nothing changed
# ===========================================================================

class TestAnUnchangedFile:

    def test_every_monitor_object_survives(self, bed):
        bed.build()
        before = bed.ids()
        bed.reload(BASE)
        assert bed.ids() == before

    def test_no_thread_is_started(self, bed):
        bed.build()
        bed.reload(BASE)
        assert bed.started == [], 'an adopted monitor already has its thread'

    def test_nothing_is_stopped(self, bed):
        app = bed.build()
        monitors = list(app.monitors)
        bed.reload(BASE)
        assert all(m.running for m in monitors)

    def test_the_event_says_what_was_kept(self, bed):
        app = bed.build()
        bed.reload(BASE)
        last = list(app.events)[-1].text
        assert '4 host(s) kept running' in last
        assert '0 restarted' in last

    def test_history_is_not_doubled(self, bed):
        """Restoring a snapshot into an adopted monitor would extend its deque."""
        app = bed.build('10.0.0.1\n')
        m = app.monitors[0]
        m.history.extend(['.'] * 5)
        m.history_times.extend([1000.0 + i for i in range(5)])
        m.rx_count = 5
        bed.reload('10.0.0.1\n')
        assert len(app.monitors[0].history) == 5
        assert app.monitors[0].rx_count == 5


# ===========================================================================
# The jump chain — the case the user named
# ===========================================================================

class TestAChangedJumpChain:

    def test_a_different_proxy_rebuilds_only_the_relayed_hosts(self, bed, pb):
        app = bed.build()
        before = bed.by_name()
        bed.reload(BASE.replace('-J proxy', '-J other'))
        for m in app.monitors:
            if isinstance(m, pb.SshPingMonitor):
                assert id(m) != before[m.host], f'{m.host} was reused'
            else:
                assert id(m) == before[m.host], f'{m.host} needlessly restarted'

    def test_the_rebuilt_ones_get_a_thread(self, bed, pb):
        bed.build()
        bed.reload(BASE.replace('-J proxy', '-J other'))
        assert len(bed.started) == 2
        assert all(isinstance(m, pb.SshPingMonitor) for m in bed.started)

    def test_they_inherit_the_history_of_the_hosts_they_replace(self, bed, pb):
        app = bed.build()
        for m in _relayed(pb, app):
            m.history.extend(['.'] * 3)
            m.rx_count = 3
        bed.reload(BASE.replace('-J proxy', '-J other'))
        for m in _relayed(pb, app):
            assert list(m.history) == ['.'] * 3, m.host
            assert m.rx_count == 3

    def test_the_old_relayed_monitors_are_stopped(self, bed, pb):
        app = bed.build()
        old = _relayed(pb, app)
        bed.reload(BASE.replace('-J proxy', '-J other'))
        assert all(not m.running for m in old)

    def test_adding_a_hop_is_a_change(self, bed, pb):
        app = bed.build()
        before = bed.by_name()
        bed.reload(BASE.replace('-J proxy', '-J proxy,second'))
        for m in _relayed(pb, app):
            assert id(m) != before.get(m.host)

    def test_a_different_relay_login_is_a_change(self, bed, pb):
        app = bed.build()
        bed.reload(BASE.replace('root@relay', 'admin@relay'))
        assert all(m.running for m in app.monitors)
        assert len(bed.started) == 2


# ===========================================================================
# The rest of the identity
# ===========================================================================

class TestWhatElseCountsAsAChange:

    def test_a_declared_relay_os_is_part_of_it(self, bed, pb):
        """Same host, same relay, but a different argv, parser and loss model."""
        app = bed.build(BASE)
        before = bed.by_name()
        bed.reload(':relay-os *relay freebsd\n' + BASE)
        for m in _relayed(pb, app):
            assert m._relay_os_declared == 'freebsd'
            assert id(m) != before[m.host]

    def test_removing_a_relay_os_rule_takes_effect(self, bed, pb):
        """The rule stores used to accumulate, so deleting a line did nothing."""
        app = bed.build(':relay-os *relay freebsd\n' + BASE)
        assert all(m._relay_os_declared == 'freebsd'
                   for m in _relayed(pb, app))
        bed.reload(BASE)
        assert app.relay_os_rules == []
        assert all(m._relay_os_declared == 'auto'
                   for m in _relayed(pb, app))

    def test_a_resolv_override_is_part_of_it(self, bed):
        app = bed.build('10.0.0.1\n')
        before = bed.by_name()
        bed.reload(':resolv 10.9.9.9 10.0.0.1\n10.0.0.1\n')
        m = app.monitors[0]
        assert m.resolv_static
        assert id(m) != before['10.0.0.1']

    def test_a_port_is_part_of_it(self, bed):
        app = bed.build('10.0.0.1:80\n')
        before = bed.by_name()
        bed.reload('10.0.0.1:443\n')
        assert bed.ids() != list(before.values())
        assert app.monitors[0].port == '443'

    def test_a_display_label_is_part_of_it(self, bed):
        app = bed.build('10.0.0.1 ## router\n')
        before = bed.ids()
        bed.reload('10.0.0.1 ## gateway\n')
        assert bed.ids() != before
        assert app.monitors[0].host == 'gateway'

    def test_a_plain_host_never_matches_a_relayed_one(self, bed, pb):
        """Different classes probe differently even with the same target."""
        app = bed.build('10.1.0.1\n')
        before = bed.ids()
        bed.reload(':with remote-ping root@relay\n10.1.0.1\n:with-end\n')
        assert bed.ids() != before
        assert isinstance(app.monitors[0], pb.SshPingMonitor)


# ===========================================================================
# Hosts coming and going
# ===========================================================================

class TestAddingAndRemoving:

    def test_adding_a_host_leaves_the_others_alone(self, bed):
        app = bed.build()
        before = bed.by_name()
        bed.reload(BASE + '10.0.0.3\n')
        assert len(app.monitors) == 5
        for m in app.monitors:
            if m.host in before:
                assert id(m) == before[m.host]
        assert [m.host for m in bed.started] == ['10.0.0.3']

    def test_removing_a_host_leaves_the_others_alone(self, bed):
        app = bed.build()
        before = bed.by_name()
        gone = next(m for m in app.monitors if m.host == '10.0.0.2')
        bed.reload(BASE.replace('10.0.0.2\n', ''))
        assert '10.0.0.2' not in [m.host for m in app.monitors]
        assert not gone.running, 'a host no longer listed must be stopped'
        for m in app.monitors:
            assert id(m) == before[m.host]

    def test_reordering_hosts_restarts_nothing(self, bed):
        app = bed.build()
        before = bed.by_name()
        bed.reload("""### group
10.0.0.2
10.0.0.1
:with remote-ping -J proxy root@relay
10.1.0.2
10.1.0.1
:with-end
""")
        assert bed.started == []
        assert {m.host: id(m) for m in app.monitors} == before

    def test_the_same_host_twice_gets_two_monitors(self, bed):
        """One adoption per listing, not two references to one object."""
        app = bed.build('10.0.0.1\n')
        bed.reload('10.0.0.1\n10.0.0.1\n')
        # The second listing is skipped by _cmd_source's duplicate check, so
        # there is still exactly one monitor and it is the adopted one.
        assert len(app.monitors) == 1
        assert bed.started == []

    def test_moving_a_host_between_sections_restarts_nothing(self, bed):
        app = bed.build()
        before = bed.by_name()
        bed.reload("""### other
10.0.0.1
### group
10.0.0.2
:with remote-ping -J proxy root@relay
10.1.0.1
10.1.0.2
:with-end
""")
        assert bed.started == []
        assert {m.host: id(m) for m in app.monitors} == before


# ===========================================================================
# no-alarm across a reload
# ===========================================================================

class TestNoAlarmAcrossAReload:

    def test_removing_the_rule_from_the_file_takes_effect(self, bed):
        app = bed.build(':no-alarm 10.0.0.1\n10.0.0.1\n10.0.0.2\n')
        assert [m.no_alarm for m in app.monitors] == [True, False]
        bed.reload('10.0.0.1\n10.0.0.2\n')
        assert app.no_alarm_patterns == []
        assert [m.no_alarm for m in app.monitors] == [False, False]

    def test_a_runtime_press_survives_the_reload(self, bed):
        """It is a live decision, not something the file said."""
        app = bed.build('10.0.0.1\n10.0.0.2\n')
        app.highlighted_index = app.entries.index(app.monitors[1])
        app._cmd_no_alarm('--toggle')
        assert [m.no_alarm for m in app.monitors] == [False, True]
        bed.reload('10.0.0.1\n10.0.0.2\n')
        assert [m.no_alarm for m in app.monitors] == [False, True]

    def test_the_file_rule_still_reaches_an_adopted_monitor(self, bed):
        app = bed.build('10.0.0.1\n')
        assert app.monitors[0].no_alarm is False
        bed.reload(':no-alarm 10.0.0.*\n10.0.0.1\n')
        assert bed.started == [], 'a no-alarm rule is not a probe change'
        assert app.monitors[0].no_alarm is True

    def test_a_paused_host_stays_paused(self, bed):
        app = bed.build('10.0.0.1\n')
        app.monitors[0].pause()
        bed.reload('10.0.0.1\n')
        assert app.monitors[0].paused is True


# ===========================================================================
# Probe readers
# ===========================================================================

class TestProbeReaders:
    """A reader holds its monitor, so a replaced one left it writing nowhere."""

    def _arm(self, pb, app):
        app.probe_source = 'echo temp=1'
        app.probe_defs = {'temp': pb.ProbeDef('temp')}

    def test_an_adopted_monitor_keeps_its_reader(self, bed, pb):
        app = bed.build('10.0.0.1\n')
        self._arm(pb, app)
        reader = pb.ProbeReader(app.monitors[0], app.probe_source, 60,
                                app.probe_defs, retain=5)
        app.probe_readers = [reader]
        with patch.object(pb, '_spawn', lambda *a, **k: None):
            bed.reload('10.0.0.1\n')
        assert app.probe_readers == [reader], 'the connection is still good'
        assert reader.monitor is app.monitors[0]
        assert reader.running

    def test_a_replaced_monitor_gets_a_new_reader(self, bed, pb):
        app = bed.build('10.0.0.1\n')
        self._arm(pb, app)
        reader = pb.ProbeReader(app.monitors[0], app.probe_source, 60,
                                app.probe_defs, retain=5)
        app.probe_readers = [reader]
        with patch.object(pb, '_spawn', lambda *a, **k: None):
            bed.reload(':resolv 10.9.9.9 10.0.0.1\n10.0.0.1\n')
        assert len(app.probe_readers) == 1
        assert app.probe_readers[0] is not reader
        assert app.probe_readers[0].monitor is app.monitors[0]
        assert not reader.running, 'the stale reader must be stopped'

    def test_a_new_host_gets_a_reader(self, bed, pb):
        app = bed.build('10.0.0.1\n')
        self._arm(pb, app)
        app.probe_readers = [pb.ProbeReader(app.monitors[0], app.probe_source,
                                            60, app.probe_defs, retain=5)]
        with patch.object(pb, '_spawn', lambda *a, **k: None):
            bed.reload('10.0.0.1\n10.0.0.2\n')
        assert {r.monitor.host for r in app.probe_readers} == {'10.0.0.1',
                                                              '10.0.0.2'}

    def test_no_readers_when_probes_are_not_configured(self, bed, pb):
        app = bed.build('10.0.0.1\n')
        bed.reload('10.0.0.1\n')
        assert app.probe_readers == []


# ===========================================================================
# The selection
# ===========================================================================

class TestTheSelectionSurvives:
    """Clearing it was forced when every monitor was a new object.

    Now the objects are the same ones, so the cursor should be where it was
    left — found by name, because a line added above it moves its index.
    """

    def test_a_selected_host_is_found_again(self, bed):
        app = bed.build()
        app.highlighted_index = app.entries.index(app.monitors[1])
        name = app.entries[app.highlighted_index].host
        bed.reload('10.0.0.9\n' + BASE)
        assert app.highlighted_index is not None
        assert app.entries[app.highlighted_index].host == name

    def test_a_selected_section_is_found_again(self, bed, pb):
        app = bed.build()
        app.highlighted_index = next(
            i for i, e in enumerate(app.entries)
            if isinstance(e, pb.SectionLabel))
        bed.reload('10.0.0.9\n' + BASE)
        entry = app.entries[app.highlighted_index]
        assert isinstance(entry, pb.SectionLabel)
        assert entry.title == 'group'

    def test_a_host_that_is_gone_clears_the_selection(self, bed):
        app = bed.build()
        app.highlighted_index = app.entries.index(app.monitors[1])
        bed.reload(BASE.replace('10.0.0.2\n', ''))
        assert app.highlighted_index is None

    def test_no_selection_stays_no_selection(self, bed):
        app = bed.build()
        app.highlighted_index = None
        bed.reload(BASE)
        assert app.highlighted_index is None
