"""Unit tests for Application._hint_text_width.

Verifies that the rendered column count matches what _draw_hint_text actually
draws — in particular that color annotations ([key:colorname]) are stripped
from the width calculation so overlay boxes are sized correctly.
"""
import pytest


def W(pb, text):
    return pb.Application._hint_text_width(text)


class TestHintTextWidth:
    def test_plain_text(self, pb):
        assert W(pb, "hello world") == len("hello world")

    def test_empty(self, pb):
        assert W(pb, "") == 0

    def test_simple_token_no_desc(self, pb):
        # [Enter] → '[' + 'Enter' + ']' = 7
        assert W(pb, "[Enter]") == 7

    def test_simple_token_with_desc(self, pb):
        # [Enter details] → '[' + 'Enter' + ' details' + ']' = 15
        assert W(pb, "[Enter details]") == 15

    def test_slash_keys(self, pb):
        # [q/Q quit] → '[' + 'q/Q' + ' quit' + ']' = 10
        assert W(pb, "[q/Q quit]") == 10

    def test_pipe_separator(self, pb):
        # [C|lear] → '[' + 'C' + 'lear' + ']' = 7  (pipe consumed, no space)
        assert W(pb, "[C|lear]") == 7

    def test_escaped_bracket(self, pb):
        # \[ outside token → literal '[', 1 char
        assert W(pb, r"\[hello") == 6  # '[' + 'hello'

    # ── Color annotation tests ──────────────────────────────────────────────

    def test_color_annotation_strips_colorname(self, pb):
        # [.:green = reply] raw len = 17
        # rendered: '[' + '.' + ' = reply' + ']' = 11
        raw = "[.:green = reply]"
        assert len(raw) == 17, "raw length sanity check"
        assert W(pb, raw) == 11

    def test_color_annotation_red(self, pb):
        # [X:red = timeout] raw len = 17
        # rendered: '[' + 'X' + ' = timeout' + ']' = 13
        raw = "[X:red = timeout]"
        assert len(raw) == 17
        assert W(pb, raw) == 13

    def test_color_annotation_brightred(self, pb):
        # [?:brightred = process error]
        # rendered: '[' + '?' + ' = process error' + ']' = 19
        assert W(pb, "[?:brightred = process error]") == 19

    def test_color_annotation_magenta(self, pb):
        # [>:magenta = ≥100 ms]
        # rendered: '[' + '>' + ' = ≥100 ms' + ']' = 13  (≥ is 1 char)
        assert W(pb, "[>:magenta = ≥100 ms]") == 13

    def test_word_color_annotation(self, pb):
        # [green:green fast (<50 ms)]
        # key = 'green' (5 chars after stripping ':green'), desc = ' fast (<50 ms)'
        # rendered: '[' + 'green' + ' fast (<50 ms)' + ']' = 21
        assert W(pb, "[green:green fast (<50 ms)]") == 21

    def test_unknown_color_not_stripped(self, pb):
        # [foo:unknown bar] — 'unknown' not in _HINT_KEY_COLORS → key stays 'foo:unknown'
        # rendered: '[' + 'foo:unknown' + ' bar' + ']' = 17
        assert W(pb, "[foo:unknown bar]") == 17

    def test_multiple_tokens_on_one_line(self, pb):
        # "  [.:green = reply]  [X:red = timeout]"
        # "  " (2) + 11 + "  " (2) + 13 = 28
        text = "  [.:green = reply]  [X:red = timeout]"
        assert W(pb, text) == 28

    def test_colored_width_less_than_raw(self, pb):
        # Any line with color annotations must be narrower than its raw length.
        raw = "  Symbols:  [.:green = reply]  [X:red = timeout]  [?:brightred = process error]  ' ' = no data"
        assert W(pb, raw) < len(raw)

    def test_legend_symbols_line_exact(self, pb):
        # Full legend line exact rendered width:
        # "  Symbols:  " (12)
        # + [.:green = reply] → 11
        # + "  " (2)
        # + [X:red = timeout] → 13
        # + "  " (2)
        # + [?:brightred = process error] → 19  ('[' + '?' + ' = process error' + ']')
        # + "  ' ' = no data" (15) … including the two spaces before "' '"
        # Total = 12 + 11 + 2 + 13 + 2 + 19 + 15 = 74
        raw = "  Symbols:  [.:green = reply]  [X:red = timeout]  [?:brightred = process error]  ' ' = no data"
        assert W(pb, raw) == 74


def S(pb, text, start=0, width=None):
    return pb.Application._hint_text_slice(text, start, width)


