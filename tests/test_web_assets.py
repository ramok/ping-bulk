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
