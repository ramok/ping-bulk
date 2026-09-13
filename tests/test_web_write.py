"""Changing something from the browser.

Three things are load-bearing here.

**Commands are addressed by uid, never by row index or by "whatever is
selected".**  An ':edit' reload rebuilds the row list, and the browser is
looking at a picture up to two seconds old, so "pause row 7" can arrive after
row 7 has become a different host.  Worse, ``highlighted_index`` is one cursor
shared with whoever is at the console — who, in this program's own kiosk
threat model, is the party it does not trust.  A queued command that meant
"the selected host" could be steered by that person between the click and the
tick.

**Nothing from a request touches application state.**  The server thread
appends to a queue; the main loop drains it at the top of a tick, moves the
cursor to the named host, dispatches through ``_dispatch_cmd`` — which is
where validation and the audit record live — and puts the cursor back.

**The safe set is an allowlist.**  A command added to this program later has
to be considered before a browser can run it, rather than being exposed until
somebody notices.
"""

import json
import os
import urllib.error
import urllib.request

import pytest
from unittest.mock import patch


BASE = """### group
10.0.0.1
10.0.0.2
10.0.0.3
"""


def _password_file(tmp_path, text='hunter2', mode=0o600):
    path = tmp_path / 'webpw'
    path.write_text(text)
    os.chmod(path, mode)
    return str(path)


def _make_app(pb, tmp_path, content=BASE, kiosk=False):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    hosts = tmp_path / 'w.hosts'
    hosts.write_text(content)
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application(pb.parse_hosts_file(str(hosts)), kiosk_mode=kiosk)
    app._monitoring_started = True
    app._hosts_path = str(hosts)
    return app


def _reload(app, content):
    with open(app._hosts_path, 'w') as f:
        f.write(content)
    with patch.object(app, '_start_monitor_thread', lambda m: None):
        app._edit_reload_inplace(app._hosts_path)


def _events(app):
    return ' | '.join(e.text for e in app.events)


class Client:
    def __init__(self, app):
        self.app = app
        host, port = app._web_server.server_address[:2]
        self.base = f'http://{host}:{port}'
        self.cookie = ''
        self.csrf = ''

    def sign_in(self):
        """Exchange the sign-in link for a session cookie.

        The link is spent on first use, so a second Client in the same test
        asks for a fresh one exactly as an operator would — ':web status'
        mints another once the last has been used.
        """
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        if self.app._web_server.token is None:
            self.app._dispatch_cmd(':web status')
        req = urllib.request.Request(
            self.base + f'/?t={self.app._web_server.token}')
        try:
            r = urllib.request.build_opener(NoRedirect).open(req, timeout=10)
            header = r.headers.get('Set-Cookie', '')
        except urllib.error.HTTPError as e:
            header = e.headers.get('Set-Cookie', '')
        self.cookie = header.split(';')[0]
        self.csrf = self.state()['csrf']
        return self

    def _go(self, req):
        if self.cookie:
            req.add_header('Cookie', self.cookie)
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def state(self):
        return json.loads(self._go(
            urllib.request.Request(self.base + '/api/state'))[1])

    def action(self, uid, verb, token='use-mine'):
        req = urllib.request.Request(
            self.base + f'/api/host/{uid}/{verb}', method='POST')
        if token is not None:
            req.add_header('X-PB-Token',
                           self.csrf if token == 'use-mine' else token)
        return self._go(req)

    def command(self, cmd, uid=None, token='use-mine'):
        body = json.dumps({'cmd': cmd, 'uid': uid}).encode()
        req = urllib.request.Request(self.base + '/api/cmd', data=body,
                                     method='POST')
        req.add_header('Content-Type', 'application/json')
        if token is not None:
            req.add_header('X-PB-Token',
                           self.csrf if token == 'use-mine' else token)
        return self._go(req)


