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
- **Running Tests**: Navigate to the root directory and execute `pytest -n auto tests/` to run the test suite in parallel. It is **highly recommended** to use `pytest -n auto` for significantly faster test execution, as test sessions are fully isolated using unique `tmux` session names via `pytest-xdist`. Ensure any new features include appropriate tests, especially for complex parsing (like brace expansion or SSH directives). For more details on the testing infrastructure and how to write tests using the headless tmux environment, refer to `tests/AI_TESTING_GUIDE.md` and `SKILL.md`.
  - **CRITICAL REQUIREMENT FOR AI AGENTS:** Before writing **any** new tests, you **MUST** read and fully understand `tests/AI_TESTING_GUIDE.md`. You **MUST** strictly follow the test templates provided in that guide to ensure consistency with the existing headless tmux testing infrastructure. Failure to do so will result in broken UI tests and test suite failures.
- **Building Documentation**: Navigate to the `doc/` directory and run `make` (requires `docutils` installed via pip) to generate the updated man page and HTML documentation.
- **Single-File Constraint**: When adding new functionality, remember the primary design goal: `ping-bulk` must remain a single, self-contained script. Avoid splitting the core logic into multiple files or adding third-party dependencies unless absolutely necessary and agreed upon.

## 6. Known Quirks & Considerations
- **Shebang Execution**: The hosts file parser supports execution via a shebang (`#!/usr/bin/env -S ping-bulk -f`). Pay attention to compatibility notes regarding `env -S` and older systems when writing documentation or examples.
- **UI Responsiveness**: Because the UI runs in the main thread while ping subprocesses run in background threads, ensure thread-safe operations when updating the shared state (history, stats) to prevent UI tearing or crashes.

## 7. Future Work / TODOs
- Maintain compatibility with different variations of the `ping` command across various Linux distributions and macOS.
- Enhance test coverage for edge cases in network failures and SSH connection drops.
- Consider adding export functionalities (e.g., CSV/JSON output for metrics) if requested, keeping the single-file constraint in mind.

## 8. Recent Work
- **Phase 8 (command flags + key binding system)**: Full flag consistency refactor, `:bind-key` rename, `:quit --confirm` re-press pattern, data-driven overlay dispatch, `--mode`/`--desc`/`--hint` flags, bottom-bar hints moved from hardcoded Python to user-configurable trie entries.
- **Phase 7 (`:if`/`:elif`/`:else`/`:fi` conditionals)**: Hosts-file conditionals with variable expansion, usable both inside and outside `:for` loops.
- **Phase 6 (`:prog-options`, mux variables, port monitoring)**: `:prog-options` command, `%r/%d/%j/%R` template variables, TCP port monitoring via `PortMonitor`, inline `##` display-name syntax.
- Fixed an `OverflowError` bug in `PortMonitor._resolve_port` when `socket.getservbyport` fails with an out-of-bounds port.
- Refactored the monitor class hierarchy to use a proper abstract base class (`Monitor`) for improved extensibility.

## 9. Monitor Class Architecture

The monitor classes use an abstract base class pattern to unify ICMP and TCP monitoring logic.

### Structure
- `Monitor` (ABC) - Abstract base class with common attributes and shared methods.
- `PingMonitor(Monitor)` - Standard ICMP ping implementation using system `ping`.
- `PortMonitor(Monitor)` - TCP port monitoring using Python's `socket.create_connection`.
- `SshPingMonitor(Monitor)` - SSH-based remote ping monitoring.

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

## 10. Key Binding System

All interactive key bindings go through a single unified system. Do **not** add new hardcoded key checks in the main loop.

### Modes
There are four UI modes that determine which binding table is active:

| Mode | Active when |
|------|-------------|
| `normal` | Default — no overlay open |
| `help` | `?` help overlay is visible |
| `details` | Host details overlay is visible |
| `command` | `:` command-line input is active |

The active mode is tracked in `self._current_mode`.

### Binding tables
- **Normal mode**: bindings stored in `_key_trie` (supports multi-key sequences like `gg`).
- **Overlay modes** (`help`, `details`, `command`): bindings stored in `_mode_bindings[mode]` — single-key only, no sequences.

### Adding a default binding (Python side)
1. In `_register_default_bindings()` use the `_b()` helper for normal-mode keys:
   ```python
   _b('q', ':quit', hint='[q]uit')
   ```
2. For overlay-mode defaults, add to `_register_mode_bindings()`:
   ```python
   self._mode_bindings.setdefault('help', {})[ord('q')] = _Binding(
       commands=[':close'], key_notation='q', mode='help', origin='default')
   ```
3. `--hint` makes the label appear in the bottom bar; only set it on the most important actions.
4. `--desc` makes the binding appear in the `?` help overlay "Custom bindings" section.

### Adding a user-configurable binding (hosts file / config)
Users write `:bind-key` directives:
```
:bind-key ? :help --desc "Show help"
:bind-key --mode details q :close --hint "[q]uit"
```
`_cmd_bindkey` parses these and populates either `_key_trie` (normal mode) or `_mode_bindings` (overlay modes).

### Dispatching
- Normal mode: `_dispatch_key(key)` walks the trie and calls `_dispatch_cmd()`.
- Overlay modes: `_dispatch_mode_key(mode, key)` looks up `_mode_bindings[mode][key]` and calls `_dispatch_cmd()`.
- The main input loop **must not** contain bare `if key == ord('x')` checks for anything user-rebindable.

### Built-in overlay commands
| Command | Effect |
|---------|--------|
| `:close` | Close the currently active overlay (uses `_current_mode` to decide which) |
| `:scroll-overlay up` | Scroll overlay content up one line |
| `:scroll-overlay down` | Scroll overlay content down one line |
| `:scroll-overlay page` | Scroll overlay content down one page |
| `:scroll-overlay page-` | Scroll overlay content up one page |

---

## 11. Command & Flag Design Policy

### Command naming
- Use **kebab-case**: `:bind-key`, `:scroll-history`, `:scroll-overlay`, `:prog-options`.
- Keep old names as **aliases** when renaming; `saveconfig` always writes the canonical (new) name.
- Register aliases in `CMD_ALIASES` (or equivalent), not as separate `CmdDef` entries.

### Flag naming
- **Long flags are canonical**: `--confirm`, `--desc`, `--hint`, `--mode`, `--split-v`, `--split-h`, `--split-window`.
- Short single-char flags (e.g., `-v`, `-h`) are **aliases only** — never the primary documented form.
- Boolean flags: `--word` with no value (`--confirm`).
- Value flags: `--word value` space-separated, value may be quoted (`--mode help`, `--desc "Show help"`).

### Direction / scroll arguments
- **Trailing dash = reverse/backward**: `half-` scrolls left/back; `half` scrolls right/forward.
- Standard set: `half`, `half-`, `full`, `full-`, `page`, `page-`.
- Old leading-dash forms (`-half`, `-full`, `-page`) are kept as **permanent aliases**; do not remove them.

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
