"""The suite must not write to the developer's shell history.

A tmux pane runs the developer's own **interactive login shell**, and these
tests type the command under test into it — so every session the suite starts
appended a line to their real ``~/.zsh_history``.  Measured on 2026-09-14:
**4559 of the 5008 lines** in one developer's history were this suite, one per
session, and with ``SAVEHIST=5000`` each run evicted nearly all of their own
commands.  Their history reached back three days.  Shell history does not come
back once it has rolled over.

Two layers, because either alone has a way to fail, and one test per layer:

1. ``ZDOTDIR`` points at the session's private temp directory, so zsh never
   reads the developer's own ``.zshrc`` — only the empty one written there —
   and therefore never assigns ``HISTFILE``, which it has no default for.
   Setting ``HISTFILE`` alone is **not** enough: an rc file that does get read
   assigns it unconditionally and beats the environment, which is exactly what
   ``~/.zshrc.min`` does on the machine where this was found.
2. ``run_shell()`` prefixes a space, which ``hist_ignore_space`` drops.  This
   covers a shell whose rc files the first layer does not govern.

The third test is the structural one, and it is the one that matters over
time: a future test that types a shell command with ``send_literal`` plus an
``Enter`` bypasses both layers, and nothing else would notice.
"""

import ast
import os
import pathlib
import time
import uuid

import pytest

from tmux_helper import TmuxSession

TESTS_DIR = pathlib.Path(__file__).parent

# A payload that starts like one of these is a command for the *shell*, not
# keystrokes for the application under test.
_SHELL_STARTS = ('python3', 'python', 'sh ', 'bash ', 'zsh ', 'env ', './', '/')


def _render(node):
    """Best-effort text of a string or f-string literal, or None."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            else:
                out.append('{}')          # a placeholder stands in for the value
        return ''.join(out)
    return None


def _looks_like_shell(text):
    if text is None:
        return False
    stripped = text.lstrip()
    if stripped.startswith(_SHELL_STARTS):
        return True
    # `cmd = f"{app_path} -f {hosts}"` renders as `{} -f {}` — the tell is that
    # it starts with a substituted value and carries a path-ish flag.
    return stripped.startswith('{}') and ' -f ' in stripped


def _shell_command_sites(path):
    """Yield (lineno, rendered) for every send_literal carrying a shell command."""
    tree = ast.parse(path.read_text())

    # Values assigned to plain names, so `cmd = f'{app_path} -f {hosts}'`
    # followed by `send_literal(cmd)` is still caught.
    assigned = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            text = _render(node.value)
            if text is None:
                continue
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assigned.setdefault(target.id, text)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == 'send_literal'):
            continue
        if not node.args:
            continue
        arg = node.args[0]
        text = _render(arg)
        if text is None and isinstance(arg, ast.Name):
            text = assigned.get(arg.id)
        if _looks_like_shell(text):
            yield node.lineno, text


def test_no_test_types_a_shell_command_with_send_literal():
    """Shell commands go through ``run_shell``, which prefixes the space.

    ``send_literal`` cannot prepend anything of its own: it is also how
    application keystrokes are typed (``send_literal('zC')``), and a leading
    space there would be typed into the app.  So the split has to be respected
    by the caller, and this is what notices when it is not.
    """
    offenders = []
    for path in sorted(TESTS_DIR.glob('*.py')):
        if path.name == pathlib.Path(__file__).name:
            continue
        for lineno, text in _shell_command_sites(path):
            offenders.append(f'{path.name}:{lineno}: send_literal({text!r})')

    assert not offenders, (
        'These type a shell command into the pane, which lands in the '
        'developer\'s own shell history. Use sess.run_shell(cmd) instead of '
        'send_literal(cmd) + send_keys("Enter"):\n  ' + '\n  '.join(offenders)
    )


def test_run_shell_prefixes_a_space(monkeypatch):
    """The space is what ``hist_ignore_space`` keys on, so it must be there."""
    typed = []
    monkeypatch.setattr(TmuxSession, 'send_literal', lambda self, text: typed.append(text))
    monkeypatch.setattr(TmuxSession, 'send_keys', lambda self, *keys: typed.append(keys))

    session = TmuxSession.__new__(TmuxSession)   # no tmux server needed for this
    session.run_shell('echo hello')

    assert typed[0] == ' echo hello', 'run_shell must prefix the command with a space'
    assert typed[1] == ('Enter',)


def test_a_session_writes_nothing_to_the_real_shell_history():
    """The layer that works even when a call site forgets the space.

    Deliberately sends the marker **without** a leading space, so this fails if
    only the ``run_shell`` layer is doing the work.

    **The command is proved to have run before its absence means anything.**
    An assertion that a marker is missing from a file passes just as well when
    the marker was never executed — and the regression that would cause that is
    the one this very change fixed: with no ``.zshrc`` in ``ZDOTDIR``, Debian's
    zsh opens the interactive ``zsh-newuser-install`` wizard, which takes the
    terminal and swallows what is typed at it. This project has shipped a guard
    that could not fail before (AGENTS.md §9d, the ``connect`` parity test);
    once is enough.

    Waiting for the token to *appear* would not prove it either, because the
    typed command line contains it too — and it appears even when the wizard is
    eating it, which is exactly the case to catch. The echo having run is the
    token showing up **twice**: once as typed, once as output.
    """
    history = pathlib.Path(os.path.expanduser('~/.zsh_history'))
    if not history.exists():
        pytest.skip('no ~/.zsh_history on this machine')

    token = f'PB-HIST-{uuid.uuid4().hex[:12]}'

    session = TmuxSession('ping-bulk-test-histclean', width=100, height=24)
    try:
        session.send_literal(f'echo {token}')   # no space: the ZDOTDIR layer alone
        session.send_keys('Enter')

        deadline = time.time() + 15
        while time.time() < deadline:
            if session.capture_pane().count(token) >= 2:
                break
            time.sleep(0.1)
        else:
            pytest.fail(
                'the pane never echoed the marker back, so this test would '
                'prove nothing about the history file — the shell did not '
                'reach a prompt, or something interactive ate the command:\n'
                + session.capture_pane()
            )

        session.send_literal('exit')            # zsh flushes its history on exit
        session.send_keys('Enter')
        time.sleep(1.0)
    finally:
        session.kill()

    # Match the token rather than checksumming the file: the developer's own
    # shell may be writing to it while this runs, so equality would flake.
    assert token not in history.read_text(errors='replace'), (
        'a test session reached the real shell history — check that '
        'ZDOTDIR is still set on tmux new-session'
    )
