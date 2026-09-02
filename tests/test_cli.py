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
    """--dump-hosts prints the expanded host inventory and exits 0.

    :for/:if/:let are resolved, hosts render as 'IP  ## name', sections
    keep their ##/### form, all other directives are omitted, :remote-ping
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

    def test_directives_skipped(self, app_path, hosts_file):
        lines = self.dump(app_path, hosts_file).stdout.splitlines()
        cmd_lines = [l for l in lines if l.startswith(':')]
        assert not cmd_lines, cmd_lines

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


# ---------------------------------------------------------------------------
# --dump-simple-script
# ---------------------------------------------------------------------------

class TestDumpSimpleScript:
    """--dump-simple-script FILE writes a self-executing expanded config:
    like --dump-hosts but with the other directives kept verbatim and a
    #!/bin/sh bootstrap header; FILE is overwritten and chmod +x'ed."""

    @pytest.fixture()
    def hosts_file(self, tmp_path):
        f = tmp_path / 'dump.hosts'
        f.write_text(DUMP_INPUT)
        return str(f)

    def gen(self, app_path, hosts_file, out):
        return run_app('--dump-simple-script', out, '-f', hosts_file,
                       app_path=app_path)

    def test_writes_executable_script(self, app_path, hosts_file, tmp_path):
        out = str(tmp_path / 'gen.hosts')
        result = self.gen(app_path, hosts_file, out)
        assert result.returncode == 0, result.stderr
        assert os.access(out, os.X_OK), "generated script must be executable"
        content = open(out).read()
        assert content.startswith('#!/bin/sh\n'), content[:40]
        assert ':set stats down' in content          # directives kept
        assert '10.30.1.1  ## sensor1-ctrl' in content
        assert ':for' not in content                 # loops expanded

    def test_overwrites_existing_file(self, app_path, hosts_file, tmp_path):
        out = tmp_path / 'gen.hosts'
        out.write_text('old content\n')
        result = self.gen(app_path, hosts_file, str(out))
        assert result.returncode == 0, result.stderr
        content = out.read_text()
        assert 'old content' not in content
        assert content.startswith('#!/bin/sh\n')

    def test_generated_script_reparses_cleanly(self, app_path, hosts_file, tmp_path):
        out = str(tmp_path / 'gen.hosts')
        self.gen(app_path, hosts_file, out)
        result = run_app('--dump-hosts', '-f', out, app_path=app_path)
        assert result.returncode == 0, result.stderr
        assert '10.30.1.1  ## sensor1-ctrl' in result.stdout
        assert result.stderr == '', result.stderr   # no parse warnings

    def test_unwritable_target_exits_nonzero(self, app_path, hosts_file, tmp_path):
        result = self.gen(app_path, hosts_file, str(tmp_path / 'no-dir' / 'x'))
        assert result.returncode == 1, result.stderr
        assert 'cannot write' in result.stderr, result.stderr

    def test_writing_to_a_file_is_silent(self, app_path, hosts_file, tmp_path):
        """Nothing on stderr, so a cron or Makefile run stays quiet."""
        out = str(tmp_path / 'gen.hosts')
        result = self.gen(app_path, hosts_file, out)
        assert result.stderr == '', result.stderr
        assert result.stdout == '', result.stdout


class TestDumpSimpleScriptToStdout:
    """'-' as the target writes the script to stdout instead of a file."""

    @pytest.fixture()
    def hosts_file(self, tmp_path):
        f = tmp_path / 'dump.hosts'
        f.write_text(DUMP_INPUT)
        return str(f)

    def gen_stdout(self, app_path, hosts_file):
        return run_app('--dump-simple-script', '-', '-f', hosts_file,
                       app_path=app_path)

    def test_script_goes_to_stdout(self, app_path, hosts_file):
        result = self.gen_stdout(app_path, hosts_file)
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith('#!/bin/sh\n'), result.stdout[:40]
        assert ':set stats down' in result.stdout
        assert '10.30.1.1  ## sensor1-ctrl' in result.stdout
        assert ':for' not in result.stdout

    def test_stderr_stays_clean_for_piping(self, app_path, hosts_file):
        result = self.gen_stdout(app_path, hosts_file)
        assert result.stderr == '', result.stderr

    def test_no_file_named_dash_is_created(self, app_path, hosts_file, tmp_path):
        result = run_app('--dump-simple-script', '-', '-f', hosts_file,
                         app_path=app_path, cwd=str(tmp_path))
        assert result.returncode == 0, result.stderr
        assert not (tmp_path / '-').exists(), "'-' must not be taken literally"

    def test_same_bytes_as_the_file_form(self, app_path, hosts_file, tmp_path):
        out = tmp_path / 'gen.hosts'
        run_app('--dump-simple-script', str(out), '-f', hosts_file,
                app_path=app_path)
        piped = self.gen_stdout(app_path, hosts_file)
        assert piped.stdout == out.read_text()

    @pytest.mark.parametrize('alias', ['-', '/dev/stdout', '/dev/fd/1',
                                       '/proc/self/fd/1'])
    def test_stdout_aliases_all_work(self, app_path, hosts_file, alias):
        result = run_app('--dump-simple-script', alias, '-f', hosts_file,
                         app_path=app_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith('#!/bin/sh\n'), result.stdout[:40]

    @pytest.mark.parametrize('alias', ['-', '/dev/stdout', '/dev/fd/1',
                                       '/proc/self/fd/1'])
    def test_stdout_alias_does_not_chmod_the_redirect_target(
            self, app_path, hosts_file, tmp_path, alias):
        """os.chmod('/dev/stdout') follows the symlink to whatever stdout is.

        Redirecting into a file must not silently make that file executable —
        the user asked for a stream, not for a mode change on their file.
        """
        out = tmp_path / 'redirected.txt'
        out.touch()
        mode_before = out.stat().st_mode
        with open(out, 'w') as fh:
            result = subprocess.run(
                [sys.executable, app_path, '--dump-simple-script', alias,
                 '-f', hosts_file],
                stdout=fh, stderr=subprocess.PIPE, text=True)
        assert result.returncode == 0, result.stderr
        assert out.stat().st_mode == mode_before, \
            f'{alias} changed the mode of the redirect target'
        assert out.read_text().startswith('#!/bin/sh\n')

    def test_warnings_go_to_stderr_not_into_the_script(self, app_path, tmp_path):
        """Silence on success must not mean silence about problems."""
        bad = tmp_path / 'bad.hosts'
        bad.write_text(':nosuchdirective foo\n10.0.0.1\n')
        result = run_app('--dump-simple-script', '-', '-f', str(bad),
                         app_path=app_path)
        assert 'nosuchdirective' in result.stderr, result.stderr
        assert 'nosuchdirective' not in result.stdout, \
            'a warning must not be mixed into the piped script'
        assert '10.0.0.1' in result.stdout

    def test_piped_output_reparses_cleanly(self, app_path, hosts_file, tmp_path):
        """A redirected script is still a valid hosts file."""
        piped = self.gen_stdout(app_path, hosts_file)
        rt = tmp_path / 'roundtrip.hosts'
        rt.write_text(piped.stdout)
        result = run_app('--dump-hosts', '-f', str(rt), app_path=app_path)
        assert result.returncode == 0, result.stderr
        assert '10.30.1.1  ## sensor1-ctrl' in result.stdout
        assert result.stderr == '', result.stderr
