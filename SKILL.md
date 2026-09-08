# ping-bulk — working notes for AI agents

`AGENTS.md` is the handover document: architecture, invariants, and the
conventions for commands, flags and key bindings. Read it first. This file
holds only the things that are easy to get wrong in practice.

## Testing

```sh
make test                              # or:
tests/venv/bin/pytest -n auto tests/   # the venv is required
make venv                              # one-time setup
```

Use the venv's pytest, not the system one: the dependencies (`pytest-xdist`,
`pytest-rerunfailures`) live there. Use `-n auto`; the UI tests each start
their own `tmux` session, so they parallelise cleanly and the suite runs in
well under a minute instead of several.

Add `-p no:randomly` when a failure needs to be reproduced in a stable order.

Before writing any test, read `tests/AI_TESTING_GUIDE.md` — the UI tests drive
a real `tmux` session and there are templates to follow.

## Verifying a change

Unit tests alone have repeatedly passed while the feature was broken on
screen. For anything that draws, also run it:

```sh
tmux new-session -d -s t -x 100 -y 20 "./ping-bulk -f hosts"; sleep 5
tmux capture-pane -p -t t; tmux kill-session -t t
```

Two habits worth keeping:

- **Check a new test fails before the fix.** Several tests in this suite were
  written against already-correct behaviour and proved nothing.
- **Prefer measuring to reasoning** about SSH, timing and terminal behaviour.
  `ssh -G <host>` prints the options that will actually be used; a stub `ssh`
  on `PATH` makes relay behaviour reproducible without a network.

## Editing the script

`ping-bulk` is one ~12k-line file, so edits are usually string replacements.
Two failure modes have bitten more than once:

- **A slice that removes a block takes its neighbours with it.** After cutting
  text between two anchors, check the methods that lived next to it still
  exist.
- **The file may change under you.** It is the same file the user runs. Do not
  `git checkout` it to build a commit while they have it open — copy the tree
  aside instead.

## Docs that must stay in step

A user-visible change usually touches four places (`AGENTS.md` §5 says so, and
it is easy to miss one):

| Place                          | What lives there                           |
| ------------------------------ | ------------------------------------------ |
| `doc/ping-bulk.rst`            | the manual; `cd doc && make` must be clean |
| `_HELP_*` in `ping-bulk`       | the `?` overlay and `--help-full`          |
| `_EXAMPLE_HELP` in `ping-bulk` | `--help-example`                           |
| `examples/ping-bulk.advance`   | the shipped example                        |

`kiosk/README.md` too, for anything that changes what kiosk mode permits.

Validate the manual without building the whole thing:

```sh
python3 -c "from docutils.core import publish_doctree
publish_doctree(open('doc/ping-bulk.rst').read(), settings_overrides={'report_level':2})"
```

An example in `examples/ping-bulk.advance` that would create files or open
connections stays commented out — running the example should be harmless.
