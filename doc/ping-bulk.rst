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
    One or more host names, IP addresses, or host:port combinations to monitor.
    If a port is specified (e.g. ``example.com:443``), it will perform a TCP
    connection check instead of an ICMP ping. Brace expansion is supported
    (see **BRACE EXPANSION** below).
    Tokens beginning with ``:`` are treated as startup commands
    (same syntax as the interactive ``:`` command line).


KEYBOARD REFERENCE
==================

All keys below are default bindings and can be remapped with
``:bindkey`` (see **Key bindings** under **COMMANDS**).

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

``D``
    Cycle the DNS display mode forward.
    Modes: ``off`` → ``hostname`` → ``ip``.

``s``
    Cycle the stats column forward.
    Modes: ``off`` → ``Down`` → ``Loss%`` → ``Avg`` → ``Min`` → ``Max`` →
    ``StDev`` → ``RX`` → ``TX`` → ``XX`` → ``All``.

``o`` / ``O``
    Cycle the sort order forward / backward.
    Orders: ``none`` → ``name`` → ``status`` → ``latency``.

``H``
    Cycle the ping-history display mode forward.
    Modes: ``success`` → ``rtt`` → ``scaled``.

``S``
    Toggle sync-history mode (wall-clock-aligned history bars).
    In sync mode all hosts share the same time axis; a host that started
    late shows a leading gap instead of appearing shifted.

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

``:set dns [off|hostname|ip]``
    With no argument, cycle the DNS display mode forward.
    With an argument, set the mode directly.

``:set stats [mode|col,col,…]``
    With no argument, cycle the stats column forward.
    With a single argument, set the column directly.
    Valid single modes: ``off``, ``Down``, ``Loss%``, ``Avg``, ``Min``, ``Max``,
    ``StDev``, ``RX``, ``TX``, ``XX``, ``All``.

    To display multiple custom columns side-by-side, pass a comma-separated
    list of column names.  Valid column names (case-insensitive): ``last``,
    ``down``, ``loss%``, ``avg``, ``min``, ``max``, ``stdev``, ``rx``,
    ``tx``, ``xx``.  The special names ``all`` and ``off`` are not valid in a
    comma list.  A bare comma (``,``) resets to ``off``.

    Examples::

        :set stats last,avg,stdev
        :set stats down,loss%
        :set stats ,

``:set sort [mode]``
    With no argument, cycle the sort order forward.
    With an argument, set the order directly.
    Valid modes: ``none``, ``name``, ``status``, ``latency``.

``:set ping-view [mode]``
    With no argument, cycle the ping-history display mode forward.
    With an argument, set the mode directly.
    Valid modes: ``success``, ``rtt``, ``scaled``.

``:set <setting> [value]``
    Generic form that accepts any display mode or parameter name.
    With no *value*, numeric settings show their current value and
    other settings are cycled forward.

    Valid settings: ``dns``, ``stats``, ``sort``, ``ping-view``,
    ``log-size``, ``history-size``.

    Examples::

        :set stats Loss%
        :set dns hostname
        :set log-size 50000

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

``:set log-size <n>``
    Set the maximum number of lines kept in the in-memory event log.
    When the limit is reached the oldest lines are discarded.
    Default: ``10000``.  Example: ``:set log-size 50000``.

Configuration
-------------

``:saveconfig``
    Save current display settings (dns, stats, sort, history, log) and
    user-defined key bindings to the XDG config file
    (``~/.config/ping-bulk/config``).  Only bindings that differ from
    the defaults are saved; unbinds of default keys are also persisted.

Key bindings
------------

``:bindkey <key> <command>``
    Bind *key* to *command*.  The key is specified in vim-like notation
    (see **KEY NOTATION** below).  The command is any ``:``-prefixed
    command (e.g. ``:quit``, ``:set dns hostname``).

    Multiple commands can be chained with ``\;``::

        :bindkey x :set stats down \; :set dns hostname

    Append ``...`` (three dots) to the command to enter *edit mode*:
    the command line is pre-filled but not executed, letting the user
    review and modify it before pressing Enter::

        :bindkey t :mux mtr %h...

``:bindkey <key>``
    Unbind *key*.  If the key had a default binding, the default is
    removed and the unbind is tracked by ``:saveconfig``.

``:bindkey``
    List all user-defined key bindings in the event log.

``:set multikey-timeout <ms>``
    Set the multi-key timeout in milliseconds (0–2000).
    Default: ``0`` (wait forever for the next key in a multi-key sequence).
    When non-zero and a pressed key has both a binding and longer
    sequences starting with it, wait *ms* milliseconds for a follow-up
    key; if none arrives, execute the single-key binding.

