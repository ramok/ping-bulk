# Custom probes (per-host values over SSH)

This note plans a mechanism for reading arbitrary values from a monitored host
— temperature, fan speed, disk use, anything a command can print — and showing
them next to the ping data. It records the options considered and why each was
chosen, in the same spirit as `remote-clock.md`.

Status: **implemented**, except the fixed-width strip column noted under
view (b) — the strip is currently the full-width view mode only.

## What it should do

A value is read from each host on an interval and can be displayed three ways:

| View            | Shows                                       | Selected with         |
| --------------- | ------------------------------------------- | --------------------- |
| stats column    | the latest value                            | `:set stats temp`     |
| history strip   | the value over time, one cell per sample    | `:set ping-view temp` |
| details overlay | current value, series statistics, sparkline | `Enter` on the host   |

## Decisions already taken

- **Values are read per host**, not from a relay on the host's behalf.
- **`-` means no data** (never read, or nothing retained); **`err` means the
  host or the probe failed**. No third symbol.
- **A probe never changes host status.** A host at 95 °C that answers ping is
  UP. Probes affect colour only.
- **One SSH connection per host**, not one per poll.

That last one is the constraint that shapes everything else. The existing
clock probe opens a fresh `ssh` for every reading, which is why its default
interval is 30 s — the code says so at `Monitor.__init__`: "for remote-ping
hosts each probe is a fresh SSH connection, so a short interval is costly."
A probe mechanism that repeated this would inherit the same ceiling.

## Transport

| Option                       | How                                                                         | Verdict                                                                                    |
| ---------------------------- | --------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ |
| One-shot per poll            | `subprocess.run(['ssh', host, cmd])` each interval, as the clock does       | rejected: the cost this design exists to remove                                            |
| `ControlMaster` multiplexing | one TCP/auth session, cheap channels per poll                               | not for probes, but **worth adopting separately** for the one-shot paths (`c`, `t`, clock) |
| Share the ping connection    | one `ssh` running both `ping` and the probe loop                            | rejected: couples the two; a probe parse bug takes ping down with it                       |
| One connection per relay     | one `ssh` to a relay that probes many targets                               | rejected: values are per host, and it only helps relayed topologies                        |
| **Persistent reader loop**   | `ssh host 'while :; do <cmd>; echo ---; sleep N; done'`, parsed as a stream | **chosen**                                                                                 |

The reader loop lands on `SubprocessMonitor`, which already solves the hard
parts of owning a long-lived remote child: both pipes are drained (so the child
cannot block writing stderr), reads are raw `os.read` rather than buffered
`readline`, stderr is classified only after exit, and a child that goes silent
is killed so the backoff loop replaces it. Those invariants are documented in
`AGENTS.md` §9 and were paid for by a real deadlock; a probe reader gets them
for free by subclassing.

With one connection held open, the interval stops being a cost decision: 5 s is
as cheap as 60 s, and changing it only restarts the remote loop.

Authentication failures need no special handling — `_FATAL_SSH_ERRORS` already
classifies "permission denied" and friends as non-retryable, so a host with no
credentials fails once instead of reconnecting forever.

## Configuration

One command supplies every value; each value declares how it is displayed:

```text
# one round trip carries all parameters
:probe-source --cmd '/usr/local/bin/pb-probe' --interval 60 --hosts '*-nuc'

# per-value display metadata
:probe temp --unit °C  --range 20:90   --warn 70 --crit 85
:probe rpm  --unit rpm --range 0:5000
:probe gps  --unit s   --range 0:5     --label GPS
```

Four later additions, each answering something the first cut could not:

- **`--hosts <globs>`** — which hosts run the command at all. Undeclared keys
  were always ignored, but that is a display filter: the connection is opened
  either way, so a file mixing Linux boards, routers and cameras opened one to
  every host and the ones with no shell each held a failing connection on a
  backoff loop for the life of the run.
- **`--script <local file>`** — the alternative to `--cmd`, for when nothing is
  installed on the hosts. Its contents are carried inside the remote command as
  base64 and decoded once per connection into a shell variable; nothing is
  written to the host. Base64 rather than inline shell because a hosts file
  expands `$name` at parse time and reads `$1` as a `:for` backreference, which
  empties or rewrites most of a real script before it is ever sent.
