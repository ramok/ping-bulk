# Project Handover Document (AGENTS.md)

## 1. Project Overview
**ping-bulk** is a self-contained, single-file Python 3 script designed for monitoring multiple hosts simultaneously with a continuous ping in a live, interactive terminal interface. The goal is to provide a rich CLI tool with features like rolling history, interactive host navigation, SSH monitoring, section folding, and event logging—all without any third-party Python dependencies (only relying on the standard library and the system's `ping` binary).

## 2. Architecture & Code Structure
The repository is structured to keep the core application as a single deployable file while providing tests, documentation, and examples alongside it.

- **`ping-bulk`**: The main executable script. All core application logic (UI, multithreading, subprocess management, configuration, and data processing) resides here.
- **`tests/`**: Contains the test suite for the application. The tests use `pytest` and mock various functionalities (like `ping` output or SSH execution) to ensure reliability without needing actual network access.
- **`examples/`**: Provides sample hosts files demonstrating various configuration directives (e.g., brace expansion, SSH monitoring, static DNS overrides) that `ping-bulk` supports.
- **`doc/`**: Contains project documentation in reStructuredText format (`ping-bulk.rst`), a `Makefile` to build man pages (`ping-bulk.1`), and an HTML version. It relies on `docutils` for building the documentation.
- **`contrib/`**: Contains additional supplementary files, such as systemd service units for running ping-bulk as a continuous background monitor.

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
- **Phase 18 (relays that do not run Linux)**: `:remote-ping` works through
  FreeBSD/OPNsense and MikroTik RouterOS relays. Declared with `--os
  auto|linux|freebsd|mikrotik` on the directive or a `:relay-os <glob> <os>`
  rule (matched like `:no-alarm`, flag beats rule, last rule wins);
  `auto` (the default) probes each relay once with `uname -s` — RouterOS
  answers `bad command name` — cached per `tuple(ssh_args)`, connection
  failures fall back to linux uncached. Per-OS profiles
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
