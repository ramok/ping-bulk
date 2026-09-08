"""Unit tests for the hosts_map shared between the app and its monitors."""

from unittest.mock import patch

import pytest


def _app(pb, tmp_path, entries):
    cfg = tmp_path / 'ping-bulk' / 'config'
    cfg.parent.mkdir(parents=True, exist_ok=True)
    cfg.write_text('')
    with patch.object(pb, '_config_path', return_value=str(cfg)):
        a = pb.Application(entries)
    a._monitoring_started = True
    return a


class TestSharedHostsMap:
    """The first monitor must share the app's hosts_map, empty or not.

    'hosts_map or {}' treated an empty dict as falsy and handed the first
    monitor a private copy, so a host built before any ':resolv' never saw the
    mappings that arrived later: its display name stayed an IP, and a glob rule
    matched on the alias could never match it.
    """

    def test_first_relayed_host_shares_the_map(self, pb, tmp_path):
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':with remote-ping relay\n'
            '    10.0.0.20 ## first-host\n'
            '    10.0.0.21 ## second-host\n'
            ':end\n'))
        for m in app.monitors:
            assert m._hosts_map is app.hosts_map, m._ping_host

    def test_first_relayed_host_resolves_its_alias(self, pb, tmp_path):
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':with remote-ping relay\n    10.0.0.20 ## first-host\n:end\n'))
        assert app._prog_match_names(app.monitors[0])[1] == 'first-host'

    def test_a_prog_options_glob_reaches_the_first_relayed_host(self, pb, tmp_path):
        """The user-visible consequence: rules matched every host but the first."""
        app = _app(pb, tmp_path, pb._HostsParser().parse(
            ':prog-options ssh *-switch -l admin\n'
            ':with remote-ping relay\n'
            '    10.0.0.20 ## power-switch\n'
            ':end\n'))
        names = app._prog_match_names(app.monitors[0])
        assert app._match_prog_options('ssh', *names) == (False, '-l admin')

    def test_an_explicit_empty_map_is_still_shared(self, pb):
        """A map handed in empty must stay the same object."""
        shared = {}
        m = pb.SshPingMonitor(['relay'], '10.0.0.1', hosts_map=shared)
        # Both directions, as _apply_hosts_entry stores them; the reverse
        # lookup skips the self-mapping so the readable alias wins.
        shared['10.0.0.1'] = ('10.0.0.1', 'alias')
        shared['alias'] = ('10.0.0.1', 'alias')
        assert m._hosts_map is shared
        assert m._reverse_lookup_alias('10.0.0.1') == 'alias'

    def test_no_map_still_gets_its_own(self, pb):
        m = pb.SshPingMonitor(['relay'], '10.0.0.1')
        assert m._hosts_map == {}