- **`--label TEXT`** — the column header, which otherwise is the name with its
  first letter capitalised. That suits `temp`; it heads a `gps` column `Gps`.
- **`--combine A,B,C`** — one column holding several readings joined with `/`,
  so `GPS s/off/sat` over `0/0/29` costs the width of one header rather than
  three each wide enough to name itself. It has no reading of its own, so the
  flags describing one are refused on it and the members carry them; it takes
  its worst member's colour, and collapses to a single `-` or `err` when no
  field has a reading, since `-/-/-` on every host the probe does not reach is
  punctuation saying what one `-` says.

The login is the host's own `:prog-options ssh` rule, so a site records it once
for `:mux`, `[c]` and the probe alike, and `--disable` there means no probe
connection either.

The remote command prints one `key=value` per line:

```text
temp=54.2
rpm=1200
```

Keys with no matching `:probe` are ignored, so one site-wide probe script can
serve hosts that display different subsets.

| Option                        | Pros                                                   | Cons                                                            |
| ----------------------------- | ------------------------------------------------------ | --------------------------------------------------------------- |
| One command per value         | simplest to describe                                   | one round trip per value, wasting the shared connection         |
| **Source command + `:probe`** | one round trip, N values; display metadata is explicit | two directives to learn                                         |
| Extend `:prog-options`        | reuses a familiar mechanism                            | that command means "flags for a program", not "a value to read" |
| Hardcode a `temp` column      | smallest change                                        | the next request is humidity                                    |

`--unit` feeds the column and the overlay, `--range` feeds the strip, and
`--warn`/`--crit` feed colour in all three views.

## View (a): stats column

Behaves like `drift`: header from the probe name, latest value, colour by
threshold. Polling should be gated on the column being displayed, the way
`_clock_stat_visible()` already gates clock probes — with a persistent
connection the gate decides whether to open it at all.

## View (b): history strip

This is the view that forces a **time series** per probe — parallel `values` and
`times` deques per host, exactly as `history` / `history_times` work for ping —
rather than the single cached reading `drift` keeps.

`get_history_string()` already does most of the work: it takes a `mode`, a
`cell_width` greater than one (that is how `rtt` prints numbers), and in `sync`
mode buckets samples by wall-clock time, leaving spaces where no sample landed.

### Time base

Ping is one sample per second and buckets are one second wide. A probe at 60 s
in one-second buckets makes a 50-cell strip cover 50 seconds and show at most
one sample.

| Option                | Pros                                                 | Cons                                                                                                                                         |
| --------------------- | ---------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------- |
| Reuse 1 s buckets     | no new code                                          | a nearly empty strip at any realistic interval                                                                                               |
| **Bucket = interval** | dense and honest; 50 cells at 60 s covers 50 minutes | `get_history_string` gains a bucket-size parameter; probe and ping strips no longer share a time axis, so `sync-history` stops aligning them |
| Hold last value       | dense, matches common dashboards                     | draws data that was never read; a stalled probe looks healthy, contradicting `-`/`err`                                                       |

Chosen: **bucket = interval**. Hold-last-value is worth keeping as an explicit
`--hold` flag, never a default.

### Value to character

| Option              | Pros                                                 | Cons                                                                                                      |
| ------------------- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------- |
| **Declared range**  | one glyph means one value on every host; predictable | the range must be known up front; out-of-range clamps                                                     |
| Auto-scale per host | no configuration                                     | the same glyph means different things per host, and rescaling rewrites the meaning of cells already drawn |
| Threshold glyphs    | reads at a glance; reuses `--warn` / `--crit`        | loses magnitude — "hot", but not how hot                                                                  |

Chosen: **declared range** as the default (digits 0-9 by bucket, as `scaled`
does), with threshold glyphs available as a second mode. They answer different
questions and share the same declarations.

### Where the strip is drawn

