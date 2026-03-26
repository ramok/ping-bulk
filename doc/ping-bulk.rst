=========
ping-bulk
=========

-------------------------------------------
monitor multiple hosts with continuous ping
-------------------------------------------

:Manual section: 1
:Manual group: User Commands


SYNOPSIS
========

| **ping-bulk** [**-f** *FILE*] [**-l** *LOGFILE*] [**--dns** *MODE*] [**--stats** *MODE*] [**--sort** *MODE*] [**--ping-view** *MODE*] [*HOST* ...]
| **ping-bulk** **-f** *FILE*


DESCRIPTION
===========

**ping-bulk** monitors one or more hosts simultaneously using a
persistent ``ping`` subprocess per host.  Results are shown in a
continuously updated terminal interface with a rolling ping-history
strip, colour-coded status, optional statistics columns, a scrollable
event log, and SSH-based remote monitoring.

The program requires no third-party Python packages.  Only the Python
3 standard library and the system ``ping`` binary (iputils-ping, which
supports ``-O`` and ``-D``) are needed.


OPTIONS
=======

``-f FILE``, ``--file FILE``
    Read hosts from *FILE* instead of (or in addition to) positional
    arguments.  See **HOSTS FILE** below for the file format.

``-l LOGFILE``, ``--log-file LOGFILE``
    Append every event-log entry to *LOGFILE* in real time.
    Overrides any ``:log`` setting in the config file.

``--dns MODE``
    Set the DNS display mode at startup.
    Valid values: ``off``, ``hostname``, ``ip``.

``--stats MODE``
    Set the stats column at startup.
    Valid values: ``off``, ``Down``, ``Loss%``, ``Avg``, ``Min``,
    ``Max``, ``StDev``, ``RX``, ``TX``, ``XX``, ``All``.

``--sort MODE``
    Set the sort order at startup.
    Valid values: ``none``, ``name``, ``status``, ``latency``.

``--ping-view MODE``
    Set the ping-history display mode at startup.
    Valid values: ``success``, ``rtt``, ``scaled``.

``HOST ...``
    One or more host names or IP addresses to ping.  Brace expansion
    is supported (see **BRACE EXPANSION** below).
    Tokens beginning with ``:`` are treated as startup commands
    (same syntax as the interactive ``:`` command line).


KEYBOARD REFERENCE
==================

Navigation
----------

``q`` / ``Q``
    Quit.

``?``
    Open the built-in help overlay.  Close with ``q``, ``Q``, or ``Esc``.

``:``
    Open the command line (see **COMMANDS** below).

``←`` / ``→``
    Scroll the ping-history strip backwards / forwards in time.

``↑`` / ``↓``
    Scroll the event log up / down one line.

``PgUp`` / ``PgDn``
    Scroll the event log up / down one page.

``Space``
    Insert a timestamped *seen* separator into the event log.

Display
-------

``d`` / ``D``
    Cycle the DNS display mode forward / backward.
    Modes: ``off`` → ``hostname`` → ``ip``.

``s`` / ``S``
    Cycle the stats column forward / backward.
    Modes: ``off`` → ``Down`` → ``Loss%`` → ``Avg`` → ``Min`` → ``Max`` →
    ``StDev`` → ``RX`` → ``TX`` → ``XX`` → ``All``.

``o`` / ``O``
    Cycle the sort order forward / backward.
    Orders: ``none`` → ``name`` → ``status`` → ``latency``.

``h`` / ``H``
    Cycle the ping-history display mode forward / backward.
    Modes: ``success`` → ``rtt`` → ``scaled``.

``p`` / ``P``
    Toggle pause (freeze the display without stopping pings).

``C``
    Open the *clear event log* confirmation prompt.


COMMANDS
========

Commands are entered at the ``:`` prompt.  The leading ``:`` is
optional when the command is used inside a hosts file.

Quitting
--------

``:q``, ``:quit``
    Quit the application.

Display
-------

``:dns [off|hostname|ip]``
    With no argument, cycle the DNS display mode forward.
    With an argument, set the mode directly.

