"""Four things an unauthenticated client could do to the listener.

None of these needed a credential, and the client allowlist stopped none of
them: ``verify_request`` runs at ``accept()``, and every refused response is
still a response.  Each test measures the behaviour rather than asserting the
shape of the fix.

1. **The connection cap did not cap.**  ``socketserver`` calls
   ``shutdown_request`` on its refusal branch too, so a refused connection
   returned a slot it never took.  3000 attempts against a cap of 16 left 1508
   live handler threads, and the descriptors they held stopped ``ping`` and
   ``ssh`` children being respawned — an unauthenticated flood stopped the
   monitoring.
2. **One request line evicted the operator's event log.**  ``log_message``
   reported every request at ``LEVEL_DEBUG``, and a log file records every
   level by design (§12), so 1117 requests/second wiped the 10 000-entry deque
   in about nine seconds and wrote some 6 GB a day to disk.
3. **``GET /?t=%ff`` was a 500.**  ``hmac.compare_digest`` refuses a ``str``
   holding non-ASCII, and a query, a cookie and a header are all chosen by the
   client.
4. **The sign-in token was replayable and written down.**  It was never
   invalidated and reached the log file, so whoever could read that file held
   access for the life of the process.
"""

import http.client
import os
import socket
import threading
import time

import pytest
from unittest.mock import patch


def _make_app(pb, tmp_path, log=False):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    hosts = tmp_path / 'web.hosts'
    hosts.write_text('10.0.0.1\n10.0.0.2\n')
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application(pb.parse_hosts_file(str(hosts)))
    app._monitoring_started = True
    if log:
        app._dispatch_cmd(':log ' + str(tmp_path / 'pb.log'))
    return app


@pytest.fixture
def served(pb, tmp_path):
    app = _make_app(pb, tmp_path, log=True)
    app._dispatch_cmd(':set web-listen 127.0.0.1:0')
    app._dispatch_cmd(':web start')
    assert app._web_server is not None, [e.text for e in app.events]
    try:
        yield app, app._web_server.server_address[1], str(tmp_path / 'pb.log')
    finally:
        app._web_stop(quiet=True)


def _raw(port, path='/', headers=None):
    """One HTTP/1.0 request, returning (status, Set-Cookie)."""
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    h = {'Host': '127.0.0.1:%d' % port}
    h.update(headers or {})
    c.request('GET', path, headers=h)
    r = c.getresponse()
    r.read()
    c.close()
    return r.status, r.getheader('Set-Cookie')


class TestTheConnectionCapHolds:
    def test_a_refused_connection_does_not_hand_back_a_slot(self, pb):
        """The accounting bug, isolated from sockets and from timing.

        socketserver._handle_request_noblock calls shutdown_request on the
        `else:` of verify_request — the refusal branch — so this drives the
        real pair of methods in that order rather than restating them.
        """
        srv = pb._WebServer.__new__(pb._WebServer)
        srv._active = 0
        srv._active_lock = threading.Lock()
        srv._admitted = set()
        opened, refused = [], 0
        for _ in range(pb._WEB_MAX_CONNECTIONS + 40):
            req, mate = socket.socketpair()
            opened.append(mate)
            if srv.verify_request(req, ('127.0.0.1', 1)):
                opened.append(req)          # admitted: still holding its slot
            else:
                refused += 1
                srv.shutdown_request(req)   # what socketserver does next
        for s_ in opened:
            try:
                s_.close()
            except OSError:
                pass
        assert refused == 40
        assert srv._active == pb._WEB_MAX_CONNECTIONS, (
            'refusals returned %d slot(s) they never took'
            % (pb._WEB_MAX_CONNECTIONS - srv._active))

    def test_idle_connections_cannot_grow_threads_past_the_cap(self, pb, served):
        app, port, _ = served
        socks = []
        try:
            for _ in range(120):
                try:
                    socks.append(socket.create_connection(
                        ('127.0.0.1', port), timeout=2))
                except OSError:
                    break
            time.sleep(1.5)
            live = sum(1 for t in threading.enumerate()
                       if 'process_request' in (t.name or ''))
            cap = pb._WEB_MAX_CONNECTIONS
            assert app._web_server._active <= cap
            assert live <= cap + 2, (
                'handler threads grew past the cap of %d: %d' % (cap, live))
        finally:
            for s in socks:
                try:
                    s.close()
                except OSError:
                    pass

    def test_slots_come_back_when_clients_leave(self, served):
        app, port, _ = served
        for _ in range(30):
            _raw(port, '/nope')
        assert app._web_server._active == 0
        assert _raw(port, '/')[0] == 200


