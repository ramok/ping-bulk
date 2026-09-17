# Project Handover Document (AGENTS.md)

## 1. Project Overview
**ping-bulk** is a self-contained, single-file Python 3 script designed for monitoring multiple hosts simultaneously with a continuous ping in a live, interactive terminal interface. The goal is to provide a rich CLI tool with features like rolling history, interactive host navigation, SSH monitoring, section folding, and event logging—all without any third-party Python dependencies (only relying on the standard library and the system's `ping` binary).

## 2. Architecture & Code Structure
The repository is structured to keep the core application as a single deployable file while providing tests, documentation, and examples alongside it.

- **`ping-bulk`**: The main executable script. All core application logic (UI, multithreading, subprocess management, configuration, and data processing) resides here.
- **`tests/`**: Contains the test suite for the application. The tests use `pytest` and mock various functionalities (like `ping` output or SSH execution) to ensure reliability without needing actual network access.
- **`examples/`**: Provides sample hosts files demonstrating various configuration directives (e.g., brace expansion, SSH monitoring, static DNS overrides) that `ping-bulk` supports.
- **`doc/`**: Contains project documentation in reStructuredText format (`ping-bulk.rst`), a `Makefile` to build man pages (`ping-bulk.1`), and an HTML version. It relies on `docutils` for building the documentation.
- **`kiosk/`**: Contains the unattended-console deployment: a systemd template unit (`ping-bulk-kiosk@.service`), the hardened tmux configuration it launches, and `README.md` documenting the kiosk security model.

## 3. Technology Stack & Requirements
- **Language**: Python 3.8+
- **Dependencies**:
  - Python Standard Library (no external pip dependencies for the core application).
  - System `ping` binary with `-O` and `-D` flag support (e.g., `iputils-ping` ≥ 20121221).
  - A terminal with color support.
- **Testing**: `pytest`, `pytest-xdist` (see `requirements-dev.txt`).
- **Documentation**: `docutils` (optional, for building man pages and HTML docs).
- **Formatters**: **never** use formatters such as ruff to fix code

## 4. Key Features & Functionality
- **Parallel Monitoring**: Each host is monitored in its own background thread with a persistent `ping` subprocess, ensuring high concurrency and responsive UI.
- **Interactive UI**: Users can navigate the host list with arrow keys, view detailed stats, scroll history, toggle display modes (DNS, stats columns, history view), and fold sections.
- **SSH Monitoring**: The ability to run `ping` on a remote machine via `ssh` and aggregate the results alongside local targets.
- **TCP Port Monitoring**: Ability to monitor connectivity to specific TCP ports (e.g., `example.com:80`).
- **Advanced Configuration**: Supports command-line arguments and robust "hosts files" with directives for brace expansion (`{1..50}`), loop blocks (`:for`/`:done`), and DNS overrides (`:resolv`).
- **Persistent Configuration**: User preferences are saved in `~/.config/ping-bulk/config`.

## 5. Development & Testing Workflow
- **Copilot Tool Permissions**:
  - This project maintains a list of pre-approved tools in `.github/copilot-instructions.md`.
  - When starting a new session, approve the tools listed in that file.
  - If a new tool is needed and approved during development, update `.github/copilot-instructions.md` to include it for future sessions.
  - This ensures consistent tool availability across sessions while maintaining security through explicit approval.
- **Git Commit Etiquette for AI Agents**:
  - **NEVER use `git add .`** or `git commit -a`. You must always meticulously specify only the intended files to add (e.g. `git add <specific file>`). Blindly adding all files risks committing unintended, unrelated, or temporary files.
  - **Commit messages must focus on User Experience (UX) impact, not just technical implementation details**. Frame the commit message to explain *how* the change affects the end user (e.g., "feat: simplify port monitoring syntax for users"), rather than just listing what functions changed. The commit message should be human-readable, formatted nicely, and concisely explain the value to the user.
- **Running the Application**: You can run the script directly from the root directory: `./ping-bulk <hosts>`.
- **Running Tests**: Navigate to the root directory and execute `tests/venv/bin/pytest -n auto tests/` to run the test suite in parallel (or simply `make test`). A dedicated venv lives in `tests/venv/`; create it once with `make venv` (or `python3 -m venv tests/venv && tests/venv/bin/pip install -r requirements-dev.txt`). It is **highly recommended** to use `-n auto` for significantly faster test execution, as test sessions are fully isolated using unique `tmux` session names via `pytest-xdist`. Ensure any new features include appropriate tests, especially for complex parsing (like brace expansion or SSH directives). For more details on the testing infrastructure and how to write tests using the headless tmux environment, refer to `tests/AI_TESTING_GUIDE.md` and `SKILL.md`.
  - **The suite is hermetic, and must stay that way.** Every test gets its own
    `XDG_CONFIG_HOME` (`conftest.isolated_config_dir`), because the tests drive
    the real `./ping-bulk`, which loads `$XDG_CONFIG_HOME/ping-bulk/config`.
    Without it the suite reads — and can *write* — whoever is running it: a
    developer's own `:layout log` fails twenty tests, with errors that look
    exactly like a regression in the code under test, and a test that calls
    `:save-config` unpatched overwrites a real config. Both happened.
    The tmux sessions need it separately (`-e XDG_CONFIG_HOME=…` on
    `tmux new-session`), because a pane inherits the tmux **server's**
    environment, not pytest's — exporting it in a fixture does not reach it.
  - **Never `tmux kill-server` to clean up.** It ends every session the user
    has, not the test ones; `TmuxSession.kill()` kills by name and that is the
    only correct way. Orphaned `ping-bulk-test-*` sessions are harmless.
  - **The suite is hermetic, and must stay that way.** Every test gets its own
    `XDG_CONFIG_HOME` (`conftest.isolated_config_dir`), because the tests drive
    the real `./ping-bulk`, which loads `$XDG_CONFIG_HOME/ping-bulk/config`.
    Without it the suite reads — and can *write* — whoever is running it: a
    developer's own `:layout log` fails twenty tests, with errors that look
    exactly like a regression in the code under test, and a test that reaches
    `:save-config` unpatched overwrites a real config. Both happened.
  - **The suite runs on its own tmux server** (`tmux -L ping-bulk-test`), so it
    cannot see, resize or kill the sessions you are working in. `conftest`
    refuses to start if anything would reach the default server — a guard added
    after a one-line experiment pointed the start-up sweep at a developer's real
    server and destroyed 11 live sessions. That sweep also requires the
    `ping-bulk-test-` prefix, so its safety no longer rests on one constant, and
    it spares sessions younger than 120 s so two concurrent pytest runs do not
    destroy each other's work.
  - **The server is started without `LINES`/`COLUMNS`.** tmux copies its own
    environment into every pane, and ncurses prefers those variables over the
    pty, so a stale `LINES=40` makes the app under test ignore every resize.
    `TmuxSession` forces the `ping-bulk-test-` prefix for a related reason — 44
    sessions once leaked under `pytest-rfold-*`, which no cleanup pattern
    matched.
  - **Never `tmux kill-server` to clean up.** It ends every session the user
    has, not the test ones — not even on the private socket. `TmuxSession.kill()`
    kills by name and that is the only correct way.
  - **The pane runs the developer's own interactive shell, so the suite must
    not leave anything in its history.** Every session typed the command under
    test at that shell's prompt: measured, **4559 of the 5008 lines** in a
    developer's `~/.zsh_history` were this suite, and `SAVEHIST=5000` meant each
    run evicted nearly all of their own commands — history that does not come
    back. Two layers, because either alone has a way to fail. `ZDOTDIR` points
    at the session's private temp directory, so zsh never reads the developer's
    own `.zshrc` — only the empty one written there — and therefore never
    assigns `HISTFILE`, which it has no default for; setting `HISTFILE` alone is
    **not** enough, since an rc file that does get read assigns it
    unconditionally and beats the environment. And `run_shell(cmd)` prefixes a
    space, which `hist_ignore_space` drops, covering a shell the first layer
    does not govern. **That empty `.zshrc` is not tidiness**: without one,
    Debian's zsh runs the *interactive* `zsh-newuser-install` wizard, which took
    over the terminal and swallowed the first command sent to the pane, so
    `start_app` waited for a UI that never started. **A bash pane is a known
    gap, not a covered case** — `~/.bashrc` can reassign `HISTFILE` just as
    `~/.zshrc` does, and the space needs `HISTCONTROL=ignorespace`, which bash
    does not set by default. Shell commands go through `run_shell`, never `send_literal` plus an
    `Enter` — `send_literal` also types application keystrokes (`'zC'`) and so
    cannot prepend anything of its own. `tests/test_shell_history_clean.py`
    fails if a new test bypasses it.
  - **CRITICAL REQUIREMENT FOR AI AGENTS:** Before writing **any** new tests, you **MUST** read and fully understand `tests/AI_TESTING_GUIDE.md`. You **MUST** strictly follow the test templates provided in that guide to ensure consistency with the existing headless tmux testing infrastructure. Failure to do so will result in broken UI tests and test suite failures.
- **Building Documentation**: Navigate to the `doc/` directory and run `make` (requires `docutils` installed via pip) to generate the updated man page and HTML documentation.
- **Keeping `--help-example` in sync**: Whenever `doc/ping-bulk.rst` or `examples/ping-bulk.advance` is updated with new features or syntax, the `_EXAMPLE_HELP` constant in `ping-bulk` (printed by `--help-example`) **must also be updated** to reflect the same features. All three should stay consistent.
- **Single-File Constraint**: When adding new functionality, remember the primary design goal: `ping-bulk` must remain a single, self-contained script. Avoid splitting the core logic into multiple files or adding third-party dependencies unless absolutely necessary and agreed upon.

## 6. Known Quirks & Considerations
- **Shebang Execution**: The hosts file parser supports execution via a shebang (`#!/usr/bin/env -S ping-bulk -f`). Pay attention to compatibility notes regarding `env -S` and older systems when writing documentation or examples.
- **UI Responsiveness**: Because the UI runs in the main thread while ping subprocesses run in background threads, ensure thread-safe operations when updating the shared state (history, stats) to prevent UI tearing or crashes.

## 7. Future Work / TODOs
- Maintain compatibility with different variations of the `ping` command across various Linux distributions and macOS.
- Enhance test coverage for edge cases in network failures and SSH connection drops.
- Consider adding export functionalities (e.g., CSV/JSON output for metrics) if requested, keeping the single-file constraint in mind.

## 8. Recent Work
- **Phase 24 (Ctrl+C is a keystroke, not an exception)**: the draw loop caught
  `KeyboardInterrupt` around exactly two calls — `stdscr.refresh()` and
  `stdscr.getch()` — and Python's default SIGINT handler raises it *wherever
  the signal lands*. Everything between those two calls is the frame being
  drawn, and it was unguarded: a Ctrl+C pressed there went past
  `curses.wrapper` and killed the process. Measured from a real failure, the
  exception surfaced inside `_hint_text_segments`, drawing the help overlay —
  so the user pressed the key that closes an overlay and got a traceback.
  **Guarding those two calls harder cannot fix it**; the signal can land on any
  bytecode boundary in between, and wrapping the loop body would mean
  re-indenting a hundred lines. `_note_interrupt` records instead of raising,
  so nothing can escape from anywhere, and the loop reads the flag at the input
  step — within one `getch` timeout, 100 ms — and turns it into key 3, which is
  what both of the old handlers already meant by it (`refresh`'s did
  `:quit --confirm`; key 3 in normal mode *is* the quit confirmation). A real
  key pressed in the same window is pushed back with `curses.ungetch` rather
  than forfeited. Safe because `multikey_timeout` only ever *shortens* the
  wait, so `getch` never blocks beyond a second.
  **Scoped to the loop, and the exit is `SIG_IGN`, not the old handler.**
  Before the UI exists Ctrl+C should still abandon the run, so the handler is
  installed in `run()` rather than `main()`. Restoring the default on the way
  out was wrong for the mirror-image reason, and measured: a burst of SIGINTs
  quit the program correctly and then raised `KeyboardInterrupt` inside
  `curses.wrapper`'s own `stdscr.keypad(0)`. Everything after the loop is
  teardown with nothing left to cancel, and `curses.wrapper(main, ...)` is the
  last statement in the file, so there is no caller to hand the signal back to.
  **The invariant under test is "never a traceback", not "still running"** — a
  burst in normal mode legitimately quits (the re-press pattern), so survival
  is the wrong assertion. `tests/test_ctrl_c.py::TestCtrlCIsNeverATraceback`
  sends 300 signals while the help overlay is open: 3 of 3 runs against the
  previous build left `KeyboardInterrupt` on screen, 5 of 5 against this one
  did not. Signals rather than keystrokes because one `send-keys` per Ctrl+C is
  a subprocess each, far too slow to land inside a 100 ms frame.
  This also removes a suite flake that had nothing obviously to do with it:
  `test_ctrl_c.py` failed about one run in five under `-n auto` once this
  session's new tests raised the scheduling pressure (measured 0/22 before them
  and 7/33 after, with the production code exonerated at 0/10 against the old
  test set). The race was always there; more load found it.
- **Phase 23 (the kiosk exemption that was never switched on)**: `_loading_file`
  was read in three places — `:bind-key`, `:web start` and `:source` — and
  **assigned in none**. So the rule those three docstrings describe, *declared
  by the trusted hosts file, never typed at the console*, did not exist under
  `--kiosk`: a kiosk hosts file's `:web start` was refused and its `:bind-key`
  lines were silently dropped, for the whole life of the feature.
  Two things hid it, and both are worth naming. The reads went through
  `getattr(self, '_loading_file', False)`, so a phantom attribute raised
  nothing and read False forever — **a `getattr` default is a silent
  assignment**, and this one was the entire feature. And the six tests that
  covered the exemptions each set the flag **by hand**
  (`tests/test_web_server.py`, `tests/test_bindkey.py`,
  `tests/test_web_write.py`), proving the gate logic works in a state
  production never reached; they passed throughout.
  `Application.__init__` now sets it around one `try`/`finally` — the entry
  loop, extracted as `_load_entries` so the window is exactly the file's own
  directives and not seventy lines of unrelated construction — and it is a
  class attribute for the reason `_entries_generation` is (§9c): several tests
  build an `Application` through `__new__` and do dispatch commands. That also
  means **nothing here can raise if the assignment goes missing again** — a
  class attribute always resolves. The only thing that catches a repeat is
  `tests/test_kiosk_declared_not_typed.py`, below.
  **`:source` keeps its guard, and that is not an oversight.** It is the one of
  the three where the unset flag was doing real work: for the other two the
  *feature* was dead, but here the always-False read meant
  `_kiosk_allow_path` **always ran**. Switching the flag on would have let a
  kiosk hosts file source any absolute path — and, through a nested `:source`,
  reach `:web start` on the outer file's trust. Measured both ways on the same
  input. Nothing legitimate is lost: the hosts file's own directory is an
  allowed prefix, which is the case that guard was written for. So the check
  is unconditional now rather than reading a flag it must not honour.
  **Deliberately not extended to the `:edit` reload**, which looks like the
  same thing and is the opposite one: `:edit` is *allowed* at the console under
  kiosk (it opens `rnano`/`rvim` on the hosts file), so a reload replays a file
  the person at the keyboard may have just written, while startup replays the
  one the operator deployed. Giving the reload the exemption would hand that
  person `:web start` and `:bind-key <k> :mux sh` through the editor.
  `:set web-anonymous` joins the two (§9d), audited like the bind.
  **`:probe-source` is described everywhere as following this rule and does
  not**: it gates on `_monitoring_started`, which `_edit_reload_inplace` also
  clears — so it *does* get its exemption on a reload while these do not. That
  predates this work and is left alone; the wording that claimed otherwise is
  corrected.
  `tests/test_kiosk_declared_not_typed.py` drives a real hosts file through
  `parse_hosts_file` + `Application.__init__` and **assigns the flag nowhere**;
  a test that did would be the bug again. Each of the seven mutations that
  matter — flag never set, flag never cleared, exemption reverted, audit
  removed, exemption widened to the reload, and the two that put the flag back
  in front of `:source`'s path guard or remove that guard outright — was
  verified to fail, and to fail on the right tests.