``:stats [mode]``
    With no argument, cycle the stats column forward.
    With an argument, set the column directly.
    Valid modes: ``off``, ``Down``, ``Loss%``, ``Avg``, ``Min``, ``Max``,
    ``StDev``, ``RX``, ``TX``, ``XX``, ``All``.

``:sort [mode]``
    With no argument, cycle the sort order forward.
    With an argument, set the order directly.
    Valid modes: ``none``, ``name``, ``status``, ``latency``.

``:ping-view [mode]``
    With no argument, cycle the ping-history display mode forward.
    With an argument, set the mode directly.
    Valid modes: ``success``, ``rtt``, ``scaled``.
    Aliases: ``:history``, ``:hist``.

``:set <setting> [value]``
    Set any display mode by name, delegating to the corresponding individual
    command.  With no *value*, the setting is cycled forward (same as calling
    the individual command with no argument).

    Valid settings: ``dns``, ``stats``, ``sort``, ``ping-view``, ``log-size``.

    Examples::

        :set stats Loss%
        :set dns

``:pause``
    Toggle pause on/off.

Event log
---------

``:seen``
    Insert a timestamped *seen* separator into the event log.

``:clear``
    Clear the event log (with confirmation prompt).

``:log [file|off]``
    With no argument, print the active log file path (or report that
    logging is off).  With a file path, save the current log to that
    file and begin streaming future events there.  With ``off``,
    disable streaming.

``:log-size <n>``
    Set the maximum number of lines kept in the in-memory event log.
    When the limit is reached the oldest lines are discarded.
    Default: ``10000``.  Example: ``:log-size 50000``.

Configuration
-------------

``:saveconfig``
    Save current display settings (dns, stats, sort, history, log) to
    the XDG config file (``~/.config/ping-bulk/config``).

Hosts and DNS
-------------

``:resolv <ip-pattern> <hostname-template>``
    Register a static name↔IP mapping.  *ip-pattern* may use brace
    expansion.  Back-reference placeholders in *hostname-template* are
    substituted for each expanded IP:

    * ``\N`` / ``\{N}`` / ``$N`` / ``${N}`` — value produced by brace
      group *N* (1-based).
    * ``\0`` / ``$0`` — the full expanded IP address for this iteration.

    Examples::

        :resolv 10.0.1.{1..4} leaf-sw\1

    Registers ``10.0.1.1``→``leaf-sw1``, ``10.0.1.2``→``leaf-sw2``,
    etc., so those IPs display with meaningful names and the ``ping``
    subprocess is also given the IP directly. ::

        :resolv 10.{1..4}.{1..2} dc\1-rack\2

    Two brace groups: ``10.1.1.0``→``dc1-rack1``, ``10.1.2.0``→``dc1-rack2``,
    ``10.2.1.0``→``dc2-rack1``, etc.  (8 mappings total from a single line.)

SSH monitoring
--------------

``:ssh [opts] <dest> <ping-host>``
    Add a monitor that runs ``ping -O -D <ping-host>`` on the remote
    machine *dest* via ``ssh -o BatchMode=yes``.  *opts* may include any
    SSH flags (e.g. ``-J bastion``).  The last token is always the
    ping target; everything else is the SSH command line.

    Examples::

        :ssh user@remote 8.8.8.8
        :ssh -J bastion ops@remote-a 10.10.0.1

``:ssh-begin [opts] <dest>``
    Open an SSH block.  Every plain host line that follows (until
    ``:ssh-end``) is automatically wrapped as
    ``:ssh [opts] <dest> <host>``.  Only valid inside a hosts file.

``:ssh-end``
    Close the current ``:ssh-begin`` block.  Only valid inside a
    hosts file.

Help
----

``:help``
    Open the built-in help overlay (same as ``?``).


HOSTS FILE
==========

A hosts file lists one entry per line.  Lines are processed in order.

Format
------

``# comment``
    Comment line — ignored entirely.

(empty line)
    Ignored.

``## Title`` or ``:title Title``
    Insert a section-header row in the display (display only; not
    pinged).

``ip-address ## label``
    An IP address followed by a ``##`` inline comment.  The label is
    registered as a static name for the IP via ``:resolv`` so that
    DNS modes ``hostname`` and ``ip`` display the label.  Example::

        10.0.0.1 ## router

