"""Unit tests for Application._register_shift_tab_seqs().

Covers both the primary curses.define_key() path and the ctypes fallback
path, including edge cases where ncurses is unavailable or raises.
"""

import curses
import os
import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helper: build a non-running Application with a temp config path
# ---------------------------------------------------------------------------

def _make_app(pb, tmp_path):
    """Return a non-running Application with a blank temp config."""
    cfg = str(tmp_path / 'ping-bulk' / 'config')
    os.makedirs(os.path.dirname(cfg), exist_ok=True)
    with open(cfg, 'w') as f:
        f.write('')
    with patch.object(pb, '_config_path', return_value=cfg):
        app = pb.Application([('host', '127.0.0.1')])
    return app


@pytest.fixture
def app(pb, tmp_path):
    """A non-running Application instance."""
    return _make_app(pb, tmp_path)


# ===========================================================================
# TestDefineKeyRegistration — _register_shift_tab_seqs()
# ===========================================================================

class TestDefineKeyRegistration:
    """Tests for Application._register_shift_tab_seqs()."""

    _SEQS = (b'\x1b[Z', b'\x1b[27;2;9~')

    # ── Primary path: curses.define_key() is available ───────────────────

    def test_define_key_called_for_each_sequence(self, app):
        """curses.define_key() must be called exactly twice (once per sequence)."""
        with patch('curses.define_key', create=True) as mock_dk:
            app._register_shift_tab_seqs()
        assert mock_dk.call_count == 2

    def test_define_key_called_with_correct_sequences(self, app):
        """Both VT100 and XTerm-modifyOtherKeys sequences must be registered."""
        with patch('curses.define_key', create=True) as mock_dk:
            app._register_shift_tab_seqs()
        first_args = [c.args[0] for c in mock_dk.call_args_list]
        for seq in self._SEQS:
            assert seq.decode() in first_args

    def test_define_key_second_arg_is_key_btab(self, app):
        """Every curses.define_key() call must map the sequence to KEY_BTAB."""
        with patch('curses.define_key', create=True) as mock_dk:
            app._register_shift_tab_seqs()
        for c in mock_dk.call_args_list:
            assert c.args[1] == curses.KEY_BTAB

    # ── Fallback path: curses.define_key() raises AttributeError ─────────

    def test_ctypes_fallback_invoked_when_define_key_raises_attribute_error(self, app):
        """When curses.define_key() is absent, ctypes.CDLL must be called."""
        mock_lib = MagicMock()
        with patch('curses.define_key', side_effect=AttributeError, create=True), \
             patch('ctypes.util.find_library', return_value='libncursesw.so'), \
             patch('ctypes.CDLL', return_value=mock_lib) as mock_cdll:
            app._register_shift_tab_seqs()
        mock_cdll.assert_called_once()

    def test_ctypes_define_key_called_for_each_sequence(self, app):
        """The ctypes fallback must call ncurses define_key() for every sequence."""
        mock_lib = MagicMock()
        with patch('curses.define_key', side_effect=AttributeError, create=True), \
             patch('ctypes.util.find_library', return_value='libncursesw.so'), \
             patch('ctypes.CDLL', return_value=mock_lib):
            app._register_shift_tab_seqs()
        assert mock_lib.define_key.call_count == 2

    def test_ncursesw_tried_before_ncurses(self, app):
        """find_library() must be queried for 'ncursesw' before 'ncurses'."""
        mock_lib = MagicMock()
        calls_seen = []

        def fake_find_library(name):
            calls_seen.append(name)
            return 'libncursesw.so'

        with patch('curses.define_key', side_effect=AttributeError, create=True), \
             patch('ctypes.util.find_library', side_effect=fake_find_library), \
             patch('ctypes.CDLL', return_value=mock_lib):
            app._register_shift_tab_seqs()
        assert calls_seen[0] == 'ncursesw'

    def test_falls_back_to_ncurses_when_ncursesw_absent(self, app):
        """When ncursesw is not found, ncurses must be tried next."""
        mock_lib = MagicMock()

        def fake_find_library(name):
            return None if name == 'ncursesw' else 'libncurses.so'

        with patch('curses.define_key', side_effect=AttributeError, create=True), \
             patch('ctypes.util.find_library', side_effect=fake_find_library), \
             patch('ctypes.CDLL', return_value=mock_lib) as mock_cdll:
            app._register_shift_tab_seqs()
        mock_cdll.assert_called_once_with('libncurses.so')

    def test_no_cdll_call_when_find_library_returns_none(self, app):
        """When neither ncursesw nor ncurses are found, CDLL must not be called."""
        with patch('curses.define_key', side_effect=AttributeError, create=True), \
             patch('ctypes.util.find_library', return_value=None), \
             patch('ctypes.CDLL') as mock_cdll:
            app._register_shift_tab_seqs()
        mock_cdll.assert_not_called()

    # ── Resilience: exceptions must never propagate ───────────────────────

    def test_ctypes_exception_swallowed_silently(self, app):
        """An OSError from ctypes.CDLL must be caught; the method must not raise."""
        with patch('curses.define_key', side_effect=AttributeError, create=True), \
             patch('ctypes.util.find_library', return_value='libncursesw.so'), \
             patch('ctypes.CDLL', side_effect=OSError('no ncurses')):
            app._register_shift_tab_seqs()  # must not raise

    def test_define_key_attribute_error_does_not_propagate(self, app):
        """An AttributeError from curses.define_key() must be caught silently."""
        with patch('curses.define_key', side_effect=AttributeError, create=True), \
             patch('ctypes.util.find_library', return_value=None):
            app._register_shift_tab_seqs()  # must not raise

