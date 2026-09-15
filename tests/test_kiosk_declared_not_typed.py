"""Three commands a kiosk hosts file may declare and a console user may not type.

``:bind-key`` and ``:web start`` are refused at the keyboard under ``--kiosk``
and allowed while the hosts file is being read, because that mode's threat
model is the person standing at the console — not the operator who deployed the
file.  ``:set web-anonymous`` joins them here.

``:source`` reads the same flag and must **not** honour it, which is the whole
of ``TestSourceKeepsItsGuard`` below.

**The exemption did not exist.**  ``_loading_file`` was read in three places
— ``:bind-key``, ``:web start`` and, then, ``:source`` — and assigned in none,
so it was always False in production: a kiosk hosts file's ``:web start`` was
refused, and its ``:bind-key`` lines were dropped.  Nothing said so, because reading a phantom attribute through
``getattr(self, ..., False)`` raises nothing — and the tests that covered the
three exemptions each set the flag **by hand**, so they proved the feature
works in a state the program never reached.

So every test below drives a real hosts file through ``parse_hosts_file`` and
``Application.__init__``.  None of them assigns ``_loading_file``; a test that
did would be the bug all over again.
"""

import os
import pathlib
import shutil
import tempfile

import pytest
from unittest.mock import patch


def _app(pb, tmp_path, content, kiosk=True):
    """Build an Application the way a run does: a file, parsed, then loaded."""
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    hosts = tmp_path / 'declared.hosts'
    hosts.write_text(content)
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application(pb.parse_hosts_file(str(hosts)),
                             hosts_file=str(hosts), kiosk_mode=kiosk)
    app._monitoring_started = True
    return app


def _events(app):
    return ' | '.join(e.text for e in app.events)


class TestTheFlagIsActuallySet:
    """The whole bug in one assertion, plus the window it is confined to."""

    def test_the_hosts_file_load_sets_it(self, pb, tmp_path):
        """A directive dispatched from the file sees the flag True.

        ':set dns' is the witness because it is inert and it really does go
        through _dispatch_cmd from the entry loop — ':let' does not, being a
        parse-time directive the Application never sees.
        """
        seen = []
        real = pb.Application._cmd_dns

        def spy(self, args=''):
            seen.append(self._loading_file)
            return real(self, args)

        with patch.object(pb.Application, '_cmd_dns', spy):
            _app(pb, tmp_path, ':set dns ip\n10.0.0.1\n')
        assert seen == [True], seen

    def test_it_is_cleared_once_the_file_is_read(self, pb, tmp_path):
        """Otherwise every later keypress would inherit the file's trust."""
        app = _app(pb, tmp_path, '10.0.0.1\n')
        assert app._loading_file is False

    def test_it_is_false_before_any_file_is_read(self, pb):
        """Several tests build an Application through __new__ and still
        dispatch commands, so the default lives on the class.

        Asserted on such an instance rather than on the class, because it is
        the instance that _dispatch_cmd reads.
        """
        bare = pb.Application.__new__(pb.Application)
        assert bare._loading_file is False


class TestWebStart:
    """':web start' — the reason this was found."""

    def test_a_kiosk_hosts_file_may_declare_the_listener(self, pb, tmp_path):
        app = _app(pb, tmp_path,
                   ':set web-listen 127.0.0.1:0\n:web start\n10.0.0.1\n')
        try:
            assert app._web_server is not None, _events(app)
        finally:
            app._web_stop(quiet=True)

    def test_the_console_still_cannot_type_it(self, pb, tmp_path):
        app = _app(pb, tmp_path, ':set web-listen 127.0.0.1:0\n10.0.0.1\n')
        app._dispatch_cmd(':web start')
        assert app._web_server is None
        assert 'kiosk' in _events(app)