- **Phase 22 (the probe strip reads like the ping strip)**: three things were
  wrong with `:set ping-view <probe>`, all reported from one screen showing
  twenty-eight satellites as a yellow `8`.
  **The cell held a bucket, not the reading.** `_probe_char` maps a value onto
  0-9 across `--range`, so `gpssat --range 0:32` drew `8` for 28 — a number the
  reader has to decode against the range to get back to what was measured. The
  cell is now sized from the range (`_probe_cell_width`, the same shape as
  `_rtt_cell_width`) and holds the reading, exactly as the `rtt` view holds a
  latency. The 0-9 glyph survives only in the details-overlay sparkline, which
  is one column per sample and carries its own axis labels.
  **The colour came from the ping palette.** The strip is painted by matching
  the *character*: `'01234'` green, `'56789'` yellow, because for latency a
  high number is a slow reply. Nothing about a probe reached that decision, so
  28 of 32 satellites drew yellow for being **good**. Cells are now coloured by
  the probe's own `--warn`/`--crit` (`_probe_strip_attr`), which is how its
  column and the overlay already judge a reading; a probe with no thresholds is
  uncoloured rather than wrong. The comparison is against the value *as drawn*
  (the cell is rounded), so a cell and its colour cannot disagree.
  **It ran backwards.** The ping strip puts the newest sample on the left
  (measured: `'90 80 70 60 50 40 30 20 10 '`); the probe strip appended
  chronologically and padded on the left, putting it on the right. `:set
  ping-view` swaps one for the other **in the same columns**, so a probe series
  appeared to run against the bar it replaced. Nothing chose that — the test
  that pinned it was named `test_short_series_is_right_aligned` and its
  docstring claimed "as the ping strip is", which was simply not true. The
  overlay sparkline still reads left to right, deliberately: it is labelled
  `^ 38 min ago … now ^` and sits among `Min / Max` and `Average`.
  **A 7th `[Probes]` help tab** appears when a `:probe` is declared, listing
  what each one reads — range, thresholds, unit, the column header it draws,
  a group's members, and the script being shipped with the file it resolved to.
  Those all come from the hosts file, so nothing else in the overlay can know
  them. Appended, never inserted: the `1`-`6` overlay keys and every `:help <n>`
  in a hosts file depend on the six standing numbers. `_resolve_help_tab` had
  to stop being a `@classmethod` to see `probe_defs`.
- **Phase 21 (several readings in one column)**: `:probe <name> --combine a,b,c`
  joins its members' latest readings with `/`, so `GPS s/off/sat` over
  `0/0/29` costs one header instead of three each wide enough to name
  themselves — which is what an 80-column kiosk console has room for. A group
  has no reading of its own: `--unit`/`--range`/`--warn`/`--crit` are refused
  on it and belong on the members, `--label` is the header used verbatim (no
  unit appended, since one member's unit would label the whole column with a
  third of the truth), `:set ping-view` needs a single series and so names a
  member, and the details overlay skips the group because its members are
  already there. The cell takes its **worst** member's colour, with "nothing
  read yet" ranking above "fine" — a dim cell says a field is missing where a
  green one would not — and collapses to a single `-` or `err` when no field
  has a reading, because `-/-/-` on the fifty hosts of fifty-four that carry no
  sensor is punctuation saying what one `-` says.
  **An undeclared member is declared implicitly** (`setdefault`), because the
  reader drops any key with no `:probe` and the overlay needs one per
  sparkline; an explicit declaration wins whether it comes before or after.
  That convenience is also where the two bugs were, both caught in review
  rather than by the tests:
  1. `setdefault` bypassed the guard that stops a probe being named after a
     built-in stat. `:probe g --combine avg,last` created a `ProbeDef('avg')`
     whose label `Avg` then resolved ahead of the built-in, so **two columns
     the user never mentioned read `-` for the rest of the run**, silently.
     `drift`/`rtime` were worse: `_clock_enabled` looks for those labels in
     `stats_custom`, so shadowing them stops the clock probe being started at
     all. Members now get the same guard, plus rejections for a member that is
     itself a group (no reading to join) and for a repeated member.
  2. `_save_config` wrote `stats_custom` — which holds **labels** — lowercased,
     and `:set stats` reads **names**. That round-tripped only while a label
     happened to equal its name, which `--label` made untrue and `--combine`
     makes untrue by design: `:set stats gps s/off/sat` refuses itself, so
     every column was lost on the next start. `_stats_custom_tokens()` is now
     the single place that turns columns back into a settable argument.
  A `--combine` group is skipped by `ProbeReader._fail_all`, which would
  otherwise build a `ProbeSeries` under a name nothing reads.
- **Phase 20 (the history bar costs a screen width, not a day of samples)**:
  `get_history_string` copied both history deques in full and walked them, in
  *both* branches, to fill the `length` cells a bar actually shows.
  `:set history-size` defaults to 86400 — 24 h at one ping a second — and
  `_section_summary` repeats the work for every host a section covers, so the
  cost grew with uptime rather than with the bar. **Measured on a 54-host
  production screen at 100 columns**: 17 ms per redraw after ten minutes,
  75 ms after an hour, 402 ms after five and a half hours, 1.8 s once the deque
  filled. The draw loop runs on a 100 ms `getch` timeout, so that *is* the key
  latency — reported as "every keypress takes about a second after a while",
  and the main thread held 14451 s of the process's 14662 s of CPU, 95 % of it
  in this one function. Now both branches walk the deque backwards and stop
  once the samples are older than the window (plus `_SYNC_SCAN_GRACE`, because
  a lost probe is dated when it was *sent*, so `history_times` is not
  monotonic): **0.07 ms, flat at every uptime**. The rebuilt tail is put back
  in order before the bucket loop — that changes no cell today, since
  `_worse_hist_sample` is symmetric over every value these deques hold, but it
  has a tie-break returning its *first* argument and an ordering this loop no
  longer guaranteed would be a silent wrong reading the moment that branch
  becomes reachable. `tests/test_history_scan_bounded.py` asserts the *read
  budget* rather than a wall-clock ratio; at 0.07 ms a timing assertion
  measures noise and would flake under `-n auto`.
- **Phase 19 (probes choose their hosts, their login, and bring their own
  script)**: `:probe-source` opened a connection to *every* monitored host and
  passed no ssh options, which made it unusable on a real mixed file — 54
  hosts including cameras and MikroTiks, each authenticating as the local user
  and the ones with no shell holding a failing connection on a backoff loop for
  the life of the run. Three additions fix that, and one more was asked for:
  `--hosts <globs>` (matched like `:no-alarm`, against the name *and* its
  `:resolv` alias, which is what a `##` label becomes); the host's own
  `:prog-options ssh` rule now supplies the probe login, with `--disable` there
  meaning no probe connection either — every other ssh path already respected
  those rules; `--script <local file>`, which carries the file inside the
  remote command as base64 so **nothing is installed on the host**; and
  `:probe --label TEXT` for the column header, since the default capitalises
  the name and heads a `gps` column `Gps`.
  **Base64 is not decoration.** Inlining the same shell in `--cmd` was tried
  first and cannot work: a hosts file expands `$name` at parse time and reads
  `$1` as a `:for` backreference, so an awk body came back shredded as
  `probe-source: unknown argument`. A base64 payload has no `$`, quote or
  backslash, so the hosts parser, `shlex`, `shlex.quote` and the remote shell
  all pass it through. It is decoded once per connection into `$_pb` and run as
  `sh -c "$_pb"` — not piped into `sh`, which would spend the script's own
  stdin, and not written to a temp file, which would need cleanup that a killed
  ssh never runs. Needs `base64` on the target. A relative `--script` path
  resolves against the hosts file's directory, falling back to the link
  target's when that file is a symlink: `:log` uses abspath so a log lands
  beside the name that was typed, but a log is *written* and a script has to
  already be there.
  A `ProxyJump` in a `:prog-options` rule cannot displace a relayed host's own
  chain, which is placed first — ssh keeps the first value of a repeated
  option, so no ssh-option parsing is needed to guarantee it (§9a).
  **Found while using it, and worse than the missing feature**: `:set stats`
  refuses the *whole* line on one unknown column, and a probe name is unknown
  until its `:probe` has been read — so a hosts file that names a probe column
  above its declaration silently lost every column and fell back to the default
  single `ms` one. The refusal was logged under category `cmd`, which is
  `LEVEL_INFO`, while the default log level is `LEVEL_NORMAL`, so **nothing
  appeared on screen at all**; it was reported as "my settings did not survive
  a restart". It now reports at `LEVEL_NORMAL`, says the previous columns are
  kept, and names the ordering rule.
- **Phase 18 (relays that do not run Linux)**: `:remote-ping` works through
  FreeBSD/OPNsense and MikroTik RouterOS relays. Declared with `--os
  auto|linux|freebsd|mikrotik` on the directive or a `:relay-os <glob> <os>`
  rule (matched like `:no-alarm`, flag beats rule, last rule wins);
  `auto` (the default) probes each relay once with `uname -s` — RouterOS
  answers `bad command name` — cached per `tuple(ssh_args)`, connection
  failures fall back to linux uncached. **The retry pause is stamped only
  after a probe has failed, never before one runs.** Stamping it up front let
  the pre-lock fast path fire while the first probe was still in flight, so
  the other monitors behind that relay skipped the per-key lock they were
  meant to wait on and took the linux fallback for the whole 60-second pause
  — `ping: illegal option -- O` once per host against a FreeBSD relay, until
  each one's backoff came round again. Measured with six threads and one slow
  probe: five wrong verdicts, one right. It was never reload-specific; an
  `:edit` reload just makes every monitor arrive at once. Per-OS profiles
  (`_RELAY_OS_PROFILES`) supply the argv (`/ping` on RouterOS, plain `ping`
  behind an `echo PING-BULK-READY` preamble on FreeBSD), the parser, and the
  loss model. **Everything measured on the real machines** (FreeBSD 14.3,
  RouterOS 7.22): RouterOS prints one row per second forever with no
  `count=`, its `timeout` rows reuse the `-O` `_pending` back-dating, and an
  ICMP-error row names the *reporting* router in HOST with that router's own
  TIME — a row with status text is a loss no matter its TIME, so only the
  exact five-token shape is a reply. FreeBSD has no `-O` and a down target
  produces zero stdout (the banner is stdio-buffered until the first reply),
  so losses are synthesized from silence at ~1/s after the ready marker and
  reconciled against the next reply's icmp_seq; the stale kill is disabled
  for that profile and `ServerAliveInterval=5` turns a wedged link into a
  child exit. Clock probe (`Drift`/`RTime`) verdicts `no-remote-time`
  immediately on both. `ProbeReader`'s `while` loop now runs under `sh -c`
  (FreeBSD root logs in with csh). A `channel open failed:
  administratively prohibited` stderr gets a one-time tip naming
  `/ip ssh set forwarding-enabled=both`. Fatal wordings extended per OS
  (`cannot resolve`, `bad command name`, `failure: resolve failed`).
  Tests: `tests/test_relay_os.py` (51 tests, fixtures are verbatim captured
  output).
