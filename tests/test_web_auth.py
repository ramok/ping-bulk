"""Who may read the host list.

Two credentials, because there are two situations.

A **token**, minted at every ':web start' and printed as a whole URL.  Nothing
to configure, nothing written down, and it dies with the process — the
loopback case, where the operator already had to get onto the machine to
start it.

A **password file**, for a listener that outlives one run.  The path and its
permissions belong to the operator, which is this program's answer to "where
would a hash live?": under the kiosk systemd unit the config directory is
readable by the console user, and that user is precisely who kiosk mode is
guarding against.  So the verifier is never written to the config — only the
path to it is.

The page itself is served without a session.  It carries no data, and there
has to be somewhere to type the password; everything that *is* data sits
behind the session cookie.
"""

import json
import os
import subprocess
import time
import urllib.error
import urllib.request

import pytest
from unittest.mock import patch


def _make_app(pb, tmp_path, kiosk=False):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '10.0.0.1')], kiosk_mode=kiosk)
    app._monitoring_started = True
    app._cfg_path = cfg
    return app


def _password_file(tmp_path, text='hunter2', mode=0o600):
    path = tmp_path / 'webpw'
    path.write_text(text)
    os.chmod(path, mode)
    return str(path)


def _events(app):
    return ' | '.join(e.text for e in app.events)


class Session:
    """A tiny cookie-aware client, so the tests read like a browser."""

    def __init__(self, app):
        host, port = app._web_server.server_address[:2]
        self.base = f'http://{host}:{port}'
        self.cookie = ''

    def _go(self, req):
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                self._store(r.headers.get('Set-Cookie'))
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            self._store(e.headers.get('Set-Cookie'))
            return e.code, e.read()

    def _store(self, header):
        if header:
            self.cookie = header.split(';')[0]

    def get(self, path='/', follow=True):
        req = urllib.request.Request(self.base + path)
        if self.cookie:
            req.add_header('Cookie', self.cookie)
        if not follow:
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **kw):
                    return None
            opener = urllib.request.build_opener(NoRedirect)
            try:
                with opener.open(req, timeout=10) as r:
                    self._store(r.headers.get('Set-Cookie'))
                    return r.status, r.read()
            except urllib.error.HTTPError as e:
                self._store(e.headers.get('Set-Cookie'))
                return e.code, e.read()
        return self._go(req)

    def login(self, password, ctype='application/json'):
        body = json.dumps({'password': password}).encode()
        req = urllib.request.Request(self.base + '/api/login', data=body,
                                     method='POST')
        req.add_header('Content-Type', ctype)
        if self.cookie:
            req.add_header('Cookie', self.cookie)
        return self._go(req)


@pytest.fixture
def served(pb, tmp_path):
    """Listener up on loopback, token only."""
    app = _make_app(pb, tmp_path)
    app._dispatch_cmd(':set web-listen 127.0.0.1:0')
    app._dispatch_cmd(':web start')
    assert app._web_server is not None, _events(app)
    try:
        yield app, Session(app)
    finally:
        app._web_stop(quiet=True)


@pytest.fixture
def served_pw(pb, tmp_path):
    """Listener up on loopback with a password configured."""
    app = _make_app(pb, tmp_path)
    app._dispatch_cmd(f':set web-password-file {_password_file(tmp_path)}')
    app._dispatch_cmd(':set web-listen 127.0.0.1:0')
    app._dispatch_cmd(':web start')
    assert app._web_server is not None, _events(app)
    try:
        yield app, Session(app)
    finally:
        app._web_stop(quiet=True)


# ===========================================================================
# The verifier
# ===========================================================================

