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
- **Testing**: `pytest` (and related standard testing tools).
- **Documentation**: `docutils` (optional, for building man pages and HTML docs).

## 4. Key Features & Functionality
- **Parallel Monitoring**: Each host is monitored in its own background thread with a persistent `ping` subprocess, ensuring high concurrency and responsive UI.
- **Interactive UI**: Users can navigate the host list with arrow keys, view detailed stats, scroll history, toggle display modes (DNS, stats columns, history view), and fold sections.
- **SSH Monitoring**: The ability to run `ping` on a remote machine via `ssh` and aggregate the results alongside local targets.
- **Advanced Configuration**: Supports command-line arguments and robust "hosts files" with directives for brace expansion (`{1..50}`), loop blocks (`:for`/`:done`), and DNS overrides (`:resolv`).
- **Persistent Configuration**: User preferences are saved in `~/.config/ping-bulk/config`.

## 5. Development & Testing Workflow
- **Running the Application**: You can run the script directly from the root directory: `./ping-bulk <hosts>`.
- **Running Tests**: Navigate to the root directory and execute `pytest tests/` to run the test suite. Ensure any new features include appropriate tests, especially for complex parsing (like brace expansion or SSH directives). For more details on the testing infrastructure and how to write tests using the headless tmux environment, refer to `tests/AI_TESTING_GUIDE.md` and `SKILL.md`.
- **Building Documentation**: Navigate to the `doc/` directory and run `make` (requires `docutils` installed via pip) to generate the updated man page and HTML documentation.
- **Single-File Constraint**: When adding new functionality, remember the primary design goal: `ping-bulk` must remain a single, self-contained script. Avoid splitting the core logic into multiple files or adding third-party dependencies unless absolutely necessary and agreed upon.

## 6. Known Quirks & Considerations
- **Shebang Execution**: The hosts file parser supports execution via a shebang (`#!/usr/bin/env -S ping-bulk -f`). Pay attention to compatibility notes regarding `env -S` and older systems when writing documentation or examples.
- **UI Responsiveness**: Because the UI runs in the main thread while ping subprocesses run in background threads, ensure thread-safe operations when updating the shared state (history, stats) to prevent UI tearing or crashes.

## 7. Future Work / TODOs
- Maintain compatibility with different variations of the `ping` command across various Linux distributions and macOS.
- Enhance test coverage for edge cases in network failures and SSH connection drops.
- Consider adding export functionalities (e.g., CSV/JSON output for metrics) if requested, keeping the single-file constraint in mind.

