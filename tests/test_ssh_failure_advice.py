"""An ssh failure ping-bulk cannot act on must at least say what to do.

Every connection this program opens carries ``BatchMode=yes`` and
``stdin=DEVNULL``, so ssh never asks anything and never reads the terminal.
The cost of that — which is the right trade, since a child that can prompt
blocks for ever and writes over the curses screen — is that a host key nobody
has accepted, a password and a locked key all come back as one terse line and
the row simply dies.

**The wordings here were measured against a real sshd, not guessed**, because
the whole point is to branch on what ssh actually prints:

    unknown key   No ED25519 host key is known for <h> and you have requested
                  strict checking. / Host key verification failed.
    changed key   WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED! /
                  Host key verification failed.
    no usable key <user>@<host>: Permission denied (publickey,password).
    too many keys Received disconnect from <h> port 22:2: Too many
                  authentication failures

The defect this fixes: all three host-key cases matched one entry that said
"ssh host key mismatch". A *mismatch* means the key CHANGED — the
man-in-the-middle case — which is both wrong and alarming for a first
connection, and it named no fix. Reported from a real run whose log read
``host startup fail: ssh host key mismatch (Host key verification failed.)``
against a relay that had simply never been connected to.
"""

import io

import pytest

# ssh's own text, captured from OpenSSH against a live sshd.
UNKNOWN_KEY = ('No ED25519 host key is known for 10.10.100.247 and you have '
               'requested strict checking.\nHost key verification failed.')
CHANGED_KEY = ('@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n'
               '@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @\n'
               'Host key verification failed.')
NO_KEY      = 'admin@10.10.100.247: Permission denied (publickey,password).'
TOO_MANY    = ('Received disconnect from 10.10.100.247 port 22:2: '
               'Too many authentication failures')
PLAIN_REJECT = 'Host key verification failed.'


class TestTheThreeHostKeyCasesAreToldApart:
    """They arrive as one line and need three different answers."""

    def test_an_unknown_key_is_not_called_a_mismatch(self, pb):
        reason = pb._host_diagnosis(UNKNOWN_KEY)
        assert reason == 'ssh host key not known yet', reason
        assert 'mismatch' not in reason, (
            'a first connection is not a changed key, and saying so sends the '
            'reader looking for an attacker')

    def test_a_changed_key_says_so_loudly(self, pb):
        assert pb._host_diagnosis(CHANGED_KEY) == 'ssh host key CHANGED'

    def test_the_bare_rejection_still_has_an_answer(self, pb):
        """Neither specific wording present: the generic entry is the floor,
        not a gap."""
        assert pb._host_diagnosis(PLAIN_REJECT) == 'ssh rejected the host key'

    def test_the_three_do_not_collapse(self, pb):
        """The ordering guard. These are substring matches, first hit wins, so
        moving the generic entry above the specific ones silently restores the
        bug this file exists for."""
        got = {pb._host_diagnosis(t)
               for t in (UNKNOWN_KEY, CHANGED_KEY, PLAIN_REJECT)}
        assert len(got) == 3, got


class TestEachFailureCarriesItsFix:
    """``_SSH_FIX_TIPS`` is the existing one-off MikroTik mechanism widened to
    the family. The tip rides through ``_note_stderr`` and is deduped like any
    other line, so it is said once per host rather than once per probe."""

    @pytest.mark.parametrize('text,must_mention', [
        (UNKNOWN_KEY, 'ssh-keyscan'),
        (CHANGED_KEY, 'ssh-keygen -R'),
        (TOO_MANY,    'IdentitiesOnly'),
        (NO_KEY,      'ssh-agent'),
    ])
    def test_the_tip_names_the_command(self, pb, text, must_mention):
        low = text.lower()
        tip = next((t for _f, mark, t in pb._SSH_FIX_TIPS if mark in low), None)
        assert tip is not None, 'no tip for: ' + text.splitlines()[0]
        assert must_mention in tip, tip

    def test_a_password_and_a_passphrase_are_not_pretended_apart(self, pb):
        """Under BatchMode both arrive as 'Permission denied' and ssh gives us
        nothing to tell them apart, so one message names both. Inventing a
        distinction would be a confident wrong answer."""
        low = NO_KEY.lower()
        tip = next(t for _f, mark, t in pb._SSH_FIX_TIPS if mark in low)
        assert 'password' in tip and 'passphrase' in tip, tip

    def test_no_tip_can_trigger_a_tip(self, pb):
        """``_note_stderr`` feeds the tip back through itself to get the
        dedupe, so a tip containing a mark would recurse."""
        for _family, _mark, tip in pb._SSH_FIX_TIPS:
            low = tip.lower()
            hit = [m for _f, m, _t in pb._SSH_FIX_TIPS if m in low]
            assert not hit, (tip, hit)

    def test_every_tip_is_reachable(self, pb):
        """First hit wins, so a mark shadowed by an earlier one is dead text."""
        for i, (_fam, mark, _tip) in enumerate(pb._SSH_FIX_TIPS):
            earlier = [m for _f, m, _t in pb._SSH_FIX_TIPS[:i] if m in mark]
            assert not earlier, (
                '%r can never fire: shadowed by %r' % (mark, earlier))


