# ping-bulk

Monitor multiple hosts simultaneously with continuous ping, displayed in a
live terminal interface.

```
Hostname            Up/Down    ms   Avg  StDev Ping History:success  40s
  router (10.10.0.1)     40s   0.3   0.3    0.0 .........................................
  gw (24.40.136.201)     40s   0.3   0.3    0.0 .........................................
  inet (8.8.8.8)         39s     -     -      - XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
  web (1.1.1.1)           0s  19.1  18.4    0.8 .XXXXXXX.XXXX........................

Events
2026-03-20T14:05:32+0200   inet host down.    Up time:   5 min 12 sec
2026-03-20T14:06:10+0200   inet host recover. Down time: 38 sec
```

## Features

- **Parallel monitoring** — each host runs in its own background thread
  with a persistent `ping` subprocess.
- **TCP port monitoring** — monitor connectivity to TCP ports
  (e.g. `example.com:443`) alongside ICMP ping.
- **Rolling history strip** — one character (or numeric cell) per ping,
  color-coded green/yellow/red.  Three display modes: success/fail,
  round-trip time, and scaled latency.
- **Interactive host navigation** — arrow keys / vim keys (↑↓/jk) to
  highlight hosts, Enter to view detailed stats.
- **Section folding** — collapsible section headers with autofold, recursive
  fold/unfold, fold-by-level, fold-healthy/unhealthy.
- **Host details overlay** — comprehensive stats for the selected host.
- **Multiple stats columns** — Last RTT, Up/Down time, Average, Min, Max,
  Loss%, StDev, RX/TX/XX counts, or all at once.