- **Phase 17 (folding follows the marker; a silent log is no longer possible)**:
  A `:no-alarm` host that is down no longer counts as down for a fold
  decision — `_counts_as_down()` is the single predicate behind `autofold`,
  the `(autofold lock)` label, `z[`/`z]` and the section badge, so they cannot
  disagree. A folded list now releases its rows: the main draw loop sizes the
  host area from `_get_visible_entry_indices()` rather than `len(self.entries)`,
  which folding does not change.

  **The observability lesson worth keeping.** A user reported "the log stops
  while the script keeps running", and the code had exactly one way to do that
  in silence: `check_state_changes` is the **only** producer of host
  up/down/recover events, it runs in one unguarded daemon thread, and Python
  sends a dying thread's traceback to stderr — which under curses is painted
  over by the next redraw. So one escaped exception ended the event log for the
  rest of the run while pings, history and the UI carried on looking healthy.
  Three fixes, in order of value:

  1. `threading.excepthook` reports any thread death into the event log. It
     chains to the hook that was there (pytest installs one), and a failure
     *inside the report* is swallowed so it cannot cascade. This also covers a
     `monitor.ping` thread dying, which silently stopped probing one host
     forever.
  2. `check_state_changes` is split into `_state_pass` / `_monitor_pass` with a
     `try/except` per monitor and one around the sweep. Reported once per
     (site, exception type), so a *different* fault at the same host is still
     news — one bad host must not cost the other 58 their events.
  3. `_append_log_line` catches `Exception`, not `OSError`, opens the file as
     explicit UTF-8, reports the first failure on screen only
     (`add_event(..., to_file=False)` — reporting through the broken file would
     recurse) and reports recovery. **Measured**: under `LC_ALL=C` the banner's
     em dash raised `UnicodeEncodeError` — a `ValueError`, so it walked
     straight past `except OSError`, out of `add_event`, and killed the caller;
     the log file was left at 0 bytes. A service unit with no `LANG=` was
     enough.
  `:log` with no argument now answers "broken, or just quiet?" — path, lines
  written this session, file size, and the last write error with its time.

  **The same bug was still in the config path, and there it was fatal.**
  `_create_default_config` writes `# Generated on first run — edit as needed.`
  and runs from `Application.__init__`, so under `LC_ALL=C` a machine with no
  config yet could not start ping-bulk at all — the `UnicodeEncodeError` left
  the constructor. Reproduced with `LC_ALL=C PYTHONUTF8=0
  PYTHONCOERCECLOCALE=0` against a fresh `XDG_CONFIG_HOME`; Python 3.7+ coerces
  a bare `LC_ALL=C` to UTF-8, so all three are needed to see it. The fix is the
  one above applied to **every** file this program writes for itself — the
  config and the command history, six handles — each opened as explicit UTF-8
  and each guarded with `except Exception`. Reads take `errors='replace'`, so a
  config hand-edited in another encoding degrades to a visible replacement
  character instead of costing the user their settings.

  **A stale `$LINES` froze the layout, and the obvious fix made it worse.**
  ncurses prefers `$LINES`/`$COLUMNS` over the kernel's window size (`use_env`
  is TRUE by default), so a shell that exports them leaves this program drawing
  the old geometry after every resize — SIGWINCH arrives, the pty really is the
  new size, and ncurses ignores both. Measured in a pane carrying `LINES=40`:
  shrinking to 15 rows left the help overlay drawing 40, its top border
  scrolled off screen, unrecoverable without a restart.

  `main()` deletes the two variables before `curses.wrapper`. **Not
  `curses.use_env(False)`** — Python's curses module does not wrap
  `use_tioctl`, and with that unavailable, disabling `use_env` makes ncurses
  fall back to *terminfo's* size instead of the ioctl: measured, the same
  40-row pane then rendered as 24. Removing the variables leaves the default
  `use_env(True)` with nothing to prefer, so it asks the kernel.

  The lesson that keeps recurring: **`except OSError` around a write of
  program-authored text is a bug**, because the interesting failure is an
  encoding one and that is a `ValueError`. If you add a file this program
  writes, name the encoding and catch `Exception`.

  **Sync mode was hiding losses**, reported as "why does sync show fewer X?".
  Two causes, both fixed: a bucket held the *last* sample written to it, so an
  `X` vanished under a reply that shared its second (now `_worse_hist_sample`,
  ranking from `_HIST_RANK`, which `_worst_history_char` also uses so a section
  header and its rows cannot disagree — resolved on the *value*, since a wide
  rtt cell holds a number and ranking its text would compare digits, and two
  replies keep the slower reading); and a loss was stamped when the verdict
  was reached, not when the probe was sent — `ping -O` reports an unanswered
  probe one interval late (**measured**: `ping -O -D` to a black hole printed
  `icmp_seq=1` at t0+1.005, `icmp_seq=2` at t0+2.010) and `_expire_pending`
  added `late-grace` on top, so the cell landed one to two seconds after its
  probe, in a second belonging to a later one. `_probe_send_time()` subtracts
  the interval; a late reply is dated the same way. `history_times` is no longer
  monotonic as a result — nothing reads it in order (checked: the sync bucket
  loop, the two deque resizes, and the `:edit` snapshot).  `_record_stale_loss`
  dates the probe it consumes the same way, so one event cannot land in two
  different seconds depending on which path noticed it.

  **`self.events` is a deque, and background threads append to it.** A user hit
  `RuntimeError: deque mutated during iteration` out of `_draw_details_overlay`;
  the same loop existed in the display-filter rebuild and in `save_to_file`,
  where it also escaped an `except OSError` that a `RuntimeError` is not. All
  three now go through `_events_snapshot()`. **Measured**: a Python-level
  `for e in self.events` failed 186 times in 7k attempts under a hammering
  writer, while `list(deque)` failed 0 times in 26k — on a GIL build it is one
  C call that never yields the GIL part way, so the snapshot needs no lock (on
  a free-threaded build that argument does not hold and this would need one). If you add a
  loop over `self.events`, use the snapshot. `_filtered_events` is a plain list
  and cannot raise, but it is trimmed from the front, so an index taken while
  walking it can point at the wrong line — the log-search builder copies first.

  **A reported thread death is not a recovered one.** Asked "is there a log
  thread, and does it restart?" — there is none (logging is synchronous inside
  `add_event`, which is *why* it recovers: no state, just the next `open()`),
  but the question exposed that a dead `monitor.ping` thread was reported and
  then left dead, taking that host off the display for the rest of the run.
  Three parts:

  - every `threading.Thread(...)` now passes `name=` (`ping:<host>`,
    `probe:<host>`, `clock:<host>`, `dns:<host>`, `state-loop`); a death report
    names the thread, and `Thread-42 (ping)` named nothing.
    `tests/test_thread_supervision.py` greps the source to keep it that way.
  - `_supervise_monitor_threads()`, run from `_state_pass` (which cannot die),
    restarts a loop whose thread has ended while the monitor is still running
    **and carries no `error`** — a fatal error is a deliberate `break`, not a
    crash, and restarting it hits the same wall. Capped at
    `_MONITOR_RESTART_LIMIT`, paced by `_MONITOR_RESTART_PAUSE`, and the
    give-up is logged once as "no longer being probed". `_start_monitor_thread`
    publishes `monitor._thread` *after* `start()`: a created-but-unstarted
    thread reports `is_alive()` False, which the supervisor would read as a
    loop to restart.
  - `_read_until_exit()` was the only unguarded call in `ping()`, and it is the
    one that parses child output; a fault there now costs one probe (reported
    through the stderr machinery, capped like the child's own messages, so once
    per distinct text) instead of the thread. `_run_clock_probe` clears
    `_clock_probing` in a `finally` — leaving it set froze that host's Drift
    with nothing retried.

    **A caught reader fault must not reach `_is_fatal_error`.** The first cut
    set `got_output = False`, which fed the post-exit classification and turned
    a transient `network is unreachable` (printed per probe while ping carries
    on) into a permanent kill — *and* set the `error` that makes the supervisor
    skip the host, so dead-but-restartable became dead-and-never-restarted.
    Measured both ways. A run whose reader failed is not a run that produced
    nothing; it is a run we did not finish reading, so `reader_failed` skips
    the classification while the backoff still grows.

  **The process names itself, in ps and in top.** Every thread starts through
  `_spawn(target, name)`, which sets the Python thread name (full, for a death
  report) *and* the kernel's `comm` via `prctl(PR_SET_NAME)` (`_os_task_name`,
  15 bytes, trimmed from the front of the host so `ping:23.254.161` survives
  instead of `ping:ses-wg-vid`). `main()` also rewrites the `COMMAND` column
  of `ps aux` — `_set_process_cmdline` writes over the argument vector in
  place, whose bounds the kernel publishes as `arg_start`/`arg_end` in
  `/proc/self/stat`. It writes only if that region still holds exactly what
  `/proc/self/cmdline` reports, never past `arg_end` (the environment lives
  there — `arg_end` *is* `env_start`), always leaving the last byte NUL, and
  fails silently. **The terminator is the subtle part**: without it the
  kernel's own read of `/proc/self/cmdline` runs past `arg_end` and returns
  environment variables as part of the title — measured, a 58-byte region came
  back as 86 bytes ending in an `AGENT_SESSION_ID=…`.

  Two dead ends, both measured, so nobody repeats them. `Py_GetArgcArgv` — the
  trick every recipe names — returns the interpreter's own `wchar_t` copy on
  the heap in Python 3, so there is nothing there to overwrite; use
  `/proc/self/stat` instead. And **do not wrap the launcher in bash's
  `exec -a`**: it does clean up the column, but Python finds its prefix by
  resolving argv[0], so any argv[0] that is not the interpreter's own path
  costs a venv interpreter its venv — `sys.prefix` silently becomes `/usr` and
  it loads the system site-packages. Measured with the same interpreter and
  only argv[0] changed. It also cannot honour the script's own `#!` line and
  hardcodes an interpreter.
  **A section title wider than the terminal killed the display.** The
  hostname column is sized from content — the longest name, the longest
  section title — and knew nothing about the screen, so `stat_col` landed past
  the right edge and the column header wrote there with a bare `addstr`:
  `_curses.error: addwstr() returned ERR`, the whole draw dead. Measured:
  `examples/ping-bulk.advance` (65-character title) died at 60 and 80 columns
  and drew at 90+. Two parts, and both are needed: `draw_hosts` clamps
  `name_col_width` so the stats and `_MIN_HIST_COLS` of history always fit,
  and every write whose start column is a computed layout offset now goes
  through `_safe_addstr`. **ncurses returns ERR only when the *start* position
  is off screen** — an overflowing string is clipped silently — which is why
  the guard belongs on those and not on the padded strings. The clamp alone
  would still crash (the badge field widens the per-row stat cell by up to 9
  columns past what the header uses); the guards alone would draw a row with a
  name and nothing else. `tests/test_wide_title_crash.py` drives `draw_hosts`
  against a fake window that raises like ncurses, and each half is verified to
  fail when the other is removed.

- **Phase 16 (probes, SSH hygiene, expected-silence hosts)**:
  `:probe-source` + `:probe` read arbitrary per-host values over **one
  persistent SSH connection per host** (`ProbeReader` on the shared
  `_PipeReaderLoop`), shown three ways — a stats column, the history strip
  (`:set ping-view <probe>`, one cell per reading), and a sparkline block in
  the details overlay. `:no-alarm <glob>` / a `~` host-line prefix / `:with
  no-alarm` mark hosts where a lost reply is *expected*: dim `o` instead of red
  `X`, a separate `1○` badge segment, events demoted to `info`; `o` toggles it
  per host. `:set ssh-options` puts sane defaults on ping-bulk's own
  connections (no X11, no forwardings), and `:set ssh-connect-rate` (5/s)
  paces them per relay. Sync mode marks seconds with no ping process as `_`.
  `--dump-simple-script -` writes to stdout. `:log` gained `$SCRIPT_DIR`,
  environment fallback and a session banner. `Connect:` in the details overlay
  is rendered from the `c` binding; `C` pre-fills that command for editing and
  `X` took over clearing the log.
  Bugs fixed, all found by measuring rather than reading: `ControlMaster=no` is
  ssh's *client* mode, so it made every monitor join one master and hit
  `MaxSessions` (`ControlPath=none` is the real switch); connections were
  opened in a 10 ms burst that tripped `MaxStartups` ~10 times per startup;
  `hosts_map or {}` gave the first monitor a private copy of an empty map, so
  it never saw later `:resolv` entries; the `;` splitter ignored quotes, which
  truncated a quoted command *and* broke the documented multi-command
  `:bind-key`; an exact `:prog-options` pattern lost to a later glob; `c` on a
  relayed host connected to the relay instead of through it; a fixed host under
  an inline `:if` warned about missing back-references.
- **Phase 15 (log file paths + session banner)**: `$SCRIPT_DIR` / `$SCRIPT_FILE`
  are predefined while a hosts *file* is parsed (`abspath`, not `realpath`;
  seeded in `_HostsParser.parse_file`, so a `:source`d file gets its own), which
  makes `:log $SCRIPT_DIR/$SCRIPT_FILE.log` portable. `$name` now falls back to
  the environment after `:let`. Undefined names still expand to `''` — the
  `${fold$N}` idiom in `examples/ping-bulk.advance` depends on it — but are
  warned about inside a `:log`/`:save`/`:source` path (`_PATH_DIRECTIVES`),
  where the truncation is silent and harmful. New `_resolve_path()` expands a
  leading `~` for every path command; `$` is deliberately *not* re-expanded
  there, since parse time already did it under different rules. The streaming
  log opens with a `# ###### log started …` banner (pid, hosts file, target
  count), written lazily on first append and tracked per path so switching
  files — or `:log off` then on — marks the resumption.
  Bugs fixed: `:log ~/x.log` and `:save --follow ~/x.log` silently logged
  nothing, because `open('~/…')` failed into the `except OSError` that exists to
  stop error events recursing; a hosts-file `:log` silently beat `-l`
  (`self.log_file` was assigned before the entry loop, not after); `hosts_file`
  and `kiosk_mode` were assigned *after* `Application.__init__`, so every
  `_kiosk_allow_path` check was inert for startup commands and `:edit` could not
  see the file — both are constructor arguments now; the `:layout` table in
  `doc/ping-bulk.rst` was malformed (one stray space), so `docutils` refused to
  render that section.
- **Phase 14 (event log + help overlay)**: Filter and search switched from
  glob/substring to case-insensitive regex (invalid patterns fall back to
  literal). `:fold close-other [regex]` / `zx` focuses one section. `:save`
  writes the event log — a snapshot by default, streaming only via `--follow`
  or the `[w]`/`[f]` prompt step — bound to `W`. `:help` now takes a tab
  (number 1-6, name, prefix, `next`/`prev`); `:help-tab` and `:saveconfig` were
  removed outright (renamed to `:help` and `:save-config`); `:man` aliases
  `:help`; `?` opens the Bindings tab.
  Bugs fixed: the `[Space]` seen marker never rendered (`mark_seen` skipped the
  `_filtered_events` cache); `z[`/`z]` were documented but unbound (dead
  `_handle_z_sequence`); overlay lines carrying `:colorname` markup were cut by
  the markup's length because sizing used rendered columns but slicing used raw
  characters; overlay nav keys could not be rebound (nav handler ran before the
  trie); a long log path pushed the Events key hints off screen.
- **Phase 12 (syntax cleanup)**: `:ssh` renamed to `:remote-ping`, `:ssh-begin`/`:ssh-end` renamed to `:remote-ping-begin`/`:remote-ping-end`. Added `:prog-options-begin <prog>` / `:prog-options-end` block form for grouping multiple prog-options rules under one program. No backward compatibility. 9 new tests added.
- **Phase 11 (vim-style UX)**: `:unbind-key <key>` removes a binding; `:bind-key <key>` (no cmd) now queries what's bound; `G`/`gg`/`Ctrl-F`/`Ctrl-B` vim navigation defaults; `:fold` word aliases (`open`, `close`, `open-recursive`, etc.); help overlay shows `:command` annotations per hotkey; `/` context-aware search (host list or event log) with `n`/`N` navigation.  (The all-bindings view is now help tab 5, reached with `?`, `5`, or `:help bindings` — the old `A` toggle no longer exists.)
- **Phase 10 (log levels)**: `quiet/normal/info/debug` log levels via `:set loglevel`, `-v`/`-q` flags, event coloring by severity.
- **Phase 9 (`:edit` improvements + `:resolv` warning fix)**: `:edit` command enhancements, resolv warning deduplication.
- **Phase 8 (command flags + key binding system)**: Full flag consistency refactor, `:bind-key` rename, `:quit --confirm` re-press pattern, data-driven overlay dispatch, `--mode`/`--desc`/`--hint` flags, bottom-bar hints moved from hardcoded Python to user-configurable trie entries.
- **Phase 7 (`:if`/`:elif`/`:else`/`:fi` conditionals)**: Hosts-file conditionals with variable expansion, usable both inside and outside `:for` loops.
- **Phase 6 (`:prog-options`, mux variables, port monitoring)**: `:prog-options` command, `%r/%d/%j/%R` template variables, TCP port monitoring via `PortMonitor`, inline `##` display-name syntax.
- Fixed an `OverflowError` bug in `PortMonitor._resolve_port` when `socket.getservbyport` fails with an out-of-bounds port.
- Refactored the monitor class hierarchy to use a proper abstract base class (`Monitor`) for improved extensibility.

## 9. Monitor Class Architecture

The monitor classes use an abstract base class pattern to unify ICMP and TCP monitoring logic.

### Structure
- `Monitor` (ABC) - Abstract base class with common attributes and shared methods.
- `SubprocessMonitor(Monitor)` - Owns the Popen/read/backoff loop shared by the two
  ping transports. `PingMonitor` and `SshPingMonitor` each used to carry a
  near-identical copy.
- `PingMonitor(SubprocessMonitor)` - Standard ICMP ping implementation using system `ping`.
- `SshPingMonitor(SubprocessMonitor)` - SSH-based remote ping monitoring.
- `PortMonitor(Monitor)` - TCP port monitoring using Python's `socket.create_connection`.
  Not a `SubprocessMonitor`: it has no child process.

### `SubprocessMonitor` invariants — do not regress these
- **Both pipes are always read.** Reading only stdout lets the child fill the
  stderr pipe and block in `write(2, …)`; it then stops pinging *and* stops
  writing stdout, while the parent waits on stdout forever. Nothing recovers.