class TestAnUnauthenticatedClientCannotFloodTheLog:
    def test_requests_write_nothing_at_the_default_level(self, served):
        app, port, logf = served
        before_events, before_bytes = len(app.events), os.path.getsize(logf)
        for _ in range(60):
            _raw(port, '/nope')
        assert len(app.events) == before_events
        assert os.path.getsize(logf) == before_bytes

    def test_refused_responses_are_just_as_quiet(self, pb, served):
        """403, 421 and 404 are responses too, so the allowlist is no defence."""
        app, port, logf = served
        app._dispatch_cmd(':set web-allow 10.99.0.0/16')
        before = len(app.events)
        for _ in range(20):
            _raw(port, '/api/state')                       # 403
            _raw(port, '/', headers={'Host': 'evil.example'})  # 421
        assert len(app.events) == before

    def test_the_operator_can_still_ask_for_the_access_log(self, pb, served):
        app, port, _ = served
        app.loglevel = pb.LEVEL_DEBUG
        before = len(app.events)
        _raw(port, '/nope')
        assert len(app.events) > before
        assert any('/nope' in e.text for e in app.events)

    def test_a_control_character_in_the_request_line_is_escaped(self, pb, served):
        """requestline is raw bytes; the base class translates, so must we.

        The handler runs on its own thread, so this has to wait for the event
        rather than assert straight after closing the socket — asserting
        immediately passes against the unfixed code, which is not a test.
        """
        app, port, _ = served
        app.loglevel = pb.LEVEL_DEBUG
        before = len(app.events)
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        c._output(b'GET /\x1b[31mred HTTP/1.0')
        c._send_output()
        try:
            c.getresponse().read()
        except Exception:
            pass
        c.close()
        deadline = time.time() + 5
        while time.time() < deadline and len(app.events) == before:
            time.sleep(0.02)
        assert len(app.events) > before, 'the access line never arrived'
        assert not any('\x1b' in e.text for e in app.events), \
            'a raw escape reached the event log'


class TestAFailedLoginIsRefusedNotCrashed:
    """The same hostile-text class, in the one credential path.

    JSON admits a lone surrogate; UTF-8 cannot encode one.  The encode sat
    outside ``_web_check_password``'s guard, so ``{"password": "\\udcff"}`` was
    an unauthenticated 500 reported at LEVEL_NORMAL — three times the byte rate
    of the DEBUG flood, straight to the log file, and it never reached the
    throttle because recording a failure is what the refusal does.  The
    precondition is a password file, which a non-loopback bind makes mandatory.
    """

    @pytest.fixture
    def with_password(self, pb, tmp_path):
        pw = tmp_path / 'web.pw'
        pw.write_text('hunter2')
        os.chmod(str(pw), 0o600)
        app = _make_app(pb, tmp_path, log=True)
        app._dispatch_cmd(':set web-password-file ' + str(pw))
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        assert app._web_server is not None, [e.text for e in app.events]
        try:
            yield app, app._web_server.server_address[1], str(tmp_path / 'pb.log')
        finally:
            app._web_stop(quiet=True)

    def _login(self, port, body):
        c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
        c.request('POST', '/api/login', body=body,
                  headers={'Host': '127.0.0.1:%d' % port,
                           'Content-Type': 'application/json'})
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    def test_the_right_password_still_works(self, with_password):
        _app, port, _ = with_password
        assert self._login(port, b'{"password": "hunter2"}') == 204

    def test_a_lone_surrogate_is_a_wrong_password_not_a_500(self, with_password):
        app, port, logf = with_password
        before = os.path.getsize(logf)
        # The JSON *escape*, sent as plain ASCII: json.loads turns it into a
        # lone surrogate, which is what UTF-8 cannot encode.  Raw surrogate
        # bytes would be rejected as a malformed body long before the check.
        body = b'{"password": "\\ud800"}'
        assert self._login(port, body) == 401
        assert os.path.getsize(logf) - before < 400, \
            'a refused login wrote a 500 report to the log file'

    def test_it_counts_against_the_throttle(self, pb, with_password):
        """A refusal that skips the gate is an unthrottled flood."""
        app, port, _ = with_password
        # The JSON *escape*, sent as plain ASCII: json.loads turns it into a
        # lone surrogate, which is what UTF-8 cannot encode.  Raw surrogate
        # bytes would be rejected as a malformed body long before the check.
        body = b'{"password": "\\ud800"}'
        codes = [self._login(port, body)
                 for _ in range(pb._WEB_LOGIN_FAILS + 2)]
        assert 429 in codes, codes


