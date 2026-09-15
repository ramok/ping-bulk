"""':set web-anonymous read-only' — a second access tier.

The listener had one level: a session, or nothing.  This adds a reader who
never signs in, for a monitor on a LAN or a VPN that colleagues and wall
displays should be able to watch without a credential.

Two settings, deliberately orthogonal: ':set web-anonymous' says who may
*look*, ':set web-commands' says what a signed-in browser may *change*.  No
value of the first reaches a write.
"""

import http.client
import json
import os

import pytest
from unittest.mock import patch


def _make_app(pb, tmp_path, kiosk=False):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    hosts = tmp_path / 'web.hosts'
    hosts.write_text('10.0.0.1\n10.0.0.2\n')
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application(pb.parse_hosts_file(str(hosts)), kiosk_mode=kiosk)
    app._monitoring_started = True
    return app


@pytest.fixture
def anon(pb, tmp_path):
    """A listener anyone may read."""
    app = _make_app(pb, tmp_path)
    app._dispatch_cmd(':set web-anonymous read-only')
    app._dispatch_cmd(':set web-listen 127.0.0.1:0')
    app._dispatch_cmd(':web start')
    assert app._web_server is not None, [e.text for e in app.events]
    port = app._web_server.server_address[1]
    uid = next(e.uid for e in app.entries if isinstance(e, pb.Monitor))
    try:
        yield app, port, uid
    finally:
        app._web_stop(quiet=True)


def _get(port, path, cookie=None):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    h = {'Host': '127.0.0.1:%d' % port}
    if cookie:
        h['Cookie'] = cookie
    c.request('GET', path, headers=h)
    r = c.getresponse()
    body = r.read()
    c.close()
    return r.status, body


def _post(port, path, cookie=None, csrf=None):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    h = {'Host': '127.0.0.1:%d' % port, 'Content-Type': 'application/json'}
    if cookie:
        h['Cookie'] = cookie
    if csrf:
        h['X-PB-Token'] = csrf
    c.request('POST', path, body=b'{}', headers=h)
    r = c.getresponse()
    r.read()
    c.close()
    return r.status


def _sign_in(port, token):
    c = http.client.HTTPConnection('127.0.0.1', port, timeout=10)
    c.request('GET', '/?t=' + token, headers={'Host': '127.0.0.1:%d' % port})
    r = c.getresponse()
    r.read()
    cookie = r.getheader('Set-Cookie')
    c.close()
    return cookie.split(';')[0]


