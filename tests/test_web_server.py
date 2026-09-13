"""The read-only HTTP listener.

This is the program's first inbound socket, so most of what is asserted here
is a refusal.  Three of them are not obvious:

**A bad ``Host`` header is rejected even though the server binds to
loopback.**  Binding to 127.0.0.1 is not a boundary against a browser: a page
the operator visits can resolve attacker.example to 127.0.0.1 and then treat
the reply as same-origin — DNS rebinding — because the request comes *from*
the browser on this machine.  Pinning the Host header is what stops it.

**The client allowlist is checked before routing**, so an address outside it
learns nothing about which paths exist.

**A handler exception reaches the event log, never stderr.**  Under curses the
next redraw paints straight over stderr, which is how "the log just stops"
happened once before in this program.  A dead handler thread would leave a
silently half-dead UI instead of a restart.

Tests bind 127.0.0.1:0 and drive the server with urllib from the same process,
so nothing here needs a fixed port or a network.
"""

import json
import os
import socket
import urllib.error
import urllib.request

import pytest
from unittest.mock import patch


def _make_app(pb, tmp_path, content='10.0.0.1\n10.0.0.2\n', kiosk=False):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    hosts = tmp_path / 'web.hosts'
    hosts.write_text(content)
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application(pb.parse_hosts_file(str(hosts)),
                             kiosk_mode=kiosk)
    app._monitoring_started = True
    return app