- **Raw fds, not `readline()`.** `select()` cannot see a line already buffered
  inside a `TextIOWrapper`, so the loop `os.read()`s and splits on `\n` itself.
- **stderr is classified only after the child exits.** `'network is unreachable'`
  is in `_FATAL_PING_ERRORS`, but ping prints it *per probe* while continuing to
  run — classifying mid-stream would permanently kill a host over a transient
  route flap, and `self.error` has no reset path anywhere.
- **A silent child is killed, not just reported.** After `_STALE_MAX_WINDOWS`
  empty read windows the child is terminated so the backoff loop replaces it —
  a stuck process neither exits nor speaks, so nothing else would ever end that
  state. Gated on having seen output first, or a slow SSH connect would be cut
  short in a loop. **"Silent" means no bytes on either pipe, not "no line this
  parser understood."** Measured the hard way: counting staleness from the
  last parsed *result* killed every host that answers with an ICMP error
  (`From … Destination Host Unreachable` matches neither `time=` nor `no
  answer yet`), and a 52-host production run logged 50 restarts and 13
  `Broken pipe` in one minute where the previous build had one restart in
  fourteen hours. A transport that needs result-recency instead — FreeBSD,
  whose stderr chatter would otherwise mask its only loss signal — gets it
  through `_stale_without_output`, and those windows never count towards the
  kill. **Exception:** the FreeBSD relay profile — FreeBSD ping has
  no `-O` and (measured) a down target produces *zero* stdout; even the PING
  banner sits in ping's stdio buffer until the first reply flushes it, so
  silence there means "target down", not "child wedged". That profile
  synthesizes ~1 loss/s from silence (reconciled against the next reply's
  icmp_seq so nothing is billed twice), disables the stale kill, and hands
  wedged-link detection to `ServerAliveInterval=5` (ssh exits → the backoff
  loop respawns). Silence only counts once the `echo PING-BULK-READY`
  preamble proves the session up (`_stale_without_output`).
- Subclasses override only `_build_ping_cmd()`, `_is_fatal_error()`,
  `_prepare_spawn()`, and the class attributes `_STALE_SECS` /
  `_STALE_MAX_WINDOWS` / `_trust_ping_timestamp`. `SshPingMonitor` further
  dispatches per relay OS through `_RELAY_OS_PROFILES` (linux/freebsd/
  mikrotik): the profile picks the remote ping argv (`ping -O -D` / plain
  `ping` / `/ping`), an optional stdout parser, the silence policy above,
  extra fatal-stderr wordings, extra ssh options, and whether the
  `-T tsandaddr` clock probe can work (`no-remote-time` verdict is immediate
  when it cannot). The OS comes from `--os` on `:remote-ping`, else the last
  matching `:relay-os` glob rule (matched like `:no-alarm`), else one cached
  `uname -s` probe per relay (`_detect_relay_os`; RouterOS answers `bad
  command name`, and connection failures fall back to linux *uncached* so a
  relay that is down at startup is not branded forever).

### Method Categorization

*Abstract methods (implemented by subclasses):*
- `ping()` - Main monitoring loop.
- `_build_ping_cmd()` - Build command for subprocess (used by `PingMonitor` and `SshPingMonitor`).
- `_is_fatal_error(stderr_text)` - Determine if an error is non-retryable.

*Shared/Overridable methods (in `Monitor` base class):*
- `resolve_dns()` - Resolve host to IP/hostname.
- `get_display_name(dns_mode)` - Format display name according to DNS mode.
- `get_history_string(length, offset, mode, cell_width)` - Format ping history visualization.
- `stop()` - Stop monitoring and cleanup.

### Common Attributes (in `Monitor` base class)
- `host`: Target hostname/IP or display name.
- `resolved_ip`: Forward DNS resolution result.
- `resolved_hostname`: Reverse DNS resolution result.
- `alive`: Current status (True/False/None).
- `latency`: Last measured latency in ms.
- `history`: deque of ping results.
- `latencies`: List of all successful latencies.
- `rx_count`, `xx_count`, `ping_count`: Statistics counters.
- `last_state`, `down_since`, `up_since`: State tracking timestamps.
- `running`: Control flag for monitoring thread.
- `lock`: Thread synchronization.
- `error`, `error_logged`: Error tracking for fatal process errors.
- `_proc`: Subprocess handle (if applicable).
- `resolv_static`: Flag for static DNS mappings.

## 9d. The web listener

The program's first inbound socket. It runs on one thread inside this process
and reads the same live state the curses view reads — not a separate engine
behind a protocol. mtr splits `mtr-packet` out for privilege separation and
that engine is *stateless*; here the engine **is** the statistics owner
(Welford accumulators and history deques live on each `Monitor`) and nothing
needs privileges, so a split would move the whole stats layer across a
boundary and buy nothing.

**What it will answer to is decided in one place**, `_handle`: GET serves the
page, the assets, `/api/state` and `/api/host/<uid>`; POST reaches only
`/api/login`, `/api/cmd` and `/api/host/<uid>/<verb>`, and any other path is a
404. What a write may then *do* is a separate question, answered by
`:set web-commands` and the safe allowlist below.

Each control below answers a specific way it could go wrong.

- **`Host:` is pinned.** Binding to loopback is *not* a boundary against a
  browser: a page the operator visits can resolve a name of its own choosing
  to `127.0.0.1` and treat the reply as same-origin (DNS rebinding), because
  the request comes *from* the browser on this machine. Anything outside
  `_web_allowed_hosts()` gets 421. A loopback bind needs no configuration for
  this; a listener reached by some other name must declare it with
  `:set web-hosts`, because the alternative — inferring the set — is the same
  as not checking.
- **The client allowlist is checked before routing**, so an address outside
  `:set web-allow` learns nothing about which paths exist.
- **CSP `default-src 'none'; script-src 'self'`**, with no inline script and
  no `on*=` attribute in the page. Assets are separate HTTP resources served
  from a constant in this file — `script-src 'self'` needs separate
  *resources*, not separate *source files*, so the single-file rule survives
  intact. The client uses `textContent`, never `innerHTML`, and `_web_json()`
  escapes `<`, `>`, `&`.
- **HTTP/1.0, so the server closes each connection.** Keep-alive would hold a
  thread per idle browser tab and `ThreadingHTTPServer` has no cap of its own;
  those threads would sit beside dozens of ping subprocesses. `verify_request`
  adds a hard cap (`_WEB_MAX_CONNECTIONS`) and `setup()` a socket timeout, so
  a client that connects and says nothing cannot hold a thread.
  **Only an admitted request gives its slot back**, which is why `_admitted`
  exists rather than a bare counter: `socketserver._handle_request_noblock`
  calls `shutdown_request` on its *refusal* branch too, so decrementing
  unconditionally returned a slot that was never taken and every refusal
  admitted one more client. Measured: 3000 attempts against a cap of 16 left
  **1508** live handler threads, and the descriptors they held made
  `SubprocessMonitor` fail to respawn `ping` and `ssh` — an unauthenticated
  flood stopped the monitoring. `verify_request` runs at `accept()`, before
  `_client_allowed`, so `:set web-allow` is no defence against this and the
  accounting has to be right on its own.
  **The access log is not written unless asked for.** `log_message` reported
  every request — including ones refused at 403, 421 and 404 — as a
  `LEVEL_DEBUG` event, and a log file records every level by design (§12), so
  an unauthenticated client could manufacture events at 1117/s: the
  10 000-entry deque of real host history was gone in about nine seconds and
  some 6 GB a day went to disk. The event is now built only at `-vvv`, where
  the operator asked for it and accepts the volume. Nothing diagnostic is
  lost: `handle_error` and the 500 branch report at `LEVEL_NORMAL` in their
  own right.
- **`allow_reuse_address`**, because the kiosk unit is `Restart=always` and a
  restart otherwise races its own `TIME_WAIT` sockets and the bind just fails.
  With that already handled, an `EADDRINUSE` means something genuinely holds
  the port — nearly always a second copy of this program — so the bind still
  **refuses** by default rather than sliding to another port and hiding it. A
  trailing `+` on `:set web-listen` opts into a bounded scan
  (`_WEB_PORT_SCAN`, 16 ports) and reports where it landed at `LEVEL_NORMAL`,
  because the configured port is what a bookmark, a firewall rule and `:set
  web-allow` were written against. Only `EADDRINUSE` is walked past: retrying
  a permission error sixteen times buries the reason under the last attempt's
  port number. The marker has to survive `_cmd_web_listen`'s normalisation —
  that function rebuilds the string as `host:port`, so the first cut dropped
  the `+` there and again in the `:save-config` that writes it back, and the
  scan silently never ran. Port `0` is a different thing and already existed:
  the kernel picks, and picks a different one every start.
- **Nothing reaches stderr.** `log_message` and `handle_error` are overridden
  to report into the event log: under curses the next redraw paints over
  stderr, which is exactly how "the log just stops" happened before (§8). A
  handler exception becomes a 500 plus an event, not a dead thread and a
  hanging request.
- **`:quit` closes the listener**, from `run()`'s `finally`, and `main()`
  installs a `SIGTERM` handler that sets `running = False` so that teardown
  actually runs under systemd. There was no signal handling in this program
  at all before.

### Who may read it

Two credentials, for two situations.

**A per-run token.** Minted at every `:web start`, printed as a whole URL, and
never written to the log file. `GET /?t=<token>` swaps it for a session
cookie and answers 303 to `/`, so the token leaves the address bar, the
history and any `Referer` after one use — and **the swap spends it**
(`server.token = None`). Leaving it live made a credential that is printed on
screen into a replayable bearer token good for the whole run, minting sessions
without limit; the 5-per-minute gate covers `/api/login` only, so replaying it
also evicted the operator's own session once 64 were held. `:web status`
mints a fresh link when the last was spent, so wanting a second browser does
not push anyone towards leaving it live.

**The link goes to the status bar, and into no event at all.** It used to be
reported twice — `to_file=False` with the link for the screen, `to_screen=False`
without it for the file — and the token therefore reached `self.events`. That
was accepted on a stated precondition: *"an authenticated session can read it
from `/api/state`'s event tail; that is not a new exposure, since such a session
already has everything the token would buy."* An anonymous read tier removes
that precondition, so the risk had to be closed before the tier landed. The
mechanism leaves no third option: `to_screen=False` returns *before*
`self.events.append`, so "on screen" **is** "in the deque" and no combination of
flags shows a line to the operator and to nobody else. `_web_announce_link`
therefore uses `_status_msg`, and the logged line carries the address without
the token plus the words `:web status`.

Two consequences worth keeping. **The status bar truncates, and half a token
looks exactly like a whole one** — it is drawn as
`msg.ljust(width - 1)[:width - 1]`, a hard slice with no ellipsis, and a
32-character token makes the full line 70 columns for `127.0.0.1:8765`, 87 for
a hostname bind and more for an IPv6 literal. On an 80-column console a
hostname bind cut *inside* the credential: the operator copies it, gets a 401,
and nothing says why — a worse failure than the disclosure being removed. So
the full form is used only when it demonstrably fits, the fallback leads with
the token where the slice cannot reach it, and below the width of the token
itself the bar says so instead of painting 29 of its 32 characters. **And there
is no screen while a hosts file is still loading**, which is why the logged
line names `:web status` rather than leaving the operator to guess.

**And a wildcard bind is announced as a real address.** `0.0.0.0` is where to
listen, not somewhere to browse: the banner read `http://0.0.0.0:8765/?t=…`,
which the operator has to translate before the link is any use to anyone —
against the whole reason it is on the status bar rather than in the log.
`_web_display_host` substitutes the first `:set web-hosts` entry that is an
address this machine holds, tested by binding it (the only answer that needs no
interface list). The locality filter is not cosmetic: one hosts file may name
both ends of a fleet so that it works on either, and the sensor-station file
does exactly that, listing the kiosk's address before the workstation's.
There is deliberately **no** check that the result is in `_web_allowed_hosts` —
that would be a tautology, since that function's last act is to add every
`web-hosts` entry — but the relationship is load-bearing (announce an address
from anywhere else, such as the default-route source address, and the
copy-paste ends in 421), so it is pinned by a test instead of by a guard that
cannot fire.

**The link got its own expiry**, `_WEB_LINK_SECONDS` (30 s), because the status
bar's existing values are 3 s for a `:set` report and 4 s for a refusal — long
enough to read a word, not long enough to transcribe a URL with a 32-character
credential in it into another machine's browser. That is also why `:web status`
re-minting stays: a transient channel is only acceptable while the thing it
carries can be asked for again, and re-minting is what stops anyone leaving a
token live so as not to lose it.

**A password file.** `:set web-password-file <path>`, holding either a plain
password or a `pbkdf2_sha256$rounds$salt$hash` verifier. Refused if it is
group- or world-readable, since the point is that the local user cannot read
it. **The verifier is never written to the config — only the path is.** That
is the answer to "where would a hash live?": under the kiosk unit
`ProtectSystem=strict` leaves the config directory writable by the service and
readable by the console user, and that user is exactly who kiosk mode guards
against. `/etc/<prog>/` is not.

**A non-loopback bind requires the password file**, because a token that dies
with the process is useless to a listener other machines keep returning to.
The refusal happens before the bind, so it is a policy and not an accident of
which addresses happen to be local. `:set web-anonymous` does not relax it:
the password stops being the way *in* and becomes the way to become an
**admin**, and a listener anyone may read and nobody may ever administer is
not worth offering.

**`:set web-anonymous off | read-only` — a reader who never signs in.** Off by
default, so an existing deployment is unchanged. It is for the case the
listener was asked for: a monitor on a LAN or a VPN that colleagues and wall
displays should watch without a credential.

Two settings, deliberately on different axes — `web-anonymous` says who may
*look*, `web-commands` says what a signed-in browser may *change*. They are
split in the code the same way: `_may_read()` is a **sibling** of
`_authenticated()`, not a widening of it, and `_write_gate` still calls the
narrow one. So there is no value of `web-anonymous` that reaches a write, and
turning reading on cannot turn writing on by accident. An anonymous caller is
handed `commands: 'read-only'` and no CSRF value: the page draws its buttons
from the first, so such a viewer gets a page without them rather than buttons
that 401.

**Declared under kiosk, never typed** — the rule `:web start` already follows,
and it is audited there like the bind. The
first cut refused it outright, reasoning that a reader who never authenticates
is further out than the console user. That is true and it is not the question:
that mode's threat is the person at the *keyboard*, and the hosts file is the
operator's own declaration. Refusing both is refusing the deployment the
setting exists for. `web-commands` stays absolutely refused because it is a
*write*, which no file should be able to hand to a console user either.

**What it publishes cannot be narrowed afterwards**, so it is stated rather
than discovered: every host name, address and `:resolv` alias, which together
are an inventory of the estate, plus the event tail. That tail is wider than
"errors": measured at the **default** log level it also carries `save`, `hosts`
and `resolv` events, and the first two carry **file paths** — a failed `:save`
names the path it could not write, a hosts-file warning names the file and the
line. Those paths are not otherwise exposed anywhere in the payload. `/api/host/<uid>` *is* redacted for these
callers (`_WEB_ANON_WITHHELD`): `cmd` is the whole ssh invocation including
key paths and the `-J` chain, `connect` is a command ready to paste into a
shell, and its per-host event list is **not** level-filtered, so it carries
debug lines the state tail withholds. Those three say how to reach the estate
rather than what it is doing; the readings stay, since they are what the
viewer came for. A denylist is right *there* and was wrong for the event tail,
because that dict is built field by field in one function — a new field is a
line in `_details_data`, next to the list.

