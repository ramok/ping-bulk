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