class TestTheseStayFatal:
    """Each of these is a standing condition, not a flap: retrying cannot
    resolve an unaccepted host key, so the row stops rather than reconnecting
    for ever against something only a human can fix."""

    @pytest.mark.parametrize('text', [UNKNOWN_KEY, CHANGED_KEY, NO_KEY, TOO_MANY])
    def test_it_is_not_retried(self, pb, text):
        assert pb._is_fatal_ssh_text(text), text.splitlines()[0]


class TestWeDoNotImposeAHostKeyPolicy:
    """The regression guard for the worst mistake of this change.

    Forcing ``StrictHostKeyChecking=yes`` bought a better message — only
    ``yes`` prefixes ``No <TYPE> host key is known for <h>``, the one thing
    that tells an unknown key apart from a changed one — and it broke a working
    fleet within hours. ssh takes the first value of a repeated option and
    ping-bulk's go first, so it overrode an ``accept-new`` the operator had set
    in **~/.ssh/config**, and every host behind the relay failed verification
    at once.

    The yielding logic only ever consulted ``:set ssh-options`` and the
    directive's own arguments. A policy set where ssh itself reads it was
    invisible to it — so "an explicit choice wins" was true of the places this
    program looks, and false of the place the operator had used.

    Measured against the real relay: the identical command differed only by
    this option, and only with it did the connection fail.
    """

    def test_no_host_key_policy_is_forced(self, pb):
        flags = ' '.join(pb._ssh_diagnostic_flags())
        assert 'StrictHostKeyChecking' not in flags, (
            'a connection\'s host-key policy belongs to whoever configured '
            'ssh; overriding it from here broke a working fleet')

    def test_not_even_a_permissive_one(self, pb):
        """'accept-new' would be the mirror-image error: deciding to trust
        whatever answers, on the operator's behalf, without being asked."""
        flags = ' '.join(pb._ssh_diagnostic_flags())
        assert 'accept-new' not in flags

    def test_the_log_level_is_still_quietened(self, pb):
        """The one option this function does set, and it yields as before."""
        assert 'LogLevel=ERROR' in ' '.join(pb._ssh_diagnostic_flags())
        assert pb._ssh_diagnostic_flags(['-o', 'LogLevel=DEBUG']) == []

    def test_the_bare_rejection_keeps_a_tip(self, pb):
        """Without the forced option ssh usually will not explain itself, so
        the generic case is the common one and must still name a way to find
        out which failure it is."""
        tip = next(t for _f, mark, t in pb._SSH_FIX_TIPS
                   if mark == 'host key verification failed')
        assert 'ssh-keygen -F' in tip