class Client:
    def __init__(self, app):
        self.app = app
        host, port = app._web_server.server_address[:2]
        self.host, self.port = host, port
        self.base = f'http://{host}:{port}'
        self.cookie = ''

    def sign_in(self):
        """Exchange the start-up token for a session cookie.

        '/api/state' is behind a session; the page and the assets are not.
        The cookie rides on the 303, so the redirect must not be followed.
        """
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        req = urllib.request.Request(
            self.base + f'/?t={self.app._web_server.token}')
        try:
            resp = urllib.request.build_opener(NoRedirect).open(req, timeout=10)
            header = resp.headers.get('Set-Cookie', '')
        except urllib.error.HTTPError as e:
            header = e.headers.get('Set-Cookie', '')
        assert header, 'the token link must hand back a session'
        self.cookie = header.split(';')[0]
        return self

    def get(self, path='/', host_header=None, method='GET', data=None):
        req = urllib.request.Request(self.base + path, data=data,
                                     method=method)
        if host_header is not None:
            req.add_header('Host', host_header)
        if self.cookie:
            req.add_header('Cookie', self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()


@pytest.fixture
def served(pb, tmp_path):
    """An application with the listener up on an ephemeral loopback port."""
    app = _make_app(pb, tmp_path)
    app._dispatch_cmd(':set web-listen 127.0.0.1:0')
    app._dispatch_cmd(':web start')
    assert app._web_server is not None, [e.text for e in app.events]
    try:
        yield app, Client(app)
    finally:
        app._web_stop(quiet=True)


def _events(app):
    return ' | '.join(e.text for e in app.events)


def _drawn(screen):
    """What a fake curses window was actually asked to write.

    The menu bar renders a label in several addstr calls, so joining the call
    reprs would split the text being looked for.
    """
    return ''.join(str(call.args[2]) for call in screen.addstr.call_args_list)


# ===========================================================================
# It serves
# ===========================================================================

class TestItServes:

    def test_the_page(self, served):
        _app, c = served
        status, headers, body = c.get('/')
        assert status == 200
        assert headers['Content-Type'].startswith('text/html')
        assert b'<title>ping-bulk</title>' in body

    def test_the_state_is_json_and_parses(self, served):
        app, c = served
        status, headers, body = c.sign_in().get('/api/state')
        assert status == 200
        assert headers['Content-Type'].startswith('application/json')
        state = json.loads(body)
        assert [r['uid'] for r in state['rows']] == \
            [m.uid for m in app.monitors]

    def test_the_static_assets(self, served):
        _app, c = served
        css = c.get('/static/app.css')
        js = c.get('/static/app.js')
        assert css[0] == 200 and css[1]['Content-Type'].startswith('text/css')
        assert js[0] == 200
        assert js[1]['Content-Type'].startswith('application/javascript')

    def test_an_unknown_path_is_404(self, served):
        _app, c = served
        assert c.get('/../etc/passwd')[0] == 404
        assert c.get('/static/../ping-bulk')[0] == 404

    def test_head_works_and_sends_no_body(self, served):
        _app, c = served
        status, headers, body = c.get('/', method='HEAD')
        assert status == 200
        assert body == b''
        assert headers['Content-Length'] != '0'


# ===========================================================================
# Refusals
# ===========================================================================

class TestRefusals:

    def test_post_reaches_no_path_that_is_not_a_write_endpoint(self, served):
        """Only the three write paths answer POST; everything else is 404.

        What a browser may *change* is a separate question, decided by
        ':set web-commands' and the safe allowlist — see test_web_write.py.
        """
        _app, c = served
        for path in ('/api/state', '/', '/static/app.js', '/nope'):
            status, _h, _body = c.get(path, method='POST', data=b'{}')
            assert status == 404, path

    def test_a_foreign_host_header_is_refused(self, served):
        """DNS rebinding: binding to loopback does not stop a browser."""
        _app, c = served
        assert c.get('/', host_header='attacker.example')[0] == 421
        assert c.get('/', host_header='')[0] == 421

    def test_the_expected_host_headers_are_accepted(self, served):
        _app, c = served
        for h in (f'localhost:{c.port}', f'127.0.0.1:{c.port}', 'localhost'):
            assert c.get('/', host_header=h)[0] == 200, h

    def test_a_client_outside_the_allowlist_is_refused(self, served):
        app, c = served
        app._dispatch_cmd(':set web-allow 10.0.0.0/8')
        assert c.get('/')[0] == 403
        assert c.get('/api/state')[0] == 403, 'checked before routing'

    def test_the_allowlist_can_be_widened_again(self, served):
        app, c = served
        app._dispatch_cmd(':set web-allow 10.0.0.0/8')
        assert c.get('/')[0] == 403
        app._dispatch_cmd(':set web-allow any')
        assert c.get('/')[0] == 200

    def test_a_loopback_allowlist_lets_loopback_in(self, served):
        app, c = served
        app._dispatch_cmd(':set web-allow 127.0.0.0/8')
        assert c.get('/')[0] == 200


# ===========================================================================
# The page cannot execute an injected string
# ===========================================================================

class TestTheContentSecurityPolicy:

    def test_every_response_carries_it(self, served):
        _app, c = served
        c.sign_in()
        for path in ('/', '/api/state', '/static/app.js', '/nope'):
            csp = c.get(path)[1].get('Content-Security-Policy', '')
            assert "script-src 'self'" in csp, path
            assert "default-src 'none'" in csp, path

    def test_the_page_has_no_inline_script_or_handler(self, pb):
        """'script-src self' only helps if nothing is inlined.

        A host name or a PTR record reaching the DOM then cannot execute even
        if the client were careless, because the policy forbids the only
        mechanisms that would run it.
        """
        html = pb._WEB_HTML
        assert '<script src=' in html
        assert '<script>' not in html
        assert 'javascript:' not in html
        assert 'onerror=' not in html and 'onload=' not in html
        assert 'onclick=' not in html

    def test_the_client_never_uses_innerhtml(self, pb):
        """textContent only: the payload is data, and must stay data."""
        js = '\n'.join(line for line in pb._WEB_JS.splitlines()
                        if not line.lstrip().startswith('//'))
        assert 'innerHTML' not in js
        assert 'outerHTML' not in js
        assert 'insertAdjacentHTML' not in js
        assert 'eval(' not in js
        assert 'textContent' in js

    def test_responses_are_not_sniffable_or_cached(self, served):
        _app, c = served
        headers = c.sign_in().get('/api/state')[1]
        assert headers.get('X-Content-Type-Options') == 'nosniff'
        assert headers.get('Cache-Control') == 'no-store'

    def test_the_server_does_not_advertise_its_python(self, served):
        _app, c = served
        assert 'Python' not in c.get('/')[1].get('Server', '')


# ===========================================================================
# Lifecycle
# ===========================================================================

class TestLifecycle:

    def test_stop_closes_the_port(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        host, port = app._web_server.server_address[:2]
        app._dispatch_cmd(':web stop')
        assert app._web_server is None
        with pytest.raises(OSError):
            socket.create_connection((host, port), timeout=2).close()

    def test_teardown_closes_it_too(self, pb, tmp_path):
        """run()'s finally: ':quit' used to leave the socket open until exit.

        Under systemd 'Restart=always' that raced the next bind.
        """
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        host, port = app._web_server.server_address[:2]
        app._web_stop(quiet=True)           # what the finally block calls
        with pytest.raises(OSError):
            socket.create_connection((host, port), timeout=2).close()

    def test_starting_twice_reports_rather_than_rebinding(self, served):
        app, _c = served
        first = app._web_server
        app._dispatch_cmd(':web start')
        assert app._web_server is first
        assert 'listening on' in _events(app)

    def test_stopping_when_not_running_says_so(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':web stop')
        assert 'not running' in _events(app)

    def test_bare_web_reports(self, pb, tmp_path):
        """A bare command reports, like every other one since :set changed."""
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':web')
        assert 'not running' in _events(app)

    def test_an_unknown_argument_is_rejected(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':web frobnicate')
        assert "unknown argument 'frobnicate'" in _events(app)

    def test_status_reports_the_bound_port_and_last_client(self, served):
        app, c = served
        c.get('/')
        app._dispatch_cmd(':web status')
        text = _events(app)
        assert f'{c.port}' in text
        assert 'last client 127.0.0.1' in text

    def test_the_menu_bar_says_it_is_listening(self, served):
        """A listening socket must not be something you find months later."""
        app, c = served
        import curses
        from unittest.mock import MagicMock
        with patch.object(curses, 'color_pair', lambda n: 0):
            screen = MagicMock()
            screen.getmaxyx.return_value = (40, 200)
            app.draw_menu_bar(screen, 40, 200)
        drawn = _drawn(screen)
        assert f'web:127.0.0.1:{c.port}' in drawn

    def test_the_indicator_is_absent_when_it_is_not_running(self, pb,
                                                            tmp_path):
        app = _make_app(pb, tmp_path)
        import curses
        from unittest.mock import MagicMock
        with patch.object(curses, 'color_pair', lambda n: 0):
            screen = MagicMock()
            screen.getmaxyx.return_value = (40, 200)
            app.draw_menu_bar(screen, 40, 200)
        assert 'web:' not in _drawn(screen)


# ===========================================================================
# Where it may and may not listen
# ===========================================================================

class TestWhereItListens:

    def test_a_non_loopback_bind_is_refused_without_a_password(self, pb,
                                                                 tmp_path):
        """A per-run token dies with the process; a LAN listener needs more."""
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen 0.0.0.0:8765')
        app._dispatch_cmd(':web start')
        assert app._web_server is None
        assert 'without a password' in _events(app)
        assert 'ssh -L' in _events(app), 'and says how to reach it instead'

    def test_the_address_is_still_remembered(self, pb, tmp_path):
        """Refusing to listen on it is not the same as rejecting the setting."""
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen 0.0.0.0:8765')
        assert app.web_listen == '0.0.0.0:8765'

    def test_a_bad_address_is_rejected_with_a_reason(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen 127.0.0.1:notaport')
        assert 'not a number' in _events(app)
        app._dispatch_cmd(':set web-listen 127.0.0.1:99999')
        assert 'out of range' in _events(app)

    def test_a_bad_allowlist_is_rejected_with_a_reason(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-allow 10.0.0.0/64')
        assert 'web-allow' in _events(app)
        assert app.web_allow == ''

    def test_changing_the_address_rebinds(self, served):
        """The setting and the socket must not be able to disagree."""
        app, c = served
        first = c.port
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        assert app._web_server is not None
        assert app._web_server.server_address[1] != first

    def test_parsing_covers_the_spellings(self, pb):
        assert pb._web_parse_listen('127.0.0.1:8765') == ('127.0.0.1', 8765)
        assert pb._web_parse_listen(':9') == ('127.0.0.1', 9)
        assert pb._web_parse_listen('[::1]:80') == ('::1', 80)
        assert pb._web_parse_listen('127.0.0.1:0')[1] == 0, 'kernel picks one'
        with pytest.raises(ValueError):
            pb._web_parse_listen('[::1')
        with pytest.raises(ValueError):
            pb._web_parse_listen('')


# ===========================================================================
# Kiosk mode
# ===========================================================================

class TestKioskMode:
    """The console user is the attacker there, so they may not open a port."""

    def test_it_is_refused_at_the_console(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, kiosk=True)
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        assert app._web_server is None
        assert 'kiosk' in _events(app)

    def test_the_hosts_file_may_still_declare_it(self, pb, tmp_path):
        """Same rule ':probe-source' follows: the file is trusted, the keyboard is not."""
        app = _make_app(pb, tmp_path, kiosk=True)
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._loading_file = True
        try:
            app._dispatch_cmd(':web start')
        finally:
            app._loading_file = False
        assert app._web_server is not None
        app._web_stop(quiet=True)

    def test_a_privileged_port_is_refused_with_the_reason(self, pb, tmp_path):
        """The kiosk unit sets NoNewPrivileges=yes, so the bind would fail."""
        app = _make_app(pb, tmp_path, kiosk=True)
        app._dispatch_cmd(':set web-listen 127.0.0.1:80')
        app._loading_file = True
        try:
            app._dispatch_cmd(':web start')
        finally:
            app._loading_file = False
        assert app._web_server is None
        assert 'NoNewPrivileges' in _events(app)

    def test_starting_is_audited(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, kiosk=True)
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        seen = []
        app._loading_file = True
        try:
            with patch.object(type(app), '_kiosk_audit',
                              lambda self, a, d='': seen.append((a, d))):
                app._dispatch_cmd(':web start')
        finally:
            app._loading_file = False
        try:
            assert any(a == 'web-start' for a, _d in seen), seen
        finally:
            app._web_stop(quiet=True)


# ===========================================================================
# Failure handling
# ===========================================================================

class TestFailuresAreVisible:

    def test_a_handler_exception_becomes_an_event_not_a_traceback(self,
                                                                  served):
        """Under curses, stderr is painted over by the next redraw.

        A handler that died silently would leave the request hanging and the
        UI looking healthy — the exact shape of a bug this program has had.
        """
        app, c = served
        c.sign_in()
        with patch.object(type(app), '_web_state',
                          side_effect=RuntimeError('boom')):
            status = c.get('/api/state')[0]
        assert status == 500
        assert 'boom' in _events(app)
        assert c.get('/api/state')[0] == 200, 'and the server still serves'

    def test_request_logging_goes_to_the_event_log(self, served):
        app, c = served
        app._dispatch_cmd(':set log-level debug')
        c.get('/nope')
        assert any(e.category == 'web' for e in app.events)

    def test_the_connection_cap_refuses_rather_than_growing_threads(self, pb,
                                                                    served):
        """ThreadingHTTPServer has no cap; idle tabs would each hold a thread."""
        app, _c = served
        server = app._web_server
        cap = pb._WEB_MAX_CONNECTIONS
        try:
            for _ in range(cap):
                assert server.verify_request(None, ('127.0.0.1', 1)) is True
            assert server.verify_request(None, ('127.0.0.1', 1)) is False, \
                'the cap must refuse rather than accept and grow a thread'
        finally:
            with server._active_lock:
                server._active = 0


# ===========================================================================
# Persistence
# ===========================================================================

class TestPersistence:

    def test_the_settings_are_saved_but_the_listener_is_not_started(
            self, pb, tmp_path):
        """A network socket should open because someone asked for it."""
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        with patch.object(pb, '_config_path', return_value=cfg):
            app = pb.Application([('host', '10.0.0.1')])
            app._monitoring_started = True
            app._dispatch_cmd(':set web-listen 127.0.0.1:9999')
            app._dispatch_cmd(':set web-allow 10.0.0.0/8')
            app._dispatch_cmd(':save-config')
        text = open(cfg).read()
        assert ':set web-listen 127.0.0.1:9999' in text
        assert ':set web-allow 10.0.0.0/8' in text
        assert ':web start' not in text

    def test_the_default_address_is_not_written(self, pb, tmp_path):
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        with patch.object(pb, '_config_path', return_value=cfg):
            app = pb.Application([('host', '10.0.0.1')])
            app._monitoring_started = True
            app._dispatch_cmd(':save-config')
        assert 'web-listen' not in open(cfg).read()

    def test_the_settings_report_and_cycle_like_every_other_one(self, pb,
                                                                tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen')
        assert app._status_msg['text'] == f'web-listen {app.web_listen}'
        app._dispatch_cmd(':set web-allow')
        assert app._status_msg['text'] == 'web-allow any'


# ===========================================================================
# The per-host details endpoint
# ===========================================================================

class TestTheDetailsEndpoint:
    """GET /api/host/<uid> — the overlay's figures, for one host."""

    def _uid(self, c):
        state = json.loads(c.get('/api/state')[2])
        return next(r['uid'] for r in state['rows'] if r['kind'] == 'host')

    def test_it_needs_a_session(self, served):
        _app, c = served
        status, _h, body = c.get('/api/host/anything')
        assert status == 401
        assert b'login required' in body

    def test_it_returns_the_same_figures_the_overlay_shows(self, served):
        app, c = served
        c.sign_in()
        uid = self._uid(c)
        status, _h, body = c.get(f'/api/host/{uid}')
        assert status == 200
        detail = json.loads(body)
        monitor = next(m for m in app.monitors if m.uid == uid)
        expected = app._details_data(monitor)
        for key in ('name', 'host', 'cmd', 'tx', 'rx', 'xx', 'alive'):
            assert detail[key] == expected[key], key

    def test_an_unknown_host_is_404_not_an_error(self, served):
        _app, c = served
        c.sign_in()
        status, _h, body = c.get('/api/host/nosuchuid')
        assert status == 404
        assert b'no such host' in body

    def test_a_section_uid_is_not_a_host(self, pb, tmp_path):
        """Sections have uids too; asking for one must not half-work."""
        app = _make_app(pb, tmp_path, '### group\n10.0.0.1\n')
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        try:
            c = Client(app).sign_in()
            section = next(e for e in app.entries
                           if isinstance(e, pb.SectionLabel))
            assert c.get(f'/api/host/{section.uid}')[0] == 404
        finally:
            app._web_stop(quiet=True)

    def test_it_carries_the_probe_blocks(self, pb, tmp_path):
        """The overlay's own rendered sparkline, not a second implementation."""
        import time as _t
        app = _make_app(pb, tmp_path,
                        ":probe-source --cmd 'echo t=1'\n"
                        ':probe t --range 0:100\n10.0.0.1\n')
        monitor = app.monitors[0]
        with monitor.lock:
            series = monitor.probes.setdefault('t', pb.ProbeSeries(10))
            series.add(42.0, _t.time())
            series.state = 'ok'
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        try:
            c = Client(app).sign_in()
            detail = json.loads(c.get(f'/api/host/{monitor.uid}')[2])
            assert detail['probes'] == app._probe_overlay_lines(monitor, 60)
            assert any('42' in line for line in detail['probes'])
        finally:
            app._web_stop(quiet=True)

    def test_a_hostile_name_stays_inert(self, pb, tmp_path):
        app = _make_app(pb, tmp_path,
                        '10.0.0.1 ## </script><img src=x onerror=alert(1)>\n')
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        try:
            c = Client(app).sign_in()
            status, _h, body = c.get(f'/api/host/{app.monitors[0].uid}')
            assert status == 200
            assert b'<' not in body and b'>' not in body
            assert '<img' in json.loads(body)['name']
        finally:
            app._web_stop(quiet=True)


class TestThePageCanShowIt:
    """Structure the client needs, asserted where it cannot silently rot."""

    def test_the_page_has_a_filter_and_a_details_panel(self, pb):
        html = pb._WEB_HTML
        assert 'id="filter"' in html
        assert 'id="detail-wrap"' in html

    def test_filtering_is_client_side(self, pb):
        """':filter' would move the terminal's view and every other viewer's.

        One person searching should not drag anybody else's screen with them.
        """
        js = '\n'.join(line for line in pb._WEB_JS.splitlines()
                       if not line.lstrip().startswith('//'))
        assert "'/api/cmd'" in js, 'the command box still posts'
        assert ':filter' not in js
        assert 'filterEl.value' in js

    def test_the_page_still_has_no_inline_script(self, pb):
        html = pb._WEB_HTML
        assert '<script>' not in html
        assert 'onclick=' not in html and 'onerror=' not in html
        assert 'addEventListener' in pb._WEB_JS