**The page is served without a session; the data is not** — unless
`web-anonymous` says otherwise. `/` and `/static/*` carry nothing, and there
has to be somewhere to type the password. `/api/state` returns 401 and the
client shows a login form.

**A message that names one setting must name the other.** `_web_access_summary`
is the single phrase both `:web start` and `:web status` report, because the
`:web` command help had claimed "(read-only)" whatever `web-commands` said —
so the default, which lets a browser pause a host, described itself as
incapable of it.

**`Content-Type: application/json` is required on `POST /api/login`.** That is
a CSRF control, not politeness: a form on another site can only send the three
"simple" content types, so requiring JSON forces a preflight it cannot
satisfy. Together with the `Host` pin and `SameSite=Strict`, a foreign page
cannot drive this.

**The login throttle refuses; it does not sleep.** Five failures per client
per minute, then 429 — and a *correct* password is refused too while blocked,
or the throttle becomes an oracle for "that guess was close". Deliberately
**not** `_ssh_spawn_gate`, which paces by sleeping: that is right for outbound
connections on their own threads and wrong in a request handler, where
sleeping holds one of a bounded number of threads and hands an attacker the
denial of service the limit exists to prevent.

**Sessions are compared in constant time** (`hmac.compare_digest` against each
live id, not a dict lookup, which leaks by timing how much of a guess
matched), expire after 12 hours, and are capped so the dict cannot grow.

**TLS is optional and handshakes on the worker thread**, not in `get_request`:
in the accept loop one slow client would stall every connection waiting to be
accepted. A non-loopback bind without it warns every time, because the
password and every reading then cross the network in clear. For anything
beyond a small trusted network, bind loopback and put a real reverse proxy in
front — that advice has not changed.

### Writes

`:set web-commands read-only | safe`, default `safe`, forced to `read-only`
under kiosk — and that is the *default* there, not something corrected later
at `:web start`, because the default and what `:set` will accept have to
agree. `:web start` forces it again anyway, for a config written before kiosk
was switched on.

**Commands are addressed by uid, never by row index or by the cursor.** The
`:edit` reload rebuilds `entries`, and the page is showing a picture up to two
seconds old, so "pause row 7" can arrive after row 7 has become a different
host. Worse, `highlighted_index` is one cursor shared with whoever is at the
console — the party kiosk mode exists to distrust — so a command meaning "the
selected host" could be *steered* between the click and the tick.

**Nothing from a request touches state.** The server thread appends to a
bounded deque; `_web_drain()` runs at the top of the main loop's tick, moves
the cursor to the named host, dispatches, and restores the cursor in a
`finally`. Inside one tick nothing else can interleave. Going through
`_dispatch_cmd` is not incidental: that is where validation happens and where
the audit record is written.

**`_WEB_SAFE_COMMANDS` is an allowlist**, so a command added to this program
later must be considered before a browser can run it rather than being exposed
until somebody notices. A test asserts the set is a strict subset of
`CMD_REGISTRY` and that the dangerous names are absent.

**Host actions are explicit verbs (`pause`/`resume`), not a toggle.** A toggle
applied to a two-second-old view does the opposite of what was clicked.
`:pause-selected` gained `on`/`off` for this; bare still toggles, which is what
the `p` key wants.

**CSRF: `X-PB-Token`, derived not stored.** The session cookie is `HttpOnly`,
so the page cannot read it to prove a request came from itself. The token is
`hmac(per-run key, session id)`, handed out in `/api/state` — bound to the
session, so one lifted from another is useless, and nothing extra to store or
expire. The header alone would already suffice (a cross-origin page cannot set
it without a preflight this server never answers); binding it to the session
is the cheap second half.

**`_kiosk_audit` gained a `principal`.** It recorded the local user for both
sides, and "who did this" is the question an audit log exists to answer. Web
commands are audited whether or not kiosk mode is on, and logged at
`LEVEL_NORMAL` — someone off this machine changing what is monitored should be
visible without first turning the log up.

**`full` shipped, gated, and was then removed.** It offered the whole `:`
line over HTTP. Every gate the first design review demanded was built — opt-in
only, a warning naming the consequence each time it was switched on, refused
in kiosk mode, refused off loopback without TLS, re-checked on a running
listener so the setting could not outrun the binding — and all of them were
verified to work. It was removed anyway, for a reason none of the gates
addressed.

**Narrowing it was tried first and cannot work.** The obvious repair is to
subtract the commands that are incoherent over a request — `:mux` and `:term`
open a pane on the *console's* terminal, which the requester can neither see
nor type into — using the `_WEB_NEVER_COMMANDS` mechanism that already
excluded `:edit`. But `_web_command_allowed` derives the command name from the
**first token** and then returns True unconditionally in `full`, so `:source
<file>` hands over a file of arbitrary directives and `:bind-key x :mux sh`
hides one behind a keypress. Measured with the never-list grown to the whole
mux family: `:mux sh` refused, `:source` allowed, and a `:set web-commands`
line inside the sourced file took effect. Subtract the launderers as well —
`source`, `bind-key`, `set`, `probe-source` — and what is left is the
allowlist `safe` already is.

That is also why `_WEB_NEVER_COMMANDS` is gone rather than kept: with every
mode an allowlist it guarded nothing, since `edit` was never in
`_WEB_SAFE_COMMANDS`. A guard that does nothing is worse than no guard,
because the next reader believes it.

**The removal degrades; it does not reject.** `:set web-commands full` still
parses, warns, and sets `safe`, and `'full'` is absent from
`_WEB_COMMAND_MODES` so a `cycle` cannot land on it. Refusing the line
outright would cost the operator their configuration file, which this program
has already done to somebody once (§11, the `:set stats` report).

What was actually wanted was never "a shell" — it was particular commands.
Those are `_WEB_SAFE_COMMANDS` entries, named one at a time, each considered
before it is exposed. And a remote command line already exists on this
machine: it is `ssh`, and it is not maintained inside the process being
defended.

**A web command behaves exactly like one typed at the `:` line** — including
that `%h`/`%r` are *not* expanded, because `_handle_cmd_key` calls
`_dispatch_cmd` directly and only `_execute_binding` expands. That was
checked rather than assumed, and it is why no second expansion path had to be
written; the council had flagged one as a thing that would drift.

### A refusal nobody can see

`_refuse()` reports at `LEVEL_NORMAL` **and** puts the text on the status bar.
Category `cmd` is `LEVEL_INFO` and the default log level is `LEVEL_NORMAL`, so
an event-only refusal says nothing at all on screen: the command appears to do
nothing and offers no reason.

**This is the third time.** `:set stats` refusing a whole line silently was
Phase 19, reported as "my settings did not survive a restart" (§8). The web
surface then reintroduced it in five places at once — `:web start`, every
`:set web-*`, refused web commands, queue overflow, and a dropped
`web-password-file`. It was found in production: a config holding `:set
web-listen 0.0.0.0:8088` with no password file, where `:web start` did nothing,
said nothing, and the explanation was reachable only by restarting at `-vvv`.
`tests/test_web_silence.py` has a structural guard that fails if a new web
handler reports a refusal the quiet way.

Four separate silences, and each needed its own fix:

- **`_queue` sent its 403 before the audit**, so a session could walk the whole
  blocked surface — `:mux sh`, `:source /etc/shadow`, `:quit` — and leave
  nothing behind: no audit record, and an access line at `LEVEL_DEBUG` that the
  default level hides. A refusal is the request most worth keeping, because a
  legitimate user does not send one. Failed *logins* were already recorded;
  failed commands were not.
- **The write queue answered `202 queued` and dropped the command.**
  `deque(maxlen=…)` evicts from the **left**, so a flood pushes out the
  operator's own click while the browser reports success. `_web_enqueue`
  returns False when full and the handler sends 503.
- **An unusable `web-password-file` dropped the setting**, and the next
  `:save-config` wrote the config back without the line — so the operator met
  "refusing to listen on 0.0.0.0 without a password", naming the setting they
  had set, with the path gone for good. A path is a path; whether it can be
  read is a question for the moment it is read, which is `:web start`. It is
  reported at once and kept.
- **The allowlisted commands were left out of the first pass** and are
  precisely the ones a browser can reach: `:pause-selected yes`, `:dns bogus`,
  `:layout bogus` and a dozen more refused in silence. Sixteen sites in
  `_WEB_SAFE_COMMANDS` handlers now go through `_refuse` too — which improves
  the terminal as much as the browser, since these are typed at the `:` line
  far more often than they are posted.
- The rest were `add_event('cmd', …)` and are now `_refuse`.

**The record must not become the flood.** Reporting every refusal at
`LEVEL_NORMAL` put it in the `:log` file by design (§12), and a session can
send refusals as fast as the socket allows: measured at 1072/s, which wipes the
10 000-entry deque in nine seconds and writes some 10 GB a day — destroying the
refusal records along with everything else, which is the exact bug this fix was
meant to close, inverted. `refuse_log_gate` reports the first
`_WEB_REFUSE_LOG_MAX` per client per minute and then one line saying it has
stopped; the command text is capped at `_WEB_REFUSE_CMD_CHARS`, because the
body limit is 64 KB and one request could otherwise write a 60 KB line. **The
syslog audit is deliberately not throttled** — it is the security record, and
syslog does its own rate control. The gate is separate from `login_gate`: a
refused command must not spend a login attempt, and a wrong password must not
quieten the audit.

`count_in_window` returns the count rather than a boolean because the first cut
asked the gate twice — once for "may I log?" and once for "may I say I have
stopped?" — and the second question consumed another slot, so the
stopped-reporting line never appeared at all.

**Not every `add_event('cmd', …)` is a refusal.** A mechanical conversion
turned `:layout`'s *success* report into one, which took over the status bar
and blanked the `layout:log` indicator the layout tests assert on. The
distinguishing mark is a `return` immediately after; the three that legitimately
carry on are checked by hand and named in `tests/test_web_silence.py`.

**A guard that matches one quoting style guards nothing.** The structural test
looked for `add_event('cmd'` while this file uses `add_event("cmd"` 136 times
to 1, so a new handler written in the house style would have sailed past it. It
now matches both and keys on the function *name* (`_web_*`, `_cmd_web*`) rather
than a hardcoded list, and has its own regression test.

### Parity with the terminal

**Two silent wrong readings, found by putting the two views side by side.**
Neither failed loudly — a blank cell and an empty strip are what a host with
no data looks like, so the browser quietly disagreed with the screen beside
it:

- a `:probe` column read `-` in the web while the terminal showed the
  reading. `_compute_stat` is a pure function over one monitor and knows
  nothing about the app's `:probe` declarations; `_stat_cell` is the
  dispatcher that does.
- with `:set ping-view <probe>` the strip came back blank, because a probe
  series is not one of the `HISTORY_MODES` `get_history_string` understands.
  `draw_hosts` asks `_probe_def_for_label` first and calls
  `_probe_history_string`; the serializer now asks the same three questions in
  the same order, including `_probe_cell_width` / `_rtt_cell_width` — a probe
  cell holds the reading, so it is wider than one column, and the client is
  told the width rather than guessing.

**`_details_data(monitor)`** is the one snapshot the overlay and
`/api/host/<uid>` both format from. The overlay used to read it inline in
*two* lock acquisitions, which made it the only host view with no accessor.
Durations come out as seconds rather than the `time.monotonic()` stamps they
derive from — those mean nothing outside this process. `_connect_preview` and
`_host_event_lines` stay outside the lock deliberately: they reach other state
and holding a monitor lock across them would invite a deadlock for no gain.
The refactor was verified by capturing every overlay line before and after,
for an up host, a down relayed host and an errored one: identical.

**`_event_class` and `_stat_class` are twins of the `*_attr` functions**, and
sit next to them so neither can be changed without seeing the other. Colour
pairs are chosen for a terminal and a browser wants a name; translating the
attribute back would be the wrong direction. The client previously guessed the
event colour by looking for `error:` in the text, which knew nothing about the
level or the category, and had no way at all to judge a probe reading.
`_stat_class` mirrors `_probe_attr`'s rank exactly, including a `--combine`
group taking its worst member and "nothing read yet" ranking above "fine".

**A twin is only as good as the proof that it is one.** The first cut mirrored
five of `_stat_attr`'s seven branches; `Last` and `Drift`/`RTime` fell through
to no class. That is not a corner: `STATS_MODES[0]` is `off`, which the
serializer maps to a single `Last` column, so **every row in the browser had an
uncoloured latency cell** while the terminal coloured it three ways — red
included, for "no reply". The test that looked like coverage compared the
*keys* of `stat_class` against the keys of `stats` and never a value, so it
passed throughout. The guard that catches the next one parses both function
bodies for the column names they name and asserts `_stat_attr`'s set is a
subset of `_stat_class`'s; nine tests now fail if either branch is removed.

**The strip is coloured by the server, one class per cell.** The client
classified one *character* at a time against the ping palette — `'0'`-`'4'`
green, `'5'`-`'9'` yellow — which is right for the one-column modes and wrong
for every wide cell, because a wide cell holds a **reading**. Measured against
a real `_web_state()` at `cell_width` 3, four of seven cells disagreed with the
screen beside them: `'49 '` split green-then-yellow where the terminal paints
the cell green, `120 ms` drew entirely green where the terminal paints it
yellow, and the fastest reply on the screen, `7 ms`, drew yellow. With `:set
ping-view <probe>` it was worse and it was familiar: a reading of `82` against
`--warn 60 --crit 80` drew `8` yellow and `2` green where the terminal paints
the cell **red** — Phase 22's "the colour came from the ping palette" (§8),
reappearing in the browser, in the commit whose subject said the two views now
agreed about colour.

The client cannot do this job: what counts as slow for a cell lives in a
`:probe` declaration it has never seen, and `_probe_strip_attr` had no web twin
at all. `_history_cell_classes` decides every **host** cell, mirroring both
branches of `draw_hosts`'s strip loop — a section's cells are a different
question and go through `_section_cell_classes`, below — and `_probe_strip_class` sits beside
`_probe_strip_attr` under the same rule as `_stat_class`. `glyphClass` is gone,
so there is one implementation of the rule rather than two that drift.

**A folded section is not a host, and was serialized as though it were.**
`_section_summary` returns three things and `_web_state` took two, dropping
`slot_ok_ratios` — which is the *only* reason a section strip differs from a
host strip. An `'X'` there summarises hosts the viewer cannot see, so the
terminal paints it **yellow** when more than half of them replied: the section
is degraded, not down. Measured on three hosts, two slots both drawing `'X'`
with ratios `0.33` and `0.67`: the browser gave both `g-bad`, so a section two
thirds of which was answering read exactly like one that was entirely dead.
`_section_cell_classes` mirrors that loop, and `'?'` — a process error, which
the terminal bolds apart from a plain lost probe — stops arriving as the same
red too.

