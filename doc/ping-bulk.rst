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


INSTALLATION
============

**Requirements:** Python 3.8+, a system ``ping`` binary with ``-O`` and
``-D`` support (iputils-ping ≥ 20121221), a colour-capable terminal.

Via pip::

    # From a local clone
    pip install .

    # Directly from a Git repository
    pip install git+https://github.com/ramok/ping-bulk.git

Single-file copy (no pip required)::

    cp ping-bulk ~/.local/bin/
    chmod +x ~/.local/bin/ping-bulk

or download the raw script straight from GitHub (curl or wget)::

    curl -fsSL https://raw.githubusercontent.com/ramok/ping-bulk/master/ping-bulk \
        -o ~/.local/bin/ping-bulk && chmod +x ~/.local/bin/ping-bulk

The ``install.sh`` script in the repository automates the single-file
install: it verifies that the system ``ping`` supports the required
``-O``/``-D`` flags, downloads the raw script into
``~/.local/bin/ping-bulk`` (overwriting a previous copy), and — when
``~/.local/bin`` is not on ``PATH`` — appends an ``export PATH`` line to
``~/.bashrc`` or ``~/.zshrc``, picked from ``$SHELL``.  Re-running it just
refreshes the installed copy::

    curl -fsSL https://raw.githubusercontent.com/ramok/ping-bulk/master/install.sh | sh


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

``--log-level LEVEL``
    Set the event-log verbosity at startup.
    Valid values: ``quiet``, ``normal``, ``info``, ``debug``.
    Default: ``normal``.  See **Log levels** under **COMMANDS**.

``-v``
    Increase the log level by one step (can be repeated: ``-vv``, ``-vvv``).
    Applied as an offset on top of ``--log-level`` (or the default).

``-q``
    Decrease the log level by one step (can be repeated: ``-qq``, ``-qqq``).

``--kiosk``
    Start in kiosk mode.  Designed for unattended physical consoles
    (e.g. ``/dev/tty1``).  When not already inside tmux, the process
    relaunches itself in a hardened tmux session using
    ``/etc/ping-bulk/kiosk.tmux.conf``.  Quit is disabled (systemd
    ``Restart=always`` handles lifecycle), SSH keys are isolated from
    ``~/.ssh/``, arbitrary commands are blocked, the editor is
    restricted (``rnano``/``rvim``), and every command dispatch is
    logged to syslog.  See ``kiosk/README.md`` for full setup
    instructions and the security model.

``--help-full``
    Print the complete built-in manual — every hotkey, ``:command``,
    hosts-file directive, and expansion rule (the same content as the
    ``?`` help overlay inside the app) — and exit.

``--help-example``
    Print a fully commented advanced hosts file demonstrating most
    features and exit.  A good starting point for a new configuration:
    ``ping-bulk --help-example > my.hosts``.