@pytest.fixture
def served(pb, tmp_path):
    app = _make_app(pb, tmp_path)
    app._dispatch_cmd(':set web-listen 127.0.0.1:0')
    app._dispatch_cmd(':web start')
    assert app._web_server is not None, _events(app)
    try:
        yield app, Client(app).sign_in()
    finally:
        app._web_stop(quiet=True)


def _uid(app, host):
    return next(m.uid for m in app.monitors if m.host == host)


def _paused(app):
    return {m.host: m.paused for m in app.monitors}


# ===========================================================================
# Addressing
# ===========================================================================

class TestCommandsAreAddressedByHost:

    def test_a_reload_that_renumbers_does_not_move_the_target(self, served):
        """The headline property, and the reason uid exists at all.

        Between the click and the tick, the row list is rebuilt with an extra
        host at the top, so every index shifts by one.
        """
        app, c = served
        uid = _uid(app, '10.0.0.3')
        c.action(uid, 'pause')
        _reload(app, "### group\n10.0.0.0\n10.0.0.1\n10.0.0.2\n10.0.0.3\n")
        app._web_drain()
        assert _paused(app) == {'10.0.0.0': False, '10.0.0.1': False,
                                '10.0.0.2': False, '10.0.0.3': True}

    def test_a_host_that_is_gone_is_reported_not_misapplied(self, served):
        app, c = served
        uid = _uid(app, '10.0.0.3')
        c.action(uid, 'pause')
        _reload(app, "### group\n10.0.0.1\n10.0.0.2\n")
        app._web_drain()
        assert not any(m.paused for m in app.monitors)
        assert 'no longer in the list' in _events(app)

    def test_the_console_cursor_is_put_back(self, served):
        """It is shared state; a web request must not leave it moved."""
        app, c = served
        app.highlighted_index = app.entries.index(app.monitors[0])
        before = app.highlighted_index
        c.action(_uid(app, '10.0.0.3'), 'pause')
        app._web_drain()
        assert app.highlighted_index == before
        assert app.monitors[2].paused

    def test_the_cursor_is_put_back_even_when_the_command_fails(self, served):
        app, c = served
        app.highlighted_index = 1
        app._web_enqueue(':pause-selected on', uid=_uid(app, '10.0.0.2'))
        with patch.object(type(app), '_dispatch_cmd',
                          side_effect=RuntimeError('boom')):
            app._web_drain()
        assert app.highlighted_index == 1
        assert 'boom' in _events(app)

    def test_nothing_changes_until_the_main_loop_runs(self, served):
        """The server thread queues; it does not touch state."""
        app, c = served
        c.action(_uid(app, '10.0.0.1'), 'pause')
        assert len(app._web_queue) == 1
        assert not any(m.paused for m in app.monitors)
        app._web_drain()
        assert app.monitors[0].paused

    def test_the_queue_is_bounded(self, pb, served):
        app, _c = served
        for _ in range(pb._WEB_QUEUE_MAX * 2):
            app._web_enqueue(':seen')
        assert len(app._web_queue) == pb._WEB_QUEUE_MAX


# ===========================================================================
# The buttons
# ===========================================================================

class TestHostActions:

    def test_pause_and_resume_are_explicit(self, served):
        """A toggle applied to a two-second-old view can do the opposite."""
        app, c = served
        uid = _uid(app, '10.0.0.1')
        c.action(uid, 'pause')
        app._web_drain()
        assert app.monitors[0].paused
        c.action(uid, 'pause')          # again: still paused, not toggled off
        app._web_drain()
        assert app.monitors[0].paused
        c.action(uid, 'resume')
        app._web_drain()
        assert not app.monitors[0].paused

    def test_no_alarm_toggles_that_host_only(self, served):
        app, c = served
        c.action(_uid(app, '10.0.0.2'), 'no-alarm')
        app._web_drain()
        assert [m.no_alarm for m in app.monitors] == [False, True, False]

    def test_an_unknown_verb_is_404(self, served):
        app, c = served
        assert c.action(_uid(app, '10.0.0.1'), 'destroy')[0] == 404
        assert len(app._web_queue) == 0

    def test_a_malformed_path_is_404(self, served):
        _app, c = served
        req = urllib.request.Request(c.base + '/api/host/abc', method='POST')
        req.add_header('X-PB-Token', c.csrf)
        assert c._go(req)[0] == 404

    def test_the_accepted_response_says_so(self, served):
        _app, c = served
        status, body = c.action(_uid(_app, '10.0.0.1'), 'pause')
        assert status == 202
        assert json.loads(body)['queued'] is True