**And the strip must be handed the hosts folding actually hid.** `draw_hosts`
passes `history_monitors=_get_hidden_section_monitors(...)`, which is a strict
subset of the section's monitors whenever a folded section holds an *unfolded*
subsection: those hosts are drawn in their own right, and a summary that
repeats what is visible beside it answers the wrong question. The badge still
counts everyone, which is why the two arguments exist. Measured on a folded
parent (one host down, one up) holding an unfolded child (one up): the hidden
pair alone is an even split, `0.50`, and red; counting the child's host too
makes it `0.67` and yellow.

**The shape of that bug is worth more than the fix.** The wrong population was
passed from the day the serializer was written and cost nothing, because the
consumer collapsed every lost slot to one colour — a wrong input is invisible
while the thing reading it cannot tell its cases apart. Making the consumer
finer-grained is what turned it into a wrong answer, and it surfaced in exactly
the cell the change existed to correct. So: **when you add a branch to a
summariser, re-check what population it is being handed**, because the
inputs were only ever as right as the old output was coarse.

**The badge lost every colour it had.** `'badge': [seg for seg, _pair in badge]`
kept the text and discarded the pair id, and the page's single `.badge` rule
then painted the lot dim, so "1 up, 2 down" reached the viewer as grey and grey
— the one distinction a badge exists to make. Segments now carry a class each.
The `'/'` separator is pair 0 and is deliberately left **classless**, so it
cannot inherit the colour of the count before it; `b-err` is a *weight*, not a
colour, because `has_error` composes with red and yellow in the terminal rather
than replacing them.

**A section strip is one character per slot, in every view.** It is built at
`cell_width=1` because it is a worst-of summary rather than a reading, and
`draw_hosts` draws it one cell per character — but `_web_state` handed it the
*view's* width. Under `:set ping-view rtt` that cut a ten-slot strip into four
cells while the host rows beside it drew ten, so the folded section was out of
step with the rows it summarises. That is a misalignment, not a wrong colour,
and it is the half of this bug that no amount of palette work would have found.
`SECTION_STRIP_CELL_WIDTH` names the rule and **every row now carries its own
`cell_width`**, so the client follows one rule per row instead of a global that
was wrong for one kind of row.

**The guard that catches the next one is the ratio boundary**, not a comparison
against the function under test — `test_web_parity.py`'s own lesson (below).
Two slots holding the same glyph and different ratios must get different
classes; stubbing `slot_ok_ratios` to a constant makes that assertion fail,
which was checked rather than assumed.

**`connect` is resolved and expanded against the host that was asked for.**
`_connect_preview(monitor)` passed its argument only to the relay wrapping; the
`%h`/`%r`/`%j` substitution came from `_binding_context()`, which takes no
argument and reads `self.entries[self.highlighted_index]`. So every host in the
browser was shown the *console's* command — `GET /api/host/<uid>` answered `ssh
router-a` for every uid while the cursor sat on router-a — and on a fresh run,
where `highlighted_index` is None, every host showed `Connect: disabled`.
`_relay_prefix_for` read the same cursor, so a plain host came back wrapped in
an unrelated relay: `ssh -t relay1 ssh router-a`.

This is §9d's own rule broken on the read side. The write path addresses hosts
by uid precisely because that cursor is shared with whoever is at the console —
the party kiosk mode exists to distrust — and a viewer being told which machine
to ssh into is exactly the instruction you do not want a stranger choosing.
`_binding_context`, `_expand_binding_commands` and `_relay_prefix_for` all take
an optional entry now; a keypress still means "the host under the cursor",
because that is what a keypress means.

**The guard for it was tautological**: the test asserted
`d['connect'] == app._connect_preview(m)` against a function that *is*
`_connect_preview`, so it could not fail. What catches this is asking whether
the answer changes when the cursor moves, which `tests/test_web_parity.py`
does for every cursor position including None.

**The page is sized from what it holds, and the client is what knows the
window.** Three numbers used to be constants and are not any more.

`name_width` is the longest name among the rows the payload actually carries.
It is measured **there**, not through `_get_name_col_width` — that helper
caches into `_name_col_cache` and clears `_name_col_dirty`, and `_web_state`
runs on the server thread under a documented promise not to mutate. The purity
test caught it doing exactly that. Measuring from the emitted rows is also the
right population: a folded section's hosts are not in `visible`, so a column
nobody is reading cannot widen the one they are. Clamped, and **the clamp is
the requirement**: sized purely from content, one 65-character section title
takes the row and leaves the strip nothing — the terminal met this as
`addwstr() returned ERR` (§8), where at least it said so.

`cols` is how many history slots the browser has room for, and it sizes a
payload built on every poll **from a value the client supplies**. So it is
clamped on the server, parsed defensively, and falls back rather than raising —
this runs in a request handler where an exception is a 500 and an event for
every browser, every couple of seconds. §9d's own history is an
unauthenticated client manufacturing work at 1117/s; an unbounded `cols` is
that mistake again, one deque at a time.

**`.strip` has `flex: 1 1 0`, and that is load-bearing rather than cosmetic.**
The client measures the strip to decide how many cells to ask for. With
`flex-basis: auto` the returned text would resize the element, which would
change the next request, which would change the width again — the two chasing
each other every poll, for ever. With basis `0` the width is exactly the space
the other columns leave and does not depend on the content at all, so the loop
settles in one step. A one-slot difference is ignored on top of that, because
rounding at the edge of a fractional character width flips back and forth.

**Two things about that loop were wrong in review, and neither was visible in
the source.** `measureCols` runs from `render()`, which runs *inside*
`poll()`'s promise chain — and that chain's tail arms the next poll, while
`schedulePoll` clears whatever is pending first. So a `schedulePoll(0)` asked
for by `measureCols` was cancelled by the tail a moment later, and the measured
width arrived a whole interval after the page had drawn the server's default.
The page looked right eventually, which is why no string-matching test saw it;
what caught it was running the real client under a virtual clock and asking
*when* the second request went out. The tail now decides, from a flag.

And the `resize` handler was undebounced. Each event rebuilt every row and
forced two synchronous layouts — but the real fault is that a render from there
is **not** inside the promise chain, so nothing cleared the re-poll it asked
for, and a sustained drag stacked concurrent fetches against
`_WEB_MAX_CONNECTIONS`. That is the same failure b1d1775 fixed, arriving by a
different door: **anything that can call `render()` from outside the poll chain
is a place where a poll can be forked.**

**The name column's real limit is the client's, not the server's.** The server
caps at `_WEB_MAX_NAME_COLS` purely as a sanity bound; what actually protects
the strip is `max-width` on `.row .name`, a share of the row, because only the
client knows the window. The first cap was 48 and was wrong: a relayed host
draws its whole jump chain, so `ses-wg-video → proxmox → nray-set2-slave
(10.123.254.1)` is 55 characters and was cut by the setting whose entire
purpose is to size the column to its content. **A server-side cap on something
only the client can measure should be generous enough never to bind.**

**A host is indented inside its name cell; a section indents its whole row.**
The padding goes on the `.name` span rather than the row — with `box-sizing:
border-box` it comes out of the fixed name width, so however deep a host sits
its stats and strip stay in the same column. Indenting the row instead would
push those right and undo the alignment a fixed name column exists for (5e535b2).

**The step that matters is title-to-host, and the first cut lost exactly
that.** The terminal puts a title at `(level - 1) * 2` columns and a host at
`level * 2`, so a host is always one step inside the header above it —
including at level 1, where the title has no indent at all. The browser gave a
host at level *N* the same padding as a *section* at level *N*, which
distinguishes nesting depth perfectly and leaves every host flush with its own
header. So the report it answered ("host under a title should be aligned") came
out half-fixed: right relative to the other hosts, wrong relative to the thing
they sit under, which is the alignment that was being asked about. A host
outside any section is level 0 and matches no rule; the client must pass that
level through rather than coercing it to 1, or those hosts get indented under
nothing.

**Clicking the open host closes it**, through the same two lines the close
button and Escape use rather than a third path, and reading `selectedUid`
fresh — `render()` clears it when the selected host leaves the list, so a
remembered copy could close something else.

**An anonymous viewer had no way to sign in, and that is what two bug reports
actually were.** `:set web-anonymous read-only` makes `/api/state` answer 200,
and `showLogin(true)` fired only on a 401 — so the branch that reveals the
sign-in form never ran, while `showLogin(false)` on every successful poll
actively hid it. A viewer could watch the whole fleet with nothing on the page
suggesting there was more to be had. Measured against a real listener:

    ANON  /api/state  200  csrf=None   commands='read-only'
    ANON  /api/host   200  events withheld
    AUTH  /api/state  200  csrf set    commands='safe'
    AUTH  /api/host   200  events present

Both halves of the report — "the fold does nothing, and there is no pointer
cursor" and "I do not see Recent events" — are that table's first two lines.
Neither was a bug in folding or in the details pane, and answering "it works,
you must be signed in" was true and useless, because the page offered no way to
become signed in. There is now a `sign in` button, shown exactly when
`state.csrf` is absent, and `showLogin(false)` no longer runs on a successful
poll — with anonymous read that is the *normal* case, so it shut the form a
couple of seconds after the viewer opened it.

**The lesson is about where to look.** A capability that is withheld rather
than broken produces symptoms indistinguishable from breakage: a control that
does nothing, and a section that is simply absent. When a feature "does not
work" for a user and the code says it should, check what their *session* is
allowed to see before checking the feature again.

**A read-only viewer is told why the fold marker does nothing.** Reported as
"click on title still do not fold in firefox", and it was not a browser bug:
measured under node, a signed-in client attaches the handler and a click on the
*title* fires `POST /api/host/<uid>/fold`, while an anonymous one attaches
nothing at all — `state.commands` is `'read-only'` for them (§"Who may read
it"), so `canWrite` is false. The marker looked identical and the page gave no
reason, which is this project's oldest recurring bug in its newest place. The
two cases are distinguished, because the way out differs: an anonymous viewer
signs in, a viewer under `:set web-commands read-only` cannot fold at all.

**The events a redaction withheld are bought back without un-redacting it.**
Reported as the host pane being "cut from the bottom": there is no
`max-height` on it anywhere, and the pane simply ended early because
`_WEB_ANON_WITHHELD` drops `events` and the section was therefore absent from
the payload. Exactly the symptom above — withheld, not broken.

The repair is the user's own suggestion and is strictly *safer* than relaxing
the denylist. `/api/state`'s tail is already sent to these callers, is already
level-filtered, and carries the category each line was filed under, so the
client can select one host's lines out of what it is holding. Nothing new
crosses the wire but the key to match on: `event_key`, which is
`get_display_name(dns_mode='off')`. **`name` cannot serve** — it is rendered
with `DNS_MODES[self.dns_mode]`, so under the common `:set dns ip+name` it
reads `10.0.0.1 (named.example)` and would match no category at all, and it
moves whenever the console operator presses `D`.

The fallback fires only when the field is absent, so a viewer who signed in
still gets the terminal's own list. That list is the wider one — matched by a
substring over the whole line rather than on the category, and not
level-filtered — which is why the narrower pane says `(at this log level)`
rather than presenting itself as the whole story.

**A section header folds on a click anywhere along it**, not just on the
`[+]`/`[-]`. One handler on the row rather than one per child, so a click
cannot fire twice. The verbs are `fold` and `unfold` rather than a toggle, for
the reason every write here is explicit: the page is showing a picture up to a
poll old, and a toggle applied to that does the opposite of what was clicked.
Nothing new was needed on the way in — `_web_index_for_uid` already matched any
entry carrying a uid, `SectionLabel` has one, and `:fold open`/`close` resolve
to `zo`/`zc`, which act on the highlighted section that `_web_drain` has
already parked the cursor on. What was missing was a verb and a control.

**The details pane sits in the row list, under the host it describes.** It is
the same node moved rather than a new one built: a node has one parent, so
appending it re-parents it, and that is what keeps its text across the poll
that clears the list every couple of seconds. Rebuilding it would blank the
pane until another fetch returned.

**Filtering is client-side.** `:filter` would move the terminal's view and
every other viewer's; one person searching should not drag anybody else's
screen with them. A test asserts the client never posts `:filter`.

**So is every other view choice**, for the same reason: the palette and which
panels are shown live in `localStorage` under one key and reach no request.
The rule is that anything describing *how this person reads the page* stays in
the browser, and only things describing *what the fleet is doing* go to the
server. `:set` is shared by every viewer and the console, so it is the wrong
instrument for the first kind however convenient it looks.

Three details that are not arbitrary. **Dark stays `:root` and light is an
override** keyed on a `data-theme` attribute, so a page whose script never
runs looks exactly as it always has. **The default is chosen in JS**, from
`localStorage` first and `prefers-color-scheme` second — asking in a media
query instead would mean writing the light palette twice, and the copy nobody
is looking at is the one that drifts. **The attribute, never a style string**:
the CSP is `style-src 'self'` with no `'unsafe-inline'`, so an inline style is
dropped and the page would silently keep the wrong palette.

Every read and write of `localStorage` is wrapped: it *throws* rather than
returning null in a private window and where site data is blocked, and a
viewer preference is not worth a dead page. A browser that refuses storage
starts from the defaults each time, which is the correct degradation.

**The browser's sort keys mirror `get_sorted_monitors` exactly**, and were
written wrong first. `status` looked like it should lead with what is broken —
that is the reason to ask for the order — but the terminal keys on
`(m.alive is not True, m.host)`, so `False` sorts first and the hosts that are
**up** lead; paused and quiet are not a rank of their own there, so they are
not one here. `name` is a plain code-point comparison rather than
`localeCompare`, because Python's `sorted()` orders by code point and
`localeCompare` folds case and accents — they disagree on exactly the names an
operator gives a device (`Echo` before `alpha` is the cheapest witness). If a
different order is wanted, change both; a structural test cannot see a
disagreement of this kind, so `tests/test_web_assets.py` runs the two
implementations over the same hosts and compares.

**Sorting hides the section headers**, which is what the terminal already does
(`_get_visible_entry_indices`: a section is visible only while `sort_by` is
`'none'`). A section says where a host sits in the configured order; once the
rows are in a different order it is labelling an arrangement that is no longer
on screen. Following the terminal here was cheaper than inventing a rule —
"sort within each section" was the alternative, and it would have been a
second answer to a question this program had already answered.

**A column can be hidden, not added.** The payload carries the columns
`:set stats` asked for, so hiding one is this browser's business; showing one
the server is not computing would mean asking for a different snapshot, which
is exactly the shared change these controls exist to avoid. The column bar is
built from `state.columns` rather than from the keys of any one row, so a host
missing a reading does not shorten it.

**A section strip is drawn only when the section is folded**, as the terminal
does — an open section's hosts are already drawing their own strips below, and
summarising them again on the header put a second, coarser answer directly
above the real one. Only the client gates: the serializer still emits
`history` for an open section, which costs a few bytes and keeps one code path
where there would otherwise be two. The terminal's condition also tests that
the bar fits the screen, which is a layout guard with no meaning in a browser
and is deliberately not mirrored.

**Kiosk mode: declared, never typed.** `:web start` is refused at the console
and allowed while `_loading_file` is set — the rule `:bind-key` already
follows. Starting is audited. A port below 1024 is refused with the reason
(`NoNewPrivileges=yes`), and port **0** is explicitly not that case: the
kernel picks an ephemeral port well above 1024, which a first cut got wrong.

**Settings persist; the listener does not.** `_save_config` writes
`web-listen` and `web-allow` but never `:web start` — a network socket should
open because someone asked, not because a preference file was written. Put
`:web start` in the hosts file to have it up from boot.

The status bar carries a `web:<host>:<port>` slot whenever the socket is open,
on the same "only when it is not the default" rule as `layout`. A listening
port must not be something you discover months later.

## 9c. The web read side: `uid` and `_web_state()`

Groundwork for a browser view. No socket yet — this is the read model only.

**`Monitor.uid` / `SectionLabel.uid` are derived from the display name, not
handed out by a counter.** Row indices are not identity: the `:edit` reload
rebuilds `entries` and `monitors` wholesale, and `highlighted_index` is a
single global cursor shared with whoever is at the console — who, in this
project's own kiosk threat model, is the attacker. A viewer that says "pause
row 7" three seconds after fetching the list would pause a different host.
Deriving from the name gets three properties at once: it survives a reload
(and an adopted monitor is literally the same object anyway, see §9b), it
survives a process restart so a browser link keeps working, and it changes
exactly when the row genuinely becomes a different row. Two hosts sharing a
display name share a uid — they already share everything the UI shows, and
`:source` refuses a duplicate name.

**`_web_state()` is pure and reads under the §9 threading rules.** Events come
from `_events_snapshot()` and are filtered against `loglevel` *here*, not
through `_get_filtered_events()` — that returns a **live plain list** which
background threads append to and trim, and a plain list has no "mutated during
iteration" guard, so a concurrent read gets silently wrong results rather than
an exception. `entries` is copied before iterating because the reload replaces
it wholesale, and the loop skips an index past the end rather than raising.
Per-host reads take `monitor.lock`, which `get_history_string` and
`_compute_stat` already do.

**The stats columns are driven by `STAT_NAMES` + `_compute_stat`**, the same
pair the terminal renders from — the `data_fields[]` idea from mtr, where one
column table drives five output formats. The history strip is the same string
`draw_hosts` gets. `_history_render_time()` was extracted so the two views
cannot drift on the floored-second bucket boundary or the one-second shift
that keeps position 0 stable in sync mode.

**`_web_json()` escapes `<`, `>` and `&`.** `json.dumps` escapes only quotes,
backslashes and control characters, so a display name of `</script>…` survives
literally — harmless in a response read with `JSON.parse`, and fatal the day
that payload is embedded in an HTML `<script>` block, because `</script>`
closes it wherever it appears, inside a string or not. Every string in the
payload is attacker-controlled: names from the hosts file, `ip` from reverse
DNS (whoever owns the PTR record picks it), `error` from ping's stderr.

`_entries_generation` is declared on the class, not in `__init__`: several
tests build an `Application` through `__new__`, and `+= 1` rebinds per
instance anyway.

## 9b. `:edit` reload keeps what it did not change

`_edit_reload_inplace` used to stop every monitor, clear the lists, rebuild all
of them and copy the history across. A host whose line was byte-identical still
lost its child and re-authenticated. **Measured on a 50-host production
screen**: the `_` cells ("no ping process this second") staircased down the
list — one or two at the top, eight or nine by the last host behind one relay —
because reconnections are paced by `_ssh_spawn_gate` at `ssh-connect-rate` 5/s,
and that relay paid fifty handshakes at once.

Now nothing is stopped before the file is read, and a monitor whose
`Monitor.identity()` still matches is **adopted**: the same object goes back
into `entries`/`monitors`, keeping its child process, SSH connection, history,
`paused` and `no_alarm`.

Three orderings are load-bearing:

1. **Reconcile after `_cmd_source`, not during it.** `:resolv` and `:relay-os`
   are applied to a monitor *after* it is built, so an identity taken at
   construction time cannot see a changed static mapping or a relay newly
   declared FreeBSD — it would adopt a monitor still aimed the old way.
2. **Reset the file-declared rule stores before re-sourcing.**
   `no_alarm_patterns` and `relay_os_rules` used to accumulate, so **deleting a
   `:no-alarm` or `:relay-os` line was a no-op** and a stale relay OS stayed in
   the identity of every host behind it. Verified before the fix: after
   removing both lines, the patterns and rules were still there and the host
   still drew `o`.
3. **`_restore_monitor` is for the *unadopted* only.** An adopted monitor
   already owns its history; extending its deque with a snapshot of itself
   doubles every row. The snapshot is still keyed on the display name, so a
   changed-but-same-name host (an edited SSH line) inherits what was measured
   through the old connection.

`identity()` is deliberately generous — an extra restart costs seconds of
history, a wrong reuse leaves a host probing the wrong target for the run. Base:
class name, `host` (the display name, which is where a `##` label ends up),
`_ping_host`, `resolv_static` and the static IP. `PortMonitor` adds the port.
`SshPingMonitor` adds `_ssh_args`, `_original_ssh_args`, `_ssh_hops`,
`_ssh_dest` and `_relay_os_declared` — **the jump chain is in there because the
user asked for it**: re-pointing `:with remote-ping` at another proxy must build
a new monitor, since the new relay may run a different OS.

