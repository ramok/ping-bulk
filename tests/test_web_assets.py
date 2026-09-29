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
import os
import re
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
  addEventListener(){}, location: {href: '', reload(){ global.__reloaded = (global.__reloaded||0)+1; }},
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
  addEventListener(){}, location: {href: '', reload(){ global.__reloaded = (global.__reloaded||0)+1; }},
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
                     style: {setProperty(){}, removeProperty(){}},
                     querySelector: () => null, getBoundingClientRect: () => ({width: 0}),
                     clientWidth: 0,
                     appendChild(c) { this.children.push(c); },
                     addEventListener(){},
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
  location: {href: '', reload(){ global.__reloaded = (global.__reloaded||0)+1; }},
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
        # The property is the *difference*: a folded section gets one child
        # more than an open one, and that child is the strip.  Asserting the
        # totals instead (3 and 2) pinned the row's whole shape, so adding the
        # fold marker broke a test that had no opinion about markers.
        assert out['folded'] == out['open'] + 1, out
        assert out['open'] >= 2, out        # at least the name and the badge


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


class TestPerViewerSortAndColumns:
    """Ordering the list and putting a column away are this browser's too.

    Sorting hides the section headers, which is what the terminal does: a
    section says where a host sits in the configured order, so once the rows
    are in a different order it describes an arrangement no longer on screen
    (``_get_visible_entry_indices`` -- a section is visible only while
    ``sort_by`` is ``'none'``).
    """

    RUNNER = r'''
const sel = {value: 'none', addEventListener(){}};
let store = JSON.parse(process.env.PREFS || '{}');
// Every DOM member the client actually touches, enumerated from the source
// rather than discovered one TypeError at a time: document.{activeElement,
// addEventListener, createElement, createTextNode, documentElement,
// getElementById, querySelectorAll} and element.{addEventListener,
// appendChild, classList, focus, getAttribute, remove, replaceChildren,
// setAttribute}.  A stub thin enough to throw is a stub that can also pass a
// broken client.
const mk = () => ({className:'', textContent:'', children:[], type:'', value:'',
                   hidden:false,
                   appendChild(c){this.children.push(c);}, setAttribute(){},
                   getAttribute:()=>null, replaceChildren(...k){this.children=k;},
                   addEventListener(){}, focus(){}, remove(){},
                   classList:{add(){},remove(){},toggle(){}}});
const colBar = mk();
global.document = {
  getElementById: (id) => (id === 'sort' ? sel : (id === 'col-bar' ? colBar : mk())),
  createElement: mk, createTextNode: (t) => ({textContent: t}),
  addEventListener(){}, body: mk(), activeElement: null,
  documentElement: {setAttribute(){}, getAttribute:()=>null, removeAttribute(){}},
  querySelectorAll: () => [],
};
global.window = { setTimeout(){return 0;}, clearTimeout(){}, addEventListener(){},
  location:{href:'',reload(){global.__reloaded=(global.__reloaded||0)+1;}},
  localStorage:{getItem:(k)=>(k in store ? store[k] : null), setItem(k,v){store[k]=v;}},
  matchMedia: () => ({matches:false}) };
global.fetch = () => Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
require(process.argv[2]);
const rows = [
  {kind:'section', title:'S1', level:1, badge:[], history:'', hist_class:[]},
  {kind:'host', uid:'d', name:'delta',   alive:true,  down:false, latency:50, stats:{}, stat_class:{}, history:'', hist_class:[]},
  {kind:'host', uid:'a', name:'alpha',   alive:false, down:true,  latency:null, stats:{}, stat_class:{}, history:'', hist_class:[]},
  {kind:'host', uid:'c', name:'charlie', alive:true,  down:false, paused:true, latency:5, stats:{}, stat_class:{}, history:'', hist_class:[]},
  {kind:'host', uid:'b', name:'bravo',   alive:true,  down:false, latency:12, stats:{}, stat_class:{}, history:'', hist_class:[]},
];
const label = (r) => (r.kind === 'section' ? '[' + r.title + ']' : r.name);
const order = (v) => { sel.value = v; return global.sortRows(rows).map(label); };
const result = {
  none: order('none'), name: order('name'),
  status: order('status'), latency: order('latency'),
  source: rows.map(label),
};
sel.value = 'none';
global.buildColBar(['Last', 'Avg', 'StDev']);
result.colButtons = colBar.children.map((b) => b.textContent);
const statRow = {kind:'host', uid:'x', name:'x', down:false, stats:{Last:'1', Avg:'2'},
                 stat_class:{}, history:'', hist_class:[]};
const statsOf = (el) => {
  const s = el.children.find((c) => c.className === 'stats');
  return s ? s.children.length : -1;
};
result.statsShown = statsOf(global.hostRow(statRow, 1));
console.log(JSON.stringify(result));
'''

    def _run(self, pb, tmp_path, prefs=None):
        app_js = tmp_path / 'app.js'
        app_js.write_text(_served_js(pb)
                          .replace('\nfunction sortRows(', '\nglobal.sortRows = function sortRows(')
                          .replace('\nfunction hostRow(', '\nglobal.hostRow = function hostRow(')
                          .replace('\nfunction buildColBar(', '\nglobal.buildColBar = function buildColBar('))
        runner = tmp_path / 'run.js'
        runner.write_text(self.RUNNER)
        env = dict(os.environ)
        if prefs:
            env['PREFS'] = json.dumps({'ping-bulk.view': json.dumps(prefs)})
        r = subprocess.run(['node', str(runner), str(app_js)],
                           capture_output=True, text=True, timeout=60, env=env)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_none_keeps_the_configured_order_and_the_sections(self, pb, tmp_path):
        out = self._run(pb, tmp_path)
        assert out['none'] == ['[S1]', 'delta', 'alpha', 'charlie', 'bravo']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_sorting_drops_the_section_headers(self, pb, tmp_path):
        out = self._run(pb, tmp_path)
        assert out['name'] == ['alpha', 'bravo', 'charlie', 'delta']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_status_matches_the_terminal_and_leads_with_what_is_up(self, pb, tmp_path):
        """get_sorted_monitors keys on (m.alive is not True, m.host), so False
        sorts first and the hosts that are up lead.

        'What is broken first' is a reasonable thing to want from this word,
        and it is what I wrote before checking -- but the browser and the
        terminal answering the same word in opposite orders is the failure
        this file keeps finding.  Changing it means changing both.
        """
        out = self._run(pb, tmp_path)
        assert out['status'] == ['bravo', 'charlie', 'delta', 'alpha']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_paused_is_not_a_rank_of_its_own(self, pb, tmp_path):
        """charlie is paused and up; the terminal does not separate it, so
        neither does this -- it sorts among the other up hosts by name."""
        out = self._run(pb, tmp_path)
        assert out['status'].index('charlie') == 1

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_host_with_no_reading_sorts_last_by_latency(self, pb, tmp_path):
        """It has not answered, which is not the same as being fast."""
        out = self._run(pb, tmp_path)
        assert out['latency'] == ['charlie', 'bravo', 'delta', 'alpha']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_sorting_does_not_reorder_the_snapshot(self, pb, tmp_path):
        """sort() is in place and rows belongs to lastState, which is re-read
        on every poll -- sorting it would make the order depend on how many
        times the page had drawn."""
        out = self._run(pb, tmp_path)
        assert out['source'] == ['[S1]', 'delta', 'alpha', 'charlie', 'bravo']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_the_column_bar_comes_from_the_payload(self, pb, tmp_path):
        """A viewer may hide a column the terminal shows, not add one it is
        not computing."""
        out = self._run(pb, tmp_path)
        assert out['colButtons'] == ['Last', 'Avg', 'StDev']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_all_columns_render_by_default(self, pb, tmp_path):
        assert self._run(pb, tmp_path)['statsShown'] == 2

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_hidden_column_is_not_rendered(self, pb, tmp_path):
        out = self._run(pb, tmp_path, prefs={'col.Avg': True})
        assert out['statsShown'] == 1


