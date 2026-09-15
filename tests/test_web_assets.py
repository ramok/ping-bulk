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
  location:{href:''},
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
  appendChild(){},setAttribute(){},getAttribute:()=>null,replaceChildren(){},
  addEventListener(){},focus(){},remove(){},classList:{add(){},remove(){},toggle(){}}});
global.document={getElementById:(i)=>(i==='sort'?sel:mk()),createElement:mk,
  createTextNode:(t)=>({textContent:t}),addEventListener(){},body:mk(),
  activeElement:null,documentElement:{setAttribute(){},getAttribute:()=>null,
  removeAttribute(){}},querySelectorAll:()=>[]};
global.window={setTimeout(){return 0;},clearTimeout(){},addEventListener(){},
  location:{href:''},localStorage:{getItem:()=>null,setItem(){}},
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
  location:{href:''},
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
  location:{href:''},
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
