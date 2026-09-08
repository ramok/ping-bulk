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
    Overrides any ``:log`` setting in the config file **or** in the hosts
    file; typing ``:log`` interactively still takes effect.
    A leading ``~`` is expanded.

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

    A *FILE* of ``-`` writes to standard output instead, so the script can
    be piped or redirected::

        ping-bulk -f net.hosts --dump-simple-script - | less
        ping-bulk -f net.hosts --dump-simple-script - > flat.hosts

    ``/dev/stdout``, ``/dev/fd/1``, and ``/proc/self/fd/1`` are accepted as
    spellings of the same thing.  They are recognised by name rather than
    opened, because ``chmod`` on ``/dev/stdout`` follows the symlink: it
    would make whatever standard output points at executable, including a
    plain file the caller merely redirected into.  The executable bit is
    therefore set only when a real file was named.

    Neither form reports success, so the command is quiet in a cron job or
    a Makefile; only real problems (parse warnings, an unwritable target)
    reach standard error.

    Variables are already substituted at this point, so a ``:log
    $SCRIPT_DIR/…`` line is written out expanded and the dumped script
    logs beside the *original* file rather than beside itself.  Edit that
    line by hand if the copy should keep its own log.

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
    With a section header selected, fold or unfold it **and its
    sub-sections** (as ``zA``), unless that header owns no hosts of its
    own — a pure grouping header is left alone, since folding it would
    hide nothing that ``zA`` does not already reach.  ``Ctrl-Space``
    toggles the selected section only (``za``).  Otherwise, insert a
    timestamped *seen* separator into the event log.

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

    A second in which no ping process was running is drawn ``_`` (dimmed)
    rather than left blank.  That covers a host still starting up, an SSH
    connection still being established — several seconds through a jump
    host — and the backoff wait between reconnection attempts::

        127.0.0.1          ............
        relay → 10.0.0.1   ......._____

    Both bars are anchored at *now* on the left, so the marked seconds are
    the oldest.  Without the marker the second bar was simply shorter, with
    nothing to say whether the missing seconds were a connection being set
    up or data that never existed — a blank still means exactly that, no
    sample and no explanation.

    These seconds carry no probe, so they are absent from every statistic;
    a recorded reply, a loss or a process error always outranks the marker
    in a cell.  The dense (non-sync) bar is one cell per probe and has no
    empty seconds, so it never shows ``_``.

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

``X``
    Open the *clear event log* confirmation prompt.  (This was ``C`` until
    that key was given to the editable SSH command below.)

``C``
    Put the SSH command for the selected host on the command line **without
    running it**, so it can be edited first — a different user, an extra
    ``-o``, a port forward.  Press ``Enter`` to run it or ``Esc`` to
    abandon it.

    The text is identical to what ``c`` would run, ``:prog-options`` and the
    relay hop included::

        :mux ssh -l root -J 217.160.7.176 10.111.1.1

``c``
    Open an SSH connection to the selected host in a split pane.  A host
    behind a relay is reached by jumping through it.  See **``c`` hotkey
    (SSH connect)** below.

``t``
    Run ``mtr`` against the selected host in a split pane.  Bound only when
    ``mtr`` is on ``PATH``.  For a host behind a relay the trace runs *on the
    relay*, since the host is not reachable from here — see **Commands that
    run where the host is reachable** below.


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
    | ``all``    | Hosts take the space they need, the log gets the rest  |
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

    A path longer than the terminal is scrolled so its end stays visible — the
    file name is the part worth reading — with a leading ``…`` marking the
    hidden head.

    Naming a directory is refused with an error rather than treated as an
    existing file, and the prompt stays open so the name can be finished.  The saved file always
    contains **all** log levels regardless of the current ``log-level``
    setting, so it stays greppable.