class TestHostileTextIsNotACrash:
    @pytest.mark.parametrize('path', ['/?t=%ff', '/?t=%c3%28', '/?t='])
    def test_a_bad_token_serves_the_page_instead_of_a_500(self, served, path):
        _, port, _ = served
        assert _raw(port, path)[0] == 200

    @pytest.mark.parametrize('header', [
        {'Cookie': 'pb_session=\udcff'},
        {'X-PB-Token': '\udcff'},
    ])
    def test_a_bad_credential_is_refused_not_a_500(self, served, header):
        app, port, _ = served
        app._web_server.new_session()          # compare loop must be non-empty
        safe = {k: v.encode('utf-8', 'surrogateescape').decode('latin-1')
                for k, v in header.items()}
        status, _ = _raw(port, '/api/state', headers=safe)
        assert status != 500, status

    def test_the_comparison_helper_never_raises(self, pb):
        for a, b in [('\xff', 'x'), ('x', '\xff'), ('\udcff', '\udcff'),
                     (None, 'x'), ('x', None), (b'x', 'x'), ('x', 'x')]:
            pb._web_constant_eq(a, b)
        assert pb._web_constant_eq('abc', 'abc') is True
        assert pb._web_constant_eq('abc', 'abd') is False
        assert pb._web_constant_eq('\xff', '\xff') is True


class TestTheSignInLinkIsSpentAndNotWrittenDown:
    def test_the_token_works_once(self, served):
        app, port, _ = served
        tok = app._web_server.token
        first, cookie = _raw(port, '/?t=' + tok)
        assert (first, bool(cookie)) == (303, True)
        again, cookie2 = _raw(port, '/?t=' + tok)
        assert again == 200 and cookie2 is None, 'the token was replayable'

    def test_it_is_not_in_the_log_file(self, served):
        app, port, logf = served
        tok = app._web_server.token
        _raw(port, '/?t=' + tok)
        text = open(logf, encoding='utf-8').read()
        assert tok not in text
        assert 'web: listening on' in text, \
            'the file must still record that a socket was opened'

    def test_status_hands_out_a_fresh_link_once_the_first_is_spent(self, served):
        app, port, logf = served
        tok = app._web_server.token
        _raw(port, '/?t=' + tok)
        assert app._web_server.token is None
        app._dispatch_cmd(':web status')
        fresh = app._web_server.token
        assert fresh and fresh != tok
        assert _raw(port, '/?t=' + fresh)[0] == 303
        assert fresh not in open(logf, encoding='utf-8').read()

    def test_the_screen_shows_the_link_the_file_does_not(self, served):
        app, _, logf = served
        onscreen = ' | '.join(e.text for e in app.events)
        assert '/?t=' in onscreen
        assert 'sign-in link not logged' in open(logf, encoding='utf-8').read()