class TestPasswordHashing:

    def test_it_round_trips(self, pb):
        v = pb._web_hash_password('hunter2')
        assert pb._web_check_password(v, 'hunter2')
        assert not pb._web_check_password(v, 'hunter3')

    def test_the_same_password_hashes_differently_each_time(self, pb):
        """Per-password salt: two operators with one password look unrelated."""
        assert pb._web_hash_password('x') != pb._web_hash_password('x')

    def test_the_verifier_says_what_it_is(self, pb):
        """Self-describing, so the cost can be raised without a flag day."""
        scheme, rounds, _salt, _hash = pb._web_hash_password('x').split('$')
        assert scheme == 'pbkdf2_sha256'
        assert int(rounds) >= 100_000

    def test_a_malformed_verifier_fails_shut(self, pb):
        for bad in ('', 'nonsense', 'pbkdf2_sha256$x$y$z', 'md5$1$a$b',
                    'pbkdf2_sha256$1000$!!$!!'):
            assert pb._web_check_password(bad, 'x') is False, bad


class TestThePasswordFile:

    def test_a_plain_password_is_hashed(self, pb, tmp_path):
        v = pb._web_read_password_file(_password_file(tmp_path, 'hunter2\n'))
        assert v.startswith('pbkdf2_sha256$')
        assert pb._web_check_password(v, 'hunter2')

    def test_an_already_hashed_file_is_used_as_is(self, pb, tmp_path):
        """So a deployment can keep the plaintext out of the image."""
        v = pb._web_hash_password('hunter2')
        assert pb._web_read_password_file(_password_file(tmp_path, v)) == v

    def test_a_readable_by_others_file_is_refused(self, pb, tmp_path):
        """The whole point is that the local user cannot read it."""
        with pytest.raises(ValueError, match='world-readable'):
            pb._web_read_password_file(_password_file(tmp_path, mode=0o644))
        with pytest.raises(ValueError, match='readable'):
            pb._web_read_password_file(_password_file(tmp_path, mode=0o640))

    def test_a_missing_or_empty_file_is_refused_with_the_reason(self, pb,
                                                                tmp_path):
        with pytest.raises(ValueError, match='cannot read'):
            pb._web_read_password_file(str(tmp_path / 'nope'))
        with pytest.raises(ValueError, match='empty'):
            pb._web_read_password_file(_password_file(tmp_path, ''))

    def test_setting_it_reports_immediately_but_keeps_the_path(self, pb,
                                                               tmp_path):
        """Said at once, and the setting survives it.

        Refusing to *store* an unusable path was worse than useless: a file
        whose mode had been relaxed by an installer or a restore dropped the
        setting silently, and the next ':save-config' wrote the config back
        without the line.  The operator then met "refusing to listen on
        0.0.0.0 without a password — set ':set web-password-file'", naming the
        setting they had set, with the path gone for good.  Whether a file can
        be read is a question for the moment it is read.
        """
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-password-file /nonexistent/pw')
        assert app.web_password_file == '/nonexistent/pw'
        assert 'cannot read' in _events(app)

    def test_an_unusable_file_still_stops_the_listener(self, pb, tmp_path):
        """Validation moved to the point of use; it did not go away."""
        import os
        pw = tmp_path / 'web.pw'
        pw.write_text('hunter2')
        os.chmod(str(pw), 0o644)                 # group- and world-readable
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':set web-password-file ' + str(pw))
        app._dispatch_cmd(':web start')
        assert app._web_server is None
        assert 'world-readable' in _events(app)
        os.chmod(str(pw), 0o600)                 # and fixing it is enough
        app._dispatch_cmd(':web start')
        try:
            assert app._web_server is not None, _events(app)
        finally:
            app._web_stop(quiet=True)

    def test_the_path_survives_a_save_and_reload(self, pb, tmp_path):
        """The round trip the old behaviour broke."""
        import os
        from unittest.mock import patch as _patch
        pw = tmp_path / 'web.pw'
        pw.write_text('hunter2')
        os.chmod(str(pw), 0o600)
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-password-file ' + str(pw))
        with _patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd(':save-config')
        os.chmod(str(pw), 0o644)                 # something relaxes the mode
        # Not _make_app: it truncates the config before constructing, and the
        # whole point here is to start from the file that was just written.
        with _patch.object(pb, '_config_path', return_value=cfg):
            app2 = pb.Application([('host', '10.0.0.1')])
        app2._monitoring_started = True
        assert app2.web_password_file == str(pw)
        with _patch.object(pb, '_config_path', return_value=cfg):
            app2._dispatch_cmd(':save-config')
        assert 'web-password-file' in open(cfg).read()


