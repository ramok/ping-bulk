"""Tests for ping-bulk command-line interface (no curses).

These tests invoke the script as a subprocess and check its exit code and
stdout/stderr output.  No tmux session is required.
"""

import subprocess
import sys
import os
import pytest


@pytest.fixture(scope='module')
def app_path() -> str:
    """Absolute path to the ping-bulk script."""
    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = os.path.join(repo_root, 'ping-bulk')
    assert os.path.isfile(path), f"ping-bulk not found at {path}"
    return path


def run_app(*args, **kwargs):
    """Run the app as a subprocess and return the CompletedProcess."""
    return subprocess.run(
        [sys.executable, kwargs.pop('app_path')] + list(args),
        capture_output=True,
        text=True,
        **kwargs,
    )


# ---------------------------------------------------------------------------
# No arguments
# ---------------------------------------------------------------------------

class TestNoArgs:
    """Invoking ping-bulk with no hosts and no -f/--file must print help and exit 0."""

    def test_exit_code(self, app_path):
        result = run_app(app_path=app_path)
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_stdout_contains_usage(self, app_path):
        result = run_app(app_path=app_path)
        assert 'usage' in result.stdout.lower(), (
            f"Expected 'usage' in stdout.\nstdout: {result.stdout!r}"
        )

    def test_stdout_contains_prog_name(self, app_path):
        result = run_app(app_path=app_path)
        assert 'ping-bulk' in result.stdout, (
            f"Expected 'ping-bulk' in stdout.\nstdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# --help flag
# ---------------------------------------------------------------------------

class TestHelpFlag:
    """``--help`` must print help to stdout and exit 0 (argparse default)."""

    def test_exit_code(self, app_path):
        result = run_app('--help', app_path=app_path)
        assert result.returncode == 0, (
            f"Expected exit 0 for --help, got {result.returncode}\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_stdout_contains_examples(self, app_path):
        result = run_app('--help', app_path=app_path)
        assert 'examples' in result.stdout.lower(), (
            f"Expected 'examples' section in --help output.\nstdout: {result.stdout!r}"
        )

    def test_stdout_mentions_file_flag(self, app_path):
        result = run_app('--help', app_path=app_path)
        assert '--file' in result.stdout, (
            f"Expected '--file' in --help output.\nstdout: {result.stdout!r}"
        )

    def test_stdout_mentions_log_file_flag(self, app_path):
        result = run_app('--help', app_path=app_path)
        assert '--log-file' in result.stdout, (
            f"Expected '--log-file' in --help output.\nstdout: {result.stdout!r}"
        )


# ---------------------------------------------------------------------------
# --dump-hosts
# ---------------------------------------------------------------------------

DUMP_INPUT = """\
:set stats down
:resolv 192.168.88.1 gw-def
:let remote 5

## Sensors
:for sensor-{1,$remote}
    ### $0
    10.30.$1.1 ## sensor$1-ctrl
:end

:if 1 in 1 -> 8.8.8.8
:with remote-ping ops@relay.example.com
10.40.0.1 ## remote-host
:end
:remote-ping ops@relay.example.com 10.50.0.1
"""


class TestDumpHosts:
    """--dump-hosts prints the expanded hosts file and exits 0.

    :for/:if/:let are resolved, hosts render as 'IP  ## name', sections
    keep their ##/### form, other directives stay verbatim, :remote-ping
    targets are flattened to plain host lines, :source is spliced in."""

    @pytest.fixture()
    def hosts_file(self, tmp_path):
        f = tmp_path / 'dump.hosts'
        f.write_text(DUMP_INPUT)
        return str(f)

    def dump(self, app_path, hosts_file):
        return run_app('--dump-hosts', '-f', hosts_file, app_path=app_path)

    def test_exit_code(self, app_path, hosts_file):
        result = self.dump(app_path, hosts_file)
        assert result.returncode == 0, (
            f"Expected exit 0, got {result.returncode}\n"
            f"stdout: {result.stdout!r}\nstderr: {result.stderr!r}"
        )

    def test_no_programming_constructs(self, app_path, hosts_file):
        out = self.dump(app_path, hosts_file).stdout
        for construct in (':for', ':if', ':let', ':with', ':end'):
            assert construct not in out, (
                f"{construct} must not appear in dump output:\n{out}"
            )

    def test_hosts_have_inline_names(self, app_path, hosts_file):
        out = self.dump(app_path, hosts_file).stdout
        assert '10.30.1.1  ## sensor1-ctrl' in out, out
        assert '10.30.5.1  ## sensor5-ctrl' in out, out

    def test_sections_expanded(self, app_path, hosts_file):
        lines = self.dump(app_path, hosts_file).stdout.splitlines()
        assert '## Sensors' in lines, lines
        assert '### sensor-1' in lines, lines
        assert '### sensor-5' in lines, lines

    def test_inline_if_host_included(self, app_path, hosts_file):
        out = self.dump(app_path, hosts_file).stdout
        assert '8.8.8.8' in out.splitlines(), out

    def test_remote_ping_flattened_to_plain_host(self, app_path, hosts_file):
        out = self.dump(app_path, hosts_file).stdout
        assert ':remote-ping' not in out, out
        assert '10.40.0.1  ## remote-host' in out, out
        assert '10.50.0.1' in out.splitlines(), out

    def test_directives_kept_verbatim(self, app_path, hosts_file):
        lines = self.dump(app_path, hosts_file).stdout.splitlines()
        assert ':set stats down' in lines, lines
        assert ':resolv 192.168.88.1 gw-def' in lines, lines

    def test_consumed_resolv_merged_into_inline_form(self, app_path, hosts_file):
        out = self.dump(app_path, hosts_file).stdout
        assert ':resolv 10.30.1.1' not in out, out

    def test_source_spliced_in(self, app_path, tmp_path):
        inner = tmp_path / 'inner.hosts'
        inner.write_text('10.99.0.1 ## sourced-host\n')
        outer = tmp_path / 'outer.hosts'
        outer.write_text(f'1.1.1.1\n:source {inner}\n')
        out = self.dump(app_path, str(outer)).stdout
        assert ':source' not in out, out
        assert '## sourced-host' in out, out

    def test_idempotent(self, app_path, hosts_file, tmp_path):
        first = self.dump(app_path, hosts_file).stdout
        again_file = tmp_path / 'again.hosts'
        again_file.write_text(first)
        second = self.dump(app_path, str(again_file)).stdout
        assert first == second

    def test_missing_file_exits_nonzero(self, app_path, tmp_path):
        result = self.dump(app_path, str(tmp_path / 'nope.hosts'))
        assert result.returncode == 1, result.stderr
        assert 'cannot open' in result.stderr, result.stderr