**Key notation**

+-------------------+-----------------------------------+
| Notation          | Meaning                           |
+===================+===================================+
| ``a``, ``1``, ``/``  | Single characters              |
| ``za``, ``gg``    | Multi-key sequences               |
| ``<C-x>``         | Ctrl+x                           |
| ``<C-Space>``     | Ctrl+Space                        |
| ``<CR>``          | Enter                             |
| ``<Esc>``         | Escape                            |
| ``<Space>``       | Space bar                         |
| ``<Tab>``         | Tab                               |
| ``<BS>``          | Backspace                         |
| ``<Up>`` ``<Down>``  | Arrow keys                     |
| ``<Left>`` ``<Right>``  | Arrow keys                  |
| ``<PageUp>`` ``<PgDn>``  | Page navigation             |
| ``<Home>`` ``<End>``  | Home / End                     |
+-------------------+-----------------------------------+

**Variable expansion** (expanded at keypress time)

+-------------------+-----------------------------------+
| Token             | Expands to                        |
+===================+===================================+
| ``%h``            | Selected host display name        |
| ``%i``            | Selected host IP (resolved)       |
| ``%H``            | All hosts in section (space-sep)  |
| ``%p``            | Port number (TCP monitor only)    |
| ``%j``            | Jump host(s) (SSH monitor only)   |
| ``%s``            | Section title                     |
| ``%%``            | Literal ``%``                     |
+-------------------+-----------------------------------+

Custom separator: ``%{H:,}`` for comma, ``%{H:\n}`` for newline.

If a required variable is unavailable (e.g. ``%p`` on an ICMP host),
the keypress is ignored and a warning is shown in the event log.

Examples::

    :bindkey t :mux mtr %h
    :bindkey x :set stats down \; :set dns hostname
    :bindkey gt :select first
    :bindkey <C-p> :pause

Hosts and DNS
-------------

``:ping HOST[:port]``
    Add a new host or TCP port to monitor interactively.

``:source <file>``
    Load hosts and commands from the specified file.

``:resolv <ip-pattern> <hostname-template>``
    Register a static name↔IP mapping.  *ip-pattern* may use brace
    expansion.  Back-reference placeholders in *hostname-template* are
    substituted for each expanded IP:

    * ``$N`` / ``${N}`` — value produced by brace
      group *N* (1-based).
    * ``$0`` — the full expanded IP address for this iteration.

    Mappings work for both local ping targets and SSH destinations.
    When using ``user@hostname`` format with ``:ssh``, the hostname
    portion is resolved while the username is preserved.

    Examples::

        :resolv 10.0.1.{1..4} leaf-sw$1

    Registers ``10.0.1.1``→``leaf-sw1``, ``10.0.1.2``→``leaf-sw2``,
    etc., so those IPs display with meaningful names and the ``ping``
    subprocess is also given the IP directly. ::

        :resolv 10.{1..4}.{1..2} dc$1-rack$2

    Two brace groups: ``10.1.1.0``→``dc1-rack1``, ``10.1.2.0``→``dc1-rack2``,
    ``10.2.1.0``→``dc2-rack1``, etc.  (8 mappings total from a single line.) ::

        :resolv 192.168.1.10 remote-server
        :ssh user@remote-server localhost

    The SSH destination becomes ``user@192.168.1.10`` while preserving
    the username.

``:resolv-port <port> <service>``
    Register a static port↔service mapping, overriding default names from
    ``/etc/services``. This affects how TCP ports are displayed in the UI.

    Examples::

        :resolv-port 8080 http-alt
        :resolv-port 8443 https-alt

Monitoring via SSH JumpHost
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

``entry1; entry2; …``
    Semicolons may be used as statement separators within a single physical
    line, equivalent to placing each entry on its own line.  For example::

        :title Gateways; 10.0.0.1; 10.0.0.2

    is identical to writing three separate lines.  The separator is applied
    *before* inline-comment stripping, so a ``## label`` only covers the
    segment it appears in.

``## Title`` or ``:title Title``
    Insert a level-1 section-header row in the display (display only;
    not pinged).

``### Title`` or ``:title2 Title``
    Insert a level-2 section-header row, indented two spaces relative
    to a level-1 section.  ``####`` / ``:title3`` etc. follow the same
    pattern.  Hosts listed under a section are indented two spaces per
    section level they belong to.