``--dump-hosts``
    Print the hosts file as a simplified, fully expanded inventory and
    exit.  ``:for`` loops, ``:if`` conditionals, ``:let`` variables and
    brace expansion are resolved; the output contains only ``IP  ## name``
    host lines (static ``:resolv`` mappings are merged into the inline
    ``##`` form) and ``##``/``###`` section titles — every other directive
    is omitted.  ``:remote-ping`` targets are flattened to plain host
    lines (the relay is dropped) and ``:source``'d files are spliced in.

``--dump-simple-script FILE``
    Write the same fully expanded configuration to *FILE* as a
    self-executing script and exit.  Unlike ``--dump-hosts``, the other
    directives (``:set``, ``:bind-key``, ``:prog-options``, …) are kept
    verbatim and a ``#!/bin/sh`` bootstrap header is prepended, so the
    result runs directly (``./FILE``).  *FILE* is overwritten when it
    already exists and is marked executable.  Useful for handing a
    working, loop-free configuration to someone who only needs to
    update IPs.

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
:`:bind-key`` (see **Key bindings** under **COMMANDS**).

Navigation
----------

``q`` / ``Q``
    Quit.

``?``
    Open the built-in help overlay on the **Bindings** tab, which lists every
    active key binding.  ``Tab`` / ``Shift-Tab`` or ``1``-``6`` switch tabs.
    Close with ``q``, ``Q``, or ``Esc``.

``:``
    Open the command line (see **COMMANDS** below).

``j`` / ``k``
    Move host selection down / up.

``↑`` / ``↓``
    When no host is selected: scroll the event log up / down one line.
    When a host is selected: move selection up / down.

``G``
    Move selection to the last host.

``gg``
    Move selection to the first host.

``Ctrl-F`` / ``Ctrl-B``
    Scroll the event log forward / backward one page.

``←`` / ``→``
    Scroll the ping-history strip backwards / forwards in time.

``PgUp`` / ``PgDn``
    Scroll the event log up / down one page.

``Space``
    Insert a timestamped *seen* separator into the event log.

``/``
    Open the search prompt (regex).  When a host is selected, searches
    hostnames; otherwise searches the event log.  Plain text matches as
    a substring; regex metacharacters work too.  ``n`` / ``N`` navigate
    to the next / previous match.  ``Esc`` cancels and clears highlights.
    Press **Tab** inside the search prompt to switch to filter mode.

``f``
    Open the filter prompt.  Type a regex to show only matching hosts;
    non-matching hosts are hidden.  Plain text matches as a substring;
    use regex metacharacters (``\d``, ``|``, ``^``, ``$``, …) for more
    power.  Invalid regex is treated as a literal string.  A full-width
    banner below the column header shows the active filter and match
    count.  Press **Enter** to confirm, **Esc** to cancel (restoring the
    previous filter), **Tab** to switch to search mode.

``F``
    Clear the active host filter immediately.

``Esc``
    Clear the active host filter (if one is set), or clear the host
    selection and return to live ping history.

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

``l``
    Show the event log full screen; press again to return to the previous
    layout.  A there-and-back peek at the log, rather than cycling around.
    The Events header labels this key ``[l full]`` or ``[l back]`` to match
    what the next press will do.

``Ctrl-L``
    Cycle the screen layout: ``all`` → ``ping`` → ``log`` → ``all``.
    See ``:layout`` under **COMMANDS**.

``W``
    Open the *write event log to file* prompt, pre-filled with the active
    log file when one is set.  If the target file already exists a second
    prompt offers ``[t]runcate`` or ``[a]ppend``.

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

``:layout [--toggle] [all|ping|log]``
    Choose how the host list and the event log share the window.  With no
    argument, cycle to the next mode (same as ``Ctrl-L``).

    +------------+--------------------------------------------------------+
    | Mode       | Effect                                                 |
    +============+========================================================+
    | ``all``    | Hosts take the space they need, the log gets the rest   |
    +------------+--------------------------------------------------------+
    | ``ping``   | Host list only — the event log is hidden               |
    +------------+--------------------------------------------------------+
    | ``log``    | Event log only, full height — the host list is hidden  |
    +------------+--------------------------------------------------------+

    In ``all`` the host list is served first, so a list long enough to fill
    the window leaves the log no rows at all.  ``log`` is the way to read the
    log in that situation.  ``ping`` only differs from ``all`` when the hosts
    do *not* fill the window, where it suppresses the log anyway.

    With ``--toggle``, switch to *mode* (default ``log``) or, when already
    there, back to the layout in use before the jump — so one key is a
    there-and-back peek rather than a cycle to walk around.  ``l`` is bound to
    ``:layout --toggle log``.  Coming back from ``log`` returns to ``ping`` if
    that is where you were, not blindly to ``all``.

    Switching to ``log`` clears the host selection so ``↑``/``↓`` scroll the
    log rather than moving an invisible cursor.  The mode is shown in the
    status bar as ``layout:<mode>`` while it is not ``all``, and is saved by
    ``:save-config``.

``:save [--follow] [file]``
    Write the buffered event log to *file* (same as ``W``).

    By default this is a **snapshot**: the file is written and logging is
    left alone.  With ``--follow`` the file also becomes the active
    streaming log, so later events keep landing there — the same thing
    ``:log`` does.

    With no filename a prompt opens, pre-filled with the active log file:

    1. ``Write log to:`` — type a path and press ``Enter``.
    2. Only if the file exists: ``[t]runcate`` or ``[a]ppend``.
    3. ``[w]rite once`` or ``[f]ollow`` — the snapshot/stream choice above.

    ``Esc`` at any step cancels without writing.

    ``Tab`` completes file and directory names at step 1.  A single match is
    filled in; several fill in the longest common prefix and open a list that
    further ``Tab`` presses cycle through (``Shift-Tab`` cycles backwards).
    Directories keep a trailing ``/`` so the next ``Tab`` descends into them.

    Naming a directory is refused with an error rather than treated as an
    existing file, and the prompt stays open so the name can be finished.  The saved file always
    contains **all** log levels regardless of the current ``log-level``
    setting, so it stays greppable.

``:log [file|off]``
    With no argument, print the active log file path (or report that
    logging is off).  With a file path, stream *future* events to that
    file — it does not write the already-buffered log; use ``:save`` for
    that.  With ``off``, disable streaming.

``:set log-size <n>``
    Set the maximum number of lines kept in the in-memory event log.
    When the limit is reached the oldest lines are discarded.
    Default: ``10000``.  Example: ``:set log-size 50000``.

Log levels
----------

``:set log-level quiet|normal|info|debug``
    Control which events appear in the event log panel.  The setting is
    applied at *display time*, so changing the level immediately reveals
    or hides previously buffered entries without losing history.  The
    active level is saved by ``:save-config``.

    +-----------+-------+------------------------------------------------------+
    | Level     | Value | What is visible                                      |
    +===========+=======+======================================================+
    | ``quiet`` |   0   | Host status changes only (up / down / recover)       |
    +-----------+-------+------------------------------------------------------+
    | ``normal``|   1   | + warnings and errors  *(default)*                   |
    +-----------+-------+------------------------------------------------------+
    | ``info``  |   2   | + command output, config, settings, resolv entries   |
    +-----------+-------+------------------------------------------------------+
    | ``debug`` |   3   | + key-binding dispatch and all internal events       |
    +-----------+-------+------------------------------------------------------+

    Event lines are colour-coded: errors are shown in red, warnings in
    yellow, and debug-level lines are dimmed.

    The level can also be set at startup via ``--log-level`` or the
    ``-v`` / ``-q`` flags (see **OPTIONS**).

Configuration
-------------

``:save-config``
    Save current display settings (dns, stats, sort, history, log) and
    user-defined key bindings to the XDG config file
    (``~/.config/ping-bulk/config``).  Only bindings that differ from
    the defaults are saved; unbinds of default keys are also persisted.

Key bindings
------------

``:bind-key [--mode MODE] [--desc TEXT] [--hint TEXT] [--if-cmd PRG] [--if-sh "CMD"] <key> <command>``
    Bind *key* to *command*.  The key is specified in vim-like notation
    (see **KEY NOTATION** below).  The command is any ``:``-prefixed
    command (e.g. ``:quit``, ``:set dns hostname``).

    Multiple commands can be chained with ``\;``::

        :bind-key x :set stats down \; :set dns hostname

    Append ``...`` (three dots) to the command to enter *edit mode*:
    the command line is pre-filled but not executed, letting the user
    review and modify it before pressing Enter::

        :bind-key t :mux mtr %i...

    Optional flags:

    ``--mode MODE``
        Bind the key in a specific UI layer.  Valid modes:

        ``normal``   Main host list (default).
        ``help``     Help overlay (``?``).
        ``details``  Host details overlay (``Enter``).
        ``command``  ``:`` command line.

        Multiple modes can be given as a comma-separated list, registering
        the same binding in each mode at once::

            :bind-key --mode help,details q :close
            :bind-key --mode normal,help,details q :quit

        When ``normal`` is included, the binding is also registered in the
        main key trie (supports multi-key sequences and context flags).
        When only overlay modes are listed, context flags are ignored.

        Example — close the help overlay with ``h``::

            :bind-key --mode help h :close

    ``--desc TEXT``
        Short description shown in the ``?`` help overlay under
        *Custom bindings*::

            :bind-key --desc "Open MTR trace" t :mux mtr %i

    ``--hint TEXT``
        Short label rendered in the bottom menu bar.  Use ``[x]``
        notation to mark the hotkey character::

            :bind-key --hint "[t]race" t :mux mtr %i

    ``--if-cmd PRG``
        Only register the binding if *PRG* is found in ``PATH``
        (checked via ``shutil.which`` at load time).  When the
        check fails the binding is silently skipped and an
        info-level event is logged.  Multiple ``--if-cmd`` flags
        may be given; all must pass::

            :bind-key --if-cmd mtr --%h t :mux mtr %r

    ``--if-sh "CMD"``
        Only register the binding if *CMD* exits with status 0
        (run via ``sh -c`` at load time, 5 s timeout).  Useful for
        checking file existence or more complex conditions.
        **Blocked in kiosk mode** for security::

            :bind-key --if-sh "man -wW ping-bulk 2> /dev/null" \
                      --mode help m :mux man ping-bulk

``:bind-key <key>``
    Query: print what command is bound to *key* in the event log.
    Does **not** remove the binding.

``:unbind-key [--mode MODE] [--%x] <key>``
    Remove a key binding.  If the key had a default binding, the default is
    removed and the unbind is recorded in the saved config as ``:unbind-key
    <key>`` so it survives restart.

``:bind-key``
    List all user-defined key bindings in the event log.

``:set multikey-timeout <ms>``
    Set the multi-key timeout in milliseconds (0–2000).
    Default: ``0`` (wait forever for the next key in a multi-key sequence).
    When non-zero and a pressed key has both a binding and longer
    sequences starting with it, wait *ms* milliseconds for a follow-up
    key; if none arrives, execute the single-key binding.

**Key notation**

+--------------------------+-----------------------------------+
| Notation                 | Meaning                           |
+==========================+===================================+
| ``a``, ``1``, ``/``      | Single characters                 |
| ``za``, ``gg``           | Multi-key sequences               |
| ``<C-x>``                | Ctrl+x                            |
| ``<C-Space>``            | Ctrl+Space                        |
| ``<CR>``                 | Enter                             |
| ``<Esc>``                | Escape                            |
| ``<Space>``              | Space bar                         |
| ``<Tab>``                | Tab                               |
| ``<BS>``                 | Backspace                         |
| ``<Up>`` ``<Down>``      | Arrow keys                        |
| ``<Left>`` ``<Right>``   | Arrow keys                        |
| ``<PageUp>`` ``<PgDn>``  | Page navigation                   |
| ``<Home>`` ``<End>``     | Home / End                        |
+--------------------------+-----------------------------------+

**Variable expansion** (expanded at keypress time)

+-------------------+-------------------------------------------------------+
| Token             | Expands to                                            |
+===================+=======================================================+
| ``%h``            | Selected host display name                            |
| ``%i``            | Selected host IP (resolved)                           |
| ``%r``            | Connectable target: static ``:resolv`` IP if set,     |
|                   | otherwise the display hostname                        |
| ``%d``            | SSH destination (``SshPingMonitor`` only, e.g.        |
|                   | ``user@gateway``)                                     |
| ``%j``            | Jump host(s) (``SshPingMonitor`` only, from ``-J``    |
|                   | flags; space-separated by default)                    |
| ``%H``            | All hosts in section (space-sep)                      |
| ``%R``            | All hosts in section using ``%r`` logic (space-sep)   |
| ``%p``            | Port number (TCP monitor only)                        |
| ``%s``            | Section title                                         |
| ``%%``            | Literal ``%``                                         |
+-------------------+-------------------------------------------------------+

Custom separator: ``%{H:,}`` for comma, ``%{H:\n}`` for newline.
The same syntax applies to list variables: ``%{j: -J }`` joins jump
hosts with the string `` -J `` between items.

Conditional variable expansion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``%{var?template}``
    Expands *template* if *var* is set (non-empty), otherwise produces
    an empty string.  Inner ``%``-variables inside *template* are also
    expanded.  This is useful to build flags that should only appear
    when an optional value is present::

        %{j?-J %{j: -J }}

    When jump hosts exist this produces ``-J host1 -J host2``; when
    there are no jump hosts it expands to nothing.

If a required variable is unavailable (e.g. ``%p`` on an ICMP host),
the keypress is ignored and a warning is shown in the event log.

Examples::

    :bind-key t :mux mtr %i
    :bind-key x :set stats down \; :set dns hostname
    :bind-key gt :select first
    :bind-key <C-p> :pause

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
    When using ``user@hostname`` format with ``:remote-ping``, the hostname
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
        :remote-ping user@remote-server localhost

    The SSH destination becomes ``user@192.168.1.10`` while preserving
    the username.

``:resolv-port <port> <service>``
    Register a static port↔service mapping, overriding default names from
    ``/etc/services``. This affects how TCP ports are displayed in the UI.

    Examples::

        :resolv-port 8080 http-alt
        :resolv-port 8443 https-alt

Monitoring via SSH
------------------

``:remote-ping [ssh-opts] <relay> <target>``
    Add a monitor that runs ``ping -O -D <target>`` on the remote
    machine *relay* via ``ssh -o BatchMode=yes``.  *ssh-opts* may include
    any SSH flags (e.g. ``-J bastion``).  The last token is always the
    ping target; everything before the last token is the SSH command line.

    Examples::

        :remote-ping user@remote 8.8.8.8
        :remote-ping -J bastion ops@remote-a 10.10.0.1

``:with remote-ping [ssh-opts] <relay>``
    Open a remote-ping block.  Every plain host line that follows (until
    ``:end``) is automatically wrapped as
    ``:remote-ping [ssh-opts] <relay> <host>``.  ``:for`` loops may appear
    inside the block.  Only valid inside a hosts file.

    Example::

        :with remote-ping -J bastion.example.com ops@remote-a
            10.10.0.{1..4}
            :for sensor-{1..3}
                10.10.1.$1
            :end
        :end

``:with prog-options <prog>``
    Open a :prog-options block for *prog*.  Every non-directive line
    until ``:end`` is treated as ``<glob> [opts|--disable]``
    and applied as ``:prog-options <prog> <glob> [opts]``.
    Only valid inside a hosts file.

    Example::

        :with prog-options ssh
          *.internal.example.com  -o ProxyJump=bastion
          *-router                -l admin
          restricted.example.com  --disable
        :end

Help
----

``:help [tab-number]``, ``:man [tab-number]``
    Open the built-in help overlay, or switch tab when it is already open.
    With no argument the *Interactive* tab is shown; ``?`` opens the
    *Bindings* tab instead.

    *tab-number* is ``1``-``6`` exactly as printed in the tab bar and as
    bound to the ``1``-``6`` overlay keys::

        1 Interactive   2 Hosts file   3 Example
        4 Commands      5 Bindings     6 Settings

    A tab name or any unique prefix works too, so ``:help bindings`` and
    ``:help bind`` both reach *Bindings*.  ``next`` and ``prev`` cycle.

    Opening the overlay starts every tab at the top; switching tabs while it
    is open preserves each tab's scroll position.

    Inside the overlay, ``Tab`` / ``Shift-Tab`` cycle tabs and ``1``-``6``
    jump straight to one.  ``↑``/``↓``/``k``/``j`` scroll, ``←``/``→``/``h``/``l``
    scroll horizontally, and ``/`` searches the current tab.

Folding
-------

``:fold <action>``
    Fold or unfold sections.  *action* accepts either vim z-notation or
    plain word aliases:

    +------------------------+---------+------------------------------------+
    | Word alias             | z-key   | Effect                             |
    +========================+=========+====================================+
    | ``toggle``             | ``za``  | Toggle fold under cursor           |
    +------------------------+---------+------------------------------------+
    | ``toggle-recursive``   | ``zA``  | Toggle fold recursively            |
    +------------------------+---------+------------------------------------+
    | ``open``               | ``zo``  | Open (unfold) section              |
    +------------------------+---------+------------------------------------+
    | ``open-recursive``     | ``zO``  | Open recursively                   |
    +------------------------+---------+------------------------------------+
    | ``close``              | ``zc``  | Close (fold) section               |
    +------------------------+---------+------------------------------------+
    | ``close-recursive``    | ``zC``  | Close recursively                  |
    +------------------------+---------+------------------------------------+
    | ``open-all``           | ``zR``  | Open all sections                  |
    +------------------------+---------+------------------------------------+
    | ``close-all``          | ``zM``  | Close all sections                 |
    +------------------------+---------+------------------------------------+
    | ``open-level``         | ``zr``  | Open one level                     |
    +------------------------+---------+------------------------------------+
    | ``close-level``        | ``zm``  | Close one level                    |
    +------------------------+---------+------------------------------------+
    | ``close-other [pat]``  | ``zx``  | Close all except match             |
    +------------------------+---------+------------------------------------+

    ``close-other`` folds every section, then recursively unfolds sections
    whose title matches the regex *pat*.  Without *pat*, unfolds the section
    at the cursor.  Plain text works as a substring match.

    Examples::

        :fold toggle
        :fold close-all
        :fold zA
        :fold close-other sensor-hub-3

``:fold-all`` / ``:unfold-all``
    Fold / unfold all sections at once (shorthand for ``:fold close-all``
    and ``:fold open-all``).

Search and Filter
-----------------

``:search``
    Open the search prompt (same as ``/``).  When a host is selected,
    searches host display names; otherwise searches the event log.
    Matching uses case-insensitive regex (plain text works as substring).
    Press ``Enter`` to confirm and jump to the first match, ``Esc`` to
    cancel.  Press **Tab** to switch to the filter prompt.

``:search-next [prev]``
    Jump to the next search match (same as ``n``).  With ``prev``,
    jump to the previous match (same as ``N``).

``:filter [pattern|--clear]``
    Set or clear the host filter (same as ``f`` / ``F``).

    With a *pattern*, show only hosts whose display name, resolved IP, or
    resolved hostname matches the regex (substring search).  Invalid regex
    is treated as a literal string.  With no arguments, open the
    interactive filter prompt.  With ``--clear``, clear the active filter.

    When a filter is active:

    * A full-width reverse-video banner is shown below the column header,
      displaying the pattern and the number of visible hosts.
    * Sections with at least one matching child are kept; empty sections
      are hidden.  Folded sections that contain a match are automatically
      expanded.
    * Navigation (``↑``/``↓``, ``j``/``k``, ``G``/``gg``) operates only
      over the visible (matching) hosts.
    * Pressing **Esc** from the normal view clears the filter first; a
      second press clears the host selection.
    * The filter is transient and is **not** saved to the config file.


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
        :end

``:for pattern``
    Open a loop.  Every body line between ``:for`` and ``:end`` is
    repeated once for each expansion of *pattern*.  Back-reference
    placeholders (``$N`` / ``${N}`` for numeric, ``$name`` / ``${name}``
    for named) in body lines are substituted with the value produced by
    brace group *N* of the expanded pattern.  ``$0`` / ``${0}`` is the
    entire expanded string.  Body lines without any back-reference are
    included only once.  ``:with`` may appear inside a ``:for`` body.

``:end``
    Close the current ``:with``, ``:for``, or ``:if`` block.  If the file ends
    without a ``:end`` (e.g. the ``:for`` block is the last thing in the file),
    an implicit ``:end`` is applied at EOF so the loop still produces its entries.
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
        :end

    For iteration ``$1=4`` the directive becomes ``:title-`` (folded by
    default); for all other iterations ``${fold$N}`` is undefined and
    expands to ``""`` giving ``:title`` (unfolded).

    **Loop-local scope** — a ``:let`` inside a ``:for`` body creates a
    loop-local variable.  It is visible only within that iteration and
    does not modify the outer variable store.

``:if VALUE in val1,val2,...``
    Open a conditional block.  The lines between ``:if`` and ``:end`` are
    included only when the condition is true.  *VALUE* is a plain string
    or a ``$variable`` / ``${variable}`` reference; it is expanded before
    the test is evaluated.  The comma-separated token list on the right
    side may also contain ``$variable`` references (expanded the same
    way), but no brace expansion is applied and the list must not
    contain spaces.

    Two condition operators are supported:

    * ``VALUE in val1,val2,...`` — true when *VALUE* matches any token.
    * ``VALUE not in val1,val2,...`` — true when *VALUE* matches **none**
      of the tokens.

    An ``:if`` block may be followed by zero or more ``:elif`` clauses and
    an optional ``:else`` clause, and must be closed with ``:end``::

        :if VALUE in val1,val2
            ...lines included when condition is true...
        :elif VALUE in other1,other2
            ...included if the first condition was false and this one is true...
        :else
            ...included if all preceding conditions were false...
        :end

    **Inline form** — when the body is a single line, the ``->`` shorthand
    avoids the block/``:end`` boilerplate::

        :if COND -> BODY

    This is exactly equivalent to the three-line block form.  No ``:end``
    is required or allowed.  ``:else``/``:elif`` are not available in the
    inline form; use the block form when they are needed.

    Conditional blocks work **at the top level** (using ``:let`` variables)
    as well as **inside** ``:for`` loop bodies (using loop back-references
    such as ``$1`` or named variables).  Blocks may be nested to arbitrary
    depth.

    **Top-level example** — select hosts based on a ``:let`` variable::

        :let env production

        :if $env in staging,production -> 10.0.0.1 ## monitoring-server

        :if $env in production
            10.0.0.2            ## prod-db
        :end

    **Inside a** ``:for`` **loop** — conditionally include per-iteration
    hosts based on the brace-group back-reference::

        :for hub in sensor-hub-{1..4}
            10.123.$1.1         ## sh$1-router
            :if $1 in 1,2 -> 10.123.$1.16 ## sh$1-activesonar
        :end

    Here ``$1`` is the numeric capture from the brace group (``1``,
    ``2``, ``3``, ``4``), so ``sh1-activesonar`` and ``sh2-activesonar``
    are added but ``sh3-activesonar`` and ``sh4-activesonar`` are not.

``:elif VALUE in val1,val2,...``
    Add a follow-on condition to the preceding ``:if`` (or ``:elif``).
    The same operators (``in`` / ``not in``) apply.  Only valid between
    ``:if`` and ``:end``.

``:else``
    Optional fallback clause.  Lines that follow are included when all
    preceding ``:if`` / ``:elif`` conditions were false.  Only valid
    between ``:if`` and ``:end``.

``:cmd [args]``
    Any command listed under **COMMANDS** above; applied immediately
    when the file is loaded.  This includes ``:bind-key``, so
    administrators can pre-configure key bindings in a hosts file.

``:prog-options <prog> <glob> <opts>``
    Add or replace an option rule for *prog* (e.g. ``ssh``).  When
    ``:mux <prog>`` is invoked from a key binding, the options matching
    the current host are automatically prepended to *prog*'s argument
    list.  Rules use ``fnmatch`` glob matching (case-sensitive) against
    both the literal hostname and the resolved hostname; the **last
    match wins**.

    The special value ``--disable`` suppresses the launch entirely for
    matching hosts::

        :prog-options ssh *.internal.example.com -o ProxyJump=bastion
        :prog-options ssh *-router                -l admin
        :prog-options ssh *-comm-mod              -l root

        # Disable SSH connect for public monitoring targets
        :prog-options ssh restricted.example.com  --disable
        :prog-options ssh 1.1.1.1                 --disable

    When there are many rules for one program, the block form avoids
    repeating the program name on every line::

        :with prog-options ssh
          *.internal.example.com  -o ProxyJump=bastion
          *-router                -l admin
          *-comm-mod              -l root
          restricted.example.com  --disable
        :end

    Each inner line is ``<glob> [opts|--disable]`` — identical to the
    last two arguments of the inline form.  The inline form continues
    to work; the block form is purely syntactic sugar.

    Additional forms:

    ``:prog-options <prog> <glob>``
        Remove the rule for that exact pattern.

    ``:prog-options <prog>``
        List all rules registered for *prog*.

    ``:prog-options``
        List all rules for all programs.

``c`` hotkey (SSH connect)
--------------------------

When a host is highlighted (``↑``/``↓`` to navigate), pressing ``c``
pre-fills the command line for editing and executes after **Enter**.

The default ``c`` binding behaves as follows:

- For ``SshPingMonitor`` hosts (those that have an SSH destination
  ``%d``, e.g. hosts added via ``:remote-ping`` or ``:with remote-ping``)::

      :mux ssh%{j? -J %{j: -J }} %d

  This reconnects to the SSH gateway, automatically appending any
  ``-J`` jump-host flags that were used in the original ``:remote-ping``
  directive.

- For plain ICMP/TCP hosts::

      :mux ssh %r

  ``%r`` resolves to the static ``:resolv`` IP if one is registered,
  otherwise to the display hostname.

Users can override the ``c`` binding in their config or hosts file::

    :bind-key c :mux ssh -l admin %r

Any ``:prog-options ssh`` rules that match the host are automatically
injected by ``:mux``, so `:prog-options` is the recommended way to
supply per-host SSH flags rather than duplicating them in every
``:bind-key`` definition.

If ping-bulk is **not** running inside a terminal multiplexer (tmux or
screen), ``c`` offers to relaunch it inside tmux.

The ``[c connect]`` hint is shown in the ping history column header when
a host is highlighted and connect is not disabled.  The host details
overlay (``Enter``) also shows the effective connect command and allows
pressing ``c`` directly.

``:mux [--split-v|--split-h|--split-window] [command…]``
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

    ``--split-v`` (or ``-v``)
        New pane below (vertical split).  This is the default.
    ``--split-h`` (or ``-h``)
        New pane to the right (horizontal split).
    ``--split-window`` (or ``-w``)
        New window.

    In **kiosk mode** only ``ssh`` and ``login`` are permitted as the
    command; all others are blocked.

``:set mux-split v|h|window``
    Set the default split direction used by ``:mux`` and the ``c``
    hotkey.  Saved by ``:save-config``.

``:edit``
    Open the loaded hosts file in an external editor.  After the editor
    exits, if the file was modified a three-option prompt appears:

    * ``[1] re-exec`` — replace the current process with a fresh
      ping-bulk invocation (``os.execvp``), picking up both the updated
      hosts script and any newer version of the ping-bulk binary itself.
      Ping history is not preserved.
    * ``[2] reload`` — in-process reload: stop monitoring threads, clear
      the host list, re-source the file, then restart monitoring.  Ping
      history and counters are preserved for hosts whose name is unchanged.
    * ``[3] / Esc / any other key`` — ignore; continue with the current session.

    If the file was not modified (or is read-only), no prompt is shown.

    Editor resolution order: ``$VISUAL`` → ``$EDITOR`` → ``editor``
    (Debian alternatives) → ``vim`` → ``vi``.

    In **kiosk mode** the editor is restricted to ``rnano`` or ``rvim``
    (``vim -Z``), which disables ``:!``, ``:shell``, and external filters
    to prevent shell escapes.  The same three-option prompt appears after
    editing.

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

- All SSH connections (both monitoring via ``:remote-ping`` and interactive via
  ``c``) prepend ``-F none -o IdentityFile=none -o IdentitiesOnly=yes``
  to ignore ``~/.ssh/`` entirely.
- If ``/etc/ping-bulk/id_ed25519`` exists it is used as the sole
  identity file (``-i /etc/ping-bulk/id_ed25519``).
- SSH ``ProxyCommand``, ``LocalCommand``, ``RemoteForward``, and related
  options are blocked to prevent shell escapes via SSH.
- ``:mux`` only allows ``ssh`` and ``login`` as commands.
- ``:bind-key --if-sh`` is blocked (arbitrary shell execution).
- ``:log`` and ``:source`` paths are restricted to ``/tmp/``,
  ``~/.local/state/ping-bulk/``, ``/etc/ping-bulk/``, and the directory
  containing the hosts file.  Symlinks are resolved before the check.
- Every ``:cmd`` dispatch is logged to syslog (``LOG_NOTICE``,
  facility ``DAEMON``) for auditing.
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
    :end

    # Named backreference examples
    :for r,n in 10.0.{1..3}.{10..12}
        :resolv $0 rack$r-node$n    # rack1-node10, rack1-node11, etc.
        $0
    :end


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
Use ``:save-config`` to write the current settings, or edit the file
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

``:bind-key [--mode MODE] [--desc TEXT] [--hint TEXT] [--if-cmd PRG] [--if-sh "CMD"] <key> <command>``
    User key bindings.  Only bindings that differ from the defaults
    are saved.  Explicit unbinds of default keys are stored as
    ``:unbind-key <key>`` lines.

Example::

    # ping-bulk configuration
    :set dns hostname
    :set stats Loss%
    :set sort status
    :set ping-view scaled
    :log /var/log/ping-bulk.log
    :bind-key --desc "MTR trace" --hint "[t]race" t :mux mtr %i
    :bind-key x :set stats down \; :set dns hostname


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

    :remote-ping -J bastion.example.com ops@remote 10.10.0.{1..8}


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