class TestTheBrowserSortsLikeTheTerminal:
    """The same word must not mean two orders.

    ``sortRows`` in the client and ``get_sorted_monitors`` in the terminal are
    two implementations of one rule, which is exactly the shape §9d keeps
    finding wrong -- and it was wrong here first: ``status`` was written to put
    what is broken at the top, while the terminal keys on
    ``(m.alive is not True, m.host)`` and leads with what is up.  A structural
    test cannot catch that.  Running both over the same hosts can.
    """

    HOSTS = [('delta', True, 50.0), ('alpha', False, None), ('charlie', True, 5.0),
             ('bravo', True, 12.0), ('Echo', None, None), ('foxtrot', False, 3.0)]

    RUNNER = r'''
const sel = {value:'none', addEventListener(){}};
const mk = () => ({className:'',textContent:'',children:[],value:'',hidden:false,
                   style:{setProperty(){},removeProperty(){}},
                   querySelector:()=>null, getBoundingClientRect:()=>({width:0}),
                   clientWidth:0,
  appendChild(){},setAttribute(){},getAttribute:()=>null,replaceChildren(){},
  addEventListener(){},focus(){},remove(){},classList:{add(){},remove(){},toggle(){}}});
global.document={getElementById:(i)=>(i==='sort'?sel:mk()),createElement:mk,
  createTextNode:(t)=>({textContent:t}),addEventListener(){},body:mk(),
  activeElement:null,documentElement:{setAttribute(){},getAttribute:()=>null,
  removeAttribute(){}},querySelectorAll:()=>[]};
global.window={setTimeout(){return 0;},clearTimeout(){},addEventListener(){},
  location:{href:'',reload(){global.__reloaded=(global.__reloaded||0)+1;}},localStorage:{getItem:()=>null,setItem(){}},
  matchMedia:()=>({matches:false})};
global.fetch=()=>Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
require(process.argv[2]);
const rows = JSON.parse(require('fs').readFileSync(process.argv[3],'utf8'));
const got = {};
['name','status','latency'].forEach((h)=>{ sel.value=h;
  got[h]=global.sortRows(rows).map(r=>r.name); });
console.log(JSON.stringify(got));
'''

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_all_three_orders_agree(self, pb, tmp_path):
        from unittest.mock import patch
        cfg = tmp_path / 'cfg'
        cfg.write_text('')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([('host', n) for n, _a, _l in self.HOSTS])
        for m, (_n, alive, lat) in zip(app.monitors, self.HOSTS):
            m.alive, m.latency = alive, lat

        rows = tmp_path / 'rows.json'
        rows.write_text(json.dumps([
            {'kind': 'host', 'name': n, 'alive': a, 'latency': l,
             'down': a is False}
            for n, a, l in self.HOSTS]))
        app_js = tmp_path / 'app.js'
        app_js.write_text(_served_js(pb).replace(
            '\nfunction sortRows(', '\nglobal.sortRows = function sortRows('))
        runner = tmp_path / 'run.js'
        runner.write_text(self.RUNNER)
        r = subprocess.run(['node', str(runner), str(app_js), str(rows)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        browser = json.loads(r.stdout.strip().splitlines()[-1])

        for how in ('name', 'status', 'latency'):
            app.sort_by = how
            terminal = [m.host for m in app.get_sorted_monitors()]
            assert browser[how] == terminal, (
                f"':sort {how}' disagrees\\n"
                f'  terminal: {terminal}\\n  browser : {browser[how]}')

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_case_is_compared_by_code_point_as_python_does(self, pb, tmp_path):
        """localeCompare folds case and accents; Python's sorted() does not.
        'Echo' before 'alpha' is the cheapest witness."""
        from unittest.mock import patch
        cfg = tmp_path / 'cfg'
        cfg.write_text('')
        with patch.object(pb, '_config_path', return_value=str(cfg)):
            app = pb.Application([('host', n) for n, _a, _l in self.HOSTS])
        app.sort_by = 'name'
        terminal = [m.host for m in app.get_sorted_monitors()]
        assert terminal.index('Echo') < terminal.index('alpha')


class TestTheViewControlsActuallyPersist:
    """Each control has to write its choice, read it back, and not churn.

    None of these had a test: a mutation removing the column button's write,
    the sort's write, the sort's read-back, or the column bar's rebuild guard
    each left the whole suite green.  The first means a click silently does
    nothing; the last rebuilds the bar on every two-second poll, throwing away
    the buttons and the focus of anyone tabbing through them.
    """

    RUNNER = r"""
const sel = {value:'none', addEventListener(_e, fn){ sel.fire = fn; }};
let store = JSON.parse(process.env.PREFS || '{}');
const clicks = [];
const mk = () => ({className:'',textContent:'',children:[],value:'',hidden:false,
                   style:{setProperty(){},removeProperty(){}},
                   querySelector:()=>null, getBoundingClientRect:()=>({width:0}),
                   clientWidth:0,
  appendChild(c){this.children.push(c);},setAttribute(){},getAttribute:()=>null,
  replaceChildren(...k){this.children=k;},
  addEventListener(_e, fn){ clicks.push({el:this, fn:fn}); },
  focus(){},remove(){},classList:{add(){},remove(){},toggle(){}}});
const colBar = mk();
global.document={getElementById:(i)=>(i==='sort'?sel:(i==='col-bar'?colBar:mk())),
  createElement:mk,createTextNode:(t)=>({textContent:t}),addEventListener(){},
  body:mk(),activeElement:null,
  documentElement:{setAttribute(){},getAttribute:()=>null,removeAttribute(){}},
  querySelectorAll:()=>[]};
global.window={setTimeout(){return 0;},clearTimeout(){},addEventListener(){},
  location:{href:'',reload(){global.__reloaded=(global.__reloaded||0)+1;}},
  localStorage:{getItem:(k)=>(k in store?store[k]:null),setItem(k,v){store[k]=v;}},
  matchMedia:()=>({matches:false})};
global.fetch=()=>Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
require(process.argv[2]);
const out = {sortOnLoad: sel.value};
global.buildColBar(['Last','Avg']);
const first = colBar.children.slice();
global.buildColBar(['Last','Avg']);
out.barRebuilt = colBar.children.some((c, i) => c !== first[i]);
global.buildColBar(['Last','Avg','StDev']);
out.barGrew = colBar.children.length === 3;
global.buildColBar(['a\u0001b']);
const joined = colBar.children.map((b) => b.textContent);
global.buildColBar(['a','b']);
out.collision = {first: joined, second: colBar.children.map((b) => b.textContent)};
global.buildColBar(['Last','Avg']);
const hit = clicks.filter((c) => colBar.children.indexOf(c.el) === 0).pop();
if (hit) { hit.fn(); }
sel.value = 'latency';
if (sel.fire) { sel.fire(); }
out.store = store;
console.log(JSON.stringify(out));
"""

    def _run(self, pb, tmp_path, prefs=None):
        app_js = tmp_path / 'app.js'
        app_js.write_text(_served_js(pb).replace(
            chr(10) + 'function buildColBar(',
            chr(10) + 'global.buildColBar = function buildColBar('))
        runner = tmp_path / 'run.js'
        runner.write_text(self.RUNNER)
        env = dict(os.environ)
        env.pop('PREFS', None)
        if prefs:
            env['PREFS'] = json.dumps({'ping-bulk.view': json.dumps(prefs)})
        r = subprocess.run(['node', str(runner), str(app_js)],
                           capture_output=True, text=True, timeout=60, env=env)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_hiding_a_column_is_written_down(self, pb, tmp_path):
        stored = json.loads(self._run(pb, tmp_path)['store']['ping-bulk.view'])
        assert stored.get('col.Last') is True

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_choosing_a_sort_is_written_down(self, pb, tmp_path):
        stored = json.loads(self._run(pb, tmp_path)['store']['ping-bulk.view'])
        assert stored.get('sort') == 'latency'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_stored_sort_is_applied_on_load(self, pb, tmp_path):
        out = self._run(pb, tmp_path, prefs={'sort': 'status'})
        assert out['sortOnLoad'] == 'status'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_an_unchanged_column_list_does_not_rebuild_the_bar(self, pb, tmp_path):
        """Rebuilding on every poll would discard the buttons twice a second,
        taking the focus of anyone tabbing through them with it."""
        out = self._run(pb, tmp_path)
        assert out['barRebuilt'] is False
        assert out['barGrew'] is True, 'but a real change must still rebuild'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_separator_inside_a_column_name_cannot_hide_a_change(self, pb, tmp_path):
        """':probe --label' lets the operator choose the name, so no character
        is safe to join on."""
        out = self._run(pb, tmp_path)
        assert out['collision']['second'] == ['a', 'b'], out['collision']


class TestTheStatColumnsLineUp:
    """Every cell in a column is the same width, and that width fits it.

    The stats block used to be a plain flex row of content-sized cells, so a
    column's left edge sat wherever the previous column's *value* happened to
    end — different on every row, for the same column.  With ':set stats
    gpsall,rtime,drift,down,last,avg,stdev' on a real 64-host file that made
    seven ragged columns out of seven.

    The width is measured over the whole visible list **before** any row is
    built.  Measuring inside ``hostRow`` is the obvious shortcut and does not
    work: the rows already emitted keep the narrower width until the next poll,
    which is the raggedness this exists to remove.  The mutation test for that
    is ``test_measuring_per_row_would_not_line_them_up``.
    """

    RUNNER = r'''
let store = JSON.parse(process.env.PREFS || '{}');
const mk = () => ({className:'', textContent:'', children:[], type:'', value:'',
                   hidden:false, attrs:{},
                   style:{setProperty(){}, removeProperty(){}},
                   querySelector:()=>null, getBoundingClientRect:()=>({width:0}),
                   clientWidth:0,
                   appendChild(c){this.children.push(c); return c;},
                   setAttribute(k,v){this.attrs[k]=v;},
                   getAttribute(k){return this.attrs[k]===undefined?null:this.attrs[k];},
                   replaceChildren(...k){this.children=k;},
                   addEventListener(){}, focus(){}, remove(){},
                   classList:{add(){},remove(){},toggle(){}}});
const byId = {};
global.document = {
  getElementById: (id) => (byId[id] || (byId[id] = mk())),
  createElement: mk, createTextNode: (t) => ({textContent: t}),
  addEventListener(){}, body: mk(), activeElement: null,
  documentElement: {setAttribute(){}, getAttribute:()=>null, removeAttribute(){}},
  querySelectorAll: () => [],
};
global.window = { setTimeout(){return 0;}, clearTimeout(){}, addEventListener(){},
  location:{href:'',reload(){global.__reloaded=(global.__reloaded||0)+1;}},
  localStorage:{getItem:(k)=>(k in store ? store[k] : null), setItem(k,v){store[k]=v;}},
  matchMedia: () => ({matches:false}) };
global.fetch = () => Promise.resolve({ok:true,status:200,json:()=>Promise.resolve({})});
require(process.argv[2]);

// Deliberately ragged input: the same column carries a 1-character reading on
// one host and a 13-character one on another, and the short one comes first.
const host = (uid, gps, last) => ({
  kind:'host', uid: uid, name: uid, down:false, cell_width:1,
  stats:{'GPS s/off/sat': gps, 'Last': last}, stat_class:{},
  history:'...', hist_class:[]});
const state = {
  time: 0, generation: 1, commands:'read-only', columns:['GPS s/off/sat','Last'],
  view:{cell_width:1}, down:[], events:[],
  rows:[host('a','-','5.0'), host('b','0/0/28','120.5'), host('c','12/3/7','7.25')],
};
global.render(state);

const widths = {}, tooNarrow = [];
for (const row of byId['rows'].children) {
  const stats = row.children.find((c) => c.className === 'stats');
  if (!stats) { continue; }
  for (const cell of stats.children) {
    const label = cell.children[0].textContent;
    const value = cell.children[1].textContent;
    const got = Number(cell.getAttribute('data-w'));
    (widths[label.trim()] = widths[label.trim()] || []).push(got);
    if (label.length + value.length > got) {
      tooNarrow.push(label + value + ' needs ' + (label.length + value.length)
                     + ' got ' + got);
    }
  }
}
const distinct = {};
Object.keys(widths).forEach((k) => { distinct[k] = [...new Set(widths[k])]; });
console.log(JSON.stringify({distinct: distinct, tooNarrow: tooNarrow,
                            cells: Object.keys(widths).length}));
'''

    def _run(self, pb, tmp_path):
        app_js = tmp_path / 'app.js'
        app_js.write_text(_served_js(pb).replace(
            '\nfunction render(', '\nglobal.render = function render('))
        runner = tmp_path / 'run.js'
        runner.write_text(self.RUNNER)
        r = subprocess.run(['node', str(runner), str(app_js)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_column_has_one_width_on_every_row(self, pb, tmp_path):
        out = self._run(pb, tmp_path)
        for name, seen in out['distinct'].items():
            assert len(seen) == 1, f'{name} drew at widths {seen}'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_the_width_fits_the_widest_reading(self, pb, tmp_path):
        """Equal widths that clip the value would pass the test above."""
        out = self._run(pb, tmp_path)
        assert out['tooNarrow'] == [], out['tooNarrow']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_measuring_per_row_would_not_line_them_up(self, pb, tmp_path):
        """The shortcut this design exists to avoid, run for real.

        ``measureColumns`` is moved inside the row builder — the obvious place
        — and the first row, which carries the short reading, keeps the narrow
        width while the later ones widen.
        """
        app_js = tmp_path / 'app.js'
        src = _served_js(pb).replace(
            '\nfunction render(', '\nglobal.render = function render(')
        assert '  measureColumns(shown);\n' in src
        src = src.replace('  measureColumns(shown);\n', '')
        old = "  var stats = document.createElement('span');\n  stats.className = 'stats';"
        assert src.count(old) == 1
        src = src.replace(old, old + '\n  measureColumns([r]);', 1)
        app_js.write_text(src)
        runner = tmp_path / 'run.js'
        runner.write_text(self.RUNNER)
        r = subprocess.run(['node', str(runner), str(app_js)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
        ragged = [n for n, seen in out['distinct'].items() if len(seen) > 1]
        assert ragged, 'the mutation must actually go ragged, or the test above proves nothing'


class TestTheDetailPaneSitsUnderItsHost:
    """It used to be a section after the whole list.

    With fifty hosts, clicking one near the top put the answer off the bottom
    of the page — the click appeared to do nothing until you scrolled.
    """

    def test_it_is_placed_in_the_row_list(self, pb):
        js = _served_js(pb)
        assert 'built.push(detailWrap)' in js, \
            'the pane is inserted among the rows, not left as a page section'

    def test_it_follows_the_selected_host(self, pb):
        js = _served_js(pb)
        assert "r.uid === selectedUid" in js

    def test_the_same_node_is_moved_rather_than_rebuilt(self, pb):
        """The row list is cleared every poll. A rebuilt pane would blank
        until the next fetch returned; re-parenting the existing node keeps
        its text, and is why no second fetch is needed."""
        js = _served_js(pb)
        assert 'detailWrap = document.getElementById' in js
        # Nothing may create a second details element.
        assert js.count("createElement('section')") == 0

    def test_opening_one_places_it_immediately(self, pb):
        """Without this the pane appears in its old place until the next poll,
        up to a full interval later."""
        js = _served_js(pb)
        detail = js[js.index('function showDetail'):js.index('function num(')]
        assert 'place()' in detail


class TestTheListIsDense:
    """The user's ask: see as many hosts at once as possible."""

    def test_rows_are_tighter_than_the_original_five_pixels(self, pb):
        css = pb._WEB_CSS
        block = css[css.index('.row { display: flex'):]
        block = block[:block.index('}')]
        assert 'padding: 1px 8px' in block, block

    def test_the_filter_shares_the_heading_line(self, pb):
        """A full-width box above the rows cost a whole row of hosts."""
        assert '<div class="head">' in pb._WEB_HTML
        css = pb._WEB_CSS
        assert '.head { display: flex' in css
        assert '.head h2 { margin: 0' in css

    def test_the_filter_no_longer_reserves_a_line_of_its_own(self, pb):
        css = pb._WEB_CSS
        block = css[css.index('#filter {'):]
        block = block[:block.index('}')]
        assert 'width: 100%' not in block, block
        assert 'margin-bottom' not in block, block


class TestTheMeasuredWidthIsAskedForAtOnce:
    """The correction must not wait out a poll interval.

    ``measureCols`` runs from ``render()``, which runs inside ``poll()``'s
    promise chain — and that chain's tail arms the next poll. Since
    ``schedulePoll`` clears whatever is pending first, a timer armed inside
    ``measureCols`` was cancelled a moment later by the tail, and the measured
    width arrived a full ``POLL_MS`` after the page had already drawn the
    server's default. The page looked right eventually, so no string-matching
    test could see it; this one runs the real client under a virtual clock and
    watches *when* the second request goes out.
    """

    HARNESS = r'''
let now = 0, timers = [], nextId = 1;
const urls = [];                 // [{at, url}] -- when, not just what
const CH = 7;                    // px per character in the probe's font
const STRIP_PX = 700;            // so 100 cells fit, against a default of 60
const mk = (tag) => ({
  tag: tag, className: '', textContent: '', children: [], value: '',
  hidden: false, attrs: {},
  style: {setProperty(){}, removeProperty(){}},
  appendChild(c) { this.children.push(c); return c; },
  removeChild(){}, remove(){},
  replaceChildren(...k) { this.children = k; },
  setAttribute(k, v) { this.attrs[k] = v; },
  getAttribute(k) { return this.attrs[k] === undefined ? null : this.attrs[k]; },
  addEventListener(){}, focus(){},
  classList: {add(){}, remove(){}, toggle(){}},
  // The font probe measures itself; a monospace face is CH per character.
  getBoundingClientRect() { return {width: this.textContent.length * CH}; },
  // Whatever the row list is asked for, hand back a strip of a known width.
  querySelector() { return {clientWidth: STRIP_PX,
                            getBoundingClientRect: () => ({width: STRIP_PX})}; },
  clientWidth: STRIP_PX,
});
const byId = {};
global.document = {
  getElementById: (id) => (byId[id] || (byId[id] = mk(id))),
  createElement: mk, createTextNode: (t) => ({textContent: t}),
  addEventListener(){}, body: mk('body'), activeElement: null,
  documentElement: {setAttribute(){}, getAttribute: () => null,
                    removeAttribute(){}},
  querySelectorAll: () => [],
};
const store = {};
global.window = {
  setTimeout(fn, ms) { const id = nextId++; timers.push({id, at: now + (ms||0), fn}); return id; },
  clearTimeout(id) { timers = timers.filter(t => t.id !== id); },
  addEventListener(){}, location: {href: '', reload(){ global.__reloaded = (global.__reloaded||0)+1; }},
  localStorage: {getItem: (k) => (k in store ? store[k] : null),
                 setItem(k, v) { store[k] = String(v); }},
  matchMedia: () => ({matches: false}),
};
global.setTimeout = global.window.setTimeout;
global.clearTimeout = global.window.clearTimeout;
global.fetch = (url) => {
  urls.push({at: now, url: String(url)});
  return Promise.resolve({ok: true, status: 200, json: () => Promise.resolve({
    rows: [{kind: 'host', uid: 'h1', name: 'h1', history: '.', hist_class: ['g-ok'],
            cell_width: 1, stats: {}, stat_class: {}, down: false, updown: '',
            paused: false, no_alarm: false}],
    down: [], events: [], time: 0, columns: [],
    view: {cell_width: 1, name_width: 8}, commands: 'safe', csrf: 'x'})});
};
const drain = async () => { for (let i = 0; i < 80; i++) await Promise.resolve(); };
const tick = async (ms) => {
  const end = now + ms;
  for (;;) {
    const due = timers.filter(t => t.at <= end).sort((a, b) => a.at - b.at)[0];
    if (!due) break;
    timers = timers.filter(t => t !== due);
    now = due.at; due.fn(); await drain();
  }
  now = end;
};
(async () => {
  require(process.argv[2]);
  await drain();
  await tick(300);              // well under one poll interval
  console.log(JSON.stringify({urls: urls, timers: timers.length}));
})();
'''

    @pytest.mark.skipif(shutil.which('node') is None,
                        reason='node not installed; this check needs a JS engine')
    def test_the_second_request_carries_cols_without_waiting(self, pb, tmp_path):
        app_js = tmp_path / 'app.js'
        app_js.write_text(_served_js(pb))
        harness = tmp_path / 'harness.js'
        harness.write_text(self.HARNESS)
        r = subprocess.run(['node', str(harness), str(app_js)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
        urls = out['urls']

        assert len(urls) >= 2, f'no correcting request inside 300 ms: {urls}'
        assert '?cols=' not in urls[0]['url'], 'nothing is measured yet'
        assert '?cols=100' in urls[1]['url'], urls
        # The whole point: it does not wait out POLL_MS (2000).
        assert urls[1]['at'] < 500, f"correction arrived at {urls[1]['at']}ms"

    def test_it_settles_rather_than_asking_again_every_poll(self, pb, tmp_path):
        """Once the width is known the request stops changing — otherwise the
        measure and the reply chase each other for the life of the page."""
        app_js = tmp_path / 'app.js'
        app_js.write_text(_served_js(pb))
        harness = tmp_path / 'harness.js'
        harness.write_text(self.HARNESS.replace('await tick(300);',
                                                'await tick(12000);'))
        r = subprocess.run(['node', str(harness), str(app_js)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
        # One chain, and every request after the correction asks for the same.
        assert out['timers'] == 1, out
        asked = [u['url'] for u in out['urls'][1:]]
        assert set(asked) == {'/api/state?cols=100'}, asked


class TestClickingTheOpenHostClosesIt:
    """Reported as: the pane opens, and clicking the same row opens it again."""

    RUNNER = r'''
let fetched = [];
const mk = () => { const o = {
  className:'', textContent:'', children:[], attrs:{}, listeners:{}, hidden:false,
  style:{setProperty(){},removeProperty(){}},
  appendChild(c){o.children.push(c); return c;}, replaceChildren(...k){o.children=k;},
  setAttribute(k,v){o.attrs[k]=v;}, getAttribute(k){return o.attrs[k]===undefined?null:o.attrs[k];},
  addEventListener(t,f){ (o.listeners[t] = o.listeners[t] || []).push(f); },
  classList:{names:[],add(...n){this.names.push(...n);},remove(){},toggle(){},
             contains(n){return this.names.indexOf(n)!==-1;}},
  querySelector(){return {clientWidth:700,
                          getBoundingClientRect:()=>({width:700})};},
  getBoundingClientRect(){return {width:(o.textContent||'').length*7};},
  removeChild(){}, clientWidth:700, tagName:'SPAN', remove(){}, focus(){}, value:'',
}; return o; };
global.document = {getElementById: mk, createElement: mk,
  createTextNode:(t)=>({textContent:t}), addEventListener(){}, body:mk(),
  documentElement:{setAttribute(){},getAttribute:()=>null,removeAttribute(){}},
  querySelectorAll:()=>[]};
global.window = {setTimeout:()=>0, clearTimeout(){}, addEventListener(){},
  location:{href:'',reload(){global.__reloaded=(global.__reloaded||0)+1;}}, localStorage:{getItem:()=>null,setItem(){}},
  matchMedia:()=>({matches:false})};
global.setTimeout = global.window.setTimeout;
global.clearTimeout = global.window.clearTimeout;
// A real state shape: the module-level poll() renders whatever this returns.
const STATE = {rows:[], down:[], events:[], time:0, columns:[],
               view:{cell_width:1, name_width:8}, commands:'safe', csrf:'x'};
global.fetch = (u) => { fetched.push(String(u));
  return Promise.resolve({ok:true, status:200,
                          json:()=>Promise.resolve(STATE)}); };
require(process.argv[2]);
const row = {kind:'host', uid:'h1', name:'h1', level:1, history:'.',
             hist_class:['g-ok'], cell_width:1, stats:{}, stat_class:{},
             down:false, updown:'', paused:false, no_alarm:false};
const fire = () => {
  const el = global.hostRow(row, 1);
  (el.listeners['click']||[]).forEach(f => f({target:{tagName:'SPAN'}}));
};
(async () => {
  fire(); await Promise.resolve();          // first click: opens
  const opened = global.readSelected();
  fetched = [];
  fire(); await Promise.resolve();          // second click on the same host
  console.log(JSON.stringify({opened: opened, closed: global.readSelected(),
                              refetched: fetched.length}));
})();
'''

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_second_click_closes_rather_than_reopening(self, pb, tmp_path):
        app_js = tmp_path / 'app.js'
        app_js.write_text(
            _served_js(pb).replace('\nfunction hostRow(', '\nglobal.hostRow = function hostRow(')
            + '\nglobal.readSelected = function () { return selectedUid; };\n')
        runner = tmp_path / 'run.js'
        runner.write_text(self.RUNNER)
        r = subprocess.run(['node', str(runner), str(app_js)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        out = json.loads(r.stdout.strip().splitlines()[-1])
        assert out['opened'] == 'h1', out
        assert out['closed'] == '', out
        assert out['refetched'] == 0, 'closing must not re-fetch the detail'


class TestFoldingNeedsNoPermission:
    """The marker used to be gated on ``canWrite`` and carried a message
    saying why it was inert — "sign in to fold sections" for an anonymous
    viewer, "web-commands is read-only" for a signed-in one.

    Both messages are gone because the condition is. Folding is a view choice
    made in this browser, so it needs no session: there is nothing left to
    explain, which is a better answer than explaining it well. A refusal
    nobody can see is this project's oldest recurring bug (AGENTS.md §9d) —
    and the cure that landed first, explaining the refusal, was still a
    refusal.
    """

    def test_no_message_survives(self, pb):
        js = _served_js(pb)
        assert 'sign in to fold sections' not in js
        assert 'web-commands is read-only' not in js

    def test_the_read_only_marker_style_went_with_it(self, pb):
        """A '.ro' marker that nothing applies is dead style the next reader
        would take for a live state."""
        marker = pb._WEB_JS[pb._WEB_JS.index('function sectionRow'):
                            pb._WEB_JS.index('function badge(')]
        assert "classList.add('ro')" not in marker


class TestAnAnonymousViewerCanStillSignIn:
    """``:set web-anonymous read-only`` makes ``/api/state`` answer 200, so the
    401 branch that used to be the only route to the sign-in form never fires.
    A viewer could watch the whole fleet with no hint that signing in offers
    anything — which is how "the fold does nothing and there are no events"
    was reported, twice."""

    def test_the_page_carries_a_sign_in_control(self, pb):
        assert 'id="signin"' in pb._WEB_HTML
        assert "signinBtn.addEventListener('click'" in _served_js(pb)

    def test_it_is_shown_only_to_anonymous_viewers(self, pb):
        assert 'signinBtn.hidden = !anonymous' in _served_js(pb)

    def test_a_successful_poll_no_longer_closes_the_form(self, pb):
        """showLogin(false) ran on every 200. With anonymous read that is the
        normal case, so the form shut a couple of seconds after the viewer
        opened it — the read succeeding is the whole point of the tier."""
        js = _served_js(pb)
        poll = js[js.index('function poll()'):]
        poll = poll[:poll.index('\n}')]
        assert 'showLogin(false)' not in poll, poll
        assert 'if (!anonymous) { showLogin(false); }' in js


class TestTheHostPaneFallsBackToTheTailItAlreadyHas:
    """A viewer with no session is sent no ``events`` for a host, and the pane
    used to end there — reported as the frame being cut off at the bottom.

    The fallback filters ``/api/state``'s tail, which that viewer already
    holds, by the category the server names in ``event_key``.  Two properties
    matter and both are asserted: the fallback fires when the field is absent,
    and it does **not** fire when it is present — a signed-in viewer must keep
    seeing the terminal's own, unfiltered list rather than a narrower one.
    """

    RUNNER = r'''
const mkEl = () => ({className: '', textContent: '', children: [], hidden: false,
                     style: {setProperty(){}, removeProperty(){}},
                     querySelector: () => null, getBoundingClientRect: () => ({width: 0}),
                     clientWidth: 0,
                     appendChild(c) { this.children.push(c); },
                     addEventListener(){},
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
  location: {href: '', reload(){ global.__reloaded = (global.__reloaded||0)+1; }},
  localStorage: {getItem: () => null, setItem(){}},
  matchMedia: () => ({matches: false}),
};
global.fetch = () => Promise.resolve({ok: true, status: 200,
                                      json: () => Promise.resolve({})});
require(process.argv[2]);

global.setLastState({events: [
  {level: 1, category: 'host-a', text: 'T   host-a is down', cls: ''},
  {level: 1, category: 'host-b', text: 'T   host-b is down', cls: ''},
  {level: 1, category: 'web',    text: 'T   web    a request', cls: ''},
]});

const base = {name: 'host-a', ip: null, cmd: '', connect: null, alive: true,
              error: null, uptime: null, downtime: null, tx: 0, rx: 0, xx: 0,
              loss_pct: null, lat_min: null, lat_max: null, lat_avg: null,
              lat_stdev: null, clock_offset_ms: null, clock_state: null,
              probes: [], event_key: 'host-a'};

const anon = global.detailText(Object.assign({}, base));
const auth = global.detailText(Object.assign({}, base,
                               {events: ['T   host-a said something else']}));
console.log(JSON.stringify({anon: anon, auth: auth}));
'''

    def _run(self, pb, tmp_path):
        app_js = tmp_path / 'app.js'
        # detailText reads lastState, which the poll assigns; nothing polls
        # here, so the harness needs a way in.
        app_js.write_text(_served_js(pb).replace(
            '\nfunction detailText(', '\nglobal.detailText = function detailText(')
            + '\nglobal.setLastState = function (s) { lastState = s; };\n')
        runner = tmp_path / 'run.js'
        runner.write_text(self.RUNNER)
        r = subprocess.run(['node', str(runner), str(app_js)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_viewer_with_no_events_field_gets_the_matching_tail(self, pb, tmp_path):
        out = self._run(pb, tmp_path)
        assert 'Recent events' in out['anon'], out['anon']
        assert 'host-a is down' in out['anon']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_the_fallback_takes_only_this_hosts_category(self, pb, tmp_path):
        """The whole tail is in hand, so selecting nothing would look like
        working code right up until a second host appeared in the pane."""
        out = self._run(pb, tmp_path)
        assert 'host-b' not in out['anon'], out['anon']
        assert 'a request' not in out['anon'], out['anon']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_supplied_events_field_wins(self, pb, tmp_path):
        """The server's list is the terminal's own and is not level-filtered;
        replacing it with the narrower tail would be a silent downgrade for
        the viewer who signed in to get it."""
        out = self._run(pb, tmp_path)
        assert 'said something else' in out['auth'], out['auth']
        assert 'is down' not in out['auth'], out['auth']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_the_narrower_list_says_that_it_is_narrower(self, pb, tmp_path):
        """Both panes are headed 'Recent events'; only one of them is the
        whole story, and a reader cannot tell the difference by looking."""
        out = self._run(pb, tmp_path)
        assert 'at this log level' in out['anon'], out['anon']
        assert 'at this log level' not in out['auth'], out['auth']


class TestAHostIsSteppedInFromItsOwnTitle:
    """The terminal puts a title at ``(level - 1) * 2`` columns and a host at
    ``level * 2`` (`ping-bulk` `draw_hosts`), so a host is always one step
    inside the header above it — including at level 1, where the title itself
    has no indent.

    Giving a host the *same* padding as a section at the same level — which is
    what shipped first — distinguishes nesting depth and loses the
    title-to-host step completely, so every host stood flush with its own
    header. That is the reported symptom half-fixed: right relative to other
    hosts, wrong relative to the thing it sits under.
    """

    STEP = 16   # px per terminal indent level

    def _rules(self, pb, kind):
        """{level: padding-px} for '.row.section.lvlN' or '.row.host.lvlN'."""
        pattern = (r'\.row\.%s\.lvl(\d)(?: \.name)? \{ padding-left: (\d+)px; \}'
                   % kind)
        return {int(lvl): int(px) for lvl, px in re.findall(pattern, pb._WEB_CSS)}

    def test_a_title_starts_one_step_left_of_its_hosts(self, pb):
        sections = self._rules(pb, 'section')
        hosts = self._rules(pb, 'host')
        assert sections and hosts, (sections, hosts)
        for level, host_px in sorted(hosts.items()):
            # A level-1 section has no rule at all, which is 0px.
            title_px = sections.get(level, 0)
            assert host_px - title_px == self.STEP, (
                'a level-%d host must sit one step inside its own title, not '
                'level with it: title %dpx, host %dpx'
                % (level, title_px, host_px))

    def test_the_levels_the_terminal_can_produce_are_all_covered(self, pb):
        """A host whose rule is missing falls back to no indent, which reads
        as "top level" — a wrong answer rather than a missing one."""
        hosts = self._rules(pb, 'host')
        assert min(hosts) == 1, 'a level-1 host is indented; the terminal does'
        assert set(hosts) == set(range(1, max(hosts) + 1)), sorted(hosts)

    def test_a_host_in_no_section_matches_no_rule(self, pb):
        """`_web_state` emits level 0 for those, and the class must carry it
        through rather than being coerced to 1 — otherwise the level-1 rule
        above would indent a host that sits under nothing."""
        assert "'row lvl' + r.level" in pb._WEB_JS, (
            'the host row class must use the level verbatim')
        assert '(r.level || 1)' not in pb._WEB_JS


class TestTheBrowserFoldsForItself:
    """The Python tests cover the payload; this covers the behaviour.

    Folding reaches no request, so nothing on the server can show that it
    works. What has to hold is that a click hides exactly the hosts the server
    said that section owns, and that the strip appears — the strip being the
    whole reason the rule stayed server-side.
    """

    RUNNER = r'''
const mkEl = () => ({className: '', textContent: '', children: [], hidden: false,
                     style: {setProperty(){}, removeProperty(){}},
                     querySelector: () => null, getBoundingClientRect: () => ({width: 0}),
                     clientWidth: 0,
                     appendChild(c) { this.children.push(c); },
                     addEventListener(type, fn) { (this.on = this.on || {})[type] = fn; },
                     setAttribute(){}, getAttribute: () => null,
                     classList: {add(){}, remove(){}}});
global.document = {
  // `value` matters: render() reads filterEl.value.trim().
  getElementById: () => Object.assign(mkEl(), {addEventListener(){},
                                               replaceChildren(){}, value: ''}),
  createElement: mkEl,
  addEventListener(){}, body: {}, documentElement: {
    setAttribute(){}, getAttribute: () => null, removeAttribute(){}},
  querySelectorAll: () => [],
};
global.window = {
  setTimeout(){ return 0; }, clearTimeout(){}, addEventListener(){},
  location: {href: '', reload(){ global.__reloaded = (global.__reloaded||0)+1; }},
  localStorage: {getItem: () => null, setItem(){}},
  matchMedia: () => ({matches: false}),
};
global.fetch = () => Promise.resolve({ok: true, status: 200,
                                      json: () => Promise.resolve({})});
require(process.argv[2]);

// One section owning two hosts, and a third host under nothing.
const section = {kind: 'section', uid: 'S', level: 1, title: 'S', folded: false,
                 badge: [{text: '2', cls: 'b-up'}],
                 history: '..........', hist_class: [], cell_width: 1};
const host = (uid, parent) => ({kind: 'host', uid: uid, parent: parent,
                                level: parent ? 1 : 0, name: uid, stats: {},
                                stat_class: {}, history: '.', hist_class: [],
                                cell_width: 1, updown: '', down: false});
const rows = [section, host('a', 'S'), host('b', 'S'), host('loose', null)];
const kinds = () => global.foldFilter(rows).map(r => r.uid);

const out = {open: kinds()};
// The click handler is what a viewer actually fires.
const row = global.sectionRow(section, 1);
out.markerOpen = row.children[0].children[0].textContent;
out.stripWhenOpen = row.children.length;
row.on.click({target: {tagName: 'DIV'}});
out.folded = kinds();
const row2 = global.sectionRow(section, 1);
out.markerFolded = row2.children[0].children[0].textContent;
out.stripWhenFolded = row2.children.length;
row2.on.click({target: {tagName: 'DIV'}});
out.reopened = kinds();
// A sorted payload carries NO section rows at all, and a terminal ':filter'
// drops the ones it does not match.  Neither may cost this viewer a fold.
global.setFolded('S', true);
global.render({rows: [host('a', 'S'), host('b', 'S')], down: [], events: [],
               columns: [], view: {}, time: 0, commands: 'read-only'});
out.survivesASortedPoll = global.isFolded(section);
// Bounded, so it cannot grow for the life of the browser profile.
for (var i = 0; i < 700; i++) { global.setFolded('s' + i, true); }
out.capped = Object.keys(global.foldStore()).length;
// 'S' is folded here, so this section draws a strip -- the case that has to
// line up with the host strips above and below it.
global.setFolded('S', true);
out.sectionBoxes = global.sectionRow(section, 1).children.map(c => c.className);
out.hostBoxes = global.hostRow(host('a', 'S'), 1).children.map(c => c.className);
out.markerParent = global.sectionRow(section, 1).children[0].children[0].className;
// The signed-in shape, which is the DEFAULT (':set web-commands safe') and
// the case the first cut of this fix left broken.
global.render({rows: [], down: [], events: [], columns: [], view: {},
               time: 0, commands: 'safe', csrf: 'x'});
out.sectionBoxesRW = global.sectionRow(section, 1).children.map(c => c.className);
out.hostBoxesRW = global.hostRow(host('a', 'S'), 1).children.map(c => c.className);
console.log(JSON.stringify(out));
'''

    def _run(self, pb, tmp_path):
        app_js = tmp_path / 'app.js'
        app_js.write_text(_served_js(pb) + '\n' + '\n'.join(
            'global.%s = %s;' % (n, n) for n in
            ('sectionRow', 'hostRow', 'foldFilter', 'isFolded', 'setFolded',
             'foldStore', 'render')
        ) + '\n')
        runner = tmp_path / 'run.js'
        runner.write_text(self.RUNNER)
        r = subprocess.run(['node', str(runner), str(app_js)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_click_hides_exactly_that_sections_hosts(self, pb, tmp_path):
        out = self._run(pb, tmp_path)
        assert out['open'] == ['S', 'a', 'b', 'loose']
        assert out['folded'] == ['S', 'loose'], (
            'folding must hide the section\'s own hosts and nothing else')
        assert out['reopened'] == ['S', 'a', 'b', 'loose'], 'and unfold again'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_the_marker_follows_this_browser_not_the_payload(self, pb, tmp_path):
        """`section.folded` stays false throughout — the payload is never
        rewritten, so a marker that tracked it could not move at all."""
        out = self._run(pb, tmp_path)
        assert out['markerOpen'] == '[-]'
        assert out['markerFolded'] == '[+]'

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_the_strip_appears_only_once_folded(self, pb, tmp_path):
        """The reason the summary rule stayed on the server: a locally folded
        section still gets the terminal's own strip rather than one the client
        worked out for itself."""
        out = self._run(pb, tmp_path)
        assert out['stripWhenFolded'] == out['stripWhenOpen'] + 1

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_poll_without_section_rows_does_not_clear_the_folds(self, pb, tmp_path):
        """The first cut dropped any uid the payload did not carry, which is
        the obvious way to bound the store and reads absence wrongly.

        A section is missing for reasons other than being gone: ``:set sort``
        emits no section rows at all and a terminal ``:filter`` drops the ones
        it does not match. Measured before the fix — two folded sections, one
        sorted poll, store empty — and this user's own config carries
        ``:set sort latency``, so it was one poll from happening.
        """
        out = self._run(pb, tmp_path)
        assert out['survivesASortedPoll'] is True, (
            'a poll carrying no section rows erased the viewer\'s folds')

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_the_store_is_bounded(self, pb, tmp_path):
        """Which is what the pruning was actually for, and a bound cannot
        misread why a row is absent."""
        out = self._run(pb, tmp_path)
        assert out['capped'] <= 500, out['capped']


class TestAFoldedSectionStripLinesUpWithTheHosts:
    """Reported as "when title is fold, ping history do not indented with host
    ping history".

    ``.strip`` is ``flex: 1 1 0``, so a section's strip and a host's strip
    begin in the same column only if everything before them is the same width.
    Three separate things made that false, and each would have been enough on
    its own: the section indented its whole **row** where a host indents inside
    its name cell; the fold marker was a sibling *before* the name, adding its
    width and a 12px gap to section rows only; and the badge took its natural
    width where a host's stat block takes seven columns.

    The terminal has always done this correctly — ``draw_hosts`` pads
    ``indent + '──' + marker + title`` into ``stat_col`` and right-aligns the
    badge inside ``stat_field_w`` — so this is the browser catching up, not a
    new rule.
    """

    def test_the_indent_is_inside_the_name_cell_for_both_kinds(self, pb):
        """Indenting the row moves the stats and the strip with it, which is
        exactly what a fixed name column exists to prevent."""
        css = pb._WEB_CSS
        assert not re.search(r'\.row\.section\.lvl\d\s*\{', css), (
            'a section must indent its name cell, not its whole row')
        for level in range(2, 7):
            assert '.row.section.lvl%d .name { padding-left:' % level in css

    def test_the_badge_takes_the_stat_field_width(self, pb):
        css = pb._WEB_CSS
        assert 'var(--stats-w' in css, 'the badge must span the stat field'
        assert '--stats-w' in pb._WEB_JS, 'and something must measure it'

    def test_the_stat_width_is_measured_from_a_host_row(self, pb):
        """Not from the section's own badge, which is the thing being sized,
        and not from the strip, which would oscillate."""
        assert "measureBox('.row.host .stats', '--stats-w')" in pb._WEB_JS
        assert "measureBox('.row.host .acts', '--acts-w')" in pb._WEB_JS

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_both_rows_put_the_same_boxes_before_the_strip(self, pb, tmp_path):
        """The structural half, and the one that actually fails when somebody
        appends a fourth child to one row kind and not the other."""
        out = TestTheBrowserFoldsForItself()._run(pb, tmp_path)
        assert out['sectionBoxes'] == ['name', 'badge', 'strip'], out['sectionBoxes']
        assert out['hostBoxes'] == ['name', 'stats', 'strip'], out['hostBoxes']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_the_marker_is_inside_the_name_cell(self, pb, tmp_path):
        """As a sibling it added its own width plus a gap to section rows and
        nothing to host rows.

        Asserting that the row's first box is ``name`` is what this did first,
        and it passes with the marker deleted entirely — it never looked at the
        marker. The class of the name cell's first child is the honest one.
        """
        out = TestTheBrowserFoldsForItself()._run(pb, tmp_path)
        assert out['markerParent'] == 'foldmark', out['markerParent']

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_it_holds_for_a_viewer_who_can_write(self, pb, tmp_path):
        """The first cut aligned the read-only case and left the default one
        broken: a host row grows an ``.acts`` box of two buttons between its
        name and its stats when ``canWrite``, and a section row had nothing
        there — about 118px, the same order as the bug being fixed. Anyone who
        signs in sees it, which is why asserting only the anonymous shape read
        as proof of something it did not cover.
        """
        out = TestTheBrowserFoldsForItself()._run(pb, tmp_path)
        assert out['hostBoxesRW'] == ['name', 'acts', 'stats', 'strip'], \
            out['hostBoxesRW']
        assert out['sectionBoxesRW'] == ['name', 'acts', 'badge', 'strip'], \
            out['sectionBoxesRW']

    def test_an_action_button_cannot_change_width_with_its_label(self, pb):
        """'pause' becomes 'resume' and 'quiet' becomes 'alarm'. Sized by its
        text, the button moves the stats and the strip of that row alone — so
        pausing one host took its strip out of line with every other host's,
        not just with the sections."""
        assert re.search(r'\.acts button \{[^}]*min-width:', pb._WEB_CSS), \
            'the labels swap, so the button needs a floor'


class TestTheStripsActuallyLineUpInABrowser:
    """The one test in this file that measures instead of inspecting.

    Two rounds of structural assertions — class names, CSS rule shapes, the
    order of boxes in each row — passed while the strips were still 17px
    apart, because *the boxes existed* was never the question. What matters is
    whether they are the same **width**, and only a layout engine knows that.
    Two causes survived both rounds and neither is visible in the shape of the
    markup:

    * ``.row`` sets ``padding: 1px 8px`` and ``.row.section`` overrode it with
      ``7px 0 1px``, so every section's content began 8px left of every host's.
    * ``--name-w`` is handed out in ``ch``, which is the width of ``0`` in the
      element's **own** font, and the section row was bold — so the same
      ``30ch`` came out 25px wider on a section than on a host. The fixed name
      column, the single thing keeping every row's strip in one place, was a
      different width for the two kinds of row.

    Measured, before: ``.name`` at 16px vs 24px, widths 292.23 vs 267.2, strip
    delta 17.03px. After: identical to the hundredth of a pixel.
    """

    PROBE = r'''
window.fetch = function () { return new Promise(function () {}); };
window.onerror = function (m, u, line) {
  document.title = 'R' + JSON.stringify({error: String(m) + ' @' + line}) + 'E';
};
'''

    MEASURE = r'''
var state = {
  time: 0, generation: 1, csrf: __CSRF__, commands: __CMD__,
  columns: ['GPS s/off/sat','RTime','Drift','Down','Last','Avg','StDev'],
  down: [], events: [],
  view: {name_width: 30, cell_width: 1, sort: 'none', dns: 'name+ip', sync: false},
  rows: [
    {kind:'section', uid:'S', level:1, title:'Comm mods', folded:true,
     badge:[{text:'3',cls:'b-up'},{text:'/',cls:''},{text:'1',cls:'b-down'}],
     history:'..........', hist_class:[], cell_width:1},
    {kind:'section', uid:'S2', level:1, title:'Cameras', folded:false,
     badge:[{text:'1',cls:'b-up'}],
     history:'..........', hist_class:[], cell_width:1},
    {kind:'host', uid:'h1', parent:'S2', level:1, name:'sh1-comm-mod',
     host:'10.0.0.1', ip:null, alive:true, paused:false, no_alarm:false,
     error:null, latency:1.2, updown:'1h', down:false,
     stats:{'GPS s/off/sat':'0/0/29','RTime':'1','Drift':'0','Down':'-',
            'Last':'1.2','Avg':'1.3','StDev':'0.1'},
     stat_class:{}, history:'..........', hist_class:[], cell_width:1}
  ]
};
function px(row, sel, what) {
  var e = row.querySelector(sel);
  if (!e) { return null; }
  var r = e.getBoundingClientRect();
  return Math.round((what === 'w' ? r.width : r.left) * 100) / 100;
}
try {
  render(state);
  var sec = document.querySelector('.row.section');
  var host = document.querySelector('.row.host');
  if (!sec || !host) { throw new Error('rows missing'); }
  document.title = 'R' + JSON.stringify({
    nameLeft:  [px(sec, '.name'), px(host, '.name')],
    nameWidth: [px(sec, '.name', 'w'), px(host, '.name', 'w')],
    stripLeft: [px(sec, '.strip'), px(host, '.strip')]
  }) + 'E';
} catch (e) {
  document.title = 'R' + JSON.stringify({error: 'render: ' + e.message}) + 'E';
}
'''

    def _measure(self, pb, tmp_path, commands, csrf):
        html = pb._WEB_HTML.replace(
            '<link rel="stylesheet" href="/static/app.css">',
            '<style>\n' + pb._WEB_CSS + '\n</style>')
        html = html.replace('<script src="/static/app.js"></script>', '')
        probe = (self.MEASURE.replace('__CMD__', json.dumps(commands))
                             .replace('__CSRF__', json.dumps(csrf)))
        html = html.replace(
            '</body>',
            '<script>' + self.PROBE + '</script>\n'
            '<script>' + pb._WEB_JS + '</script>\n'
            '<script>' + probe + '</script>\n</body>')
        page = tmp_path / 'page.html'
        page.write_text(html)
        # Its own profile directory: this must never touch the developer's
        # running browser or its session.
        r = subprocess.run(
            ['google-chrome', '--headless', '--no-sandbox', '--disable-gpu',
             '--window-size=1400,900',
             '--user-data-dir=' + str(tmp_path / 'chrome'),
             '--virtual-time-budget=4000', '--dump-dom', page.as_uri()],
            capture_output=True, text=True, timeout=180)
        found = re.search(r'R(\{.*?\})E</title>', r.stdout, re.S)
        assert found, 'no measurement came back:\n' + r.stdout[:600] + r.stderr[-600:]
        out = json.loads(found.group(1))
        assert 'error' not in out, out['error']
        return out

    @pytest.mark.skipif(shutil.which('google-chrome') is None,
                        reason='needs google-chrome to measure real layout')
    @pytest.mark.parametrize('commands,csrf', [('read-only', None), ('safe', 'tok')])
    def test_a_folded_section_strip_starts_where_a_hosts_does(
            self, pb, tmp_path, commands, csrf):
        """Both permission modes: the ``.acts`` box a signed-in viewer gets is
        one of the causes, so measuring only one mode proves half of it."""
        out = self._measure(pb, tmp_path, commands, csrf)
        sec, host = out['stripLeft']
        assert sec == host, (
            'a folded section\'s strip is %s px from the host\'s (%s vs %s) '
            'under commands=%r' % (round(sec - host, 2), sec, host, commands))

    @pytest.mark.skipif(shutil.which('google-chrome') is None,
                        reason='needs google-chrome to measure real layout')
    def test_the_name_column_is_one_width_for_both_row_kinds(self, pb, tmp_path):
        """``ch`` resolves against the element's own font, so a bold section
        row silently widened the column that exists to be fixed."""
        out = self._measure(pb, tmp_path, 'read-only', None)
        assert out['nameWidth'][0] == out['nameWidth'][1], out['nameWidth']
        assert out['nameLeft'][0] == out['nameLeft'][1], out['nameLeft']


class TestTheOpenTabReloadsItself:
    """The client half of the restart check."""

    RUNNER = r'''
const mkEl = () => ({className: '', textContent: '', children: [], hidden: false,
                     style: {setProperty(){}, removeProperty(){}},
                     querySelector: () => null, getBoundingClientRect: () => ({width: 0}),
                     clientWidth: 0,
                     appendChild(c) { this.children.push(c); },
                     addEventListener(){},
                     setAttribute(){}, getAttribute: () => null,
                     classList: {add(){}, remove(){}}});
global.document = {
  getElementById: () => Object.assign(mkEl(), {addEventListener(){},
                                               replaceChildren(){}, value: ''}),
  createElement: mkEl,
  addEventListener(){}, body: {}, documentElement: {
    setAttribute(){}, getAttribute: () => null, removeAttribute(){}},
  querySelectorAll: () => [],
};
global.__reloaded = 0;
global.window = {
  setTimeout(){ return 0; }, clearTimeout(){}, addEventListener(){},
  location: {href: '', reload(){ global.__reloaded++; }},
  localStorage: {getItem: () => null, setItem(){}},
  matchMedia: () => ({matches: false}),
};
global.fetch = () => Promise.resolve({ok: true, status: 200,
                                      json: () => Promise.resolve({})});
require(process.argv[2]);

const poll = (run) => global.render({
  rows: [], down: [], events: [], columns: [], view: {}, time: 0,
  commands: 'read-only', run: run});

const out = {};
poll('aaa'); poll('aaa'); poll('aaa');
out.sameRun = global.__reloaded;        // the normal case: never reload
poll('bbb');
out.afterRestart = global.__reloaded;   // exactly one reload
poll('bbb'); poll('bbb');
out.settled = global.__reloaded;        // and it does not keep firing
global.__reloaded = 0;
console.log(JSON.stringify(out));
'''

    def _run(self, pb, tmp_path):
        app_js = tmp_path / 'app.js'
        app_js.write_text(_served_js(pb) + '\nglobal.render = render;\n')
        runner = tmp_path / 'run.js'
        runner.write_text(self.RUNNER)
        r = subprocess.run(['node', str(runner), str(app_js)],
                           capture_output=True, text=True, timeout=60)
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout.strip().splitlines()[-1])

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_steady_program_never_reloads_the_page(self, pb, tmp_path):
        """The half that would be intolerable to get wrong: a page that
        reloads on its own every couple of seconds is worse than a stale one,
        and a first poll has no baseline to compare against."""
        assert self._run(pb, tmp_path)['sameRun'] == 0

    @pytest.mark.skipif(shutil.which('node') is None, reason='needs node')
    def test_a_new_run_id_reloads_once(self, pb, tmp_path):
        out = self._run(pb, tmp_path)
        assert out['afterRestart'] == 1, out
        assert out['settled'] == 1, (
            'the reload must not repeat while the answer keeps changing: '
            'a real page records the new id as its own baseline')
