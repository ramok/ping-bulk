"""The page the server actually sends has to be valid, not just look valid.

``_WEB_JS`` is a non-raw Python triple-quoted string, so a ``\\n`` written for
JavaScript is consumed by Python and served as a real line break.  Inside a
quoted JS literal that is a syntax error, and a syntax error in a classic
``<script src>`` discards the whole file — so one character cost the entire
client: no poll, no render, and in password mode no way to log in, because the
login form is ``hidden`` in the HTML and only the script reveals it.

The suite fetched ``/static/app.js`` and asserted 200 and a content type, and
the other client tests were substring checks against the constant.  None of
them parsed it, so 153 web tests passed against a page that could not load.
"""

import json
import shutil
import subprocess

import pytest


def _served_js(pb):
    """Exactly the bytes GET /static/app.js returns."""
    return pb._WEB_JS


class TestServedJavaScriptIsWellFormed:
    def test_no_string_literal_spans_a_line(self, pb):
        """A raw line break inside '…' or "…" is the failure mode to catch.

        Counting quotes per line is enough and needs no parser: an apostrophe
        in a // comment is the only benign way to leave one unbalanced, so
        comments are stripped first.
        """
        bad = []
        for n, line in enumerate(_served_js(pb).split('\n'), 1):
            code = line.split('//', 1)[0]
            if code.count("'") % 2 or code.count('"') % 2:
                bad.append((n, line))
        assert bad == [], (
            "unterminated string literal in the served JS: %r" % (bad,)
        )

    def test_the_newline_escape_reaches_the_client(self, pb):
        r"""The specific escape that was eaten, asserted as itself.

        detailText() joins its lines with '\\n'.  If Python consumes the
        backslash the join argument becomes a real line break and the literal
        never closes, so the presence of the two-character escape in the
        served text is the thing to pin.
        """
        assert '\\n' in _served_js(pb)

    @pytest.mark.skipif(shutil.which('node') is None,
                        reason='node not installed; the parser check is optional')
    def test_node_parses_it(self, pb, tmp_path):
        """When a JS engine is available, let it be the judge."""
        f = tmp_path / 'app.js'
        f.write_text(_served_js(pb), encoding='utf-8')
        r = subprocess.run(['node', '--check', str(f)],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_the_css_and_html_carry_no_eaten_escapes(self, pb):
        for name in ('_WEB_HTML', '_WEB_CSS'):
            text = getattr(pb, name)
            bad = [(n, ln) for n, ln in enumerate(text.split('\n'), 1)
                   if ln.count('"') % 2 and '<!--' not in ln]
            assert bad == [], '%s: %r' % (name, bad)


class TestThePageKeepsOnePollChain:
    """A click must not fork a second self-perpetuating poll.

    ``poll()`` re-arms itself when it finishes, so anything that *also* called
    it — a row button, a successful login — started a chain that never ended.
    Measured against the real client under a virtual clock: 26 clicks left 27
    live timers issuing 296 requests in 20 s, against a server that accepts 16
    connections at once (``_WEB_MAX_CONNECTIONS``).  Clicking for a few minutes
    locked the operator out of their own monitor.
    """

    HARNESS = r'''
let now = 0, timers = [], nextId = 1, fetches = 0;
const el = () => new Proxy(function(){}, {
  get: (t, k) => (k === 'value' ? '' :
                  k === 'classList' ? {add(){}, remove(){}, toggle(){}} :
                  k === 'style' ? {} :
                  typeof k === 'string' && k.startsWith('add') ? () => {} : el()),
  set: () => true, apply: () => el(),
});
global.document = { getElementById: el, createElement: el, addEventListener(){}, body: el() };
global.window = {
  setTimeout(fn, ms) { const id = nextId++; timers.push({id, at: now + (ms||0), fn}); return id; },
  clearTimeout(id) { timers = timers.filter(t => t.id !== id); },
  addEventListener(){}, location: {href: ''},
};
global.setTimeout = global.window.setTimeout;
global.clearTimeout = global.window.clearTimeout;
global.fetch = () => { fetches++; return Promise.resolve({
  ok: true, status: 200,
  json: () => Promise.resolve({rows: [], down: [], events: [], time: 0,
                               view: {cell_width: 1}, commands: 'safe', csrf: 'x'}),
}); };
const drain = async () => { for (let i = 0; i < 50; i++) await Promise.resolve(); };
const tick = async (ms) => {
  const end = now + ms;
  for (;;) {
    const due = timers.filter(t => t.at <= end).sort((a,b) => a.at - b.at)[0];
    if (!due) break;
    timers = timers.filter(t => t !== due);
    now = due.at; due.fn(); await drain();
  }
  now = end;
};
(async () => {
  require(process.argv[2]);
  await drain();
  await tick(2000);
  fetches = 0;
  for (let i = 0; i < 26; i++) { global.act('uid' + i, 'pause'); await drain(); }
  await tick(20000);
  console.log(JSON.stringify({requests: fetches, timers: timers.length}));
})();
'''

    @pytest.mark.skipif(shutil.which('node') is None,
                        reason='node not installed; this check needs a JS engine')
    def test_clicking_leaves_exactly_one_timer(self, pb, tmp_path):
        app_js = tmp_path / 'app.js'
        # act() is a top-level function; the harness needs a handle on it.
        app_js.write_text(
            _served_js(pb).replace('\nfunction act(', '\nglobal.act = function act('))
        harness = tmp_path / 'harness.js'
        harness.write_text(self.HARNESS)
        r = subprocess.run(['node', str(harness), str(app_js)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
        assert out['timers'] == 1, f"{out['timers']} poll chains after 26 clicks"
        # 26 click-kicks + ~10 scheduled polls.  The old code issued 296.
        assert out['requests'] < 60, out

    def test_only_one_place_arms_the_timer(self, pb):
        """Structural, so it still guards where node is unavailable."""
        code = '\n'.join(line for line in _served_js(pb).split('\n')
                         if not line.strip().startswith('//'))
        assert code.count('setTimeout(poll') == 1
        assert 'clearTimeout' in code