# ===========================================================================
# Cross-site request forgery
# ===========================================================================

class TestTheCsrfToken:

    def test_a_write_without_the_header_is_refused(self, served):
        """A form on another site can reach this origin; it cannot add a
        header of our choosing without a preflight we never answer."""
        app, c = served
        assert c.action(_uid(app, '10.0.0.1'), 'pause', token=None)[0] == 403
        assert len(app._web_queue) == 0

    def test_a_wrong_header_is_refused(self, served):
        app, c = served
        assert c.action(_uid(app, '10.0.0.1'), 'pause',
                        token='not-the-token')[0] == 403

    def test_another_sessions_token_is_refused(self, served):
        """It is derived from the session, so a lifted one is useless."""
        app, c = served
        other = Client(app).sign_in()
        assert other.csrf != c.csrf
        assert c.action(_uid(app, '10.0.0.1'), 'pause',
                        token=other.csrf)[0] == 403

    def test_a_write_without_a_session_is_refused_first(self, served):
        app, c = served
        c.cookie = ''
        status, body = c.action(_uid(app, '10.0.0.1'), 'pause')
        assert status == 401
        assert b'login required' in body

    def test_the_token_is_only_handed_to_an_authenticated_client(self, served):
        _app, c = served
        anon = Client(_app)
        assert 'csrf' not in anon.state()

    def test_it_is_stable_within_a_session(self, served):
        _app, c = served
        assert c.state()['csrf'] == c.csrf


# ===========================================================================
# The allowlist
# ===========================================================================

class TestTheSafeSet:

    # ':edit' is absent on purpose: it is refused for a stronger reason and
    # in every mode, so it has its own test (TestFullMode).
    REFUSED = [':mux sh', ':term', ':source /etc/passwd',
               ':log /tmp/x', ':save /tmp/x', ':save-config', ':quit',
               ':bind-key x :mux sh', ':probe-source --cmd id',
               ':remote-ping root@relay 10.0.0.9', ':ping 10.0.0.9',
               ':set ssh-options -o ProxyCommand=sh', ':web stop',
               ':relay-os * linux', ':prog-options ssh * --disable']

    ALLOWED = [':seen', ':clear', ':fold-all', ':unfold-all',
               ':filter 10.0.0', ':sync-history on', ':dns cycle',
               ':sort name', ':pause on']

    @pytest.mark.parametrize('cmd', REFUSED)
    def test_it_refuses_anything_that_reaches_the_system(self, served, cmd):
        app, c = served
        status, body = c.command(cmd)
        assert status == 403, cmd
        assert b'not in the safe set' in body, cmd
        assert len(app._web_queue) == 0, cmd

    @pytest.mark.parametrize('cmd', ALLOWED)
    def test_it_allows_the_monitoring_ones(self, served, cmd):
        app, c = served
        assert c.command(cmd)[0] == 202, cmd
        app._web_drain()

    def test_an_empty_command_is_refused(self, served):
        _app, c = served
        assert c.command('')[0] == 403

    def test_the_set_is_a_whitelist_not_a_blacklist(self, pb):
        """A command added later must be considered, not exposed by default."""
        every = {name for cmd in pb.CMD_REGISTRY for name in cmd.names}
        assert pb._WEB_SAFE_COMMANDS < every, 'safe set must be a subset'
        for dangerous in ('mux', 'term', 'edit', 'source', 'log', 'save',
                          'save-config', 'quit', 'bind-key', 'unbind-key',
                          'set', 'web', 'probe-source', 'remote-ping', 'ping'):
            assert dangerous not in pb._WEB_SAFE_COMMANDS, dangerous

    def test_a_command_can_carry_its_own_host(self, served):
        app, c = served
        assert c.command(':pause-selected on',
                         uid=_uid(app, '10.0.0.2'))[0] == 202
        app._web_drain()
        assert _paused(app) == {'10.0.0.1': False, '10.0.0.2': True,
                                '10.0.0.3': False}