**Probe readers hold their monitor**, and the reload never touched them, so
after one the readers were writing into objects nothing displayed while the
replacements had none. `_resync_probe_readers` stops the orphans and opens
readers for the uncovered; an adopted monitor keeps the reader it had, because
the object did not change.

**A runtime `o` press is not a file rule.** It used to be appended to
`no_alarm_patterns`, which resetting that list would have thrown away — and
turning *off* a glob-marked host meant deleting the glob for everyone it
covered. `no_alarm_manual` is a per-host `{name: bool}` that beats the globs
(the more recent decision) and survives the reload.

**It has to round-trip through `:save-config`, and `--remove` cannot express
it** — that flag deletes a glob, so a False entry written as
`:no-alarm --remove <name>` matched nothing in the pattern list and the line
did nothing. Caught by saving and re-reading: a host toggled off under
`:no-alarm 10.0.0.*` came back marked. `--mark <host>…` / `--unmark <host>…`
write the store by name and are what `_save_config` emits. `:no-alarm` with no
argument lists the globs and the overrides separately — it is the command that
answers "why is this host marked?", and a decision it cannot show is worse than
no answer.

Still open: `prog_options` and `probe_defs` accumulate across a reload the way
the other two did, so removing a `:prog-options` or `:probe` line has no effect
until restart. Neither feeds `identity()`, so adoption is unaffected.

## 9a. SSH connection pacing and sharing

Many hosts commonly sit behind one relay (`:with remote-ping <relay>` over a
whole section), and two server-side limits bite from opposite directions:

| Limit         | Default     | Bites when                                                                |
| ------------- | ----------- | ------------------------------------------------------------------------- |
| `MaxStartups` | `10:30:100` | many *connections* authenticate at once — random early drop from the 10th |
| `MaxSessions` | `10`        | many *sessions* share one multiplexed connection — the 11th is refused    |

So neither extreme works for a relay with 54 hosts behind it: 54 simultaneous
connections trip `MaxStartups`, and one multiplexed master trips `MaxSessions`.
**Do not "solve" the burst by turning on `ControlMaster` for the ping
connections** — that converts a retry storm which recovers into hosts that are
never monitored at all.

Both were measured, not theorised. `start_monitoring()` used to start every
thread in a tight loop and each `ping()` called `Popen` immediately: 20 relayed
hosts opened 20 `ssh` processes within 10 ms, and a real 54-host log carried
10-20 `kex_exchange_identification: read: Connection reset by peer` per
startup, all within 0-1 s of it. It looked like it worked because the backoff
loop retried once the herd cleared, at the cost of those hosts coming up
seconds late.

### Pacing (implemented)

`_ssh_spawn_gate(endpoint)` is a leaky bucket, `:set ssh-connect-rate`
(default 5/s), applied in `SubprocessMonitor.ping()` and `ProbeReader.run()`
just before `Popen`. Measured after: 20 connections over 3.8 s, at most 6 in
any one-second window.

Three details that are deliberate:

- **Keyed on `_ssh_first_hop()`**, not the target. With `-J` the local ssh
  authenticates to the *jump host*, so that is the daemon under load; hosts
  behind one relay share a budget and hosts on different relays do not wait
  for each other.
- **A rate limiter, not a fixed per-host offset.** The same storm happens on
  every mass reconnect — a relay restart has every monitor retry at once, and
  the backoff carries no jitter — so a startup-only stagger would fix the
  first minute and nothing after it.
- **Inside the monitor thread**, not in `start_monitoring()`. Sleeping there
  would block the UI for the whole ramp.

A local `ping` returns `None` from `_spawn_endpoint()` and is never paced: it
contacts no daemon.

**Every connection ping-bulk opens for itself must pass the gate.** All four
now do: `SubprocessMonitor.ping()`, `ProbeReader.run()`, `_detect_relay_os()`
and `_clock_probe_once()`. The clock probe was missed for a long time and was
the worst of them, because its burst is *periodic*, not one-off: each host
sets `_clock_next_ts = now + clock_interval` when its probe finishes, so the
probes never drift apart and all of them come due on the same tick. **Measured
in a production log**: 47 relayed hosts, `clock-interval` 30 s, and one tick's
worth of 47 simultaneous handshakes was enough to trip `MaxStartups` on the
jump host — `Connection closed by UNKNOWN port 65535` (ssh cannot name the
peer, because with `-J` the relay connection rides a channel that has no peer
address of its own) — and to stall the *monitoring* connections through the
same hop for 6 s, which the stale-child watchdog answered by restarting all 47
at once. The gate belongs in the short-lived `clock:<host>` thread, before
`subprocess.run`, so its timeout budget starts after the wait.

### The jump chain is a list, and ssh options are built from it

`SshPingMonitor._ssh_hops` holds the directive's jump hosts, read out of its
flags **once**, in `__init__`. Everything that needs them — the display name,
`ProbeReader._jump_args()`, `_relay_prefix_for()`, `connect_chain()` — reads
that list. **Do not scan ssh flags again at runtime.** The first attempt at
the fix below did, and taking ssh options apart is where the bugs are: `-J`
has three spellings (`-J h`, `-Jh`, `-o ProxyJump=h`, and the `-oProxyJump=h`
run-together form), roughly twenty short options swallow the next argument so
the destination cannot be found without a table of them, a bracketed IPv6
hop hides its port where the bare form does not, and a mistake rewrites the
user's own command. Composing options from a list has none of those failure
modes.

### A relay is sometimes one of its own hosts

`:remote-ping <relay> <relay>` is a real configuration — a relay worth
watching as a host — and it puts the target in its own jump chain, which ssh
refuses: `jumphost loop via <host>`. `connect_chain()` cuts the chain before
that host and hands back the hop's own spelling of the login, which is the
one ping-bulk already uses on it.

**Measured** (OpenSSH 10, `-F /dev/null -G`, so nothing connects): ssh
compares the *effective* user, host **and** port. `-J b b` is refused —
both sides default to the same local user — while `-J admin@b b` is
accepted, `-l admin -J admin@b b` refused, `-J b:2222 b` accepted and
`-o ProxyJump=b b` refused. So the port is part of the identity, while the
user deliberately is not: a difference that only `ssh_config` or a
later-injected `-l` knows about cannot be seen from here, and a refused
chain is the worse outcome. Two spellings collapse that ssh would have
accepted (a port arriving via `:prog-options ssh <host> -p 2222`, and `[h]`
against `h`); both still reach the host. Do not add a user comparison to
recover them: a ping target never carries `user@` — `ping admin@host` is
not a thing — so the branch would be unreachable.

Endpoints are compared through the `:resolv` map *and* the monitor's
`resolved_ip`, so an alias, a DNS name and the address behind them are one
host whichever spelling each side used. A `:resolv` written after the
`:remote-ping` line leaves the relay under its alias while the target is
already an address, and the two would otherwise look unrelated. The one
direction still open is a relay named in DNS against a target given as an
address: resolving a hop's name would need DNS at keypress time.

The `c`/`C` default binding is `:mux ssh %{J?-J %{J:,} }%r`, where `%J` and
`%r` both come from `connect_chain()`. The `-J` sits *inside* the
conditional because a relay with no hops in front of it leaves the chain
empty, and `-J` with an empty value is not something ssh accepts. That in
turn required `_expand_conditional()` to record the names a `%{var?…}` group
mentions — guard included, fired or not — or `_relay_prefix_for()` sees a
binding that names only `%r` and wraps the command in a second ssh to the
relay.

### Sharing

`_ssh_sharing_flags(share)` encodes the split rather than putting a single
answer in `_SSH_MONITOR_OPTIONS_DEFAULT`:

| Connection      | Reaches         | Sharing                               | Why                                                         |
| --------------- | --------------- | ------------------------------------- | ----------------------------------------------------------- |
| ping            | the relay       | `ControlMaster=no` `ControlPath=none` | many hosts per relay, so a shared master hits `MaxSessions` |
| clock probe     | the relay       | `ControlMaster=no` `ControlPath=none` | same endpoint as ping                                       |
| `:probe-source` | the host itself | shared master                         | one endpoint per host; reconnects reuse the master          |

**`ControlMaster=no` does not mean "no sharing".** It is the *client* mode —
ssh_config(5): "Additional sessions can connect to this socket using the same
ControlPath with ControlMaster set to no (the default)". Setting only that made
every ping connection join whatever master the user's `ControlPath` pointed at,
and sshd refused them past `MaxSessions` with `Session open refused by peer`.
Reproduced locally: 14 clients through one master, 4 refused. Use
`ControlPath=none` to actually disable sharing.

Saying `no` explicitly also stops the ping connections racing for a
`ControlPath` set by the user's own `Host *` block. Naming any `Control*`
option in `:set ssh-options` overrides all of it — ssh takes the *first* value
of a repeated option and these are placed first, so an explicit choice would
otherwise be silently ignored.

### The kiosk blocklist is the only guard on `:set ssh-options`

`_cmd_ssh_options` is **not** one of the commands kiosk mode refuses at the
console — it is typeable at the `:` line, by design, and
`_kiosk_validate_ssh_args` is the whole of its protection. Two things make
that load-bearing rather than defence in depth:

- `_ssh_monitor_flags()` is placed **before** `_kiosk_ssh_flags()` in
  `ProbeReader`'s argv, and ssh keeps the *first* value of a repeated option
  (the same rule §9a relies on for `ProxyJump`). So an option smuggled in
  there **beats** the `ProxyCommand=none` that is supposed to isolate it —
  measured: `-o 'ProxyCommand /bin/evilsh' -o ProxyCommand=none` resolves to
  the injected one, and reversing the order reverses the winner. The clock
  probe prepends no kiosk flags at all.
- ssh takes `-o` "in the format used in the configuration file", and
  ssh_config(5) separates a keyword from its argument with whitespace, `=`,
  or both, ignoring any around them. A check that only understood `=` read
  `'ProxyCommand /bin/sh'` as one keyword and matched nothing, so **three
  spellings walked straight past it** — all verified against OpenSSH 10.0p2
  with `-G`, which resolves options without connecting:

  | `-o` argument | before | now |
  | ------------------------- | ------- | ------- |
  | `ProxyCommand=/bin/sh`    | blocked | blocked |
  | `ProxyCommand /bin/sh`    | **accepted** | blocked |
  | ` ProxyCommand = /bin/sh` | **accepted** | blocked |
  | `-oProxyCommand /bin/sh`  | **accepted** | blocked |

