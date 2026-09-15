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
const attrs = {};
const root = {
  setAttribute: (k, v) => { attrs[k] = v; },
  getAttribute: (k) => (k in attrs ? attrs[k] : null),
  removeAttribute: (k) => { delete attrs[k]; },
};
global.document = {
  getElementById: el, createElement: el, addEventListener(){}, body: el(),
  documentElement: root,
  // Array, not a NodeList: the client walks it with Array.prototype.forEach.
  querySelectorAll: () => [],
};
const store = {};
global.window = {
  setTimeout(fn, ms) { const id = nextId++; timers.push({id, at: now + (ms||0), fn}); return id; },
  clearTimeout(id) { timers = timers.filter(t => t.id !== id); },
  addEventListener(){}, location: {href: ''},
  localStorage: {
    getItem: (k) => (k in store ? store[k] : null),
    setItem: (k, v) => { store[k] = String(v); },
  },
  matchMedia: () => ({matches: false}),
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


class TestPerViewerState:
    """Theme and panel choices live in this browser and go nowhere else.

    The terminal's ':set' values are shared by every viewer and the console, so
    a person changing how they read the page would move somebody else's screen
    -- the same reasoning that already keeps the filter client-side.
    """

    STUB = r'''
const attrs = {};
const clicks = {};
const hidden = {};
const root = {
  setAttribute: (k, v) => { attrs[k] = v; },
  getAttribute: (k) => (k in attrs ? attrs[k] : null),
  removeAttribute: (k) => { delete attrs[k]; },
};
const mkButton = (id) => {
  const a = {};
  return {
    id,
    textContent: '',
    setAttribute: (k, v) => { a[k] = v; },
    getAttribute: (k) => (k in a ? a[k] : null),
    addEventListener: (_ev, fn) => { clicks[id] = fn; },
    appendChild(){}, replaceChildren(){},
    classList: {add(){}, remove(){}, toggle(){}},
  };
};
const buttons = {
  'theme-toggle': mkButton('theme-toggle'),
  'down': mkButton('down'),
  'events': mkButton('events'),
};
// data-panel is fixed markup; everything else falls through to whatever
// setAttribute stored, or the stub would hide the client's own writes.
const withPanel = (btn, name) => {
  const inner = btn.getAttribute;
  btn.getAttribute = (k) => (k === 'data-panel' ? name : inner(k));
};
withPanel(buttons['down'], 'down');
withPanel(buttons['events'], 'events');
const panelEl = (name) => ({
  get hidden() { return hidden[name]; },
  set hidden(v) { hidden[name] = v; },
  appendChild(){}, replaceChildren(){},
  classList: {add(){}, remove(){}, toggle(){}},
});
const generic = () => new Proxy(function(){}, {
  get: (t, k) => (k === 'value' ? '' :
                  k === 'classList' ? {add(){}, remove(){}, toggle(){}} :
                  k === 'hidden' ? false :
                  typeof k === 'string' && k.startsWith('add') ? () => {} : generic()),
  set: () => true, apply: () => generic(),
});
const byId = {
  'theme-toggle': buttons['theme-toggle'],
  'down-wrap': panelEl('down'),
  'events-wrap': panelEl('events'),
};
global.document = {
  getElementById: (id) => (id in byId ? byId[id] : generic()),
  createElement: generic, addEventListener(){}, body: generic(),
  documentElement: root,
  querySelectorAll: () => [buttons['down'], buttons['events']],
};
let store = {};
global.STORE_THROWS = false;
global.window = {
  setTimeout(){ return 0; }, clearTimeout(){},
  addEventListener(){}, location: {href: ''},
  localStorage: {
    getItem(k) { if (global.STORE_THROWS) { throw new Error('blocked'); }
                 return k in store ? store[k] : null; },
    setItem(k, v) { if (global.STORE_THROWS) { throw new Error('blocked'); }
                    store[k] = String(v); },
  },
  matchMedia: () => ({matches: global.SYSTEM_LIGHT === true}),
};
global.fetch = () => Promise.resolve({
  ok: true, status: 200, json: () => Promise.resolve({}),
});
global.seed = (obj) => { store = obj; };
global.peek = () => ({theme: attrs['data-theme'] || null,
                      label: buttons['theme-toggle'].textContent,
                      aria: buttons['theme-toggle'].getAttribute('aria-label'),
                      stored: store,
                      hiddenPanels: hidden,
                      pressed: {
                        down: buttons['down'].getAttribute('aria-pressed'),
                        events: buttons['events'].getAttribute('aria-pressed'),
                      }});
global.click = (id) => clicks[id]();
'''

    def _run(self, pb, tmp_path, script, presets=''):
        app_js = tmp_path / 'app.js'
        app_js.write_text(_served_js(pb))
        runner = tmp_path / 'run.js'
        runner.write_text(self.STUB + presets +
                          "\nrequire(process.argv[2]);\n" + script)
        r = subprocess.run(['node', str(runner), str(app_js)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_it_starts_dark_and_stores_nothing(self, pb, tmp_path):
        """Dark is the base, so an untouched page looks as it always has."""
        out = self._run(pb, tmp_path, 'console.log(JSON.stringify(peek()));')
        assert out['theme'] is None
        assert out['label'] == 'light', 'the button offers the other theme'
        assert out['stored'] == {}, 'looking at the page must not write'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_click_switches_and_remembers(self, pb, tmp_path):
        out = self._run(pb, tmp_path,
                        "click('theme-toggle'); console.log(JSON.stringify(peek()));")
        assert out['theme'] == 'light'
        assert out['label'] == 'dark', 'the button offers the other theme'
        assert out['aria'] == 'switch to the dark theme', \
            'the accessible name must describe the action, not claim a state'
        assert 'ping-bulk.view' in out['stored']
        assert json.loads(out['stored']['ping-bulk.view'])['theme'] == 'light'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_stored_choice_is_applied_on_load(self, pb, tmp_path):
        out = self._run(pb, tmp_path, 'console.log(JSON.stringify(peek()));',
                        presets='seed({"ping-bulk.view": "{\\"theme\\":\\"light\\"}"});')
        assert out['theme'] == 'light'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_the_system_preference_is_the_default(self, pb, tmp_path):
        """Asked in JS, so the light palette is written once.  Two copies of a
        palette drift, and the one nobody is looking at drifts first."""
        out = self._run(pb, tmp_path, 'console.log(JSON.stringify(peek()));',
                        presets='global.SYSTEM_LIGHT = true;')
        assert out['theme'] == 'light'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_stored_choice_beats_the_system(self, pb, tmp_path):
        out = self._run(pb, tmp_path, 'console.log(JSON.stringify(peek()));',
                        presets='global.SYSTEM_LIGHT = true;'
                                'seed({"ping-bulk.view": "{\\"theme\\":\\"dark\\"}"});')
        assert out['theme'] is None, 'dark is the absence of the attribute'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_blocked_storage_does_not_break_the_page(self, pb, tmp_path):
        """localStorage throws in a private window.  A viewer preference is not
        worth a dead page."""
        out = self._run(pb, tmp_path,
                        "click('theme-toggle'); console.log(JSON.stringify(peek()));",
                        presets='global.STORE_THROWS = true;')
        assert out['theme'] == 'light', 'the toggle still works'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_panels_start_shown(self, pb, tmp_path):
        out = self._run(pb, tmp_path, 'console.log(JSON.stringify(peek()));')
        assert out['pressed']['events'] == 'true'
        assert out['hiddenPanels'].get('events') is not True

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_hiding_a_panel_sticks(self, pb, tmp_path):
        out = self._run(pb, tmp_path,
                        "click('events'); console.log(JSON.stringify(peek()));")
        assert out['hiddenPanels']['events'] is True
        assert out['pressed']['events'] == 'false'
        assert json.loads(out['stored']['ping-bulk.view'])['panel.events'] is False

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_button_naming_no_panel_does_not_kill_the_page(self, pb, tmp_path):
        """applyPanel runs at module scope, before poll().

        A TypeError there leaves no polling, no render and -- in password mode
        -- no way to log in, because the login form is hidden in the HTML and
        only the script reveals it.  Part 2 of this work adds more view
        controls, so one button added without a matching entry is a live
        hazard rather than a hypothetical.
        """
        extra = ("global.document.querySelectorAll = () => ["
                 "  buttons['down'], buttons['events'],"
                 "  {getAttribute: (k) => (k === 'data-panel' ? 'nosuchpanel' : null),"
                 "   setAttribute(){}, addEventListener(){}}];")
        out = self._run(pb, tmp_path, 'console.log(JSON.stringify(peek()));',
                        presets=extra)
        assert out['theme'] is None, 'the page still ran to completion'


class TestTheSectionStripFollowsTheFold:
    """Only a folded section draws one, as the terminal does.

    An open section's hosts are already drawing their own strips underneath,
    so summarising them again on the header put a second, coarser answer
    directly above the real one.
    """

    RUNNER = r'''
// Each created element keeps its OWN children, so counting the row's does not
// also count the spans badge() appends inside its own wrapper.
const mkEl = () => ({className: '', textContent: '', children: [],
                     appendChild(c) { this.children.push(c); },
                     setAttribute(){}, getAttribute: () => null,
                     classList: {add(){}, remove(){}}});
global.document = {
  getElementById: () => Object.assign(mkEl(), {addEventListener(){},
                                               replaceChildren(){}}),
  createElement: mkEl,
  addEventListener(){}, body: {}, documentElement: {
    setAttribute(){}, getAttribute: () => null, removeAttribute(){}},
  querySelectorAll: () => [],
};
global.window = {
  setTimeout(){ return 0; }, clearTimeout(){}, addEventListener(){},
  location: {href: ''},
  localStorage: {getItem: () => null, setItem(){}},
  matchMedia: () => ({matches: false}),
};
global.fetch = () => Promise.resolve({ok: true, status: 200,
                                      json: () => Promise.resolve({})});
require(process.argv[2]);
const row = (folded) => ({kind: 'section', level: 1, title: 'S', folded: folded,
                          badge: [{text: '1', cls: 'b-up'}],
                          history: '..........', hist_class: [], cell_width: 1});
const count = (folded) => global.sectionRow(row(folded), 1).children.length;
console.log(JSON.stringify({folded: count(true), open: count(false)}));
'''

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_only_a_folded_section_gets_a_strip(self, pb, tmp_path):
        app_js = tmp_path / 'app.js'
        app_js.write_text(_served_js(pb).replace(
            '\nfunction sectionRow(', '\nglobal.sectionRow = function sectionRow('))
        runner = tmp_path / 'run.js'
        runner.write_text(self.RUNNER)
        r = subprocess.run(['node', str(runner), str(app_js)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
        # name + badge, plus the strip only when folded
        assert out['folded'] == 3, out
        assert out['open'] == 2, out


class TestBothPalettesDefineTheSameTokens:
    """A token defined in one palette and not the other is invisible.

    Light simply inherits the dark value -- a dark colour on a pale ground --
    and every class-level guard still passes, because the class does have a
    rule and the rule does reference a token.  The gap is one layer below
    ``test_every_class_the_server_emits_is_styled``.
    """

    @staticmethod
    def _tokens(css, selector):
        import re
        m = re.search(re.escape(selector) + r'\s*\{(.*?)\}', css, re.S)
        assert m, f'no {selector} block'
        return set(re.findall(r'(--[a-z-]+)\s*:', m.group(1)))

    def test_light_defines_every_token_dark_does(self, pb):
        css = pb._WEB_CSS
        dark = self._tokens(css, ':root')
        light = self._tokens(css, '[data-theme="light"]')
        assert dark - light == set(), f'light inherits dark for: {sorted(dark - light)}'
        assert light - dark == set(), f'light defines unused: {sorted(light - dark)}'

    def test_every_token_used_is_defined(self, pb):
        import re
        css = pb._WEB_CSS
        used = set(re.findall(r'var\((--[a-z-]+)\)', css))
        assert used - self._tokens(css, ':root') == set()
        assert used - self._tokens(css, '[data-theme="light"]') == set()

    def test_no_colour_escapes_the_palettes(self, pb):
        """A literal cannot be themed, which is why they became tokens."""
        import re
        css = pb._WEB_CSS
        outside = re.sub(r'(:root|\[data-theme="light"\])\s*\{.*?\}', '', css, flags=re.S)
        assert not re.findall(r'#[0-9a-fA-F]{3,8}\b', outside)