# ===========================================================================
# read-only and kiosk
# ===========================================================================

class TestReadOnly:

    def test_read_only_refuses_every_write(self, served):
        app, c = served
        app._dispatch_cmd(':set web-commands read-only')
        status, body = c.action(_uid(app, '10.0.0.1'), 'pause')
        assert status == 403
        assert b'read-only' in body
        assert c.command(':seen')[0] == 403

    def test_the_page_is_told_so_it_can_hide_the_buttons(self, served):
        app, c = served
        assert c.state()['commands'] == 'safe'
        app._dispatch_cmd(':set web-commands read-only')
        assert c.state()['commands'] == 'read-only'

    def test_kiosk_refuses_to_enable_writes(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, kiosk=True)
        assert app.web_commands == 'read-only', 'and that is the default there'
        app._dispatch_cmd(':set web-commands safe')
        assert app.web_commands == 'read-only'
        assert 'kiosk mode allows read-only only' in _events(app)

    def test_kiosk_forces_read_only_at_start(self, pb, tmp_path):
        """A config written before kiosk was switched on must not carry over."""
        app = _make_app(pb, tmp_path, kiosk=True)
        app.web_commands = 'safe'       # as a stale config would leave it
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._loading_file = True
        try:
            app._dispatch_cmd(':web start')
        finally:
            app._loading_file = False
        try:
            assert app.web_commands == 'read-only'
            assert 'forcing read-only' in _events(app)
        finally:
            app._web_stop(quiet=True)

    def test_an_unknown_mode_is_rejected(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-commands wide-open')
        assert app.web_commands == 'safe'
        assert "unknown value 'wide-open'" in _events(app)


# ===========================================================================
# The record
# ===========================================================================

class TestItIsAudited:

    def test_every_web_command_reaches_syslog_with_the_client(self, served):
        """The audit format had no field for a requester off the machine."""
        app, c = served
        seen = []
        with patch.object(type(app), '_kiosk_audit',
                          lambda self, a, d='', principal='':
                              seen.append((a, d, principal))):
            c.action(_uid(app, '10.0.0.1'), 'pause')
        assert seen, 'nothing was audited'
        action, detail, principal = seen[0]
        assert action == 'web-cmd'
        assert 'pause-selected' in detail
        assert principal == '127.0.0.1'

    def test_it_is_audited_outside_kiosk_mode_too(self, pb, served):
        app, _c = served
        assert not app.kiosk_mode
        with patch.object(pb._syslog, 'syslog') as log:
            app._kiosk_audit('web-cmd', ':seen', principal='10.0.0.9')
        assert log.called
        assert 'from=10.0.0.9' in log.call_args[0][1]

    def test_the_event_log_names_the_client(self, served):
        app, c = served
        c.action(_uid(app, '10.0.0.1'), 'pause')
        assert "127.0.0.1 ran ':pause-selected on'" in _events(app)


# ===========================================================================
# 'full' was removed, and a config written for it still loads
# ===========================================================================

class TestFullModeIsGone:
    """It offered the whole ':' line over HTTP, gated four ways, and went.

    Not because the gates failed — each one was verified to work — but because
    narrowing it to the commands that *can* work over a request turned out to
    be impossible.  ``_web_command_allowed`` derives the name from the first
    token and then allowed everything, so ':source <file>' handed over a file
    of arbitrary directives and ':bind-key x :mux sh' hid one behind a
    keypress.  Subtract those too and what is left is the allowlist 'safe'
    already is.
    """

    def test_it_is_not_a_mode_any_more(self, pb):
        assert 'full' not in pb._WEB_COMMAND_MODES
        assert pb._WEB_COMMAND_MODES == ('read-only', 'safe')

    def test_the_word_still_parses_and_degrades(self, served):
        app, _c = served
        app._dispatch_cmd(':set web-commands full')
        assert app.web_commands == 'safe'
        assert 'has been removed' in _events(app)

    def test_a_config_written_for_it_still_loads(self, pb, tmp_path):
        """Rejecting the line would cost the operator the whole file (§11)."""
        cfg = tmp_path / 'ping-bulk' / 'config'
        os.makedirs(str(cfg.parent), exist_ok=True)
        cfg.write_text(':set web-commands full\n')
        hosts = tmp_path / 'web.hosts'
        hosts.write_text('10.0.0.1\n')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application(pb.parse_hosts_file(str(hosts)))
        assert app.web_commands == 'safe'
        assert 'has been removed' in _events(app)

    def test_it_is_not_written_back(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-commands full')
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        with patch.object(pb, '_config_path', return_value=cfg):
            app._dispatch_cmd(':save-config')
        assert 'full' not in open(cfg).read()

    def test_cycling_only_ever_yields_a_live_mode(self, pb, served):
        """Not a guard against 'full' returning — that is the test above.

        Re-adding 'full' to _WEB_COMMAND_MODES would leave this passing,
        because the cycle branch re-dispatches through _cmd_web_commands and
        the degrade fires before the value is ever stored.  What this pins is
        that cycling cannot reach a value the rest of the program rejects.
        """
        app, _c = served
        seen = set()
        for _ in range(6):
            app._dispatch_cmd(':set web-commands cycle')
            seen.add(app.web_commands)
        assert seen == set(pb._WEB_COMMAND_MODES)

    def test_cycling_backwards_is_the_same_set(self, pb, served):
        app, _c = served
        seen = set()
        for _ in range(6):
            app._dispatch_cmd(':set web-commands cycle-')
            seen.add(app.web_commands)
        assert seen == set(pb._WEB_COMMAND_MODES)

    def test_kiosk_still_forces_read_only(self, pb, tmp_path):
        app = _make_app(pb, tmp_path, kiosk=True)
        app._dispatch_cmd(':set web-commands full')
        assert app.web_commands == 'read-only'

    def test_the_page_is_never_told_about_a_command_box(self, served):
        app, c = served
        assert c.state()['commands'] == 'safe'
        app._dispatch_cmd(':set web-commands full')
        assert c.state()['commands'] == 'safe'


class TestNothingLaundersItsWayIn:
    """The commands that made narrowing impossible are refused by name.

    Each of these was *allowed* in 'full', and each is a way to run the
    others: ':source' executes a file of directives, ':bind-key --if-sh' runs
    a string through a shell, ':probe-source --cmd' runs one over ssh, and
    ':set' reaches the SSH options every monitor uses.
    """

    @pytest.mark.parametrize('cmd', [
        ':mux sh', ':tmux sh', ':screen sh', ':term sh', ':xterm sh',
        ':source /dev/null', ':bind-key x :mux sh', ':edit',
        ':probe-source --cmd id', ':set web-commands full', ':set ssh-options -o x',
        ':web stop', ':quit', ':log /tmp/x', ':save /tmp/x', ':save-config',
    ])
    def test_it_is_refused(self, served, cmd):
        app, c = served
        status, _body = c.command(cmd)
        assert status == 403, cmd
        assert len(app._web_queue) == 0, cmd

    def test_the_refusal_no_longer_advertises_a_way_round_it(self, served):
        _app, c = served
        body = c.command(':mux sh')[1]
        assert b'full' not in body, body