``hostname ## inline-label``
    A hostname followed by a ``##`` inline section marker.  The marker
    and everything after it are stripped from the target name and treated
    as if ``## inline-label`` appeared before the host line.  This is
    equivalent to placing a ``## Title`` directive immediately before
    the host.  ``###``, ``####``, … set the section level.

``ip-address ## label``
    An IP address followed by a ``##`` inline comment.  The label is
    registered as a static name for the IP via ``:resolv`` so that
    DNS modes ``hostname`` and ``ip`` display the label.  Example::

        10.0.0.1 ## router

``hostname-or-ip``
    A host or IP address to monitor.  Brace expansion is applied.

``?hostname-or-ip``
    An **optional** host.  Added to the monitor list only when a
    ``:resolv`` mapping for the expanded name has been registered
    earlier in the same file (or config).  If no mapping exists the
    line is silently skipped.  Useful inside ``:for`` loops where some
    iterations do not have a particular device:

    .. code-block:: none

        :resolv 10.0.{1,2,4}.10  hub$1-cam
        # hub3 does not have a camera
        :for hub-{1..4}
            ### $0
            hub$1-router
            ?hub$1-cam
        :done

``:for pattern``
    Open a loop.  Every body line between ``:for`` and ``:done`` is
    repeated once for each expansion of *pattern*.  Back-reference
    placeholders (``$N`` / ``${N}`` for numeric, ``$name`` / ``${name}``
    for named) in body lines are substituted with the value produced by
    brace group *N* of the expanded pattern.  ``$0`` / ``${0}`` is the
    entire expanded string.  Body lines without any back-reference are
    included only once.  ``:for`` may appear inside an ``:ssh-begin`` block.

``:done``
    Close the current ``:for`` loop.  If the file ends without a ``:done``
    (e.g. the ``:for`` block is the last thing in the file), an implicit
    ``:done`` is applied at EOF so the loop still produces its entries.
    This also applies when a file is loaded interactively via ``:source``.

``:let name [value]``
    Define (or redefine) a variable named *name* with the given *value*.
    When *value* is omitted the variable is set to the empty string.

    Variables can be referenced anywhere in subsequent non-``:let`` lines
    using bare syntax (``$name``) or brace-delimited syntax (``${name}``).
    Both forms behave identically: the variable value is substituted when
    defined, or the **empty string** when not defined.  The brace form is
    useful to delimit the variable name from adjacent characters::

        :let net 10.0.1
        ${net}.100      # → 10.0.1.100
        $net.100        # same result

    **Brace expansion on the name** — *name* may itself use brace
    expansion to define multiple indexed variables at once::

        :let fold{1..3,5} -

    This stores ``fold1``, ``fold2``, ``fold3``, and ``fold5`` each set to
    ``"-"``.  Inside the value, ``$1`` refers to the corresponding brace
    group, so::

        :let hub{1..4} 10.0.$1.0/24

    stores ``hub1=10.0.1.0/24``, ``hub2=10.0.2.0/24``, and so on.

    **Two-level ``${name_$N}`` expansion** — inside ``${...}`` the inner
    ``$N`` digits are expanded using the current loop back-references
    *first*, then the resulting string is looked up as a variable name.
    Undefined variables expand to the empty string, so only the iterations
    that need a special value require a ``:let``::

        :let fold4 -            # only hub-4 starts folded

        :for sensor-hub-{1..5}
            :title${fold$1} $0
            sensor-hub-$1-router
        :done

    For iteration ``$1=4`` the directive becomes ``:title-`` (folded by
    default); for all other iterations ``${fold$N}`` is undefined and
    expands to ``""`` giving ``:title`` (unfolded).

    **Loop-local scope** — a ``:let`` inside a ``:for`` body creates a
    loop-local variable.  It is visible only within that iteration and
    does not modify the outer variable store.

``:cmd [args]``
    Any command listed under **COMMANDS** above; applied immediately
    when the file is loaded.  This includes ``:bindkey``, so
    administrators can pre-configure key bindings in a hosts file.

``:connect-options <glob-pattern> <ssh-opts>``
    Set SSH flags to be prepended when the ``c`` hotkey is used on a host
    whose name matches *glob-pattern* (``fnmatch`` rules, case-sensitive).
    Rules are evaluated in definition order; the **last match wins**.

    The special value ``-`` **disables** the SSH connect hotkey for
    matching hosts (useful for public IPs where SSH makes no sense)::

        :connect-options *-router     -l admin
        :connect-options *-comm-mod   -l root
        :connect-options *-jetson     -l jetson
        :connect-options *-nuc        -l dev
        :connect-options *-ps*        -l dev

        # Disable connect for public monitoring targets
        :connect-options 1.1.1.1      -
        :connect-options *.google.com -

    Pattern is matched against both the literal hostname and the resolved
    hostname (if DNS resolution has run).  ``SshPingMonitor`` hosts
    reuse their existing jump-host arguments from the ``:ssh`` directive.

    Called interactively as ``:connect-options`` (no args) it clears all
    rules; with one argument it removes that pattern's rule.

