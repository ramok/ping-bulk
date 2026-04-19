#!/usr/bin/env python3
"""keypress-overlay.py — accumulate key presses on a scrolling line.

Reads key descriptions from a named FIFO, appends each to a growing display
line. When the line exceeds the terminal width the oldest keys drop off the
left. The newest key is highlighted; older keys are dim. After
IDLE_CLEAR_SECONDS of no new input the line is cleared.

Usage:
    python3 keypress-overlay.py /tmp/demo-keys.fifo

Protocol (write to FIFO):
    Each line is one key description, e.g.:  d   Space   ?   Ctrl-F   ↓
    A blank line clears the accumulated display immediately.
    Writing "QUIT" exits the overlay.
"""

import os
import sys
import time
import threading
from collections import deque

FADE_SECONDS = 2.0   # seconds before newest key stops being highlighted
IDLE_CLEAR   = 5.0   # seconds of inactivity before clearing all keys
SEP          = ' › '

DIM  = '\033[2m'
BOLD = '\033[1m'
CYAN = '\033[36m'
RST  = '\033[0m'
CLR  = '\033[2K\r'   # erase line + carriage return


def _get_width() -> int:
    try:
        return os.get_terminal_size().columns
    except OSError:
        return 120


def _render(keys: list, highlight_last: bool) -> str:
    if not keys:
        return CLR
    max_w = _get_width() - 4   # 4 = len('⌨  ')

    parts = list(keys)

    def _joined_len(p):
        return sum(len(x) for x in p) + len(SEP) * (len(p) - 1)

    # Drop oldest keys until the text fits
    while len(parts) > 1 and _joined_len(parts) > max_w:
        parts.pop(0)

    out = CLR + BOLD + '⌨  ' + RST
    for i, key in enumerate(parts):
        if i > 0:
            out += DIM + SEP + RST
        if i == len(parts) - 1 and highlight_last:
            out += BOLD + CYAN + key + RST
        else:
            out += DIM + key + RST
    return out


def main():
    if len(sys.argv) < 2:
        print("Usage: keypress-overlay.py <fifo-path>", file=sys.stderr)
        sys.exit(1)

    fifo_path = sys.argv[1]
    if not os.path.exists(fifo_path):
        os.mkfifo(fifo_path)

    keys: deque = deque()
    lock = threading.Lock()
    running = True
    last_key_time = [0.0]
    highlight = [True]

    def timer_loop():
        while running:
            time.sleep(0.1)
            now = time.time()
            with lock:
                idle = now - last_key_time[0] if last_key_time[0] else 0
                if keys and idle > IDLE_CLEAR:
                    keys.clear()
                    sys.stdout.write(CLR)
                    sys.stdout.flush()
                elif keys and idle > FADE_SECONDS and highlight[0]:
                    highlight[0] = False
                    sys.stdout.write(_render(list(keys), False))
                    sys.stdout.flush()

    threading.Thread(target=timer_loop, daemon=True).start()

    while running:
        try:
            with open(fifo_path, 'r') as fifo:
                for raw_line in fifo:
                    line = raw_line.rstrip('\n')
                    if line == 'QUIT':
                        running = False
                        break
                    with lock:
                        if line == '':
                            keys.clear()
                        else:
                            keys.append(line)
                        highlight[0] = True
                        last_key_time[0] = time.time()
                        sys.stdout.write(_render(list(keys), True))
                        sys.stdout.flush()
        except OSError:
            break

    sys.stdout.write(CLR)
    sys.stdout.flush()


if __name__ == '__main__':
    main()