- **Remote clock monitoring** — `:set stats drift` shows each host's clock
  offset and `:set stats rtime` shows its clock time, read straight from the
  ICMP reply via `ping -T tsandaddr` — no SSH, no agent on the host, and it
  sees through NAT.  See [Remote clock monitoring](#remote-clock-monitoring).
- **DNS display modes** — off, hostname, IP, name+ip, ip+name.
- **Flexible sorting** — by name, status, or latency.
- **Remote monitoring** — run `ping` on a remote host via `:remote-ping`
  (SSH), one host at a time or a whole `:with remote-ping` block.  The relay
  may run Linux, FreeBSD/OPNsense or MikroTik RouterOS; its OS is detected
  automatically, or declared with `--os` / `:relay-os`.
- **Mux sessions** — open `mtr`, `ssh`, or any command in a tmux split
  pane directly from the host list (`:mux`).
- **Custom program options** — `:prog-options` / `:prog-options-begin`
  lets you pass extra flags to `ping`, `mtr`, etc. per host pattern.
- **Static DNS overrides** — `:resolv` maps IPs to display names.
- **Brace expansion** — `10.0.0.{1..50}` expands to 50 hosts in one line.
- **Loop blocks** — `:for`/`:done` repeats body lines with back-references
  (`$0`–`$9` or `$name`) per iteration.
- **Conditionals** — `:if`/`:elif`/`:else`/`:fi` with variable expansion.
- **Variables** — `:let` defines variables; `%r`, `%d`, `%j`, `%R` template
  variables available in `:prog-options` and `:mux`.
- **Key binding system** — fully rebindable keys via `:bind-key` /
  `:unbind-key`, with per-mode bindings (normal, help, details, command).
- **Search** — `/` search in host list or event log with `n`/`N` navigation.
- **Configurable log levels** — quiet/normal/info/debug via `:set log-level`,
  `-v`/`-q` flags.  Event coloring by severity.
- **Event log** — timestamped up/down/recover events with up-time and
  down-time durations, scrollable on screen and optionally streamed to a file.
- **Live editing** — `:edit` opens the hosts file in `$EDITOR`; changes
  reload automatically.
- **Persistent config** — display preferences saved to
  `~/.config/ping-bulk/config`.
- **Hosts file scripting** — shebang support (`#!/usr/bin/env -S ping-bulk -f`),
  making hosts files directly executable.
- **Kiosk mode** — `--kiosk` runs ping-bulk as the sole application on a
  physical console (e.g. `/dev/tty1`) via systemd.  SSH-only access through
  a hardened tmux session, restricted editor, syslog audit trail, and
  blocked escape routes.  See [`kiosk/README.md`](kiosk/README.md) for
  setup instructions.

## Design goals

**ping-bulk** is a single self-contained Python 3 script.  It has no
third-party dependencies — only the Python standard library and the system
`ping` binary are required.  Installing it is as simple as copying one file.

## Installation

**Requirements:**

- Python 3.8+
- Linux `ping` with `-O` and `-D` flag support (iputils-ping ≥ 20121221)
- A terminal with colour support

### Via pip

```sh
# From a local clone
pip install .

# Directly from GitHub
pip install git+https://github.com/ramok/ping-bulk.git
```

### Single-file copy

From a local clone:

```sh
cp ping-bulk ~/.local/bin/
chmod +x ~/.local/bin/ping-bulk
```

Or download the raw script straight from GitHub:

```sh
curl -fsSL https://raw.githubusercontent.com/ramok/ping-bulk/master/ping-bulk \
    -o ~/.local/bin/ping-bulk && chmod +x ~/.local/bin/ping-bulk

# the same with wget
wget -qO ~/.local/bin/ping-bulk \
    https://raw.githubusercontent.com/ramok/ping-bulk/master/ping-bulk \
    && chmod +x ~/.local/bin/ping-bulk
```

### Installer script

[`install.sh`](install.sh) automates the single-file install: it verifies
that the system `ping` supports the required `-O`/`-D` flags, downloads the
raw script into `~/.local/bin/ping-bulk` (overwriting a previous copy), and
— when `~/.local/bin` is not on `PATH` — appends an `export PATH` line to
`~/.bashrc` or `~/.zshrc`, picked from `$SHELL`:

```sh
curl -fsSL https://raw.githubusercontent.com/ramok/ping-bulk/master/install.sh | sh
```

The script is idempotent: re-running it just refreshes the installed copy.

## Quick start

```sh
# Ping a few hosts directly
ping-bulk 8.8.8.8 1.1.1.1 9.9.9.9

# Load from a hosts file
ping-bulk -f hosts.txt

# Combine both; stream the event log to a file
ping-bulk -l events.log -f hosts.txt 8.8.8.8

# Brace expansion on the command line
ping-bulk 10.0.0.{1..20}
```

Press **`?`** inside the running app for the full keyboard reference.

## CLI Options

```
usage: ping-bulk [-h] [--dns MODE] [--stats MODE] [--sort MODE]
                 [--ping-view MODE] [-l LOGFILE] [-f FILE]
                 [--sync-history {on,off}] [--kiosk] [--log-level LEVEL] [-v]
                 [-q] [--help-full] [--help-example] [--dump-hosts]
                 [--dump-simple-script FILE]
                 [HOST ...]

positional arguments:
  HOST                  hosts/IPs to ping

options:
  -h, --help            show this help message and exit
  --dns MODE            DNS display mode at startup: off | hostname | ip |
                        name+ip | ip+name
  --stats MODE          stats column at startup: off | down | loss% | avg |
                        min | max | stdev | rx | tx | xx | all
  --sort MODE           sort order at startup: none | name | status | latency
  --ping-view MODE      ping history display mode at startup: success | rtt |
                        scaled
  -l, --log-file LOGFILE
                        append event log entries to this file in real time
  -f, --file FILE       hosts file; may be given multiple times, loaded in
                        order
  --sync-history {on,off}
                        align history bars to wall-clock time (default: on)
  --kiosk               run in kiosk mode: auto-launch tmux, restrict
                        commands, use rnano/rvim
  --log-level LEVEL     event log verbosity: quiet normal info debug trace
                        (default: normal)
  -v                    increase log verbosity (-v info, -vv debug)
  -q                    decrease log verbosity (-q quiet)
  --help-full           show full manual and exit
  --help-example        show full advanced example and exit
  --dump-hosts          print only the expanded host inventory ("IP ## name"
                        lines and ## titles; no : commands) and exit
  --dump-simple-script FILE
                        write a self-executing hosts script to FILE (chmod +x,
                        overwrites): fully expanded like --dump-hosts but with
                        : commands kept and a #!/bin/sh header; FILE of '-'
                        (or /dev/stdout) writes to stdout instead, unchanged
                        and not chmod'ed, so it can be piped
```

Command-line options override settings from the config file
(`~/.config/ping-bulk/config`).

### Built-in help

`--help-full` prints the complete built-in manual — every hotkey, `:command`,
hosts-file directive, and expansion rule (the same content as the `?` overlay
inside the app).  `--help-example` prints a fully commented advanced hosts
file demonstrating most features; it mirrors
[`examples/ping-bulk.advance`](examples/ping-bulk.advance) and is a good
starting point: `ping-bulk --help-example > my.hosts`.

### Dumping an expanded hosts file

Hosts files can use loops, conditionals, and variables (see below).  Two
flags turn such a file into a flat, human-editable copy with every
`:for`/`:if`/`:let` and brace expansion already resolved:

- `--dump-hosts` prints a plain inventory to stdout: one `IP  ## name` line
  per monitored target plus `##`/`###` section titles, nothing else.
- `--dump-simple-script FILE` writes a runnable copy instead: the other
  directives (`:set`, `:bind-key`, `:prog-options`, …) are kept and a
  `#!/bin/sh` self-exec header is prepended, so `./FILE` starts ping-bulk
  directly.  `FILE` is overwritten and marked executable; `-` (or
  `/dev/stdout`) writes to stdout so the script can be piped, leaving the
  destination's permissions alone.

Both flatten `:remote-ping` targets to plain hosts and splice `:source`'d
files in, which is handy for handing a working configuration to someone who
only needs to update IPs.  Try them on the files in
[`examples/`](examples/):

```sh
ping-bulk --dump-hosts -f examples/ping-bulk.advance
ping-bulk --dump-simple-script flat.hosts -f examples/ping-bulk.advance
ping-bulk --dump-simple-script - -f examples/ping-bulk.advance | less
```

## Hosts file

A hosts file lists one host per line with optional section headers,
comments, and command directives:

```
#!/usr/bin/env -S ping-bulk -f
## Gateways
10.0.0.1  ## main-gw
10.0.0.2  ## backup-gw

:title Cloud DNS
8.8.8.8
1.1.1.1

## Office LAN
:resolv 10.1.0.{1..4}  switch$1
10.1.0.{1..4}

## Remote site — single host via SSH
:resolv 10.99.0.100  remote-server
:remote-ping user@remote-server 10.20.0.1

## Remote site — many hosts via SSH (one SSH connection per host)
:with remote-ping user@remote-server
10.10.0.{1..8}
:end

## Behind a MikroTik router (RouterOS '/ping'; 'auto' would detect it too)
:with remote-ping --os mikrotik admin@10.0.0.1
10.30.0.{1..4}
:end

:log /var/log/ping-bulk.log
```

Because the first line is a shebang, you can make the file executable and
run it directly:

```sh
chmod +x hosts.txt
./hosts.txt
```

### Shebang: why `env -S`?

The Linux kernel passes only a *single* argument string to the interpreter
in a `#!` line.  Without `-S`, `env` would look for a binary literally
named `ping-bulk -f`.  The `-S` / `--split-string` flag tells `env` to
split the argument on whitespace first, so `ping-bulk` and `-f` arrive as
two separate tokens.

`env -S` requires **GNU coreutils ≥ 8.30** (Debian 10+, Ubuntu 20.04+,
Fedora 29+) or **macOS 12+**.  On older systems use the portable polyglot
shebang instead:

```
#!/bin/sh
# \
exec ping-bulk -f "$0" "$@"
```

This works because shell treats `# \` as a comment (ignoring the
backslash) and runs the `exec` line, while ping-bulk joins the two lines
via backslash continuation — making the whole thing a single comment that
is silently skipped.  Extra arguments passed on the command line are
forwarded via `"$@"`.

> **Note:** logging and other options can be set inside the hosts file
> itself with `:log /path/to/file` rather than via command-line flags.

See the [man page](doc/ping-bulk.rst) or `doc/` for the full syntax
reference.

## Keyboard shortcuts

| Key                 | Action                      |
| -----               | --------                    |
| `q` / `Q`           | Quit                        |
| `?`                 | Help overlay                |
| `:`                 | Open command line           |
| `d` / `D`           | Cycle DNS mode              |
| `s` / `S`           | Cycle stats column          |
| `o` / `O`           | Cycle sort order            |
| `h` / `H`           | Cycle history mode          |
| `p` / `P`           | Toggle pause                |
| `↑` / `↓`           | Navigate host list          |
| `Enter`             | Show detailed stats         |
| `Space`             | Insert marker / Toggle fold |
| `Esc`               | Clear host selection        |
| `C`                 | Clear event log             |
| `←` / `→`           | Scroll history (step)       |
| `Ctrl+←` / `Ctrl+→` | Scroll history (page)       |
| `PgUp` / `PgDn`     | Scroll event log            |

## Remote clock monitoring

Two stat columns expose each host's own clock — handy for catching dead NTP,
missing RTCs, wrong timezones, or VM time skew across a fleet:

- `:set stats drift` — the signed **offset** from this machine's clock
  (`-0.7s`, `+11h06m`).
- `:set stats rtime` — the host's **clock time** of day in UTC (`10:32:14`),
  ticking live.

They share one probe and can be combined (`:set stats rtime,drift`).

```
Hostname         ms     RTime      Drift   Ping History:success
10.123.2.2      45.7   10:32:14    -0.7s   ..........   (green: within a second)
10.122.0.62     42.0   21:38:20   +11h06m  ..........   (magenta: way off)
8.8.8.8         15.0    no-rt      no-rt   ..........   (dim: no timestamp support)
```

Colours match the `ms` column: green under 1 s of offset, yellow up to a
minute, magenta beyond. Open a host's details overlay for the remote clock, the
local clock, and the signed offset side by side.

**How it works.** The offset is read directly from the ICMP reply using the IP
timestamp option (`ping -T tsandaddr`) — each hop stamps the packet with its own
clock and address, and ping-bulk picks out the target's stamp (which works even
when NAT rewrites the host's address). No SSH login and no agent are needed on
the monitored host; for `:remote-ping` hosts the same probe runs from the relay.
Design notes and the NAT walk-through are in
[`doc/remote-clock.md`](doc/remote-clock.md).

The probe is separate from the liveness ping and is armed the first time a host
comes up:

- If the host answers, its offset is polled every `:set clock-interval` seconds
  (default 30).
- If the host pings but never returns a timestamp — the option is stripped
  along the path (common on the public internet), or its `ping` lacks `-T`
  (e.g. busybox) — it is marked `no-rt` and **not probed again** until it next
  recovers, so no packets are wasted.

**Limitations.** Works on LAN / overlay networks only (IP-option packets are
usually dropped across the internet). The ICMP timestamp is milliseconds since
**UTC midnight**, so there is no date or timezone: the remote time is shown in
UTC, and a clock wrong by whole days but right within the day is not
detectable; offsets are folded to ±12 h. Auto-discovery reaches a host up to 4
hops away (an IPv4 protocol limit) — deeper hosts show `no-rt`. See
[`doc/remote-clock.md`](doc/remote-clock.md) for the full rationale.

## Documentation

Full documentation is in [`doc/ping-bulk.rst`](doc/ping-bulk.rst)
(reStructuredText).  Build a man page or HTML with
[docutils](https://docutils.sourceforge.io/):

```sh
pip install docutils   # if not already installed
make -C doc            # produces doc/ping-bulk.1 and doc/ping-bulk.html
man doc/ping-bulk.1
```

## Examples

Ready-to-run hosts files are in the [`examples/`](examples/) directory.

## Credits

**ping-bulk** was inspired by
[ping-multi](https://github.com/famzah/ping-multi) and
[ping-multi-ext](https://github.com/famzah/ping-multi-ext) by
Ivan Zahariev ([famzah](https://github.com/famzah)).