``c`` hotkey (SSH connect)
--------------------------

When a host is highlighted (``↑``/``↓`` to navigate), pressing ``c``
pre-fills the command line with::

    mux ssh [connect-options-flags] <host>

The user can review and edit the command before pressing **Enter**.

If ping-bulk is **not** running inside a terminal multiplexer (tmux or
screen), ``c`` offers to relaunch it inside tmux.

The ``[c connect]`` hint is shown in the ping history column header when
a host is highlighted and connect is not disabled.  The host details
overlay (``Enter``) also shows the effective connect command and allows
pressing ``c`` directly.

``:mux [-v|-h|-w] [command…]``
    Run *command* in a new tmux or screen pane/window.  Also available
    as ``:tmux`` and ``:screen``; the command name serves as a preference
    hint for which backend to use.

    When called **without a command**:

    - If already inside a tmux or screen session, opens a new split/window
      running the current ping-bulk invocation (same arguments).  If a host
      is highlighted, ``--select <host>`` is appended so the new instance
      starts with that host pre-selected.
    - If **not** inside any multiplexer, offers to relaunch the current
      process inside tmux (same as the automatic relaunch prompt).

    Split options override the ``:set mux-split`` default for that call:

    ``-v``
        New pane below (vertical split).  This is the default.
    ``-h``
        New pane to the right (horizontal split).
    ``-w``
        New window.

    In **kiosk mode** only ``ssh`` and ``login`` are permitted as the
    command; all others are blocked.

``:set mux-split v|h|window``
    Set the default split direction used by ``:mux`` and the ``c``
    hotkey.  Saved by ``:saveconfig``.

``:edit``
    Open the loaded hosts file in an external editor.  After the editor
    exits, ping-bulk prompts to reload the file (``Y``/``n``).

    Editor resolution order: ``$VISUAL`` → ``$EDITOR`` → ``editor``
    (Debian alternatives) → ``vim`` → ``vi``.

    In **kiosk mode** the editor is restricted to ``rvim`` (``vim -Z``),
    which disables ``:!``, ``:shell``, and external filters to prevent
    shell escapes.  The file is reloaded automatically (no prompt).

Kiosk mode
----------

Passing ``--kiosk`` on the command line enables kiosk mode, which is
intended for unattended deployment on a physical console (e.g. ``/dev/tty1``)
controlled by systemd.

When ``--kiosk`` is active and ping-bulk is **not** already inside a
terminal multiplexer, it automatically executes::

    tmux -f /etc/ping-bulk/kiosk.tmux.conf new -As <session-name> -- <argv>

The session name is derived from the loaded hosts file: ``-`` and ``.``
are replaced with ``_`` (e.g. ``ping-bulk.evo-lan`` → ``ping_bulk_evo_lan``).
When no hosts file is used, the session is named ``ping_bulk``.

The hardened tmux configuration (``kiosk/ping-bulk-kiosk.tmux.conf``
in the repository) removes all tmux key bindings (``unbind-key -a``) and
sets ``default-command login``, so any new window or pane opened by the
user requires login authentication.

Security features in kiosk mode:

- All SSH connections (both monitoring via ``:ssh`` and interactive via
  ``c``) prepend ``-F none -o IdentityFile=none -o IdentitiesOnly=yes``
  to ignore ``~/.ssh/`` entirely.
- If ``/etc/ping-bulk/id_ed25519`` exists it is used as the sole
  identity file (``-i /etc/ping-bulk/id_ed25519``).
- ``:mux`` only allows ``ssh`` and ``login`` as commands.
- ``:q`` / ``q`` quit is not disabled, but ``Restart=always`` in the
  systemd unit ensures ping-bulk is restarted immediately.

See ``kiosk/README.md`` in the repository for the full setup guide.