class TestHintTextSlice:
    """_hint_text_slice must cut by rendered columns, never raw characters.

    Regression: the help overlay measured lines with _hint_text_width (which
    strips ':colorname' markup) but cut them with plain string indexing, so any
    line carrying colour markup lost exactly the markup's length off its tail.
    """

    def test_plain_text_matches_string_slice(self, pb):
        assert S(pb, "hello world", 0, 5) == "hello"

    def test_no_width_returns_whole_string(self, pb):
        assert S(pb, "[C|lear] tail") == "[C|lear] tail"

    def test_full_width_is_lossless(self, pb):
        """Slicing to exactly the rendered width must keep every raw char."""
        text = "[1:tabactive Interactive] [2 Hosts file]"
        assert S(pb, text, 0, W(pb, text)) == text

    def test_colour_markup_not_counted_against_budget(self, pb):
        """The ':tabactive' annotation costs raw chars but no columns."""
        text = "[1:tabactive Interactive]"
        assert len(text) > W(pb, text)          # markup makes raw longer
        assert S(pb, text, 0, W(pb, text)) == text

    def test_slice_never_renders_wider_than_width(self, pb):
        text = "[a:green x] [b:red y] plain tail"
        for w in range(0, W(pb, text) + 2):
            assert W(pb, S(pb, text, 0, w)) <= w, f"width={w}"

    def test_token_is_never_split(self, pb):
        """A token that does not fit is dropped whole, not cut in half."""
        text = "ab[Enter details]"
        # 'ab' = 2 cols; the token is 15 cols, so widths 2..16 keep only 'ab'
        for w in range(2, 16):
            assert S(pb, text, 0, w) == "ab", f"width={w}"
        assert S(pb, text, 0, 17) == text

    def test_start_col_skips_leading_columns(self, pb):
        assert S(pb, "abcdef", 2, 3) == "cde"

    def test_start_col_skips_whole_tokens(self, pb):
        text = "[C|lear] tail"
        # [C|lear] renders 7 cols; starting past it yields the remainder
        assert S(pb, text, 7, 10) == " tail"

    def test_legend_line_survives_at_its_own_width(self, pb):
        """A legend entry with colour markup must not gain a spurious cut."""
        text = "  [.:green = reply]  [X:red = timeout]"
        assert S(pb, text, 0, W(pb, text)) == text

    def test_escaped_bracket_counts_one_column(self, pb):
        text = r"\[literal"
        assert S(pb, text, 0, W(pb, text)) == text


class TestTabHeaderFits:
    """The pinned help tab-bar must not lose its tail when the box fits it."""

    def _app(self, pb, tmp_path):
        import os
        from unittest.mock import patch
        cfg = str(tmp_path / 'ping-bulk' / 'config')
        os.makedirs(os.path.dirname(cfg), exist_ok=True)
        open(cfg, 'w').close()
        with patch.object(pb, '_config_path', return_value=cfg):
            return pb.Application([('host', '127.0.0.1')])

    def test_header_raw_longer_than_rendered(self, pb, tmp_path):
        """Guards the premise: the active-tab marker is zero-width markup."""
        app = self._app(pb, tmp_path)
        header = app._build_tab_header_line()
        assert len(header) > W(pb, header)

    @pytest.mark.parametrize('tab', range(6))
    def test_header_intact_when_it_fits(self, pb, tmp_path, tab):
        """At inner_w == the header's rendered width, nothing may be dropped.

        Previously line[:inner_w] cut 10 raw chars (':tabactive'), leaving the
        nav hint as '[Tab]/[S-' on the tabs where the header was the widest
        line — Hosts file and Bindings.
        """
        app = self._app(pb, tmp_path)
        app.help_tab = tab
        header = app._build_tab_lines()[0]
        inner_w = W(pb, header)
        assert S(pb, header, 0, inner_w) == header

    @pytest.mark.parametrize('tab', range(6))
    def test_header_keeps_nav_hint_when_it_fits(self, pb, tmp_path, tab):
        app = self._app(pb, tmp_path)
        app.help_tab = tab
        header = app._build_tab_lines()[0]
        sliced = S(pb, header, 0, W(pb, header))
        assert sliced.rstrip().endswith('↔ tab')

    def test_narrow_box_degrades_at_token_boundary(self, pb, tmp_path):
        """A cut header must not end mid-label (e.g. '[5 Bind')."""
        app = self._app(pb, tmp_path)
        app.help_tab = 1
        header = app._build_tab_lines()[0]
        for inner_w in range(20, W(pb, header)):
            sliced = S(pb, header, 0, inner_w)
            assert sliced.count('[') == sliced.count(']'), (
                f"unbalanced markup at inner_w={inner_w}: {sliced!r}"
            )


class TestCompactPath:
    """The Events header shortens the log path; key hints must never be lost."""

    def C(self, pb, path, w):
        return pb.Application._compact_path(path, w)

    def test_short_path_unchanged(self, pb):
        assert self.C(pb, '/tmp/a.log', 40) == '/tmp/a.log'

    def test_home_collapses_to_tilde(self, pb):
        import os
        p = os.path.join(os.path.expanduser('~'), 'logs', 'a.log')
        assert self.C(pb, p, 40) == '~/logs/a.log'

    def test_tilde_form_used_even_when_it_then_fits(self, pb):
        import os
        home = os.path.expanduser('~')
        p = os.path.join(home, 'x.log')
        out = self.C(pb, p, len(p))          # would fit unshortened too
        assert out.startswith('~')

    def test_long_path_is_elided_from_the_left(self, pb):
        out = self.C(pb, '/very/deeply/nested/place/events.log', 20)
        assert len(out) <= 20
        assert out.startswith('…')
        assert out.endswith('events.log'), "the file name must survive"

    def test_never_exceeds_budget(self, pb):
        p = '/a/b/c/d/e/f/g/h/i/events.log'
        for w in range(0, len(p) + 5):
            assert len(self.C(pb, p, w)) <= max(0, w), f"width={w}"

    def test_zero_or_negative_budget_yields_nothing(self, pb):
        assert self.C(pb, '/tmp/a.log', 0) == ''
        assert self.C(pb, '/tmp/a.log', -5) == ''

    def test_tiny_budget_degrades_to_ellipsis(self, pb):
        assert self.C(pb, '/tmp/a.log', 2) == '……'
