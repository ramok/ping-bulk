"""A ':mux' pane is handed ping-bulk's own ssh agent.

The pane is started by the **tmux (or screen) server**, so it inherits that
server's environment and not ping-bulk's.  A session older than the running
agent therefore opens every pane with a socket path that no longer exists, and
'ForwardAgent yes' has nothing to forward — while ping-bulk's own ssh children,
which inherit this process's environment, still reach the agent.

Measured on a developer's machine: the live agent was
``/tmp/ssh-ESQYUdN7aIoQ/agent.3177767`` and ping-bulk held it, while 20 of 22
tmux sessions' environments still named agents that had been gone for days.  An
interactive zsh pane hid it (``~/.zshrc`` runs ``keychain``, which re-exports a
live socket); the 'c' pane runs ``sh -c 'ssh …'``, which reads no rc file at
all, so it got the dead one.
"""

import os
import socket
import subprocess
import time

import pytest

from utils.hosts_helper import write_hosts
from tmux_helper import TmuxSession, tmux_cmd, _TMUX_ENV

from test_prog_options import _make_app


@pytest.fixture
def app(pb, tmp_path):
    return _make_app(pb, tmp_path)


def _live_socket(path):
    """Bind a real AF_UNIX socket at *path* and keep it open for the test."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.bind(str(path))
    return sock


def _script_env(script):
    """The environment ``sh -c <script>`` exports, with nothing inherited.

    Run under ``env -i`` so a value in the suite's own environment cannot be
    mistaken for one the script set.  The command is replaced by ``env`` so
    the script's real text — quoting included — is what is exercised.
    """
    run = subprocess.run(['env', '-i', 'sh', '-c', script],
                         capture_output=True, text=True)
    return dict(
        line.split('=', 1)
        for line in run.stdout.splitlines() if '=' in line
    )


class TestThePaneGetsOurOwnAgent:
    """Only a socket that is actually there, and never in kiosk mode."""

    def test_a_live_socket_is_exported(self, app, pb, tmp_path, monkeypatch):
        sock_path = tmp_path / 'agent.sock'
        with _live_socket(sock_path):
            monkeypatch.setenv('SSH_AUTH_SOCK', str(sock_path))
            script = app._mux_pane_script(['env'])
        assert _script_env(script).get('SSH_AUTH_SOCK') == str(sock_path)

    def test_the_echoed_line_is_still_the_command(self, app, pb, tmp_path,
                                                  monkeypatch):
        """The pane's first line is there to be read and copied, so the
        export goes after it rather than in front of the command."""
        sock_path = tmp_path / 'agent.sock'
        with _live_socket(sock_path):
            monkeypatch.setenv('SSH_AUTH_SOCK', str(sock_path))
            script = app._mux_pane_script(['ssh', '-J', 'a,b', 'c'])
        assert script.startswith("printf '$ %s\\n' 'ssh -J a,b c'; ")
        assert script.index('SSH_AUTH_SOCK') < script.index('ssh -J a,b c; _rc')

    @pytest.mark.parametrize('name', ['agent sock', "agent'sock", 'a$gent;sock'])
    def test_an_awkward_path_survives_the_shell(self, app, pb, tmp_path,
                                                monkeypatch, name):
        sock_path = tmp_path / name
        with _live_socket(sock_path):
            monkeypatch.setenv('SSH_AUTH_SOCK', str(sock_path))
            script = app._mux_pane_script(['env'])
        assert _script_env(script).get('SSH_AUTH_SOCK') == str(sock_path)

    def test_nothing_is_exported_when_there_is_no_agent(self, app, pb,
                                                        monkeypatch):
        monkeypatch.delenv('SSH_AUTH_SOCK', raising=False)
        script = app._mux_pane_script(['env'])
        assert 'SSH_AUTH_SOCK' not in script
        assert 'SSH_AUTH_SOCK' not in _script_env(script)

    def test_a_dangling_path_is_left_alone(self, app, pb, tmp_path, monkeypatch):
        """Attaching a client refreshes the session environment, so where
        *this* process holds the stale value the pane's own is the better of
        the two.  Overriding it with a dead path would break that case."""
        monkeypatch.setenv('SSH_AUTH_SOCK', str(tmp_path / 'gone.sock'))
        assert 'SSH_AUTH_SOCK' not in app._mux_pane_script(['env'])

    def test_a_regular_file_is_not_an_agent(self, app, pb, tmp_path, monkeypatch):
        plain = tmp_path / 'not-a-socket'
        plain.write_text('')
        monkeypatch.setenv('SSH_AUTH_SOCK', str(plain))
        assert 'SSH_AUTH_SOCK' not in app._mux_pane_script(['env'])

    def test_kiosk_mode_keeps_its_agent_to_itself(self, app, pb, tmp_path,
                                                  monkeypatch):
        """_kiosk_ssh_flags() isolates a session from the user's home
        directory but says nothing about ForwardAgent, and the console user
        is the party that mode exists to distrust."""
        sock_path = tmp_path / 'agent.sock'
        with _live_socket(sock_path):
            monkeypatch.setenv('SSH_AUTH_SOCK', str(sock_path))
            app.kiosk_mode = True
            script = app._mux_pane_script(['ssh', 'host'])
        assert 'SSH_AUTH_SOCK' not in script
        assert 'ssh host' in script, "the command itself still runs"


class TestLiveAgentSocket:
    """The predicate on its own."""

    def test_unset_is_none(self, pb, monkeypatch):
        monkeypatch.delenv('SSH_AUTH_SOCK', raising=False)
        assert pb._live_agent_socket() is None

    def test_empty_is_none(self, pb, monkeypatch):
        monkeypatch.setenv('SSH_AUTH_SOCK', '')
        assert pb._live_agent_socket() is None

    def test_a_directory_is_not_an_agent(self, pb, tmp_path, monkeypatch):
        monkeypatch.setenv('SSH_AUTH_SOCK', str(tmp_path))
        assert pb._live_agent_socket() is None

    @pytest.mark.skipif(os.geteuid() == 0,
                        reason='root stats through a 0o000 directory, so the '
                               'OSError branch is never reached')
    def test_an_unreadable_parent_does_not_raise(self, pb, tmp_path, monkeypatch):
        """os.stat raises EACCES rather than returning: the caller must not
        take a draw-loop exception for a missing agent."""
        hidden = tmp_path / 'locked'
        hidden.mkdir()
        (hidden / 'agent.sock').write_text('')
        hidden.chmod(0o000)
        monkeypatch.setenv('SSH_AUTH_SOCK', str(hidden / 'agent.sock'))
        try:
            assert pb._live_agent_socket() is None
        finally:
            hidden.chmod(0o700)

    def test_a_live_socket_is_returned(self, pb, tmp_path, monkeypatch):
        sock_path = tmp_path / 'agent.sock'
        with _live_socket(sock_path):
            monkeypatch.setenv('SSH_AUTH_SOCK', str(sock_path))
            assert pb._live_agent_socket() == str(sock_path)


class TestTheHandBuiltMirrorsStillMatch:
    """Two test files rebuild the pane script by hand to assert what
    ``_cmd_mux`` hands the backend.

    They diverged silently when the agent segment was added, and passed only
    because the machine they ran on held a **dead** ``SSH_AUTH_SOCK`` — so the
    suite had come to depend on the developer not having a working agent, and
    11 tests failed as soon as one was bound.  This pins them."""

    @pytest.mark.parametrize('tokens', [
        ['ssh', 'host'],
        ['ssh', '-o', 'ProxyJump=gw', 'myhost'],
        ['mtr', 'host'],
    ])
    def test_both_mirrors_agree_with_the_real_script(self, app, pb, tmp_path,
                                                     monkeypatch, tokens):
        import test_mux
        import test_prog_options

        sock_path = tmp_path / 'agent.sock'
        with _live_socket(sock_path):
            monkeypatch.setenv('SSH_AUTH_SOCK', str(sock_path))
            real = ['sh', '-c', app._mux_pane_script(tokens)]
            assert test_prog_options._held(pb, tokens) == real
            assert test_mux.TestCmdMuxDirection._held(pb, tokens) == real


class TestThePaneBeatsAStaleSessionEnvironment:
    """End to end, against the mechanism itself.

    A structural assertion on the script cannot show that tmux hands the pane
    the *session's* environment rather than the client's — only running it can.
    """

    def test_c_reaches_the_live_agent_through_a_stale_session(
            self, pb, tmp_path, check_integration_deps):
        live = tmp_path / 'live-agent.sock'
        stale = tmp_path / 'stale-agent.sock'       # bound by nobody
        recorded = tmp_path / 'recorded'
        probe = tmp_path / 'probe.sh'
        probe.write_text(
            '#!/bin/sh\nprintf %s "$SSH_AUTH_SOCK" > ' + str(recorded) + '\n')
        probe.chmod(0o755)

        hosts = write_hosts(tmp_path, "127.0.0.1\n:bind-key c :mux " + str(probe) + "\n")

        sess = TmuxSession('ping-bulk-test-agentsock', width=120, height=40)
        try:
            # The session environment names an agent that is not there — which
            # is what a session older than the running agent looks like.
            subprocess.run(
                tmux_cmd('set-environment', '-t', sess.name,
                         'SSH_AUTH_SOCK', str(stale)),
                check=True, env=_TMUX_ENV,
            )
            with _live_socket(live):
                # ping-bulk itself gets the live one, as it does when started
                # from a shell whose agent is current.
                sess.run_shell(
                    f"SSH_AUTH_SOCK={live} python3 "
                    f"{os.path.abspath('ping-bulk')} -f {hosts}")
                sess.wait_for('DNS:', timeout=10)
                sess.send_keys('c')
                deadline = time.time() + 15
                while time.time() < deadline and not recorded.exists():
                    time.sleep(0.2)
                assert recorded.exists(), (
                    "the pane never ran:\n" + sess.capture_pane())
                assert recorded.read_text() == str(live), (
                    "the pane got the stale session value, not ping-bulk's")
        finally:
            sess.kill()