Section headers (``##`` / ``:title``, ``###`` / ``:title2``, …) group
hosts into collapsible blocks.  Sections can be nested up to any depth.

**Display layout**

A level-1 section header is not indented.  Each additional level adds
two spaces of indentation.  Hosts are indented by ``level × 2`` spaces
relative to the left edge.  Example::

    ── [-] LAN                    5↑
      router               0.3 ....
      nas                  0.2 ....
      ── [-] servers           3↑/1↓
        web                0.4 ....
        db                 0.3 ....

**Section status badge**

When a section is expanded the badge shows the aggregate status of all
descendant hosts.  When folded it also shows the section's combined
ping-history bar.

The badge format is ``N↑/N↓/N-`` where each counter is only shown when
non-zero:

``N↑`` (green)
    Hosts with at least one successful reply (``alive = True``).

``N↓`` (red)
    Hosts that last received a timeout or "no answer" reply
    (``alive = False``).

``N-`` (yellow)
    Hosts that have not yet received any reply — either because they
    are still starting up, waiting in backoff after an unexpected exit,
    or connecting via SSH.

When **any** host in the section has a fatal process error (e.g. SSH
authentication failure, DNS resolution failure, or an unresolvable
hostname), the ``↓`` and ``-`` counters are displayed in **bold**.
This distinguishes "some monitors are still connecting" (``N-``,
non-bold) from "some monitors hit an unrecoverable error" (``N-``,
bold).  A fatal-error host always shows ``??`` in its own stat column.

**Folding keys**

``[`` / ``]``
    Fold all / unfold all sections.

``z`` + ``M``
    Fold all sections (vim-style).

``z`` + ``R``
    Unfold all sections (vim-style).

``z`` + ``c`` / ``z`` + ``o``
    Fold / unfold the section under the cursor.

``Space``
    Toggle fold state of the section under the cursor (when a section
    header is selected).

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

Backreferences
--------------

When using brace expansion with ``:for`` loops or ``:resolv`` commands,
you can reference the expanded values using backreference placeholders:

**Numeric backreferences:**

``$N`` or ``${N}``
    Reference the value from brace group *N* (1-based index).
    ``$0`` or ``${0}`` references the entire expanded string.

**Named backreferences:**

``$name`` or ``${name}``
    Reference named capture groups when supported by the expansion
    context. Names must start with a letter or underscore and may
    contain letters, digits, and underscores.

The braced form ``${...}`` is useful when the placeholder is immediately
followed by a digit or letter that would otherwise be interpreted as part
of the reference.

Examples::

    10.0.0.{1,2,5}          → 10.0.0.1  10.0.0.2  10.0.0.5
    10.0.0.{1..4}           → 10.0.0.1 … 10.0.0.4
    10.0.0.{1-4}            → same (zsh-style)
    10.{1..2}.0.{1,5}       → 4 addresses (cartesian product)
    web{1..3}.example.com   → web1.example.com … web3.example.com
    10.0.0.{10,11..12,14}   → .10 .11 .12 .14
    10.0.{1..2}.{10,2{1,2}} → 8 addresses (nested braces)

    # Backreference examples
    :for 10.0.{1..3}.{10..12}
        :resolv $0 rack$1-node$2    # rack1-node10, rack1-node11, etc.
        $0
    :done

    # Named backreference examples
    :for r,n in 10.0.{1..3}.{10..12}
        :resolv $0 rack$r-node$n    # rack1-node10, rack1-node11, etc.
        $0
    :done


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

``:set dns off|hostname|ip``
    DNS display mode.

``:set stats off|Down|Loss%|Avg|Min|Max|StDev|RX|TX|XX|All``
    Stats column — single mode.

``:set stats last,avg,stdev``
    Custom multi-column stats.  Comma-separated list of column names:
    ``last``, ``down``, ``loss%``, ``avg``, ``min``, ``max``, ``stdev``,
    ``rx``, ``tx``, ``xx``.  Use ``:set stats ,`` to reset to ``off``.

``:set sort none|name|status|latency``
    Sort order.

``:set ping-view success|rtt|scaled``
    History display mode.

``:set log-size <n>``
    Event log maximum line count.  Default: ``10000``.

``:log /path/to/file``
    Path to stream the event log; omit to disable.

``:set multikey-timeout <ms>``
    Multi-key sequence timeout in milliseconds (0–2000).  Default: ``0``.

``:bindkey <key> <command>``
    User key bindings.  Only bindings that differ from the defaults
    are saved.  Unbinds of default keys are stored as bare
    ``:bindkey <key>`` lines.

Example::

    # ping-bulk configuration
    :set dns hostname
    :set stats Loss%
    :set sort status
    :set ping-view scaled
    :log /var/log/ping-bulk.log
    :bindkey t :mux mtr %h
    :bindkey x :set stats down \; :set dns hostname


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