class TestATipIsNotSomethingTheChildSaid:
    """``_note_stderr`` feeds tips back through itself to get the dedupe, and
    that put them in the accumulator behind ``self.error`` — so a run reported
    ``error: tip: this host key has never been accepted here…``, quoting us
    back as though ssh had said it. Seen on a real screen, not reasoned about.
    """

    def _monitor(self, pb, tmp_path):
        import os
        from unittest.mock import patch
        cfg = str(tmp_path / 'c' / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        hosts = tmp_path / 'h.hosts'
        hosts.write_text(':with remote-ping relay\n10.0.0.1 ## target\n')
        with patch.object(pb, '_config_path', return_value=cfg):
            app = pb.Application(pb.parse_hosts_file(str(hosts)),
                                 hosts_file=str(hosts))
        return app.monitors[0]

    def test_the_tip_reaches_the_log(self, pb, tmp_path):
        m = self._monitor(pb, tmp_path)
        m._note_stderr(UNKNOWN_KEY.splitlines()[0])
        assert any(t.startswith('tip:') for t in m.take_new_stderr())

    def test_but_never_the_error_text(self, pb, tmp_path):
        m = self._monitor(pb, tmp_path)
        m._note_stderr(UNKNOWN_KEY.splitlines()[0])
        joined = ' '.join(m._stderr_lines)
        assert 'tip:' not in joined, joined
        assert not m.last_stderr[0].startswith('tip:'), m.last_stderr

    def test_the_row_reason_is_the_diagnosis_not_the_tip(self, pb, tmp_path):
        m = self._monitor(pb, tmp_path)
        m._note_stderr(UNKNOWN_KEY.splitlines()[0])
        assert pb._host_diagnosis(m.last_stderr[0]) == 'ssh host key not known yet'

    def test_one_tip_per_failure(self, pb, tmp_path):
        """ssh prints the explanation *and* the verdict. A tip on each is two
        answers to one question, which is what the first cut did."""
        m = self._monitor(pb, tmp_path)
        for line in UNKNOWN_KEY.splitlines():
            m._note_stderr(line)
        tips = [t for t in m.take_new_stderr() if t.startswith('tip:')]
        assert len(tips) == 1, tips


class TestNoConnectionCanAskAHuman:
    """Taking the terminal away is half the job; ssh has a second route.

    With no controlling tty ssh does not give up — it falls back to
    ``SSH_ASKPASS`` and puts the same host-key question in a **GUI window**,
    which blocks exactly as the terminal prompt did and is further out of reach
    of whoever is watching the screen. Reported as a gpg-agent dialog carrying
    the same "yes" question, on a machine where nothing but ``DISPLAY`` was
    set — so the first fix had moved the problem rather than closed it.
    """

    def test_the_gui_fallback_is_refused(self, pb):
        assert pb._ssh_child_env()['SSH_ASKPASS_REQUIRE'] == 'never'

    def test_and_the_older_routes_to_it_are_removed(self, pb, monkeypatch):
        """``SSH_ASKPASS_REQUIRE`` is OpenSSH 8.4+; an older ssh consults
        ``DISPLAY`` and ``SSH_ASKPASS`` on their own."""
        monkeypatch.setenv('DISPLAY', ':0')
        monkeypatch.setenv('SSH_ASKPASS', '/usr/bin/ssh-askpass')
        env = pb._ssh_child_env()
        assert 'DISPLAY' not in env
        assert 'SSH_ASKPASS' not in env

    def test_the_agent_is_kept(self, pb, monkeypatch):
        """An agent answers without asking anybody, which is the case worth
        having — dropping it would turn working key auth into a failure."""
        monkeypatch.setenv('SSH_AUTH_SOCK', '/tmp/ssh-xxx/agent.1')
        assert pb._ssh_child_env()['SSH_AUTH_SOCK'] == '/tmp/ssh-xxx/agent.1'

    def test_the_rest_of_the_environment_survives(self, pb, monkeypatch):
        """It is a copy with three keys touched, not a hand-built environment:
        ssh still needs HOME to find its config and known_hosts."""
        monkeypatch.setenv('HOME', '/home/someone')
        assert pb._ssh_child_env()['HOME'] == '/home/someone'

    def test_every_connection_we_open_uses_it(self, pb):
        """The four spawns ping-bulk makes for itself. A new one that forgets
        this reopens the GUI prompt for whichever host it reaches."""
        import re
        src = io.open(pb.__file__, encoding='utf-8').read() if hasattr(pb, '__file__') else None
        if src is None:
            import pathlib
            src = pathlib.Path('/home/komar/work/github/ping-bulk.git/ping-bulk').read_text()
        assert src.count('env=_ssh_child_env()') == 4, (
            'expected the four self-opened connections to carry it')


class TestTheTipTableIsWellFormed:
    """The guard for a mistake that cost a full suite run.

    ``_SSH_FIX_TIPS`` grew a family column and three rows did not get it, so
    the table held a mix of 2- and 3-tuples. ``for family, mark, tip in …``
    then raised inside ``_note_stderr``, which runs in the reader loop — so
    **67 monitor tests failed with empty history and no latency**, reporting a
    monitor that had simply died, with nothing anywhere naming the real cause.
    It passed in isolation, because that one test never produced a stderr line.

    One assertion on the shape of the table turns that into an instant,
    obvious failure.
    """

    def test_every_row_has_the_same_shape(self, pb):
        shapes = {len(row) for row in pb._SSH_FIX_TIPS}
        assert shapes == {3}, (
            'mixed arity unpacks wrongly inside the reader loop and kills the '
            'monitor: %r' % (shapes,))

    def test_every_row_is_three_strings(self, pb):
        for row in pb._SSH_FIX_TIPS:
            assert all(isinstance(x, str) and x for x in row), row

    def test_the_families_are_the_known_ones(self, pb):
        """A typo'd family silently stops deduping instead of failing."""
        assert {r[0] for r in pb._SSH_FIX_TIPS} == {
            'forward', 'hostkey', 'auth', 'sessions'}

    def test_the_other_table_keeps_its_own_shape(self, pb):
        """``_HOST_DIAGNOSES`` sits beside ``_SSH_FIX_TIPS`` and shares its
        wordings, so an edit aimed at one lands in the other — which is exactly
        what happened: the family column was added to the diagnoses table by
        mistake and `_host_diagnosis` raised on every transport error."""
        shapes = {len(row) for row in pb._HOST_DIAGNOSES}
        assert shapes == {2}, shapes


class TestARelayOutOfSessionsNamesTheSetting:
    """A fleet behind one relay walks into its ssh server's session ceiling.

    Measured end to end on 2026-10-09: ~45 monitors through a MikroTik
    CRS328-24P-4S+ (RouterOS 7.22) used as a ``-J`` jump failed host after host
    with ``Stdio forwarding request failed: Session open refused by peer``. The
    cap was read live off the box — ``/ip service`` ``max-sessions=20``, the
    stock default — and every measurement lines up with it: 20 concurrent all
    succeeded, and 30 through a single shared master got 22 through before the
    rest were refused.

    **The setting is in ``/ip service``, not ``/ip ssh``**, which is why it is
    missed: the ``/ip ssh`` menu holds only ciphers, host keys and forwarding.
    Naming the wrong menu would be worse than saying nothing, so the tip names
    both the right one and the command.

    A shared connection is **not** a workaround, and the tip must not suggest
    one: ``max-sessions`` counts sessions, so moving them onto one connection
    changes nothing — measured, and the reason that avenue was closed.
    """

    REFUSED = ('Stdio forwarding request failed: '
               'Session open refused by peer')
    FORWARD_FAILED = 'Stdio forwarding request failed'

    def _tip(self, pb, text):
        low = text.lower()
        return next((t for _f, mark, t in pb._SSH_FIX_TIPS if mark in low), None)

    def test_the_refusal_gets_a_tip(self, pb):
        assert self._tip(pb, self.REFUSED) is not None

    def test_it_names_the_right_menu(self, pb):
        tip = self._tip(pb, self.REFUSED)
        assert '/ip service set ssh max-sessions' in tip, tip

    def test_and_says_it_is_not_the_other_menu(self, pb):
        """An operator who goes to '/ip ssh' finds ciphers and host keys and
        concludes there is no such setting — which is what happened."""
        tip = self._tip(pb, self.REFUSED)
        assert '/ip ssh' in tip and 'NOT' in tip, tip

    def test_it_gives_the_default_so_the_number_can_be_judged(self, pb):
        tip = self._tip(pb, self.REFUSED)
        assert '20' in tip, tip

    def test_an_openssh_relay_is_not_left_out(self, pb):
        """The same wording is OpenSSH's MaxSessions refusal, and a reader on
        a Linux relay must not be sent to a RouterOS menu that does not exist
        for them."""
        assert 'MaxSessions' in self._tip(pb, self.REFUSED)

    def test_both_wordings_are_one_family(self, pb):
        """ssh reports the refusal and the failed '-W' setup as separate
        lines of the same failure; two tips would be two answers to one
        question."""
        fams = {f for f, mark, _t in pb._SSH_FIX_TIPS
                if mark in (self.REFUSED.lower(), self.FORWARD_FAILED.lower())}
        assert fams == {'sessions'}, fams

    def test_a_target_that_is_simply_unreachable_gets_no_session_tip(self, pb):
        """'channel open failed: connect failed' means the jump could not
        reach the host — a different fault, and sending the reader to raise a
        session limit would waste their time."""
        assert self._tip(pb, 'channel 0: open failed: connect failed:') is None
