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