| Option                                | Pros                                           | Cons                                                        |
| ------------------------------------- | ---------------------------------------------- | ----------------------------------------------------------- |
| **View mode** (`:set ping-view temp`) | full width; reuses scroll and offset machinery | ping is hidden while a probe is shown                       |
| Second row per host                   | ping and probe visible together                | doubles list height; a 47-host file stops fitting on screen |
| **Fixed-width strip column**          | both visible; composes with multi-column stats | narrow, so little history; variable-width column logic      |

Chosen: **view mode** first — `:set ping-view <probe>` swaps the strip over to
that value, and `[H]` cycles back to the ping modes.  The fixed-width strip
column is not built yet; it is the remaining piece of this view.

Two things about that first cut turned out to be wrong, and were corrected once
a real probe was on screen:

**The cell shows the reading, not a bucket of it.** A 0-9 glyph mirrors the
`scaled` ping mode, but a latency bucket is read against a scale everybody
knows, while a probe bucket has to be decoded against that probe's `--range`:
`gpssat --range 0:32` drew `8` for twenty-eight satellites. The strip now sizes
its cell from the range and prints the value, exactly as the `rtt` view prints a
latency — `28`, at the cost of the columns the digits take. The 0-9 glyph
survives in the overlay sparkline, which has one column per sample and its own
axis labels.

**Cells are coloured by `--warn`/`--crit`, like the column and the overlay.**
Colouring by position in the range meant colouring by the shared ping palette,
where `5`-`9` is yellow because for latency a high number is a slow reply. A
probe is not latency: twenty-eight of thirty-two satellites drew yellow for
being *good*. Judging the reading the way the other two views judge it makes a
probe without thresholds uncoloured rather than wrong, which is the honest
answer — the number is on screen either way.

**The newest sample is on the left**, where the ping strip puts it. These two
occupy the same columns and `:set ping-view` swaps one for the other, so
opposite directions made a probe series appear to run backwards against the bar
it replaced. The overlay sparkline still reads left to right, because it is
labelled `^ 38 min ago … now ^` and sits among `Min / Max` and `Average` rather
than next to the ping bar.

## View (c): details overlay

The overlay is a list of lines built per host, already organised as titled
blocks — `Packet Statistics:`, `Latency Statistics:`, `Clock (from ICMP
timestamp, UTC):` — each with indented `label: value` rows, and it scrolls.
Four shapes were considered.

**Compact list.** One line per probe:

```text
  Probes:
    temp      54.2 °C    12s ago
    rpm       1200 rpm   12s ago
    humidity  -
```

Scales to many probes and is trivial to build, but shows no trend or spread —
everything the retained series knows is thrown away.

**Statistics block per probe**, mirroring `Latency Statistics`:

```text
  Probe: temp (°C)
    Current:     54.2      warn 70   crit 85
    Min / Max:   41.0 / 62.5
    Average:     52.8
    Samples:     1440  (24 h retained)
    Last probe:  12s ago
```

Matches the overlay's existing idiom exactly, and answers "is this normal for
this host" — but costs six lines per probe.

**Block with sparkline**, reusing the strip renderer at full overlay width:

```text
  Probe: temp (°C)                       range 20:90
    Current:     54.2      warn 70   crit 85
    Min / Max:   41.0 / 62.5        Average: 52.8
    Last probe:  12s ago             1440 samples, 24 h
    History:     3334444455555555544444333344445555666
                 ^ 38 min ago                     now ^
```

Answers "is it rising", which is usually the actual question, and costs no new
rendering code — the strip renderer is already there and the overlay sizes its
width dynamically.

**Table**, when a host has many probes:

```text
  Probes:
    Name       Current      Min      Max      Avg   Age   State
    temp       54.2 °C     41.0     62.5     52.8   12s   ok
    rpm       1200 rpm    900.0   1400.0   1150.0   12s   ok
    humidity          -        -        -        -     -   no data
```

Comparable at a glance and compact for six probes, but alignment work, and
still no trend.

Chosen: **block with sparkline**, falling back to the table if hosts commonly
carry more than three or four probes. The block form matches how the overlay
already presents packet, latency and clock data, and a host realistically has
one or two probes rather than twenty. The sparkline is the reason to open the
overlay at all — the column already gives the current number.