class TestOffIsTheDefaultAndUnchanged:

    def test_off_by_default(self, pb, tmp_path):
        assert _make_app(pb, tmp_path).web_anonymous == 'off'

    def test_reads_still_need_a_session(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        port = app._web_server.server_address[1]
        uid = next(e.uid for e in app.entries if isinstance(e, pb.Monitor))
        try:
            assert _get(port, '/api/state')[0] == 401
            assert _get(port, f'/api/host/{uid}')[0] == 401
        finally:
            app._web_stop(quiet=True)


class TestAnonymousMayRead:

    def test_the_host_list_is_served_without_a_cookie(self, anon):
        _app, port, _uid = anon
        status, body = _get(port, '/api/state')
        assert status == 200
        assert json.loads(body)['rows']

    def test_no_csrf_value_is_handed_out(self, anon):
        """There is no session to bind one to, and nothing it could authorise."""
        _app, port, _uid = anon
        assert 'csrf' not in json.loads(_get(port, '/api/state')[1])

    def test_the_page_is_told_it_is_read_only(self, anon):
        """The client draws its write controls from this, so an anonymous
        viewer gets a page with no buttons rather than buttons that 401."""
        _app, port, _uid = anon
        assert json.loads(_get(port, '/api/state')[1])['commands'] == 'read-only'


class TestAnonymousMayNotWrite:
    """No value of ':set web-anonymous' reaches a write: _write_gate asks
    _authenticated, which this tier does not widen."""

    def test_the_command_endpoint_is_refused(self, anon):
        _app, port, _uid = anon
        assert _post(port, '/api/cmd') == 401

    def test_a_host_verb_is_refused(self, anon):
        _app, port, uid = anon
        assert _post(port, f'/api/host/{uid}/pause') == 401

    def test_even_with_web_commands_safe(self, anon):
        """'safe' is about what a *signed-in* browser may change."""
        app, port, uid = anon
        assert app.web_commands == 'safe'
        assert _post(port, f'/api/host/{uid}/pause') == 401


class TestTheDetailEndpointIsRedacted:
    """'/api/host/<uid>' is leakier than '/api/state': three of its fields are
    instructions for reaching the estate rather than facts about it."""

    def test_the_login_instructions_are_withheld(self, anon):
        _app, port, uid = anon
        detail = json.loads(_get(port, f'/api/host/{uid}')[1])
        for field in ('cmd', 'connect', 'events'):
            assert field not in detail, field

    def test_the_readings_are_kept(self, anon):
        """Redaction drops how to log in, not what the monitor measured."""
        _app, port, uid = anon
        detail = json.loads(_get(port, f'/api/host/{uid}')[1])
        for field in ('name', 'ip', 'alive', 'loss_pct', 'probes'):
            assert field in detail, field

    def test_a_signed_in_caller_still_sees_everything(self, anon):
        app, port, uid = anon
        cookie = _sign_in(port, app._web_server.token)
        detail = json.loads(_get(port, f'/api/host/{uid}', cookie)[1])
        for field in ('cmd', 'connect', 'events'):
            assert field in detail, field

    def test_every_withheld_field_is_one_an_admin_actually_gets(self, anon, pb):
        """Derived from the constant rather than a copy of it, so the list
        cannot drift into naming a field that does not exist — which would
        withhold nothing while looking as though it did."""
        app, port, uid = anon
        anon_detail = json.loads(_get(port, f'/api/host/{uid}')[1])
        cookie = _sign_in(port, app._web_server.token)
        admin_detail = json.loads(_get(port, f'/api/host/{uid}', cookie)[1])
        assert pb.Application._WEB_ANON_WITHHELD
        for field in pb.Application._WEB_ANON_WITHHELD:
            assert field in admin_detail, f'{field} is not a real field'
            assert field not in anon_detail, f'{field} reached an anonymous reader'


class TestAnonymousReadsNoCredential:
    """The reason the sign-in token left the event log.

    ':web start' used to print its link through an event, which was accepted
    while every reader of '/api/state' had to be signed in already — this tier
    is exactly what removes that precondition.  The two changes are only safe
    together, so the combination is pinned here: if the token came back to the
    deque, or a new event carried one, an anonymous reader could mint an admin
    session and nothing else in the suite would notice.
    """

    def _payloads(self, port, uid):
        return (_get(port, '/api/state')[1].decode('utf-8', 'replace')
                + _get(port, f'/api/host/{uid}')[1].decode('utf-8', 'replace'))

    def test_the_sign_in_token_is_not_served(self, anon):
        app, port, uid = anon
        token = app._web_server.token
        assert token, 'fixture should have an unspent token'
        assert token not in self._payloads(port, uid)

    def test_a_re_minted_token_is_not_served_either(self, anon):
        """':web status' mints a fresh one, and it must not appear either."""
        app, port, uid = anon
        _sign_in(port, app._web_server.token)          # spends the first
        app._dispatch_cmd(':web status')
        assert app._web_server.token not in self._payloads(port, uid)

    def test_no_session_id_or_csrf_key_is_served(self, anon):
        app, port, uid = anon
        cookie = _sign_in(port, app._web_server.token)
        sid = cookie.split('=', 1)[1]
        body = self._payloads(port, uid)
        assert sid not in body
        assert app._web_server.csrf_for(sid) not in body
        assert app._web_server._csrf_key.hex() not in body


class TestSigningInStillWorks:

    def test_the_token_still_buys_a_session(self, anon):
        app, port, _uid = anon
        cookie = _sign_in(port, app._web_server.token)
        state = json.loads(_get(port, '/api/state', cookie)[1])
        assert 'csrf' in state
        assert state['commands'] == 'safe'


class TestTheSetting:

    def test_unknown_value_is_refused_and_visible(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-anonymous maybe')
        assert app.web_anonymous == 'off'
        last = list(app.events)[-1]
        assert 'unknown value' in last.text
        assert last.level == pb.LEVEL_NORMAL, 'a refusal must be visible'

    def test_kiosk_refuses_it(self, pb, tmp_path):
        """Typed at the console, that is — the hosts file may declare it.

        The original reasoning here was "a reader who never authenticates is
        further out than the console user", which is true and is not the
        question: that mode's threat is the person at the *keyboard*, and the
        hosts file is the operator's own declaration.  Refusing both refused
        the deployment the setting exists for.  See
        tests/test_kiosk_declared_not_typed.py for the other half.
        """
        app = _make_app(pb, tmp_path, kiosk=True)
        app._dispatch_cmd(':set web-anonymous read-only')
        assert app.web_anonymous == 'off'
        assert 'kiosk' in list(app.events)[-1].text

    def test_it_survives_save_and_reload(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-anonymous read-only')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._cmd_saveconfig()
        assert ':set web-anonymous read-only' in open(cfg).read()
        fresh = _make_app(pb, tmp_path)
        fresh._dispatch_cmd(':set web-anonymous read-only')
        assert fresh.web_anonymous == 'read-only'

    def test_off_writes_no_line(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        app = _make_app(pb, tmp_path)
        with patch.object(pb, '_config_path', return_value=cfg):
            app._cmd_saveconfig()
        assert 'web-anonymous' not in open(cfg).read()


class TestTheReportNamesBothHalves:
    """A message naming one setting without the other has been wrong before:
    ':web' advertised itself as read-only whatever ':set web-commands' said."""

    def test_the_start_line_says_who_may_read(self, anon):
        app, _port, _uid = anon
        line = [e.text for e in app.events if 'listening on' in e.text][-1]
        assert 'anyone may read' in line
        assert 'commands: safe' in line

    def test_sign_in_required_when_off(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        try:
            line = [e.text for e in app.events if 'listening on' in e.text][-1]
            assert 'sign-in required' in line
        finally:
            app._web_stop(quiet=True)

    def test_the_command_help_makes_no_read_only_claim(self, pb):
        """':web' is not read-only by default — web-commands defaults to safe."""
        web = [c for c in pb.CMD_REGISTRY if 'web' in c.names][0]
        assert 'read-only' not in web.help