``hostname-or-ip``
    A host or IP address to monitor.  Brace expansion is applied.

``:for pattern``
    Open a loop.  Every body line between ``:for`` and ``:done`` is
    repeated once for each expansion of *pattern*.  Back-reference
    placeholders (``\N`` / ``$N``, N = 0–9) in body lines are
    substituted with the value produced by brace group *N* of the
    expanded pattern.  ``\0`` / ``$0`` is the entire expanded string.
    Body lines without any back-reference are included only once.
    ``:for`` may appear inside an ``:ssh-begin`` block.

``:done``
    Close the current ``:for`` loop.

``:cmd [args]``
    Any command listed under **COMMANDS** above; applied immediately
    when the file is loaded.

Shebang support
---------------

A hosts file may include a shebang on its first line so that it can be
run directly like a script::

    #!/usr/bin/env -S ping-bulk -f

Make the file executable and invoke it directly::

    chmod +x myhosts
    ./myhosts

**Why** ``env -S`` **?**
    The Linux kernel only passes a *single* argument string to the
    interpreter named in a ``#!`` line.  Without ``-S``, ``env`` would
    try to find a binary literally named ``ping-bulk -f``, which does
    not exist.  The ``-S`` flag (``--split-string``) tells ``env`` to
    split that single argument on whitespace before executing, so
    ``ping-bulk`` and ``-f`` are passed as two separate tokens.

**Portability**
    ``env -S`` requires **GNU coreutils ≥ 8.30** (Linux, available in
    Debian 10+, Ubuntu 20.04+, Fedora 29+) or **macOS 12 Monterey or
    later** (which ships a compatible ``/usr/bin/env``).

    On older systems that lack ``env -S`` you can use a small wrapper
    script instead::

        #!/bin/sh
        exec ping-bulk -f "$0" "$@"

    Place that block as the first two lines of the hosts file and
    ``chmod +x`` it as usual.  The ``$0`` passes the file's own path to
    ``-f``, and ``$@`` forwards any additional arguments.

**Passing extra flags via the shebang**
    Additional flags supported by ``ping-bulk`` (such as ``-l``) can be
    appended to the shebang line::

        #!/usr/bin/env -S ping-bulk -f -l /var/log/myhosts.log

    Because ``-S`` splits on whitespace, all tokens after ``env -S``
    are passed verbatim to ``ping-bulk``.


BRACE EXPANSION
===============

Brace expansion applies to host/IP arguments and to the IP side of
``:resolv`` commands.

Supported forms:

``{a,b,c}``
    Comma-separated list — expands to each item in turn.

``{n..m}``
    Inclusive integer range — expands to every integer from *n* to *m*.
    A descending range (``{4..1}``) is supported.

``{n-m}``
    Same as ``{n..m}`` (zsh-style dash separator).

Mixed items (``{10,11..13,15}``) are allowed within a single group.
Multiple brace groups in a single string produce the **cartesian
product** of all groups.  Nested braces are expanded inside-out.

Examples::

    10.0.0.{1,2,5}          → 10.0.0.1  10.0.0.2  10.0.0.5
    10.0.0.{1..4}           → 10.0.0.1 … 10.0.0.4
    10.0.0.{1-4}            → same (zsh-style)
    10.{1..2}.0.{1,5}       → 4 addresses (cartesian product)
    web{1..3}.example.com   → web1.example.com … web3.example.com
    10.0.0.{10,11..12,14}   → .10 .11 .12 .14
    10.0.{1..2}.{10,2{1,2}} → 8 addresses (nested braces)


HISTORY MODES
=============

``success``
    One character per ping: ``.`` success, ``X`` timeout, ``?``
    process error.

``rtt``
    Numeric RTT (ms) right-justified in a fixed-width cell.  Cell
    width adapts to the largest RTT seen.

``scaled``
    Digit 0–9 mapping 10 ms buckets: 0 = <10 ms, 1 = 10–19 ms, …,
    9 = 90–99 ms, ``>`` = ≥ 100 ms.


STATS COLUMNS
=============

``off``
    Show the last RTT only (colour-coded green/yellow).

``Down``
    Time spent in the current state (up or down).  Shown in red when
    the host is currently down.

