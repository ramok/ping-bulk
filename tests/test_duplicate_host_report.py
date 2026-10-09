"""A dropped host must say which one, and what already holds its address.

Reported as *"I add SH254. but for some reason parser drop many hosts from
it"*. Nothing was wrong: three of the generated addresses were already
monitored under other names, and ping-bulk deduplicates by target because
pinging one box twice doubles the traffic and tells you nothing new.

It did warn — and the warning was ``duplicate host ignored: 10.123.254.1``,
which names neither the line that was dropped nor the one that already had the
address. In a file of forty-odd hosts across nested ``:for`` loops that sends
the reader hunting, which is why the drop read as a parser bug.
"""

import pytest

FILE = """## harbour-network
10.123.254.1   ## harbour-router
10.123.254.2   ## proxmox
10.123.254.20  ## cortex
### sensor-hub-254
10.123.254.1   ## sh254-router
10.123.254.2   ## sh254-comm-mod
10.123.254.8   ## sh254-jetson
10.123.254.20  ## sh254-power-switch
"""


def _warnings(pb, tmp_path, text=FILE):
    f = tmp_path / 'h.hosts'
    f.write_text(text)
    return [e[1] for e in pb.parse_hosts_file(str(f))
            if isinstance(e, tuple) and e and e[0] == 'warn']


class TestADroppedHostNamesBothSides:
    def test_it_names_the_host_that_was_dropped(self, pb, tmp_path):
        warns = _warnings(pb, tmp_path)
        assert any('sh254-router' in w for w in warns), warns

    def test_and_what_already_held_the_address(self, pb, tmp_path):
        warns = _warnings(pb, tmp_path)
        assert any('already monitored as harbour-router' in w for w in warns), warns

    def test_the_address_is_still_there_to_grep_for(self, pb, tmp_path):
        """The log is read with grep as often as with eyes."""
        warns = _warnings(pb, tmp_path)
        assert any('10.123.254.1' in w for w in warns), warns

    def test_one_warning_per_dropped_host(self, pb, tmp_path):
        warns = [w for w in _warnings(pb, tmp_path) if 'duplicate host' in w]
        assert len(warns) == 3, warns

    def test_the_survivor_is_not_warned_about(self, pb, tmp_path):
        """10.123.254.8 is unique and must pass through silently."""
        assert not any('254.8' in w for w in _warnings(pb, tmp_path))


class TestAnUnlabelledDuplicateStillReads:
    """Not every host carries a '##' label; the message must degrade rather
    than print an empty name or repeat the address twice."""

    PLAIN = '10.0.0.1\n10.0.0.1\n'

    def test_it_does_not_say_the_address_twice(self, pb, tmp_path):
        warns = _warnings(pb, tmp_path, self.PLAIN)
        assert warns, 'the duplicate must still be reported'
        assert '10.0.0.1 (10.0.0.1)' not in warns[0], warns[0]

    def test_it_names_the_address(self, pb, tmp_path):
        assert '10.0.0.1' in _warnings(pb, tmp_path, self.PLAIN)[0]


class TestTheRuleItself:
    def test_deduplication_is_by_address_not_by_name(self, pb, tmp_path):
        """Two different labels on one address are one box, so one monitor —
        which is why the second is dropped even though its name is new, and
        why the warning has to name the first. If this ever becomes per-name,
        the message above is wrong too."""
        f = tmp_path / 'h.hosts'
        f.write_text('10.0.0.1 ## first\n10.0.0.1 ## second\n')
        entries = pb.parse_hosts_file(str(f))
        hosts = [e[1] for e in entries
                 if isinstance(e, tuple) and e and e[0] == 'host']
        assert hosts == ['first'], hosts
