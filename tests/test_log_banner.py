"""Unit tests for the streaming event log's session banner.

Covers:
  - a banner opens the file, before the first event line
  - it carries pid, hosts file and target count
  - exactly one banner per logging session, not one per event
  - switching log files writes a banner in the new file
  - switching back writes a fresh banner, marking the resumption
  - ':save --follow' gets one too
  - the comment prefix matches the headers written by ':save'

The banner is written lazily, on the first append: there is no open moment to
hook, because every append opens the file, and the path can arrive from five
places (config, hosts file, -l, ':log', ':save --follow').
"""

import os

import pytest


BANNER_MARK = '###### log started'


def banners(text):
    return [ln for ln in text.splitlines() if BANNER_MARK in ln]


@pytest.fixture
def app(pb):
    a = pb.Application([('host', '10.0.0.1'), ('host', '10.0.0.2'),
                        ('section', 'Group', 1, False, False)],
                       hosts_file='/opt/net/pb.hosts')
    a._monitoring_started = True     # as after start_monitoring()
    return a


class TestBannerContent:

    def test_banner_is_written(self, app, tmp_path):
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'host down')
        assert len(banners(log.read_text())) == 1

    def test_banner_is_the_first_line(self, app, tmp_path):
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'host down')
        assert BANNER_MARK in log.read_text().splitlines()[0]

    def test_banner_is_comment_prefixed_like_save(self, app, tmp_path):
        """':save' writes '# ...' headers; the two dialects must not diverge."""
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'host down')
        assert log.read_text().splitlines()[0].startswith('#')

    def test_banner_carries_pid(self, app, tmp_path):
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'host down')
        assert f'pid {os.getpid()}' in banners(log.read_text())[0]

    def test_banner_carries_hosts_file(self, app, tmp_path):
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'host down')
        assert '/opt/net/pb.hosts' in banners(log.read_text())[0]

    def test_banner_carries_target_count(self, app, tmp_path):
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'host down')
        assert '2 targets' in banners(log.read_text())[0], \
            'the section entry must not be counted as a target'

    def test_banner_omits_hosts_file_when_absent(self, pb, tmp_path):
        """Hosts given on the command line: there is no file to name."""
        a = pb.Application([('host', '10.0.0.1')])
        a._monitoring_started = True
        log = tmp_path / 'pb.log'
        a._cmd_log(str(log))
        a.add_event('10.0.0.1', 'host down')
        line = banners(log.read_text())[0]
        assert 'hosts file' not in line
        assert '1 targets' in line

    def test_target_count_is_stable_before_monitors_exist(self, pb, tmp_path):
        """A banner written during startup must not report zero targets.

        len(self.monitors) is still growing while entries are dispatched, so the
        count comes from the entry list instead.
        """
        log = tmp_path / 'pb.log'
        a = pb.Application([('cmd', f':log {log}'),
                            ('host', '10.0.0.1'), ('host', '10.0.0.2')])
        a.add_event('startup', 'something worth logging')
        assert '2 targets' in banners(log.read_text())[0]


class TestOneBannerPerSession:

    def test_many_events_share_one_banner(self, app, tmp_path):
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        for i in range(10):
            app.add_event('10.0.0.1', f'event {i}')
        assert len(banners(log.read_text())) == 1

    def test_switching_file_banners_the_new_one(self, app, tmp_path):
        first, second = tmp_path / 'a.log', tmp_path / 'b.log'
        app._cmd_log(str(first))
        app.add_event('10.0.0.1', 'in first')
        app._cmd_log(str(second))
        app.add_event('10.0.0.1', 'in second')
        assert len(banners(second.read_text())) == 1
        assert 'in second' in second.read_text()

    def test_switching_back_marks_the_resumption(self, app, tmp_path):
        first, second = tmp_path / 'a.log', tmp_path / 'b.log'
        app._cmd_log(str(first))
        app.add_event('10.0.0.1', 'first visit')
        app._cmd_log(str(second))
        app.add_event('10.0.0.1', 'elsewhere')
        app._cmd_log(str(first))
        app.add_event('10.0.0.1', 'second visit')
        assert len(banners(first.read_text())) == 2, \
            'resuming a log should mark where the gap was'

    def test_log_off_then_on_rebanners(self, app, tmp_path):
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'before off')
        app._cmd_log('off')
        app.add_event('10.0.0.1', 'while off')
        app._cmd_log(str(log))
        app.add_event('10.0.0.1', 'after on')
        text = log.read_text()
        assert len(banners(text)) == 2
        assert 'while off' not in text


class TestBannerViaOtherEntryPoints:

    def test_save_follow_gets_a_banner(self, app, tmp_path):
        log = tmp_path / 'followed.log'
        app._open_prompt_save(f'--follow {log}')
        app.add_event('10.0.0.1', 'streamed after follow')
        assert len(banners(log.read_text())) == 1

    def test_seen_marker_path_also_banners(self, app, tmp_path):
        """The '[Space]' seen marker appends through its own code path."""
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.mark_seen()
        assert len(banners(log.read_text())) == 1

    def test_bad_log_path_does_not_raise(self, app):
        """A failing open() must stay silent — an error event would recurse."""
        app._cmd_log('/nonexistent-dir-pb/pb.log')
        app.add_event('10.0.0.1', 'host down')   # must not raise


class TestBannerCountsRelayedHosts:
    """A relayed host arrives as a ':remote-ping' command, not a 'host' entry.

    Counting only 'host' reported "2 targets" for a file whose 54 hosts all sit
    inside a ':with remote-ping' block — the two direct hosts.
    """

    def _app(self, pb, entries):
        a = pb.Application(entries, hosts_file='/opt/net/pb.hosts')
        a._monitoring_started = True
        return a

    def test_remote_ping_hosts_are_counted(self, pb, tmp_path):
        app = self._app(pb, [('host', '10.0.0.1'),
                             ('cmd', ':remote-ping relay 10.1.0.1'),
                             ('cmd', ':remote-ping relay 10.1.0.2')])
        log = tmp_path / 'pb.log'
        app._cmd_log(str(log))
        app.add_event('x', 'y')
        assert '3 targets' in banners(log.read_text())[0]

    def test_the_count_matches_the_monitors(self, pb, tmp_path):
        entries = [('host', '10.0.0.1')] + [
            ('cmd', f':remote-ping relay 10.1.0.{i}') for i in range(1, 11)]
        app = self._app(pb, entries)
        assert app._target_count == len(app.monitors)

    def test_other_commands_are_not_counted(self, pb, tmp_path):
        app = self._app(pb, [('host', '10.0.0.1'),
                             ('cmd', ':set dns hostname'),
                             ('cmd', ':resolv 10.0.0.1 gw')])
        assert app._target_count == 1