`_kiosk_ssh_option_key()` is the single place that takes a keyword out of an
argument, and it keeps the spelling the user typed so the refusal names it
back to them.

**Two options were missing outright**, and neither is covered by any
prepended isolation flag, so argv order does not save those: `KnownHostsCommand`
— confirmed to actually run its argument, `-o 'KnownHostsCommand=/bin/sh -c
"touch …"'` created the file on a real connection attempt — and
`PKCS11Provider`, which `dlopen()`s an attacker-named `.so` into the ssh
client. `Match exec` is the other obvious vector and is **not** one: OpenSSH
10 answers `Host directive not supported as a command-line option`.

**A mixed-case entry in the set is dead code**, since the lookup lowercases;
`proxyuseFdpass` sat there unable to match anything. `tests/test_kiosk_ssh_blocklist.py`
asserts the whole set is lowercase, which is what catches the next one.

## 10. Key Binding System

All interactive key bindings go through a single unified system. Do **not** add new hardcoded key checks in the main loop.

### Modes
There are four UI modes that determine which binding table is active:

| Mode      | Active when                      |
| --------- | -------------------------------- |
| `normal`  | Default — no overlay open        |
| `help`    | `?` help overlay is visible      |
| `details` | Host details overlay is visible  |
| `command` | `:` command-line input is active |

The active mode is tracked in `self._current_mode`.

### Binding tables
All modes live in the **same** `_key_trie`, in per-mode buckets
(`node.bindings[mode]`). There is no `_mode_bindings` dict.
- **Normal mode**: supports multi-key sequences like `gg`.
- **Overlay modes** (`help`, `details`, `command`): single-key only, no sequences.

### Adding a default binding (Python side)
1. In `_register_default_bindings()` use the `_b()` helper for normal-mode keys:
   ```python
   _b('q', ':quit', hint='[q]uit')
   ```
2. For overlay-mode defaults, use the `_mb()` helper in `_register_mode_bindings()`:
   ```python
   _mb('help', 'q', ':close', desc='close help overlay')
   ```
3. `--hint` makes the label appear in the bottom bar; only set it on the most important actions.
4. `--desc` makes the binding appear in the `?` help overlay "Custom bindings" section.

### Adding a user-configurable binding (hosts file / config)
Users write `:bind-key` directives:
```text
:bind-key --desc "Show help" ? :help
:bind-key --mode details --hint "[q]uit" q :close
```
`_cmd_bindkey` parses these and inserts into `_key_trie` under the target mode. **Every flag comes before the key.** The parser strips flags only from the front of its argument string, so a trailing `--desc` is passed through as part of the bound command — the examples above used to show that form and it never worked. `doc/ping-bulk.rst` has always documented the leading form.

`--desc` is optional, and the Bindings tab falls back to the `CmdDef.help` of the first command when it is missing, so a binding without one still reads sensibly (`_binding_desc`).

### Dispatching
- Normal mode: `_dispatch_key(key)` walks the trie and calls `_dispatch_cmd()`.
- Overlay modes: `_dispatch_mode_key(mode, key)` resolves `_key_trie` in that
  mode bucket and calls `_dispatch_cmd()`; it returns False when nothing is bound.
- The main input loop **must not** contain bare `if key == ord('x')` checks for anything user-rebindable.
- `_dispatch_mode_key` runs **before** `_dispatch_overlay_nav_key`, which is only
  a fallback for keys with no binding. Reversing that order makes every overlay
  nav key unrebindable — that was a real bug.
- Mode lookup does **not** fall back to normal mode: a key unbound in `help`
  does nothing rather than firing its normal-mode binding.

### One key, two lists: guarded bindings and the hint that follows them

`PgUp`/`PgDn` page the *host selection* while there is one, and the *event log*
otherwise. That is three bindings per key in the same normal-mode bucket —
`context=frozenset('h')`, `context=frozenset('s')`, and an unguarded fallback —
resolved by `_resolve_binding`, which takes the largest context that is a
subset of `_binding_context()`. Two guarded copies are needed because a
selected section builds `%s` and a selected host builds `%h`; there is no key
both states share (`%H`/`%R` are absent for a section that owns no hosts).
`<C-f>`/`<C-b>` stay unguarded, so the log is never unreachable.

**The direction is inverted between the two commands.** Per §11 a trailing dash
is backwards, and for a *list* backwards is up — so `<PageUp>` is
`:select page-`. For the *log*, bare `page` already scrolls up, which is what
the neighbouring `:scroll event-history page` binding says. Copying the line
below it pages the wrong way, and both spellings look right in review.

**A hint that describes a key must live in exactly one place — never zero.**
The selection banner carries `[PgUp/PgDn page]` and `draw_events` stops naming
those keys for the log, so `_selection_active()` is the single predicate both
ask. Written twice, the state where the command line is open (banner
suppressed, keys back on the log) is one edit away from showing the hint
nowhere. `draw_events` names `C-b/C-f` instead while a selection is active —
scrolled back in the log, a hint naming keys that no longer resume it is a
dead end.

Paging **clamps** where `:select up`/`down` wrap: a held `PgDn` must come to
rest on the last host rather than silently start over at the top. The step is
`_host_page_size`, cached by the layout maths in `run()` exactly as
`_log_page_size` is, and read through `getattr` because the `log` layout draws
no hosts.

### Built-in overlay commands
| Command                 | Effect                                                                    |
| ----------------------- | ------------------------------------------------------------------------- |
| `:close`                | Close the currently active overlay (uses `_current_mode` to decide which) |
| `:scroll-overlay up`    | Scroll overlay content up one line                                        |
| `:scroll-overlay down`  | Scroll overlay content down one line                                      |
| `:scroll-overlay page`  | Scroll overlay content down one page                                      |
| `:scroll-overlay page-` | Scroll overlay content up one page                                        |

---

## 11. Command & Flag Design Policy

### Command naming
- Use **kebab-case**: `:bind-key`, `:scroll-history`, `:scroll-overlay`, `:prog-options`.
- Keep old names as **aliases** when renaming *unless* the user asks for a clean
  break; `:saveconfig` → `:save-config` and `:help-tab` → `:help` were removed
  outright. `_save_config` always writes the canonical (new) name.
- Register aliases in `CMD_ALIASES` (or equivalent), not as separate `CmdDef` entries.

### Flag naming
- **Long flags are canonical**: `--confirm`, `--desc`, `--hint`, `--mode`, `--split-v`, `--split-h`, `--split-window`.
- Short single-char flags (e.g., `-v`, `-h`) are **aliases only** — never the primary documented form.
- Boolean flags: `--word` with no value (`--confirm`).
- Value flags: `--word value` space-separated, value may be quoted (`--mode help`, `--desc "Show help"`).

### Direction / scroll arguments
- **Trailing dash = reverse/backward**: `half-` scrolls left/back; `half` scrolls right/forward.
- Standard set: `half`, `half-`, `full`, `full-`, `page`, `page-`.

### One rule for every settable parameter

`:set <param>` with no value **reports**; `cycle` / `cycle-` step forward and
back; anything else is a value. `_handle_param_verb` is the only
implementation, called from `_cmd_set` and from the head of each parameter's
own command, so `:set dns cycle` and `:dns cycle` cannot drift apart.

A bare invocation used to change things — `:dns` cycled, `:sync-history` and
`:pause` toggled. That made a hosts file non-idempotent, and the bug it caused
was reported from production: a config holding `:set sync-history off` plus a
hosts file holding a bare `:sync-history` came up **on** (the file flipped the
config) and went **off** after the first `:edit` reload (the file flipped it
again). Startup state depended on what `:save-config` last wrote.

Consequences worth knowing:

- **The default keys name the verb** (`D` → `:dns cycle`, `S` →
  `:sync-history cycle`, `P` → `:pause cycle`, …). A user's own
  `:bind-key <C-p> :pause` now reports instead of pausing; the shipped example
  and the rst were both corrected, and `tests/test_param_verbs.py` asserts no
  default is bound to a bare parameter name.
- **`--toggle` is a flag, not the positional verb**, and keeps its distinct
  meaning: `:layout --toggle log` remembers where it came from, which stepping
  through a value list cannot do. Same for `:no-alarm --toggle`.
- **`reverse` survives as an alias for `:sort cycle-`** (§11: keep old names as
  aliases), and `cycle-` is what `_save_config` and the docs use.
- **An unrecognised value is rejected, not toggled.** `:pause yes` used to
  unpause a paused fleet, and `:sync-history yes` did the opposite of what it
  said, because both fell through to a toggle.
- **A free-form value cannot be cycled from a list.** `SetParam.values` holds a
  *string* for those — `'_complete_stats_arg'` names a completer,
  `'<flags>|default|none'` is a usage synopsis — and walking either stepped
  through its characters: `:set ssh-options cycle` set the options to `<`.
  `next_value` now returns None for any non-list, `stats` supplies a `cycler`,
  and `ssh-options` says it cannot be cycled.
- **A report goes to `_status_msg`, not only the log.** Category `cmd` is
  `LEVEL_INFO`, so an event-only answer is invisible at the default log level.
  A cycle skips the event copy (`to_log=False`) because several handlers
  already log the change in their own, better words.
- Found while adding this: `SetParam('terminal')`'s getter read `app.terminal`,
  but the attribute is `app.terminal_emulator`, so that row had always shown
  `?` in the Settings tab. A test now asserts no parameter reports `?`.

### `autosave`, and why it compares text rather than counting commands

`:set autosave on` writes the config whenever a setting the file holds changes.
Off by default: quietly rewriting a file somebody hand-edited is not something
to start doing unasked, and the skeleton written on first run says `:set
autosave off` in an **active** line rather than a commented one, because a
commented default answers "does this thing rewrite my file?" only for a reader
who already knows the setting exists.

**`_config_text()` is the single renderer**, split out of `_save_config` so
`_autosave` can ask "has anything persisted actually changed?" by comparing the
rendered file. The alternative — a list of which commands are persisted — is
every `:set`, plus `:layout`, `:log`, `:no-alarm`, `:relay-os`,
`:prog-options` and every user key binding, and it would fall behind the next
addition silently. Comparing the text cannot. The split is also what makes the
atomic write possible: the whole text has to exist before anything opens the
file.

Hooked at the tail of `_dispatch_cmd`, which every command passes through — the
`:` line, a key binding, a hosts-file directive, a web request. Guarded on
`_monitoring_started`, **and re-baselined at the end of an `:edit` reload**,
which is the subtle half: the reload flips that flag False and back around
`_cmd_source`, so without a fresh baseline the next command would write the
*hosts file's* settings into the user's own config. Those belong to the file
that declared them.

Four things this cost, all found in review or in use:

- **The seeded line must not carry a trailing comment.** `_load_config` skips
  lines that *start* with `#` and never strips one, so `:set autosave off  #
  explanation` reached the handler as the unknown value `off  # explanation` —
  a fresh install reporting an error about the file it had just written, on
  every start, forever. The explanation goes on the `#` line above. This is not
  specific to `autosave`: **no directive may carry a trailing comment.**
- **A failed save must be audible.** `_save_config` reports under category
  `config`, which is `LEVEL_INFO` and therefore invisible by default; with
  autosave on the operator would believe settings were being kept while every
  command silently failed to write one — measured, 24 of 25. It reports through
  `_refuse` once, stays quiet until a save succeeds, and says so when one does
  (`_autosave_broken`).
- **A failed save must not destroy what was there.** `open(path, 'w')`
  truncates before the first byte, so any later failure leaves an empty file.
  `_write_file_atomically` writes a sibling temp file, fsyncs, and
  `os.replace`s. **Not hypothetical — a real config was emptied this way during
  development.**
- **`autosave`, `_config_on_disk` and `_autosave_broken` are class attributes**,
  for the reason `_entries_generation` is (§9c): several tests build an
  `Application` through `__new__`, and `_dispatch_cmd` — which they do call —
  reads all three.

### Confirmation UX
- Destructive commands support `--confirm`.
- Pattern: first press sets a 2-second deadline and shows a transient `_status_msg`; second press within deadline executes.
- Do **not** use a `[y/N]` blocking prompt — use `_status_msg` instead.

### Bottom bar hints
- Action labels in the bottom bar (e.g., `[q]uit`, `help:[?]`) come from `hint=` on trie/mode bindings.
- **Do not hardcode** new action labels in `draw_menu_bar`; add `hint=` to the binding registration.
- Keep hints ≤ 12 chars. Only the most important actions need hints.

### Status bar indicators
- Left-side indicators (DNS / stats / order / history / sync / pause) are **internal-only** hardcoded in `draw_menu_bar`.
- There is no user-facing `--status` flag; do not add one.

## 12. Log Level System

### Constants (module-level)
```python
LEVEL_QUIET  = 0   # host status changes only
LEVEL_NORMAL = 1   # + warnings/errors  (default)
LEVEL_INFO   = 2   # + cmd output, config, resolv
LEVEL_DEBUG  = 3   # + bind-key dispatch, all internal
```

### EventEntry class
`self.events` is a `deque[EventEntry]` where each `EventEntry(level, category, text)` stores:
- `level` — one of the `LEVEL_*` constants
- `category` — string tag (host name, `'cmd'`, `'bind-key'`, `'resolv'`, …)
- `text` — the full formatted line (timestamp + message)

The class delegates `__str__`, `__contains__`, `lower()`, `startswith()`, `__eq__` to `.text` for backward compatibility.

### Level inference
`add_event(category, message, level=None)` infers level from `_CATEGORY_LEVELS` dict when no explicit level is given.  Unknown categories (host names) default to `LEVEL_QUIET`.

### Display-time filtering
`draw_events` filters `self.events` at display time: `[e for e in self.events if e.level <= self.loglevel]`.  Changing `loglevel` instantly reveals/hides buffered history without re-ingesting.

### Coloring (`_event_color_attr`)
| Condition                                                        | Curses attribute |
| ---------------------------------------------------------------- | ---------------- |
| level == DEBUG or category == 'bind-key'                         | `A_DIM`          |
| message starts with `warning:` or category in `('warn','hosts')` | yellow (pair 3)  |
| message starts with `error:` or category == `'save'`             | red (pair 2)     |
| everything else                                                  | 0 (default)      |

### CLI flags
- `--log-level quiet|normal|info|debug` — explicit startup level
- `-v` / `-vv` / `-vvv` — increase from default (argparse `action='count'`)
- `-q` / `-qq` / `-qqq` — decrease from default

### Persistence
`_save_config` writes `:set log-level <label>`.  `_cmd_loglevel` is a `:set` handler registered via `SetParam('log-level', ...)`.

### File output
`save_to_file` always writes **all** levels regardless of `self.loglevel`.  Users grep the file for filtering.

The one place this cuts the other way is the web access log: because the file
records every level, an event created per HTTP request let an unauthenticated
client write to disk without limit. `_WebHandler.log_message` therefore does
not *create* the event below `-vvv` (§9d) — the rule here is unchanged, what
changed is that the event no longer exists to be recorded.