``Loss%``
    Packet-loss percentage since startup.

``Avg``
    Average RTT (ms) of all successful pings since startup.

``Min`` / ``Max``
    Minimum / maximum RTT since startup.

``StDev``
    Population standard deviation of all RTT samples.

``RX``
    Total successful pings received.

``TX``
    Total pings sent (RX + XX).

``XX``
    Total lost pings (timeouts).

``All``
    All of the above in a single wide row.


DNS MODES
=========

``off``
    Display the name exactly as given on the command line.

``hostname``
    Reverse-DNS lookup: IP → hostname.  Forward lookup for hostnames.
    Falls back to the original value on failure.

``ip``
    Forward-DNS lookup: hostname → IP.  Pass-through for IPs.
    Falls back to the original value on failure.

Resolution runs in a background thread and does not block the UI.
Static ``:resolv`` mappings take priority over DNS and are applied
immediately.


CONFIGURATION FILE
==================

Settings are stored in ``$XDG_CONFIG_HOME/ping-bulk/config``
(defaults to ``~/.config/ping-bulk/config``).

A skeleton file with commented defaults is created on first run.
Use ``:saveconfig`` to write the current settings, or edit the file
directly.

Recognised settings
-------------------

``:dns off|hostname|ip``
    DNS display mode.

``:stats off|Down|Loss%|Avg|Min|Max|StDev|RX|TX|XX|All``
    Stats column.

``:sort none|name|status|latency``
    Sort order.

``:ping-view success|rtt|scaled``
    History display mode.

``:log-size <n>``
    Event log maximum line count.  Default: ``10000``.

``:log /path/to/file``
    Path to stream the event log; omit to disable.

Example::

    # ping-bulk configuration
    :dns hostname
    :stats Loss%
    :sort status
    :ping-view scaled
    :log /var/log/ping-bulk.log


EVENT LOG
=========

**ping-bulk** records the following events:

- Host starts up (first successful ping after launch).
- Host goes down (first timeout after being up).
- Host recovers (first successful ping after being down), including
  total downtime.
- Fatal process errors (DNS resolution failure, permission denied, …).

Each line is prefixed with an ISO 8601 timestamp including timezone
offset::

    2026-03-20T14:05:32+0200   192.168.1.1   host down
    2026-03-20T14:06:10+0200   192.168.1.1   host recover. Down time: 38 sec

The log is scrollable in the UI (``↑``/``↓``/``PgUp``/``PgDn``) and
can be streamed to a file with ``-l``/``--log-file`` or ``:log``.


SSH MONITORING
==============

Remote monitoring requires passwordless SSH access (key-based
authentication or an active ssh-agent).  The connection uses
``BatchMode=yes`` so no password prompt ever appears.

Fatal errors (permission denied, host-key verification failure, too
many authentication failures) stop the monitor permanently.  Transient
errors (connection refused, no route to host, timeout) trigger an
automatic retry with exponential backoff (1 s → 2 s → 4 s … capped at
30 s).

The display label for an SSH monitor is ``dest→ping-host``, e.g.
``ops@remote-a→10.10.0.1``.


EXAMPLES
========

Ping a few public resolvers::

    ping-bulk 8.8.8.8 1.1.1.1 9.9.9.9

Load hosts from a file and stream events to a log::

    ping-bulk -f /etc/ping-bulk/hosts.txt -l /var/log/ping-bulk.log

Use brace expansion to monitor a whole subnet::

    ping-bulk 10.0.0.{1..254}

Combine a hosts file with extra command-line hosts::

    ping-bulk -f office.hosts 8.8.8.8 1.1.1.1

Run an executable hosts file directly::

    chmod +x office.hosts
    ./office.hosts

Monitor remote hosts via an SSH jump host::

    :ssh -J bastion.example.com ops@remote 10.10.0.{1..8}


FILES
=====

``~/.config/ping-bulk/config``
    User configuration file (XDG: ``$XDG_CONFIG_HOME/ping-bulk/config``).


SEE ALSO
========

**ping**\(8), **ssh**\(1)


CREDITS
=======

**ping-bulk** was inspired by
`ping-multi <https://github.com/famzah/ping-multi>`_ by
Ivan Zahariev (famzah).