class TestBindKey:
    """':bind-key' — silently dropped from every kiosk hosts file until now.

    'Y' rather than 'G': 'G' carries a default binding (vim's jump-to-last), so
    resolving it finds that whether or not the ':bind-key' line took effect.
    """

    def test_a_kiosk_hosts_file_may_declare_a_binding(self, pb, tmp_path):
        app = _app(pb, tmp_path,
                   ':bind-key --desc "go" Y :select last\n10.0.0.1\n')
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('Y'), set())
        assert binding is not None, _events(app)

    def test_the_console_still_cannot_type_one(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        app._dispatch_cmd(':bind-key Y :select last')
        binding, _ = app._key_trie.resolve(pb._parse_key_notation('Y'), set())
        assert binding is None


class TestWebAnonymous:
    """':set web-anonymous' now follows the same rule as the bind."""

    def test_a_kiosk_hosts_file_may_declare_it(self, pb, tmp_path):
        app = _app(pb, tmp_path, ':set web-anonymous read-only\n10.0.0.1\n')
        assert app.web_anonymous == 'read-only', _events(app)

    def test_the_console_still_cannot_type_it(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        app._dispatch_cmd(':set web-anonymous read-only')
        assert app.web_anonymous == 'off'
        assert 'kiosk' in _events(app)

    def test_the_refusal_is_visible_at_the_default_log_level(self, pb, tmp_path):
        """Category 'cmd' is LEVEL_INFO, so an event-only refusal says nothing
        on screen — this program has shipped that bug three times."""
        app = _app(pb, tmp_path, '10.0.0.1\n')
        app._dispatch_cmd(':set web-anonymous read-only')
        hits = [e for e in app.events
                if 'web-anonymous' in e.text and e.level <= pb.LEVEL_NORMAL]
        assert hits, _events(app)

    def test_declaring_it_under_kiosk_is_audited(self, pb, tmp_path):
        """Opening the estate to anyone who can reach the port is at least as
        consequential as the bind, which is audited."""
        seen = []
        with patch.object(pb.Application, '_kiosk_audit',
                          lambda self, a, d='': seen.append((a, d))):
            _app(pb, tmp_path, ':set web-anonymous read-only\n10.0.0.1\n')
        assert ('web-anonymous', 'read-only') in seen, seen

    def test_turning_it_off_is_always_allowed(self, pb, tmp_path):
        """A refusal that also blocks 'off' would be a setting you cannot undo."""
        app = _app(pb, tmp_path, ':set web-anonymous read-only\n10.0.0.1\n')
        app._dispatch_cmd(':set web-anonymous off')
        assert app.web_anonymous == 'off'

    def test_it_is_unrestricted_when_kiosk_mode_is_off(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n', kiosk=False)
        app._dispatch_cmd(':set web-anonymous read-only')
        assert app.web_anonymous == 'read-only'


class TestTheEditReloadIsNotALoad:
    """The extension that looks obvious and is wrong.

    ':edit' is *allowed* at the console under kiosk — it opens a restricted
    editor (rnano/rvim) on the hosts file.  So a reload replays a file the
    person at the keyboard may have just written, while startup replays the one
    the operator deployed.  Giving the reload the same exemption would hand
    that person ':web start' and ':bind-key <k> :mux sh' through the editor.
    """

    def test_a_reload_does_not_inherit_the_file_s_trust(self, pb, tmp_path):
        app = _app(pb, tmp_path, '10.0.0.1\n')
        hosts = tmp_path / 'declared.hosts'
        hosts.write_text(':set web-listen 127.0.0.1:0\n:web start\n10.0.0.1\n')
        app._edit_reload_inplace(str(hosts))
        try:
            assert app._web_server is None, _events(app)
            assert 'kiosk' in _events(app)
        finally:
            app._web_stop(quiet=True)

    def test_a_reload_outside_kiosk_mode_is_unaffected(self, pb, tmp_path):
        """The restriction is kiosk's, not the reload's."""
        app = _app(pb, tmp_path, '10.0.0.1\n', kiosk=False)
        hosts = tmp_path / 'declared.hosts'
        hosts.write_text(':set web-listen 127.0.0.1:0\n:web start\n10.0.0.1\n')
        app._edit_reload_inplace(str(hosts))
        try:
            assert app._web_server is not None, _events(app)
        finally:
            app._web_stop(quiet=True)


@pytest.fixture
def outside_tmp():
    """Two directories under /var/tmp: where the hosts file lives, and one that
    is outside every kiosk-allowed prefix.

    Both details are load-bearing.  ``tmp_path`` cannot be used at all here,
    because pytest puts it under ``/tmp`` and ``/tmp/`` **is** an allowed
    prefix — the guard would then pass for a reason unrelated to what is being
    asserted.  And the second directory is a *sibling*, never a child: the
    hosts file's own directory is itself an allowed prefix, so a subdirectory
    of it is admitted too.  Both mistakes were made first, and both made the
    test pass while proving nothing.
    """
    home = pathlib.Path(tempfile.mkdtemp(prefix='pb-kiosk-home-', dir='/var/tmp'))
    try:
        away = pathlib.Path(
            tempfile.mkdtemp(prefix='pb-kiosk-away-', dir='/var/tmp'))
        try:
            yield home, away
        finally:
            shutil.rmtree(away, ignore_errors=True)
    finally:
        shutil.rmtree(home, ignore_errors=True)


class TestSourceKeepsItsGuard:
    """':source' reads the same flag and must not honour it.

    For ':bind-key' and ':web start' the unset flag meant the *feature* was
    dead.  Here it meant the opposite: the always-False read made
    ``_kiosk_allow_path`` run every time, so turning the flag on would have
    *removed* a guard that was working — a kiosk hosts file could then source
    any absolute path, and through a nested ':source' reach ':web start' on the
    outer file's trust.  Nothing legitimate is lost, because the hosts file's
    own directory is an allowed prefix.
    """

    def test_a_kiosk_hosts_file_cannot_source_outside_the_allowed_paths(
            self, pb, outside_tmp):
        home, away = outside_tmp
        (away / 'extra.hosts').write_text('10.9.9.9\n')
        app = _app(pb, home, f':source {away}/extra.hosts\n10.0.0.1\n')
        assert [m.host for m in app.monitors] == ['10.0.0.1'], _events(app)
        assert 'not in allowed directories' in _events(app)

    def test_a_nested_source_cannot_reach_the_listener(self, pb, outside_tmp):
        """The escalation the guard exists to stop, spelled out."""
        home, away = outside_tmp
        (away / 'extra.hosts').write_text(
            ':set web-listen 127.0.0.1:0\n:web start\n')
        app = _app(pb, home, f':source {away}/extra.hosts\n10.0.0.1\n')
        try:
            assert app._web_server is None, _events(app)
        finally:
            app._web_stop(quiet=True)

    def test_a_sibling_of_the_hosts_file_is_still_allowed(self, pb, outside_tmp):
        """The case _kiosk_allow_path was written for must keep working.

        Nothing is under /tmp, so the hosts file's own directory is the only
        prefix that can admit this — which is the point.
        """
        home, _away = outside_tmp
        (home / 'extra.hosts').write_text('10.9.9.9\n')
        app = _app(pb, home, f':source {home}/extra.hosts\n10.0.0.1\n')
        assert '10.9.9.9' in [m.host for m in app.monitors], _events(app)

    def test_outside_kiosk_mode_any_path_is_fine(self, pb, outside_tmp):
        home, away = outside_tmp
        (away / 'extra.hosts').write_text('10.9.9.9\n')
        app = _app(pb, home, f':source {away}/extra.hosts\n10.0.0.1\n',
                   kiosk=False)
        assert '10.9.9.9' in [m.host for m in app.monitors], _events(app)
