"""A refused command must say so on screen, not only at -vvv.

Category ``cmd`` is ``LEVEL_INFO`` while the default log level is
``LEVEL_NORMAL``, so an event-only refusal is invisible: the command appears
to do nothing and offers no reason.  This program has shipped that three
times — ``:set stats`` losing every column on restart (AGENTS.md §8 Phase 19,
reported as "my settings did not survive a restart"), and then the entire web
surface.

The instance that prompted this was a real production config: ``:set
web-listen 0.0.0.0:8088`` with no password file, where ``:web start`` did
nothing, said nothing, and the explanation — "refusing to listen on 0.0.0.0
without a password" — was reachable only by restarting at ``-vvv``.

Four silences, one per class:

1. ``:web start`` refusals and every ``:set web-*`` rejection.
2. A refused web *command* left no record at all: the 403 was sent before the
   audit, so a session could walk the whole blocked surface in silence.
3. The write queue answered ``202 queued`` and then dropped the command,
   because a bounded deque evicts from the **left** — the flooder wins and
   the operator's own click is discarded.
4. An unusable ``web-password-file`` dropped the *setting*, and the next
   ``:save-config`` erased the path for good.
"""

import json
import os
import urllib.error
import urllib.request

import pytest
from unittest.mock import patch


def _make_app(pb, tmp_path, kiosk=False):
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    open(cfg, 'w').close()
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '10.0.0.1'), ('host', '10.0.0.2')],
                             kiosk_mode=kiosk)
    app._monitoring_started = True
    return app


def _visible(app, since):
    """What the operator actually sees at the default log level."""
    return [e.text for e in list(app.events)[since:] if e.level <= app.loglevel]


class TestEveryWebRefusalIsVisible:
    @pytest.fixture
    def app(self, pb, tmp_path):
        return _make_app(pb, tmp_path)

    @pytest.mark.parametrize('cmd', [
        ':set web-listen not-a-port',
        ':set web-listen 1.2.3.4:99999',
        ':set web-allow 10.0.0.0/99',
        ':set web-commands readonly',
        ':set web-password-file /nonexistent/pw',
        ':web startt',
    ])
    def test_it_reaches_the_log_at_the_default_level(self, app, cmd):
        n = len(app.events)
        app._dispatch_cmd(cmd)
        assert _visible(app, n), f'{cmd} said nothing on screen'

    @pytest.mark.parametrize('cmd', [
        ':set web-listen not-a-port',
        ':set web-allow 10.0.0.0/99',
        ':set web-commands readonly',
        ':web startt',
    ])
    def test_it_reaches_the_status_bar_too(self, app, cmd):
        """The log may be scrolled back, filtered, or below the fold."""
        app._status_msg = None
        app._dispatch_cmd(cmd)
        assert app._status_msg and app._status_msg.get('text'), cmd

    def test_the_production_case(self, app):
        """0.0.0.0 with no password file: the one that was reported."""
        app._dispatch_cmd(':set web-listen 0.0.0.0:8088')
        app._status_msg = None
        n = len(app.events)
        app._dispatch_cmd(':web start')
        assert app._web_server is None
        shown = ' | '.join(_visible(app, n))
        assert 'without a password' in shown, shown
        assert app._status_msg['text']

    def test_a_startup_refusal_is_visible_without_a_status_bar(self, pb,
                                                               tmp_path):
        """There is no screen yet while a config is loading."""
        cfg = tmp_path / 'ping-bulk' / 'config'
        os.makedirs(str(cfg.parent), exist_ok=True)
        cfg.write_text(':set web-allow 10.0.0.0/99\n')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([('host', '10.0.0.1')])
        assert any(e.level <= app.loglevel and 'web-allow' in e.text
                   for e in app.events)

    def test_no_web_handler_reports_a_refusal_the_quiet_way(self, pb):
        """Structural: the next handler added must not reintroduce this.

        Matches both quotings — the first cut looked only for
        ``add_event('cmd'`` while the file uses ``add_event("cmd"`` 136 times
        to 1, so a new handler written in the house style would have walked
        straight past it.  And it keys on the *name*, so a future ``_web_foo``
        or ``_cmd_web_bar`` is covered without anyone extending a list.
        """
        import inspect
        import re
        src = inspect.getsource(pb).splitlines()
        current, offenders = None, []
        for i, line in enumerate(src, 1):
            m = re.match(r'    def (\w+)', line)
            if m:
                current = m.group(1)
            name = current or ''
            web = name.startswith(('_web_', '_cmd_web'))
            if web and re.search(r"""add_event\(\s*['"]cmd['"]""", line):
                offenders.append((i, current))
        assert not offenders, (
            'refusals that will be invisible at the default level: %s'
            % offenders)

    def test_the_guard_catches_a_handler_written_in_the_house_style(self, pb):
        """The guard's own regression test: it must match both quotings."""
        import re
        pattern = re.compile(r"""add_event\(\s*['"]cmd['"]""")
        assert pattern.search("""            self.add_event("cmd", 'nope')""")
        assert pattern.search("""            self.add_event('cmd', 'nope')""")
        assert not pattern.search("""            self._refuse('cmd', 'nope')""")


