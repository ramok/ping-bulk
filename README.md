# ping-bulk

Monitor multiple hosts simultaneously with continuous ping, displayed in a
live terminal interface.

```
Hostname          ms   Ping history [success]
google.com      15.3   ..............................
8.8.8.8          1.2   ..............................
1.1.1.1          0.8   ..............................
192.168.1.1      2.1   ...........XXXXXXXX...........
10.0.0.1         0.4   ..............................

Events
2026-03-20T14:05:32+0200   192.168.1.1 host down
2026-03-20T14:06:10+0200   192.168.1.1 host recover. Down time: 38 sec
```

## Features

- **Parallel monitoring** — each host runs in its own background thread
  with a persistent `ping` subprocess.
- **Rolling history strip** — one character (or numeric cell) per ping,
  color-coded green/yellow/red.
- **Interactive host navigation** — arrow keys (↑/↓) to highlight hosts,
  Enter to view detailed stats.
- **Section folding** — collapsible section headers (Space key toggles fold state).
- **Host details window** — comprehensive stats overlay for selected host
  (latency, uptime, packet loss).
- **Multiple stats columns** — Last RTT, Down/Up time, Average, Min, Max,
  Loss%, StDev, RX/TX/XX counts, or all at once.
- **DNS display modes** — show hostnames, IPs, or original names.
- **Flexible sorting** — by name, status, or latency.
- **SSH monitoring** — run `ping` on a remote machine via `ssh -o BatchMode=yes`
  and show results alongside local hosts.
- **Static DNS overrides** — map IPs to names without relying on DNS.
- **Brace expansion** — `10.0.0.{1..50}` expands to 50 hosts in one line.
- **Loop blocks** — `:for`/`:done` repeats body lines for every expansion of
  a pattern, substituting back-references (`$0`–`$9` or `$name`) per iteration.
- **Event log** — timestamped up/down/recover events, scrollable on screen
  and optionally streamed to a file.
- **Persistent config** — display preferences saved to
  `~/.config/ping-bulk/config`.

## Design goals

**ping-bulk** is a single self-contained Python 3 script.  It has no
third-party dependencies — only the Python standard library and the system
`ping` binary are required.  Installing it is as simple as copying one file.

## Installation

```sh
# Copy the script somewhere on your PATH
cp ping-bulk ~/.local/bin/
chmod +x ~/.local/bin/ping-bulk
```

**Requirements:**

- Python 3.8+
- Linux `ping` with `-O` and `-D` flag support (iputils-ping ≥ 20121221)
- A terminal with colour support

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
usage: ping-bulk [-h] [-f FILE] [-l LOGFILE] [--dns MODE] [--stats MODE]
                 [--sort MODE] [--ping-view MODE] [HOST ...]

positional arguments:
  HOST                  hosts/IPs to ping

optional arguments:
  -h, --help            show this help message and exit
  -f FILE, --file FILE  hosts file (# comment, ## section header, one host per line)
  -l LOGFILE, --log-file LOGFILE
                        append event log entries to this file in real time
  --dns MODE            DNS display mode at startup: off | hostname | ip
  --stats MODE          stats column at startup: off | Down | Loss% | Avg | Min | Max |
                        StDev | RX | TX | XX | All
  --sort MODE           sort order at startup: none | name | status | latency
  --ping-view MODE      ping history display mode at startup: success | rtt | scaled
```

Command-line options override settings from the config file
(`~/.config/ping-bulk/config`).

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
:ssh user@remote-server 10.20.0.1

## Remote site — many hosts via SSH (one SSH connection per host)
:ssh-begin user@remote-server
10.10.0.{1..8}
:ssh-end

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

 | Key             | Action                   | 
 | -----           | --------                 | 
 | `q` / `Q`       | Quit                            |
 | `?`             | Help overlay                    |
 | `:`             | Open command line               |
 | `d` / `D`       | Cycle DNS mode                  |
 | `s` / `S`       | Cycle stats column              |
 | `o` / `O`       | Cycle sort order                |
 | `h` / `H`       | Cycle history mode              |
 | `p` / `P`       | Toggle pause                    |
 | `↑` / `↓`       | Navigate host list              |
 | `Enter`         | Show detailed stats             |
 | `Space`         | Insert marker / Toggle fold     |
 | `Esc`           | Clear host selection            |
 | `C`             | Clear event log                 |
 | `←` / `→`           | Scroll history (step)           |
 | `Ctrl+←` / `Ctrl+→` | Scroll history (page)           |
 | `PgUp` / `PgDn` | Scroll event log                |

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
