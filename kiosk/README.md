# ping-bulk kiosk mode

Kiosk mode runs ping-bulk as the sole application on a physical console
(e.g. `/dev/tty1`), started by systemd.  Users can monitor hosts and SSH
into them, but cannot escape to an unrestricted shell.

## Directory contents

| File | Purpose |
|------|---------|
| `ping-bulk-kiosk@.service` | systemd service unit (parameterised by tty) |
| `ping-bulk-kiosk.tmux.conf` | hardened tmux config used in kiosk mode |

---

## Quick setup

### 1. Create the dedicated user

```sh
useradd -r -m -d /var/lib/ping-monitor -s /bin/bash ping-monitor
```

### 2. Create the hosts file

```sh
mkdir -p /etc/ping-bulk
cp /path/to/your/hosts /etc/ping-bulk/hosts
chown root:ping-monitor /etc/ping-bulk/hosts
chmod 640 /etc/ping-bulk/hosts
```

### 3. Install ping-bulk

```sh
install -m 755 ping-bulk /usr/local/bin/ping-bulk
```

### 4. Install and enable the service

```sh
install -m 644 kiosk/ping-bulk-kiosk@.service \
    /etc/systemd/system/ping-bulk-kiosk@.service

# Install the hardened tmux config
install -m 644 kiosk/ping-bulk-kiosk.tmux.conf \
    /etc/ping-bulk/kiosk.tmux.conf

systemctl daemon-reload

# Disable the normal getty on tty1 and start kiosk instead
systemctl disable getty@tty1
systemctl stop   getty@tty1
systemctl enable ping-bulk-kiosk@tty1
systemctl start  ping-bulk-kiosk@tty1
```

### 5. Set up SSH access (optional)

For the kiosk to monitor remote hosts via `:ssh`, give the `ping-monitor`
user a passwordless SSH key.  In kiosk mode, SSH connections automatically
ignore keys in `~/.ssh/` and use only the key at `/etc/ping-bulk/id_ed25519`
(if present).

```sh
# Generate a dedicated kiosk key (no passphrase)
ssh-keygen -t ed25519 -N '' -C 'ping-bulk-kiosk' \
    -f /etc/ping-bulk/id_ed25519

chown root:ping-monitor /etc/ping-bulk/id_ed25519
chmod 640 /etc/ping-bulk/id_ed25519

# Copy the public key to each monitored host
ssh-copy-id -i /etc/ping-bulk/id_ed25519.pub user@remote-host
```

For interactive SSH connections (the `c` hotkey), the same key is used
automatically in kiosk mode.

---

## Security model

| Feature | Behaviour in kiosk mode |
|---------|------------------------|
| `c` hotkey SSH | Allowed; uses `/etc/ping-bulk/id_ed25519` if present |
| `~/.ssh/` keys | **Ignored** (`-F none -o IdentityFile=none -o IdentitiesOnly=yes`) |
| SSH ProxyCommand | **Blocked** — `-o ProxyCommand`, `LocalCommand`, `RemoteForward`, etc. are rejected |
| `:mux` arbitrary cmds | Blocked — only `ssh` and `login` are whitelisted |
| `:mux` backend | **tmux only** — screen and X terminals are not used in kiosk mode |
| New tmux window/pane | Runs `login` for authentication |
| tmux hotkeys | All removed (`unbind-key -a`); prefix key set to `None` |
| `:q` / `q` / `Q` | Disabled — systemd `Restart=always` handles cleanup |
| `:edit` | Uses `rnano` (restricted nano) or `rvim` (restricted vim) — `$VISUAL`/`$EDITOR` are ignored |
| `:edit` permission | Checked — write access to the hosts file is required |
| `:log` / `:source` paths | Restricted to `/tmp/`, `~/.local/state/ping-bulk/`, `/etc/ping-bulk/`, and the hosts-file directory |
| Symlink traversal | Blocked — all path checks use `realpath()` |
| Command audit log | Every `:cmd` dispatch is logged to syslog (`LOG_NOTICE`, facility `DAEMON`) |
| Session lock | Optional via `lock-after-time` in `ping-bulk-kiosk.tmux.conf` |

---

## Session locking by inactivity

tmux can automatically lock the session after a period of no keyboard input.
To enable, uncomment these lines in `/etc/ping-bulk/kiosk.tmux.conf`:

```
set-option -g lock-after-time 600     # seconds; 0 disables
set-option -g lock-command "vlock -c" # requires vlock package
```

`vlock -c` locks only the current virtual console.  Install it with
`apt install vlock`.  When triggered, the user must enter the `ping-monitor`
Unix password to unlock.  Alternatively use `physlock` for a tighter lock.

---

## Auto-relaunch

When `--kiosk` is passed and ping-bulk is **not** already inside tmux, it
automatically relaunches itself inside a new tmux session using the hardened
`/etc/ping-bulk/kiosk.tmux.conf`.  This is transparent when started by
systemd.

If tmux is not installed, ping-bulk falls back to running directly on the
tty (less secure — tmux is strongly recommended for kiosk use).

---

## Tips

- The `ping-monitor` user's `~/.ssh/known_hosts` must be pre-populated for
  each jump/remote host before kiosk mode starts (SSH will refuse unknown
  hosts).  Run `ssh-keyscan remote-host >> /var/lib/ping-monitor/.ssh/known_hosts`
  as root, or use `ssh-keyscan` during provisioning.
- To reload the hosts file without rebooting: `systemctl restart ping-bulk-kiosk@tty1`
- To login for maintenance: switch to tty2 with `Alt+F2` and log in normally.