# ===========================================================================
# What needs a session and what does not
# ===========================================================================

class TestTheAuthGate:

    def test_the_data_needs_a_session(self, served):
        _app, s = served
        status, body = s.get('/api/state')
        assert status == 401
        assert b'login required' in body

    def test_the_page_and_assets_do_not(self, served):
        """There has to be somewhere to type the password."""
        _app, s = served
        assert s.get('/')[0] == 200
        assert s.get('/static/app.js')[0] == 200
        assert s.get('/static/app.css')[0] == 200

    def test_the_token_link_signs_you_in(self, served):
        app, s = served
        status, _body = s.get(f'/?t={app._web_server.token}', follow=False)
        assert status == 303, 'redirected, so the token leaves the address bar'
        assert s.cookie.startswith('pb_session=')
        assert s.get('/api/state')[0] == 200

    def test_a_wrong_token_signs_nobody_in(self, served):
        _app, s = served
        s.get('/?t=not-the-token', follow=False)
        assert s.cookie == ''
        assert s.get('/api/state')[0] == 401

    def test_a_forged_session_is_refused(self, served):
        _app, s = served
        s.cookie = 'pb_session=' + 'a' * 32
        assert s.get('/api/state')[0] == 401

    def test_an_expired_session_is_refused(self, served):
        app, s = served
        # follow=False: the cookie rides on the 303, and urlopen would follow
        # it and hand back the headers of the page instead.
        s.get(f'/?t={app._web_server.token}', follow=False)
        assert s.get('/api/state')[0] == 200
        sid = s.cookie.split('=', 1)[1]
        with app._web_server._session_lock:
            app._web_server.sessions[sid] = time.monotonic() - 1
        assert s.get('/api/state')[0] == 401

    def test_the_cookie_is_locked_down(self, served):
        app, s = served
        req = urllib.request.Request(
            s.base + f'/?t={app._web_server.token}')

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        try:
            urllib.request.build_opener(NoRedirect).open(req, timeout=10)
            header = ''
        except urllib.error.HTTPError as e:
            header = e.headers.get('Set-Cookie', '')
        assert 'HttpOnly' in header
        assert 'SameSite=Strict' in header
        assert 'Secure' not in header, 'no TLS here, so no Secure'

    def test_the_token_is_fresh_every_start(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        first = app._web_server.token
        app._dispatch_cmd(':web stop')
        app._dispatch_cmd(':web start')
        try:
            assert app._web_server.token != first
        finally:
            app._web_stop(quiet=True)

    def test_the_start_message_is_a_usable_url(self, served):
        """On the status bar — deliberately not in the event log.

        /api/state serves the event deque, and ':set web-anonymous' lets an
        unauthenticated client read it, so a credential in an event is a
        credential on the network.
        """
        app, _s = served
        token = app._web_server.token
        assert f'?t={token}' in app._status_msg['text']
        assert token not in _events(app)

    def test_the_start_event_says_how_to_get_the_link_back(self, served):
        """There is no screen while a hosts file loads, so the line that *is*
        logged has to name the command that re-shows the link."""
        app, _s = served
        assert ':web status' in _events(app)


# ===========================================================================
# Logging in with a password
# ===========================================================================

class TestPasswordLogin:

    def test_the_right_password_works(self, served_pw):
        _app, s = served_pw
        assert s.login('hunter2')[0] == 204
        assert s.get('/api/state')[0] == 200

    def test_the_wrong_password_does_not(self, served_pw):
        _app, s = served_pw
        assert s.login('hunter3')[0] == 401
        assert s.get('/api/state')[0] == 401

    def test_with_no_password_configured_nothing_logs_in(self, served):
        """Token-only must not mean 'any password works'."""
        _app, s = served
        assert s.login('')[0] == 401
        assert s.login('anything')[0] == 401

    def test_a_form_post_is_refused(self, served_pw):
        """Content-Type is a CSRF control, not politeness.

        A page on another site can only send the three 'simple' content types,
        so requiring application/json forces a preflight it cannot satisfy.
        """
        _app, s = served_pw
        status, body = s.login('hunter2',
                               ctype='application/x-www-form-urlencoded')
        assert status == 400
        assert b'application/json' in body
        assert s.get('/api/state')[0] == 401, 'and it did not log in'

    def test_a_failed_login_is_logged_with_the_client(self, served_pw):
        app, s = served_pw
        s.login('hunter3')
        assert 'failed login from 127.0.0.1' in _events(app)

    def test_a_successful_login_is_logged_too(self, served_pw):
        app, s = served_pw
        s.login('hunter2')
        assert 'login from 127.0.0.1' in _events(app)


class TestTheLoginThrottle:

    def test_repeated_failures_are_refused_outright(self, pb, served_pw):
        _app, s = served_pw
        for _ in range(pb._WEB_LOGIN_FAILS):
            assert s.login('wrong')[0] == 401
        assert s.login('wrong')[0] == 429

    def test_the_right_password_is_throttled_too(self, pb, served_pw):
        """Otherwise the throttle is an oracle for 'that one was close'."""
        _app, s = served_pw
        for _ in range(pb._WEB_LOGIN_FAILS):
            s.login('wrong')
        assert s.login('hunter2')[0] == 429

    def test_it_refuses_rather_than_sleeping(self, pb, served_pw):
        """A handler that slept would hold one of a bounded set of threads.

        Throttling that way hands an attacker the denial of service it is
        meant to prevent, which is why this is not _ssh_spawn_gate.
        """
        _app, s = served_pw
        for _ in range(pb._WEB_LOGIN_FAILS):
            s.login('wrong')
        start = time.monotonic()
        assert s.login('wrong')[0] == 429
        assert time.monotonic() - start < 1.0

    def test_success_clears_the_count(self, pb, served_pw):
        _app, s = served_pw
        for _ in range(pb._WEB_LOGIN_FAILS - 1):
            s.login('wrong')
        assert s.login('hunter2')[0] == 204
        for _ in range(pb._WEB_LOGIN_FAILS - 1):
            assert s.login('wrong')[0] == 401, 'the counter restarted'

    def test_the_window_expires(self, pb):
        gate = pb._WebLoginGate(limit=2, window=0.2)
        gate.record_failure('h')
        gate.record_failure('h')
        assert gate.blocked('h')
        time.sleep(0.25)
        assert not gate.blocked('h')

    def test_clients_are_counted_apart(self, pb):
        gate = pb._WebLoginGate(limit=1, window=60)
        gate.record_failure('a')
        assert gate.blocked('a')
        assert not gate.blocked('b')


# ===========================================================================
# Binding somewhere other than loopback
# ===========================================================================

class TestNonLoopback:

    ADDR = '10.255.255.254'     # never bindable here; refused before any bind

    def test_it_is_refused_without_a_password(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(f':set web-listen {self.ADDR}:8765')
        app._dispatch_cmd(':web start')
        assert app._web_server is None
        assert 'without a password' in _events(app)
        assert 'ssh -L' in _events(app), 'and offers the alternative'

    def test_the_refusal_happens_before_the_bind(self, pb, tmp_path):
        """An unbindable address proves the check is not just a bind failure."""
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(f':set web-listen {self.ADDR}:8765')
        app._dispatch_cmd(':web start')
        assert 'cannot listen' not in _events(app)

    def test_a_password_unlocks_it(self, pb, tmp_path):
        """Bound to a real local address, so it actually listens."""
        import socket as _s
        probe = _s.socket(_s.AF_INET, _s.SOCK_DGRAM)
        probe.connect(('10.255.255.255', 1))
        addr = probe.getsockname()[0]
        probe.close()
        if pb._web_is_loopback(addr):
            pytest.skip('no non-loopback address on this machine')
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(f':set web-password-file {_password_file(tmp_path)}')
        app._dispatch_cmd(f':set web-listen {addr}:0')
        app._dispatch_cmd(':web start')
        try:
            assert app._web_server is not None, _events(app)
            assert 'without TLS' in _events(app), 'and says the password is in clear'
        finally:
            app._web_stop(quiet=True)

    def test_extra_host_names_can_be_declared(self, pb, tmp_path):
        """Inferring them would mean accepting any Host, which is the check."""
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-hosts monitor.lan, ping.example')
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        try:
            s = Session(app)
            req = urllib.request.Request(s.base + '/')
            req.add_header('Host', 'monitor.lan')
            with urllib.request.urlopen(req, timeout=10) as r:
                assert r.status == 200
            req = urllib.request.Request(s.base + '/')
            req.add_header('Host', 'other.example')
            with pytest.raises(urllib.error.HTTPError) as e:
                urllib.request.urlopen(req, timeout=10)
            assert e.value.code == 421
        finally:
            app._web_stop(quiet=True)

    def test_declared_hosts_reach_a_running_server(self, served):
        app, s = served
        app._dispatch_cmd(':set web-hosts late.example')
        req = urllib.request.Request(s.base + '/')
        req.add_header('Host', 'late.example')
        with urllib.request.urlopen(req, timeout=10) as r:
            assert r.status == 200


# ===========================================================================
# TLS
# ===========================================================================

def _self_signed(tmp_path):
    pem = tmp_path / 'web.pem'
    proc = subprocess.run(
        ['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
         '-keyout', str(pem), '-out', str(pem), '-days', '1',
         '-subj', '/CN=localhost'],
        capture_output=True)
    if proc.returncode != 0:
        pytest.skip('openssl could not make a test certificate')
    return str(pem)


class TestTls:

    def test_a_bad_certificate_is_refused_with_the_reason(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-tls-cert /nonexistent/web.pem')
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        assert app._web_server is None
        assert 'web-tls-cert' in _events(app)

    def test_it_serves_https(self, pb, tmp_path):
        import ssl as _ssl
        pem = _self_signed(tmp_path)
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(f':set web-tls-cert {pem}')
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        try:
            assert app._web_server is not None, _events(app)
            assert app._web_server.is_tls
            host, port = app._web_server.server_address[:2]
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE
            with urllib.request.urlopen(f'https://{host}:{port}/',
                                        context=ctx, timeout=10) as r:
                assert r.status == 200
                assert b'<title>ping-bulk</title>' in r.read()
            assert 'https://' in _events(app)
        finally:
            app._web_stop(quiet=True)

    def test_the_cookie_is_marked_secure_over_tls(self, pb, tmp_path):
        import ssl as _ssl
        pem = _self_signed(tmp_path)
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(f':set web-tls-cert {pem}')
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        try:
            host, port = app._web_server.server_address[:2]
            ctx = _ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = _ssl.CERT_NONE

            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, *a, **kw):
                    return None

            opener = urllib.request.build_opener(
                NoRedirect, urllib.request.HTTPSHandler(context=ctx))
            try:
                opener.open(
                    f'https://{host}:{port}/?t={app._web_server.token}',
                    timeout=10)
                header = ''
            except urllib.error.HTTPError as e:
                header = e.headers.get('Set-Cookie', '')
            assert 'Secure' in header
        finally:
            app._web_stop(quiet=True)


# ===========================================================================
# Persistence
# ===========================================================================

class TestPersistence:

    def test_the_path_is_saved_and_the_password_is_not(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        pwf = _password_file(tmp_path)
        app._dispatch_cmd(f':set web-password-file {pwf}')
        app._dispatch_cmd(':set web-hosts monitor.lan')
        app._dispatch_cmd(':set web-tls-cert /etc/ping-bulk/web.pem')
        with patch.object(pb, '_config_path', return_value=app._cfg_path):
            app._dispatch_cmd(':save-config')
        text = open(app._cfg_path).read()
        assert f':set web-password-file {pwf}' in text
        assert ':set web-hosts monitor.lan' in text
        assert ':set web-tls-cert /etc/ping-bulk/web.pem' in text
        assert 'hunter2' not in text
        assert 'pbkdf2' not in text

    def test_the_settings_report_like_every_other_one(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-password-file')
        assert app._status_msg['text'] == 'web-password-file none'
        app._dispatch_cmd(':set web-hosts')
        assert app._status_msg['text'] == 'web-hosts none'
