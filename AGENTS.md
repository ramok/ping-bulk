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
- Fixed an `OverflowError` bug in `PortMonitor._resolve_port` when standard library `socket.getservbyport` fails with an out-of-bounds port by catching `OverflowError` alongside `OSError`.
- Refactored the monitor class hierarchy to use a proper abstract base class (`Monitor`) for improved extensibility.
- Implemented TCP port monitoring via `PortMonitor` and added the `:ping <host>:<port>` syntax.
- Integrated event logs into the expanded host details overlay with scrolling support.
- Configured keyboard navigation (Up, Down, Page Up, Page Down) to handle scrolling within the details view.
- Added ESC to the help text to indicate clearing host selection.

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