``:log [file|off]``
    With no argument, print the active log file path (or report that
    logging is off).  With a file path, stream *future* events to that
    file — it does not write the already-buffered log; use ``:save`` for
    that.  With ``off``, disable streaming.  A leading ``~`` is expanded.

    A ``:log`` in the config file or the hosts file yields to
    ``-l``/``--log-file`` on the command line, and the skipped path is
    reported at ``info`` log level.  Typing ``:log`` interactively always
    takes effect.

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

    One exception to the table: a ``:command`` **rejected while a config or
    hosts file is being read** is reported at ``normal`` rather than ``info``.
    A line written in a file that then does nothing — an unknown setting, a bad
    value, an unrecognised ``--%x`` guard — is a configuration error the user
    has to see, and at the default level ``info`` would hide it.  Command
    output typed interactively stays at ``info``, since the log is right there
    in front of whoever typed it.

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

    ``--%x`` (context guard)
        Only fire the binding when variable ``%x`` has a value for the
        current selection.  This lets one key mean different things for
        different kinds of host — the built-in ``c`` uses ``--%d`` to
        treat a relayed host differently from a direct one.  Valid
        guards are exactly the variable names listed under **Variable
        expansion** below:

            ``--%h``  ``--%i``  ``--%r``  ``--%d``  ``--%j``
            ``--%p``  ``--%s``  ``--%H``  ``--%R``

        Several may be combined; all must have a value.  Guards apply to
        normal mode only.  An unrecognised guard is rejected and the whole
        binding is dropped — reported at ``normal`` level, so a mistake in
        a hosts file is visible without raising the log level::

            :bind-key --if-cmd mtr --%i T :mux --no-focus mtr %i

        A guard is not always needed: a binding using ``%i`` on a host with
        no resolved IP is simply ignored, with a ``%i: no value`` warning.
        The guard is for when a *different* binding should take over
        instead.

        More specific guards win over less specific ones, and an explicit
        user binding wins over a built-in default of equal specificity.

``:bind-key <key>``
    Query: print what command is bound to *key* in the event log.
    Does **not** remove the binding.

``:unbind-key [--mode MODE] [--%x] <key>``
    Remove a key binding.  If the key had a default binding, the default is
    removed and the unbind is recorded in the saved config as ``:unbind-key
    <key>`` so it survives restart.

``:bind-key``
    List all user-defined key bindings in the event log.

``:probe-source [--cmd 'CMD'] [--interval SEC] [--retain N] | off``
    Command run on each monitored host that prints one ``key=value`` per
    line.  It is wrapped in a loop on the far side and the SSH connection is
    held open, so one connection per host serves every reading and the
    interval is not a cost decision.  A host reached through a relay is
    probed *through* that relay, since the values belong to the host.
    Default interval 60 s; ``--retain`` bounds the samples kept per host.

    In kiosk mode this may only be declared in the hosts file, not typed at
    the ``:`` prompt, and the command must be an absolute path to a script
    that is not group- or world-writable and has no writable directory on the
    path to it.  Shell metacharacters (``;`` ``|`` ``&`` ``$`` ``>`` and
    backticks) are refused there, since only the first token's ownership can
    be checked.  The connection carries the same SSH isolation flags as
    ``:mux``.

``:probe <name> [--unit U] [--range MIN:MAX] [--warn N] [--crit N] [--on-fail retry|give-up]``
    Declare how one key from ``:probe-source`` is displayed.  Keys with no
    declaration are ignored, so a single site-wide script can serve hosts
    that show different subsets.  ``--range`` scales the history strip,
    ``--warn``/``--crit`` colour the column and the overlay, and ``--unit``
    labels both.

    A probe never changes host status: a host at 95 °C that answers ping is
    still UP.  ``-`` means nothing has been read yet, ``err`` means the read
    or the connection failed.  With ``--on-fail give-up`` polling stops after
    three failed rounds — the behaviour ``no-rt`` has for clocks — and the
    details overlay says so; the default keeps retrying, which costs nothing
    while the connection is open.

    The value appears in three places::

        :set stats temp          # a column, latest value
        :set ping-view temp      # the history strip, one cell per reading
        Enter on a host          # current value, spread, and a sparkline

    See ``doc/custom-probes.md`` for the design and the alternatives weighed.

