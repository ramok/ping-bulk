# Remote clock monitoring (drift / rtime)

This note explains how ping-bulk reads a remote host's clock, the NAT/overlay
problem that shaped the design, the alternatives considered, and why the
`ping -T tsandaddr` approach was chosen.

## What it does

Two stat columns expose a monitored host's own clock:

| Stat    | Shows                                  | Example   |
| ------- | -------------------------------------- | --------- |
| `drift` | signed offset from this machine's clock | `+10h58m` |
| `rtime` | the host's clock time of day (UTC)      | `22:45:33` |

Enable with `:set stats drift`, `:set stats rtime`, or both
(`:set stats rtime,drift`). Colours match the `ms` column: green under 1 s of
offset, yellow up to a minute, magenta beyond. `no-rt` means the host does not
provide a usable timestamp. The host details overlay shows the remote clock,
the local clock, and the offset side by side.

## How the clock is read

The offset comes straight from the ICMP echo reply using the IPv4 **timestamp
option** (`ping -T`) — the host stamps the packet with its own clock as it
passes. No SSH login and no agent are required on the monitored host. The probe
is separate from the liveness ping and is armed the first time a host comes up;
hosts that answer are re-polled every `:set clock-interval` seconds (default
30), and hosts that ping but never return a timestamp are marked `no-rt` and
not probed again until they next recover.

## The NAT / overlay problem

The IPv4 timestamp option matches hops **by address**. That breaks under NAT.

Consider `10.123.2.2`, reached over a ZeroTier overlay, which NATs to the
host's real inside address `10.0.0.2`:

```
ping -T tsprespec 10.123.2.2 10.123.2.2   →   TS: 10.123.2.2  <local-looking time>
ssh root@10.123.2.2 date -u               →   Tue Apr 28 22:45 UTC   (clock is wrong!)
```

The stamp *labelled* `10.123.2.2` reads a correct-looking time, yet the host's
real clock is ~11 hours off. The reason: we route to `10.123.2.2`, but NAT
rewrites the destination to `10.0.0.2` before the host sees it. The host
identifies itself as `10.0.0.2`, so it does **not** match a `tsprespec` for
`10.123.2.2` — the NAT gateway (which owns `10.123.2.2`, with a correct clock)
stamps that slot instead. We end up reading the gateway's clock, not the host's.

`tsandaddr` fixes this because it records the stamping **address** next to each
timestamp, so the host's real inside address and its real clock come back in the
reply itself:

```
ping -T tsandaddr 10.123.2.2
TS:  10.122.0.129  11:21:07   (us — correct)
     10.122.0.62   22:27:32   (relay — wrong)
     10.123.2.1    11:21:07   (far NAT gateway — correct)
     10.0.0.2      22:27:32   (the host, real inside addr — wrong ← target)
Unrecorded hops: 3
```

### Selecting the target hop

The option is stamped by every hop in path order: outbound hops, the
destination, then return hops. The destination is the last **new** address
before the path folds back. ping-bulk therefore takes the hop just before the
first repeated address; if no address repeats (the option filled on the way
out), the deepest recorded hop is the target:

| Path recorded                          | First repeat | Target        |
| -------------------------------------- | ------------- | ------------- |
| `[us, relay, gw, 10.0.0.2]` (NAT host) | none          | `10.0.0.2`    |
| `[us, dest, dest, us]` (1-hop host)    | `dest` again  | `dest`        |

A reading is rejected (`no-rt`) when only our own egress stamped (fewer than two
distinct addresses — the host did not answer the option) or the value is out of
range (a non-standard high-bit timestamp).

## Alternatives considered

| Option       | Identifies host?              | Depth        | Verdict                          |
| ------------ | ----------------------------- | ------------ | -------------------------------- |
| `tsonly`     | no — timestamps carry no address | 9 hops    | unusable: cannot attribute a stamp to a host (the same clock appears in several slots) |
| `tsprespec`  | yes, if the real address is known | unlimited | needs the inside address up front; wrong device answers under NAT when the routed address is used |
| `tsandaddr`  | yes — address travels with each stamp | ≤ 4 hops | **chosen**: one probe, no pre-known address, works through NAT |

### Why `tsandaddr` was chosen

- It is the simplest option that reads the **correct** host: one probe, one
  parser, addresses included, and it works through NAT without any per-host
  configuration.
- The alternative that removes the depth limit — discover the address with
  `tsandaddr`, then probe with `tsprespec` — adds a two-step flow and caching
  for a case (hosts more than 4 hops away) that does not arise on a LAN or a
  typical NAT'd overlay fleet, where the host is within a few hops.

## Limits

- **LAN / overlay only.** Packets carrying IP options are commonly dropped by
  internet routers and firewalls (e.g. `8.8.8.8` returns nothing), so the probe
  only works on directly reachable / overlay networks. This is expected — the
  liveness ping is unaffected and the host shows `no-rt`.
- **4 recorded hops.** This is a hard IPv4 protocol limit: the IP header allows
  at most 40 bytes of options, and each `tsandaddr` entry is 8 bytes (4 address
  + 4 timestamp), giving 4 entries. A host more than 4 hops away cannot be
  discovered this way and shows `no-rt`. For a NAT'd overlay fleet 4 hops is
  enough (in the example the host sits at hop 4).
- **UTC, no date, no timezone.** The ICMP timestamp is milliseconds since UTC
  midnight, so the remote clock is shown in UTC and a clock wrong by whole days
  but correct within the day is not detectable. Offsets are folded to ±12 h.
- **Middlebox masking.** If the host itself does not stamp but a transit device
  does, the transit device's clock is reported. The two-distinct-address guard
  rejects the trivial "only us stamped" case, but cannot detect a transit hop
  impersonating the target.

## Possible future extension

For hosts deeper than 4 hops, add a `:resolv`-style mapping that declares the
host's real (inside) address, then probe with `ping -T tsprespec <real-addr>
<routed-ip>`. `tsprespec` only stamps the prespecified address and ignores
transit hops, so it works at any distance once the address is known. This was
deliberately left out of the initial implementation to keep the common case
simple.
