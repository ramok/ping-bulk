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
        tip = next((t for mark, t in pb._SSH_FIX_TIPS if mark in low), None)
        assert tip is not None, 'no tip for: ' + text.splitlines()[0]
        assert must_mention in tip, tip

    def test_a_password_and_a_passphrase_are_not_pretended_apart(self, pb):
        """Under BatchMode both arrive as 'Permission denied' and ssh gives us
        nothing to tell them apart, so one message names both. Inventing a
        distinction would be a confident wrong answer."""
        low = NO_KEY.lower()
        tip = next(t for mark, t in pb._SSH_FIX_TIPS if mark in low)
        assert 'password' in tip and 'passphrase' in tip, tip

    def test_no_tip_can_trigger_a_tip(self, pb):
        """``_note_stderr`` feeds the tip back through itself to get the
        dedupe, so a tip containing a mark would recurse."""
        for _mark, tip in pb._SSH_FIX_TIPS:
            low = tip.lower()
            hit = [m for m, _ in pb._SSH_FIX_TIPS if m in low]
            assert not hit, (tip, hit)

    def test_every_tip_is_reachable(self, pb):
        """First hit wins, so a mark shadowed by an earlier one is dead text."""
        for i, (mark, _tip) in enumerate(pb._SSH_FIX_TIPS):
            earlier = [m for m, _ in pb._SSH_FIX_TIPS[:i] if m in mark]
            assert not earlier, (
                '%r can never fire: shadowed by %r' % (mark, earlier))


class TestTheseStayFatal:
    """Each of these is a standing condition, not a flap: retrying cannot
    resolve an unaccepted host key, so the row stops rather than reconnecting
    for ever against something only a human can fix."""

    @pytest.mark.parametrize('text', [UNKNOWN_KEY, CHANGED_KEY, NO_KEY, TOO_MANY])
    def test_it_is_not_retried(self, pb, text):
        assert pb._is_fatal_ssh_text(text), text.splitlines()[0]


class TestSshIsAskedToExplainItself:
    """The diagnosis above is only possible if ssh says which problem it is,
    and by default it does not.

    Measured against a real relay with ping-bulk's own flags: the default
    ``StrictHostKeyChecking=ask`` answers the bare ``Host key verification
    failed.``, which cannot tell a host nobody has accepted from one whose key
    has changed — and those need opposite answers. ``yes`` prefixes ``No RSA
    host key is known for <h> …``. Under ``BatchMode`` both refuse identically,
    so this buys the explanation and changes no outcome.

    Found by running it, not by reading it: the first cut of this fix shipped a
    branch that could never fire in production, because the test fixture had
    passed ``UserKnownHostsFile=/dev/null`` and that alone makes ssh explain.
    """

    def test_it_asks_for_the_explanation(self, pb):
        assert '-o' in pb._ssh_diagnostic_flags()
        assert 'StrictHostKeyChecking=yes' in pb._ssh_diagnostic_flags()

    def test_it_never_accepts_a_key_on_its_own(self, pb):
        """'accept-new' would make the message problem go away by trusting
        whatever answers, which is the one thing the check exists to stop."""
        assert 'accept-new' not in ' '.join(pb._ssh_diagnostic_flags())

    def test_an_explicit_choice_wins(self, pb):
        """ssh keeps the first value of a repeated option and these are placed
        first, so not yielding here would silently ignore the user."""
        got = pb._ssh_diagnostic_flags(['-o', 'StrictHostKeyChecking=accept-new'])
        assert 'StrictHostKeyChecking=yes' not in got, got
        assert 'LogLevel=ERROR' in got, 'the two must yield independently'

    def test_the_log_level_still_yields_on_its_own(self, pb):
        got = pb._ssh_diagnostic_flags(['-o', 'LogLevel=DEBUG'])
        assert 'LogLevel=ERROR' not in got
        assert 'StrictHostKeyChecking=yes' in got, got


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