## Failure handling

`-` and `err` are display states; what happens *after* a failure is
configurable, because both behaviours are wanted:

| `--on-fail` | Behaviour                                                               | Suits                                                                     |
| ----------- | ----------------------------------------------------------------------- | ------------------------------------------------------------------------- |
| `retry`     | keep polling forever (default)                                          | a probe expected to work; transient failures; a sensor that appears later |
| `give-up`   | stop after N consecutive failures until the host goes down and up again | a command absent on some hosts — the `no-rt` behaviour of clocks          |

`give-up` mirrors `clock_state == 'no-remote-time'` and its
`_CLOCK_NO_RT_PROBES` counter, which exists so a single lost packet cannot
brand a host permanently. A probe that gave up still shows `err`; the overlay
explains that polling stopped, and an event records it. No new column symbol.

With a persistent connection the cost difference between the two is small — the
remote loop is already running — so `retry` is the better default and `give-up`
is for hosts where the command genuinely does not exist.

## Refactors this needs first

1. **Stat cells become a registry.** `_compute_stat` is a twelve-branch
   `elif mode == ...` chain; user-defined column names cannot live in it. It
   needs a `name -> (header, width, formatter)` mapping. Worth doing on its own.
2. **`get_history_string` gains a bucket size** and a per-mode value-to-character
   mapper, so ping and probe series share one renderer.
3. **A generic per-monitor store.** The clock feature added six ad-hoc
   attributes to `Monitor.__init__`; probes need one
   `monitor.probes: dict[name] -> (values, times, state)` instead of repeating
   that per parameter.

## Kiosk mode

A probe runs a command of someone's choosing on every monitored host, and in
kiosk mode the person at the console is the adversary. Working out where the
hole actually was decided the design:

- **The hosts file is already admin-controlled.** It lives in
  `/etc/ping-bulk/`, `:edit` requires write access and refuses without it, and
  `:edit` can only open the hosts file, not an arbitrary path. A probe declared
  there is as trusted as the rest of that file.
- **The `:` command line was wide open.** Typing `:probe-source --cmd ...` would
  run a chosen command on every host, repeatedly, with no pane to show it.

So `:probe` and `:probe-source` are refused *interactively* in kiosk mode and
accepted only from the hosts file at startup. That closes the hole; a path
restriction would not have, since a console user could name any file under an
allowed directory.

On top of that, the script a kiosk deployment names is verified rather than
assumed: a regular file, not group- or world-writable, with no
group/other-writable directory on the path to it -- a writable parent lets the
file be swapped wholesale. This is what `ssh` does for a private key and `sudo`
for sudoers. Only the first token of a `--cmd` can be ownership-checked, so a
kiosk probe must be a script rather than a shell pipeline, and `;`, `|`, `&`,
backticks, `$`, and redirections are refused outright in it — otherwise
`/usr/bin/true; curl … | sh` would pass a check on `/usr/bin/true` and run
whatever follows on every host.

`--script` is checked the same way, on the **local** file it ships. The
metacharacter rule does not carry over and must not: the command that reaches
the host is composed by ping-bulk and contains `|` and `$` by construction, so
applying it there would refuse every `--script`. The question the rule exists
to answer is "can the console user choose what runs", and for `--script` that
is settled by the ownership of the file being read.

The probe connection also carries the same SSH isolation flags as `:mux` and
`:remote-ping` (`-F none`, `IdentityFile=none`, `ProxyCommand=none`). Without
them a probe would read `~/.ssh/config` and the user's keys, which is precisely
what kiosk keeps out of reach.

## Open questions

- **Retention.** `history-size` defaults to 86400, meaning 24 h at one ping per
  second. At a 60 s probe interval the same number is 60 days. Own setting per
  probe, or derived from the interval?
- **Threshold events.** Colour only is settled for status, but should crossing
  `--crit` write a line to the event log? It would be the first event a probe
  can raise.
- **Probe source failure vs value failure.** If the source command runs but
  omits a key, is that `-` (no data) or `err` (failure)? They are different
  causes with the same look.
