#!/usr/bin/env python3
"""Runs on the Linux side. Listens to global keyboard and mouse-button events via
XInput2 raw events (X11, no root needed) and forwards them to key_injector.py running
inside Wine, so the pet sees typing/clicking done in native Linux programs.

Protocol, one line per event:
  "D|U <set1-scancode> <extended 0/1>"   key down / up
  "B <button 1-3> <1 down|0 up> <x> <y>"  mouse button at root coordinates
"""
import socket
import struct
import sys
import time

from Xlib import X, display, error
from Xlib.ext import xinput

GENERIC_EVENT = getattr(X, "GenericEvent", 35)
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 47811
WINE_CLASS = "steam_proton"

# evdev code (X keycode - 8) -> (set1 scancode, extended)
# evdev 1..88 equal set1 scancodes; the rest need the E0-prefixed mapping.
EXTENDED = {
    96: 0x1C, 97: 0x1D, 98: 0x35, 99: 0x37, 100: 0x38, 102: 0x47, 103: 0x48,
    104: 0x49, 105: 0x4B, 106: 0x4D, 107: 0x4F, 108: 0x50, 109: 0x51,
    110: 0x52, 111: 0x53, 125: 0x5B, 126: 0x5C, 127: 0x5D,
}


def to_scan(xkeycode: int):
    ev = xkeycode - 8
    if 1 <= ev <= 88:
        return ev, 0
    if ev in EXTENDED:
        return EXTENDED[ev], 1
    return None


def connect() -> socket.socket:
    while True:
        try:
            s = socket.create_connection(("127.0.0.1", PORT), timeout=2)
            s.settimeout(None)
            return s
        except OSError:
            time.sleep(1)


def pointer_over_wine(d):
    """(over_wine, x, y): walk down the window stack under the pointer and report
    whether any level belongs to Wine (then Wine already gets the click itself)."""
    w = d.screen().root
    p = w.query_pointer()
    x, y = p.root_x, p.root_y
    try:
        while p.child:
            w = p.child
            cls = w.get_wm_class()
            if cls and cls[1] == WINE_CLASS:
                return True, x, y
            p = w.query_pointer()
    except error.XError:
        pass
    return False, x, y


def main() -> None:
    d = display.Display()
    if not d.has_extension("XInputExtension"):
        sys.exit("key_forwarder: XInput2 not available (Wayland session?)")
    xi_opcode = d.query_extension("XInputExtension").major_opcode
    d.screen().root.xinput_select_events(
        [(xinput.AllMasterDevices,
          xinput.RawKeyPressMask | xinput.RawKeyReleaseMask |
          xinput.RawButtonPressMask | xinput.RawButtonReleaseMask)])

    sock = connect()
    forwarded_buttons = set()  # buttons whose "down" we forwarded -> forward the "up"
    while True:
        e = d.next_event()
        if e.type != GENERIC_EVENT or e.extension != xi_opcode:
            continue
        data = e.data
        if isinstance(data, (bytes, bytearray)):
            # python-xlib leaves XIRawEvent undecoded: deviceid u16, time u32, detail u32
            detail = struct.unpack_from("<HII", data, 0)[2]
        else:
            detail = data.detail

        if e.evtype in (xinput.RawKeyPress, xinput.RawKeyRelease):
            m = to_scan(detail)
            if not m:
                continue
            kind = "D" if e.evtype == xinput.RawKeyPress else "U"
            msg = f"{kind} {m[0]} {m[1]}\n"
        elif e.evtype in (xinput.RawButtonPress, xinput.RawButtonRelease):
            if detail not in (1, 2, 3):  # 4-7 are the scroll wheel
                continue
            down = e.evtype == xinput.RawButtonPress
            if down:
                over_wine, x, y = pointer_over_wine(d)
                if over_wine:
                    continue
                forwarded_buttons.add(detail)
            else:
                if detail not in forwarded_buttons:
                    continue
                forwarded_buttons.discard(detail)
                _, x, y = pointer_over_wine(d)
            msg = f"B {detail} {int(down)} {x} {y}\n"
        else:
            continue
        try:
            sock.sendall(msg.encode())
        except OSError:
            sock = connect()


if __name__ == "__main__":
    main()
