"""Unit tests for _derive_prog_name()."""

import pytest


class TestDerivProgName:
    """Tests for _derive_prog_name() using explicit argv lists."""

    def test_normal_binary(self, pb):
        assert pb._derive_prog_name(['./ping-bulk', '8.8.8.8']) == 'ping-bulk'

    def test_renamed_binary(self, pb):
        assert pb._derive_prog_name(['ping-bulk.evo-lan', '-f', 'hosts.txt']) == 'ping-bulk.evo-lan'

    def test_absolute_path_binary(self, pb):
        assert pb._derive_prog_name(['/usr/local/bin/ping-bulk', '8.8.8.8']) == 'ping-bulk'

    def test_python_with_script(self, pb):
        # python3 ping-bulk 8.8.8.8 → argv[0] is the script itself
        assert pb._derive_prog_name(['ping-bulk', '8.8.8.8']) == 'ping-bulk'

    def test_python_interpreter_with_f(self, pb):
        assert pb._derive_prog_name(['python3', '-f', 'network.pb']) == 'network.pb'

    def test_python_interpreter_with_file_long(self, pb):
        assert pb._derive_prog_name(['python3', '--file=network.pb']) == 'network.pb'

    def test_python_interpreter_no_f(self, pb):
        assert pb._derive_prog_name(['python3']) == 'ping-bulk'

    def test_python_version_prefix(self, pb):
        # python3.11 — starts with 'python'
        assert pb._derive_prog_name(['python3.11', '-f', 'nets.pb']) == 'nets.pb'

    def test_pytest_fallback(self, pb):
        assert pb._derive_prog_name(['pytest', 'tests/']) == 'ping-bulk'

    def test_dunder_main_fallback(self, pb):
        assert pb._derive_prog_name(['__main__', '-f', 'net.pb']) == 'net.pb'

    def test_py_extension_fallback(self, pb):
        # Script run as 'python foo.py -f hosts'
        assert pb._derive_prog_name(['foo.py', '-f', 'hosts.pb']) == 'hosts.pb'

    def test_py_extension_no_f(self, pb):
        assert pb._derive_prog_name(['foo.py']) == 'ping-bulk'

    def test_extension_preserved(self, pb):
        # Full basename including extension must be returned
        assert pb._derive_prog_name(['python3', '-f', '/path/to/network.pb']) == 'network.pb'

    def test_last_f_wins(self, pb):
        # Multiple -f arguments — last one wins
        result = pb._derive_prog_name(['python3', '-f', 'first.pb', '-f', 'last.pb'])
        assert result == 'last.pb'

    def test_file_eq_syntax(self, pb):
        assert pb._derive_prog_name(['python3', '--file=/path/to/net.pb']) == 'net.pb'

    def test_python_c_fallback(self, pb):
        # python -c "..." sets argv[0] to '-c' (pytest-xdist workers do this)
        assert pb._derive_prog_name(['-c', '-f', 'net.pb']) == 'net.pb'

    def test_python_c_no_f_fallback(self, pb):
        assert pb._derive_prog_name(['-c']) == 'ping-bulk'

    def test_renamed_binary_no_extension(self, pb):
        assert pb._derive_prog_name(['/usr/bin/pb-monitor', '1.2.3.4']) == 'pb-monitor'