``:set ssh-options <flags> | default | none``
    SSH options for the connections **ping-bulk makes itself** — running
    ``ping`` on a relay, reading a ``:probe``, taking a clock reading.
    Sessions opened by ``c``, ``C`` or ``:mux ssh`` are deliberately not
    affected: those are interactive, where X11 or agent forwarding may be
    exactly what is wanted.  Use ``:prog-options ssh`` for those.

    The default answers two things a monitoring connection never needs, both
    of which a ``Host *`` block in ``~/.ssh/config`` commonly turns on::

        -o ForwardX11=no -o ForwardX11Trusted=no
        -o ClearAllForwardings=yes

    ``ForwardX11`` makes every connection ask the relay for an X11 channel;
    a relay without ``xauth`` refuses and logs *X11 forwarding request
    failed on channel 0* once per host.  ``ClearAllForwardings`` stops a
    ``LocalForward`` meant for an interactive session from being set up once
    per monitored host, where the first to bind holds the port.

    **Connection sharing** is deliberately not part of that default, because
    the right answer differs by connection kind:

    +----------------------+--------------------------+---------------------+
    | Connection           | Reaches                  | Sharing             |
    +======================+==========================+=====================+
    | ``ping``             | the relay                | ``ControlMaster=no``|
    +----------------------+--------------------------+---------------------+
    | clock probe (drift)  | the relay                | ``ControlMaster=no``|
    +----------------------+--------------------------+---------------------+
    | ``:probe-source``    | the host itself          | shared master       |
    +----------------------+--------------------------+---------------------+

    Many monitored hosts share one relay, and sharing *those* onto a single
    master is a trap rather than an optimisation: ``sshd``'s ``MaxSessions``
    defaults to **10**, so behind a relay carrying more hosts than that the
    eleventh onwards is refused with *Session open refused by peer*.

    Declining it takes both ``-o ControlMaster=no`` **and**
    ``-o ControlPath=none``.  ``ControlMaster=no`` is the *client* mode, not
    "off": ssh_config(5) says additional sessions connect to an existing
    socket *with ``ControlMaster`` set to no*, so on its own it makes every
    connection join whatever master the user's own ``ControlPath`` points at.
    ``ControlPath=none`` is the documented way to disable sharing.  It also
    stops them racing for that path — the losers of such a race log
    *ControlSocket … already exists, disabling multiplexing*.

    A probe reader is the opposite case: one endpoint per host, reconnecting
    whenever its remote loop restarts, so a master turns each reconnection
    into a channel instead of a fresh handshake and authentication.  Its
    socket goes in ``$XDG_RUNTIME_DIR/ping-bulk/`` — already private,
    on tmpfs, and cleared at logout so no stale socket survives — falling back
    to ``$XDG_CACHE_HOME/ping-bulk/`` (or ``~/.cache/ping-bulk/``) and then
    ``/tmp/ping-bulk-<uid>/``, each created mode ``0700``.  The directory is
    private for a reason beyond tidiness: SSH options are decided by the
    *master*, so a socket anything else could join would impose this
    connection's ``ForwardX11=no`` on a later session that reused it.

    Naming any ``Control*`` option in ``:set ssh-options`` turns all of this
    off and uses yours instead, for every connection kind.

    ``ForwardAgent`` is deliberately absent from the default — it is how the
    next hop authenticates in a multi-jump chain, so it stays under the
    control of ``~/.ssh/config``.

    A change applies to connections started from then on; those already
    running keep the options they were started with until they reconnect.
    Saved by ``:save-config`` when not the default.  In kiosk mode the same
    blocklist as ``:remote-ping`` applies, since an option here reaches every
    monitoring connection.

``:set late-grace <seconds>``
    How long a probe reported unanswered by ``ping -O`` may still be
    answered before it counts as lost.  Default: ``1``.

    **Late replies.**  ``ping -O`` prints ``no answer yet for icmp_seq=N``
    as soon as the *next* request goes out, so its deadline is the ping
    interval (1 s) — not ``-W``.  A host whose RTT exceeds that interval
    therefore has every probe reported unanswered and then answered a
    moment later.  ping-bulk pairs the two by ``icmp_seq``: such a probe
    is a single reply, drawn ``x`` (yellow) instead of ``.``, counted as
    one success, and it never marks the host down.

    A probe still unanswered *late-grace* seconds after the ``-O`` line is
    written off as genuinely lost — drawn ``X``, counted in ``XX``, and the
    host goes down.  So the effective tolerance is the ping interval plus
    this value: the default catches replies up to about 2 s.

    Raising it tolerates slower hosts but delays down-detection by the same
    amount; lowering it detects outages sooner at the cost of drawing very
    slow hosts as down.  Saved by ``:save-config`` when not the default.

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
The same syntax applies to list variables: ``%{j:,}`` joins jump hosts
with a comma, which is the form ``ssh -J`` expects for multiple hops.
Note that repeating the flag instead (``%{j: -J }``) does *not* work:
``ssh`` uses the first value of a repeated option, so ``-J a -J b``
silently ignores ``b``.