class TestARefusedCommandLeavesARecord:
    @pytest.fixture
    def served(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        assert app._web_server is not None, [e.text for e in app.events]
        try:
            yield app, _Client(app)
        finally:
            app._web_stop(quiet=True)

    @pytest.mark.parametrize('cmd', [':mux sh', ':source /etc/shadow',
                                     ':quit', ':edit'])
    def test_the_refusal_is_logged_at_the_default_level(self, served, cmd):
        app, c = served
        n = len(app.events)
        assert c.command(cmd)[0] == 403
        shown = ' | '.join(_visible(app, n))
        assert 'refused' in shown and cmd.lstrip(':').split()[0] in shown

    def test_it_is_audited(self, served):
        app, c = served
        seen = []
        with patch.object(app, '_kiosk_audit',
                          side_effect=lambda *a, **k: seen.append(a[0])):
            c.command(':mux sh')
        assert 'web-cmd-refused' in seen

    def test_an_allowed_command_is_still_audited_as_run(self, served):
        app, c = served
        seen = []
        with patch.object(app, '_kiosk_audit',
                          side_effect=lambda *a, **k: seen.append(a[0])):
            c.command(':seen')
        assert seen == ['web-cmd']
        app._web_queue.clear()


class TestTheRecordDoesNotBecomeTheFlood:
    """The fix for "refusals leave no record" must not destroy every record.

    A refusal event at LEVEL_NORMAL goes to the ':log' file by design (§12),
    and a session can send them as fast as the socket allows — measured at
    1072/s, which wipes the 10 000-entry deque in nine seconds and writes some
    10 GB a day.  The body limit is 64 KB, so one request could write a 60 KB
    line.  The syslog audit is deliberately *not* throttled: it is the security
    record, and syslog does its own rate control.
    """

    @pytest.fixture
    def served(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':log ' + str(tmp_path / 'pb.log'))
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        try:
            yield app, _Client(app), str(tmp_path / 'pb.log')
        finally:
            app._web_stop(quiet=True)

    def test_a_flood_of_refusals_is_bounded(self, pb, served):
        app, c, logf = served
        before = len(app.events)
        for _ in range(200):
            assert c.command(':mux sh')[0] == 403
        new = [e.text for e in list(app.events)[before:]]
        assert len(new) <= pb._WEB_REFUSE_LOG_MAX + 1, len(new)

    def test_it_still_records_the_first_few(self, pb, served):
        app, c, _ = served
        before = len(app.events)
        for _ in range(200):
            c.command(':mux sh')
        new = [e.text for e in list(app.events)[before:]]
        assert sum('was refused' in t for t in new) == pb._WEB_REFUSE_LOG_MAX
        assert any('refused repeatedly' in t for t in new), \
            'nothing said it had stopped reporting'

    def test_every_refusal_is_still_audited(self, served):
        """Throttling the event must not throttle the security record."""
        app, c, _ = served
        seen = []
        with patch.object(app, '_kiosk_audit',
                          side_effect=lambda *a, **k: seen.append(a[0])):
            for _ in range(20):
                c.command(':mux sh')
        assert seen.count('web-cmd-refused') == 20

    def test_a_huge_command_cannot_write_a_huge_line(self, pb, served):
        app, c, logf = served
        before = os.path.getsize(logf)
        assert c.command(':mux ' + 'A' * 60000)[0] == 403
        grew = os.path.getsize(logf) - before
        assert grew < 2 * pb._WEB_REFUSE_CMD_CHARS + 300, grew

    def test_the_throttle_does_not_consume_a_login_attempt(self, pb, served):
        """Separate gates: a refused command is not a wrong password."""
        app, c, _ = served
        for _ in range(pb._WEB_LOGIN_FAILS + 5):
            c.command(':mux sh')
        assert not app._web_server.login_gate.blocked('127.0.0.1')


class TestSafeListedCommandsSpeakUpToo:
    """Everything a browser can send, refused with a bad value.

    The first pass covered the web *settings* surface only, and left the
    allowlisted commands — which are precisely the ones a browser can reach.
    """

    @pytest.fixture
    def app(self, pb, tmp_path):
        return _make_app(pb, tmp_path)

    @pytest.mark.parametrize('cmd', [
        ':pause-selected yes', ':dns bogus', ':sort bogus', ':layout bogus',
        ':pause yes', ':sync-history yes', ':autofold yes',
        ':ping-view bogus', ':no-alarm --remove nosuch',
    ])
    def test_a_bad_value_is_visible(self, app, cmd):
        app._status_msg = None
        n = len(app.events)
        app._dispatch_cmd(cmd)
        assert _visible(app, n), f'{cmd} said nothing'
        assert app._status_msg, f'{cmd} left the status bar empty'

    def test_a_successful_change_does_not_hijack_the_status_bar(self, app):
        """':layout log' reports success; the bar already shows 'layout:log'.

        Converting that report to a refusal blanked the indicator the layout
        tests assert on — a reminder that not every add_event('cmd') is a
        refusal.
        """
        app._status_msg = None
        app._dispatch_cmd(':layout log')
        assert not app._status_msg


class TestAFullQueueSaysSo:
    @pytest.fixture
    def served(self, pb, tmp_path):
        app = _make_app(pb, tmp_path)
        app._dispatch_cmd(':set web-listen 127.0.0.1:0')
        app._dispatch_cmd(':web start')
        try:
            yield app, _Client(app)
        finally:
            app._web_stop(quiet=True)

    def test_overflow_is_503_not_a_lying_202(self, pb, served):
        app, c = served
        codes = [c.command(':seen')[0]
                 for _ in range(pb._WEB_QUEUE_MAX + 4)]
        assert set(codes[:pb._WEB_QUEUE_MAX]) == {202}
        assert set(codes[pb._WEB_QUEUE_MAX:]) == {503}

    def test_the_queued_commands_are_the_ones_accepted(self, pb, served):
        """The deque evicted from the left, so the flooder won."""
        app, c = served
        for i in range(pb._WEB_QUEUE_MAX + 4):
            c.command(':filter marker%d' % i)
        queued = [item['cmd'] for item in app._web_queue]
        assert ':filter marker0' in queued, 'the first accepted was dropped'
        assert ':filter marker%d' % (pb._WEB_QUEUE_MAX + 3) not in queued


class _Client:
    """Signed-in POSTer for /api/cmd."""

    def __init__(self, app):
        self.app = app
        host, port = app._web_server.server_address[:2]
        self.base = f'http://{host}:{port}'

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **kw):
                return None

        if app._web_server.token is None:
            app._dispatch_cmd(':web status')
        req = urllib.request.Request(
            self.base + f'/?t={app._web_server.token}')
        try:
            r = urllib.request.build_opener(NoRedirect).open(req, timeout=10)
            header = r.headers.get('Set-Cookie', '')
        except urllib.error.HTTPError as e:
            header = e.headers.get('Set-Cookie', '')
        self.cookie = header.split(';')[0]
        state = urllib.request.urlopen(urllib.request.Request(
            self.base + '/api/state',
            headers={'Cookie': self.cookie}), timeout=10)
        self.csrf = json.loads(state.read())['csrf']

    def command(self, cmd):
        req = urllib.request.Request(
            self.base + '/api/cmd', data=json.dumps({'cmd': cmd}).encode(),
            headers={'Content-Type': 'application/json',
                     'Cookie': self.cookie, 'X-PB-Token': self.csrf},
            method='POST')
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
