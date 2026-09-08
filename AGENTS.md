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
  short in a loop.
- Subclasses override only `_build_ping_cmd()`, `_is_fatal_error()`, and the class
  attributes `_STALE_SECS` / `_STALE_MAX_WINDOWS` / `_trust_ping_timestamp`.

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

## 9a. SSH connection behaviour (no staggering — read before "fixing" it)

`start_monitoring()` starts every monitor thread in a tight loop, and each
`SshPingMonitor.ping()` calls `Popen` immediately. **There is no stagger, no
ramp and no connection pooling.** Measured: 20 relayed hosts opened 20 `ssh`
processes within 10 ms.

That matters because many hosts commonly sit behind one relay
(`:with remote-ping <relay>` over a whole section), and two server-side limits
bite from opposite directions:

| Limit         | Default     | Bites when                                                                |
| ------------- | ----------- | ------------------------------------------------------------------------- |
| `MaxStartups` | `10:30:100` | many *connections* authenticate at once — random early drop from the 10th |
| `MaxSessions` | `10`        | many *sessions* share one multiplexed connection — the 11th is refused    |

So neither extreme works for a relay with, say, 54 hosts behind it: 54
independent connections trip `MaxStartups`, and one multiplexed master trips
`MaxSessions`. **Do not "fix" the burst by turning on `ControlMaster` alone** —
that converts a retry storm which recovers into hosts that are never monitored
at all.

It is not hypothetical. A real 54-host log showed 10-20 occurrences of
`kex_exchange_identification: read: Connection reset by peer` per affected
session, all within 0-1 s of startup — the client-side signature of a
pre-auth drop. It looks like it works because the existing exponential
backoff in `SubprocessMonitor.ping()` retries and succeeds once the herd
clears; the cost is that those hosts come up seconds late. Since the sync-mode
`_` marker landed, that delay is visible on screen instead of showing as a
merely shorter bar.

Three ways out, none implemented:

1. **Stagger the spawns** (e.g. a few per second). `MaxStartups` counts only
   *unauthenticated* connections and key auth clears in well under a second,
   so a modest ramp keeps the count under 10. Cheapest, no shared failure
   domain, needs nothing from the relay. Preferred.
2. **Raise `MaxSessions` on the relay** and multiplex. Cheapest at runtime —
   one TCP, one auth — but makes ping-bulk depend on server config, and an
   unconfigured relay silently loses hosts past the tenth.
3. **A pool of masters**, `ceil(hosts / MaxSessions)` of them. Works against a
   stock `sshd` but the pool size depends on a server value the client cannot
   discover.

`:set ssh-options` (default includes `-o ControlMaster=no`) makes the current
behaviour deterministic — every monitoring connection is independent — rather
than depending on whether the user's `ssh_config` says `ControlMaster auto`.

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
```
:bind-key ? :help --desc "Show help"
:bind-key --mode details q :close --hint "[q]uit"
```
`_cmd_bindkey` parses these and inserts into `_key_trie` under the target mode.

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