Conditional variable expansion
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``%{var?template}``
    Expands *template* if *var* is set (non-empty), otherwise produces
    an empty string.  Inner ``%``-variables inside *template* are also
    expanded.  This is useful to build flags that should only appear
    when an optional value is present::

        %{j?-J %{j:,}}

    When jump hosts exist this produces ``-J host1,host2``; when there
    are no jump hosts it expands to nothing.

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

    ``--if-hosts`` makes the action apply only to a section that owns hosts,
    leaving a header whose children are all sub-sections untouched.  Folding
    such a header hides nothing on its own, so this keeps ``Space`` — which is
    recursive — from collapsing a whole group from a pure container.  The
    ``z``-actions do not take the flag and stay unconditional, which is what
    makes ``zA`` the deliberate way to fold a group.

    Examples::

        :fold toggle
        :fold close-all
        :fold zA
        :fold toggle-recursive --if-hosts
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
    Both forms behave identically.  A name is resolved in three steps: the
    ``:let`` value if one is defined, then the **environment** variable of
    the same name, and finally the **empty string**.  The brace form is
    useful to delimit the variable name from adjacent characters::

        :let net 10.0.1
        ${net}.100      # → 10.0.1.100
        $net.100        # same result
        $HOME/logs      # environment, when no :let defines HOME

    Because the environment is only a fallback, a ``:let`` of the same name
    always wins — a hosts file can therefore pin a value that would
    otherwise vary between machines.

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

**Predefined variables**

Two variables are set automatically while a hosts *file* is being parsed:

``$SCRIPT_DIR``
    Absolute directory holding the file, without a trailing slash.

``$SCRIPT_FILE``
    Base name of the file.

They let a self-executing hosts file keep its log beside itself, so the
script and its log travel together and no ``-l`` is needed at the call
site::

    #!/usr/bin/env -S ping-bulk -f
    :log $SCRIPT_DIR/$SCRIPT_FILE.log

The path is built with ``abspath``, not ``realpath``: a script reached
through a symlink writes beside the name that was typed, not beside the
link target.  Both are ordinary variables, so a later ``:let`` of the same
name overrides them, and a file pulled in with ``:source`` gets its own
values — each file is expanded in its own parse pass.

Hosts read from the command line have no file, so neither variable is
defined there.  An undefined variable inside a ``:log``, ``:save``, or
``:source`` path is reported as a warning, because it would silently
truncate the path (``:log $TYPO/pb.log`` becomes ``:log /pb.log``).
Elsewhere an empty expansion stays silent — the ``${fold$N}`` pattern
above depends on it.

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
    both the literal hostname and the resolved hostname.

    A rule naming **one host exactly beats any glob**, whatever order they
    are written in::

        tent-router  -l root      # this host
        *-router     -l admin     # every other router

    Among rules of the same kind the **last match wins**, so an exact rule
    can be overridden by a later exact rule and a glob by a later glob.
    Ordering alone used to decide everything, which meant a specific rule
    had to be written after the glob it refined — and stopped working as
    soon as another glob was appended.

    For a host monitored through a relay (``:remote-ping`` or ``:with
    remote-ping``) the patterns are matched against the **target** — its
    address and its ``:resolv`` alias — not against the composite
    ``relay→target`` display name.  So ``*-router -l admin`` applies to
    ``tent-router`` whether it is pinged directly or through a relay.  A
    rule naming the relay applies only when the relay itself is monitored
    as a host, not to the hosts reached through it; the injected options
    describe the connection endpoint, and the relay is only a ``-J`` hop.

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

      :mux ssh -J %{j?%{j:,},}%d %r

  ping-bulk reaches these hosts by running ``ping`` on the relay, so a
  shell on the host itself means jumping through that relay: the relay
  becomes the final ``-J`` hop and the monitored host is the
  destination.  Any jump hosts from the original ``:remote-ping``
  directive are kept ahead of it in the same comma-separated list.  For
  ``:with remote-ping ses-wg-video`` over ``10.111.1.1`` this runs::

      ssh -J ses-wg-video 10.111.1.1

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


Commands that run where the host is reachable
---------------------------------------------

A host behind a relay is reachable *only* from that relay — that is why its
``ping`` runs there.  A diagnostic tool aimed at such a host therefore has no
route to it from here at all: ``mtr 10.123.1.8`` on the local machine does not
reach a host that lives behind the relay, it fails or traces something else
entirely.

So when a ``:mux`` command comes from a key binding and is aimed at a relayed
host, ping-bulk runs it on that host's relay::

    :bind-key --if-cmd mtr t :mux mtr %r

    # selected host is plain      → mtr <host>
    # selected host is relayed    → ssh -t <relay> mtr <target>
    # relayed, with -J bastion    → ssh -t -J bastion <relay> mtr <target>

One binding covers both cases, and it works for any program — ``traceroute``,
``tracepath``, ``iperf3``, ``curl``, ``nmap``.  There is no list of known tools.

Whether a command is aimed at the host is decided by the variables the binding
uses:

+-------------------------+-----------------------------------------------+
| Binding uses            | Behaviour                                     |
+=========================+===============================================+
| ``%h`` / ``%i`` / ``%r``| Names the host, so it runs on the relay       |
+-------------------------+-----------------------------------------------+
| ``%d``                  | Already relay-aware (as ``c`` is, jumping     |
|                         | through it) — left exactly as written         |
+-------------------------+-----------------------------------------------+
| neither                 | Nothing to do with the host (``:mux man       |
|                         | ping-bulk``) — stays local                    |
+-------------------------+-----------------------------------------------+

``-t`` is always added, because these are interactive terminal tools and their
display needs a tty on the far side.  The ``-J`` chain stops *before* the relay:
the wrapper logs in **to** it, unlike ``c``, which jumps **through** it.

``:prog-options`` are resolved per endpoint.  The wrapped program keeps being
matched against the target it acts on, while the ``ssh`` rules applied to the
wrapper are matched against the **relay**, because that login lands there::

    :prog-options ssh ses-wg-video  -l admin      # the relay login
    :prog-options ssh *-jetson      -l jetson     # the target, used by 'c'
    :prog-options mtr *             -4

    # t on a relayed jetson → ssh -l admin -t ses-wg-video mtr -4 <target>
    # c on the same host    → ssh -l jetson -J ses-wg-video <target>

If ``:prog-options ssh`` disables the relay itself there is no way in, so the
command is refused with a message rather than run in a misleading form.

Two limits worth knowing.  ``--if-cmd`` tests the **local** machine, so a tool
present here but missing on the relay still binds the key and the pane reports
``command not found`` from the far side; there is no remote equivalent.  And a
tool needing extra privileges (``mtr`` wants ``CAP_NET_RAW``) may fail over SSH
where a local run would have worked.

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
  The restriction covers the startup commands in the hosts file as well
  as those typed interactively.
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
    Hosts whose last probe was written off as lost (``alive = False``).
    A probe that ``ping -O`` reported as unanswered is *not* counted here
    until the ``late-grace`` window expires — see **Late replies** below.

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
    Toggle fold state of the section under the cursor and of its
    sub-sections (when a section header is selected).  A section header
    stands for a whole subtree on screen, so unfolding one reveals the
    subtree rather than leaving its children closed.  Use ``Ctrl-Space``
    to toggle just the selected section.

    A header whose children are *all* sub-sections is skipped: it owns no
    hosts, so a single-level fold would hide nothing, and a recursive one
    would collapse a whole group from a header that has nothing of its own
    in it.  A short message names ``zA`` as the way to fold such a group
    on purpose.  This is ``:fold <action> --if-hosts``; the ``z``-actions
    are unconditional.

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
- Diagnostic messages written by ``ping`` itself (e.g.
  ``ping: sendmsg: Network is unreachable``).  Such a message can repeat for
  every probe, so each distinct text is reported **once** per host rather than
  once per second.
- ``ping-bulk: no output for Ns — restarting ping``.  A ``ping`` that has been
  answering and then goes completely silent is presumed stuck: the missed
  probes are recorded as losses, and after a few silent intervals the process
  is terminated and a fresh one started.  Nothing else would end that state —
  a stuck child neither exits nor speaks — so without this the host would stay
  frozen at its last reading indefinitely.  A process that has not produced any
  output *yet* is left alone, so a slow SSH connection is never cut short.

Each line is prefixed with an ISO 8601 timestamp including timezone
offset::

    2026-03-20T14:05:32+0200   192.168.1.1   host down
    2026-03-20T14:06:10+0200   192.168.1.1   host recover. Down time: 38 sec

When ``ping`` reported a reason shortly before the host went down, that reason
is appended to the *host down* line, so the log says why and not merely that::

    2026-03-20T14:05:32+0200   192.168.1.1   host down.    Up time:   3600 sec (60 min 0 sec)  (ping: sendmsg: Network is unreachable)

The log is scrollable in the UI (``↑``/``↓``/``PgUp``/``PgDn``) and
can be streamed to a file with ``-l``/``--log-file`` or ``:log``.

Each logging session opens with a banner line naming the process and what it
is watching::

    # ###### log started 2026-03-20T14:05:30+0200 — ping-bulk, pid 31337, hosts file /opt/net/pb.hosts, 47 targets

The pid is there because a log path set inside a hosts file is reused by every
run of that script: two concurrent runs append to the same file, and the
banners are what separate them.  A banner is written once per logging session —
switching to another file, or turning logging off and on again, starts a new
one, so a resumed log shows where the gap was.  The ``#`` prefix matches the
headers ``:save`` writes, keeping a file that has been both streamed to and
saved into readable as one document.


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
