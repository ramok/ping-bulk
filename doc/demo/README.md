# ping-bulk Demo Recordings

Reproducible terminal demos of ping-bulk that can be regenerated whenever
features or the UI change.

## Directory layout

```
doc/demo/
├── Makefile                  Build targets for each demo tier
├── README.md                 This file
├── mock-ping                 Deterministic fake ping with timed failure
├── keypress-overlay.py       2-line overlay showing pressed keys in real time
├── record.sh                 Main orchestrator (tmux + asciinema + agg)
├── scenarios/
│   ├── basic.sh              ~30s scenario script
│   ├── standard.sh           ~60s scenario script
│   └── advanced.sh           ~90s scenario script
├── hosts/
│   ├── basic.hosts           5 hosts + TCP port target
│   ├── standard.hosts        8 hosts, 2 sections
│   └── advanced.hosts        12+ hosts, autofold, port monitors, remote-ping
└── output/                   Generated files (gitignored)
    ├── basic.cast / .gif / .webp
    ├── standard.cast / .gif / .webp
    └── advanced.cast / .gif / .webp
```

## Requirements

| Tool | Install |
|------|---------|
| `asciinema` | `apt install asciinema` |
| `agg` | `cargo install agg` or [GitHub releases](https://github.com/asciinema/agg/releases) |
| `tmux` | `apt install tmux` |
| `python3` | `apt install python3` |

## Generating demos

```sh
cd doc/demo

# Generate all three demos (both .gif and .webp)
make all

# Single tier
make basic
make standard
make advanced

# GIF only (faster, skip WebP)
make basic ARGS='--gif'

# Re-run even if output already exists
make clean && make all
```

## Demo tiers

### basic (~30s)
Covers: startup, live ping display, TCP port target, host details overlay,
host failure event + recovery with Down/Up time in event log.

### standard (~60s)
Covers everything in basic, plus: host navigation (↑/↓), DNS mode cycling,
stats column cycling, history mode cycling, section fold/unfold, fold-all /
unfold-all, help overlay (scroll), search (/), filter view, command line (:).

### advanced (~90s)
Covers everything in standard, plus: vim-style navigation (j/k/gg/G),
autofold (healthy sections collapse automatically), `:edit` with live reload,
`:mux mtr` (MTR in a tmux split), SSH connect (c), `:remote-ping`.

## How it works

1. `record.sh` creates a tmux session with two panes:
   - **Top pane** (main): `ping-bulk` using `mock-ping` (fake, deterministic ping)
   - **Bottom pane** (2 lines): `keypress-overlay.py` reads key names from a
     FIFO and displays `⌨ key` in real time
2. `asciinema` attaches to the tmux session in read-only mode and records to
   a `.cast` file
3. The scenario script sends `tmux send-keys` commands to ping-bulk and writes
   key labels to the overlay FIFO for on-screen display
4. After the scenario ends, `agg` converts the `.cast` to `.gif` and/or `.webp`

## Updating a demo after a feature change

1. Edit the relevant scenario in `scenarios/<tier>.sh` and/or the hosts file
   in `hosts/<tier>.hosts`
2. Run `make clean && make <tier>` to regenerate
3. Commit the updated `output/<tier>.gif` (and `.webp`) to the repository

## mock-ping environment variables

The fake ping respects these variables (set automatically by `record.sh`):

| Variable | Default | Description |
|----------|---------|-------------|
| `MOCK_PING_LATENCY_BASE` | 1.0 | Base RTT in ms |
| `MOCK_PING_LATENCY_JITTER` | 0.2 | ± jitter in ms |
| `MOCK_PING_SEED` | 42 | RNG seed (reproducibility) |
| `MOCK_PING_FAIL_AFTER` | inf | Seconds until host goes down |
| `MOCK_PING_FAIL_DURATION` | 5.0 | Seconds the host stays down |
| `MOCK_PING_INTERVAL` | 1.0 | Ping interval in seconds |
