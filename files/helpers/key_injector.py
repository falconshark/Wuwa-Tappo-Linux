# Runs INSIDE Wine (Windows embeddable Python).
# Receives input events from key_forwarder.py (Linux side) over TCP and replays them
# with SendInput, so the app's hooks / Raw Input see typing and clicking done in
# native Linux programs (Wine only gets input for its own windows).
#   * keys: only injected while no Wine window is focused (foreground == desktop),
#     so they're never typed into a Wine window twice;
#   * clicks: the forwarder only sends clicks that did NOT land on a Wine window; we
#     first move Wine's (stale) cursor to the real pointer position, so the click hits
#     no Wine window instead of e.g. a button on the pet.
# Also handles "R": force the pet's WebView to repaint (see redraw_pet).
import ctypes
import ctypes.wintypes as wt
import socket
import sys
import threading

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 47811

user32 = ctypes.WinDLL("user32", use_last_error=True)

INPUT_MOUSE, INPUT_KEYBOARD = 0, 1
KEYEVENTF_EXTENDEDKEY = 0x1
KEYEVENTF_KEYUP = 0x2
KEYEVENTF_SCANCODE = 0x8
MOUSEEVENTF_MOVE, MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_VIRTUALDESK = 0x1, 0x8000, 0x4000
BUTTON_FLAGS = {  # X button -> (down flag, up flag)
    1: (0x0002, 0x0004),  # left
    2: (0x0020, 0x0040),  # middle
    3: (0x0008, 0x0010),  # right
}
SM_XVIRTUALSCREEN, SM_YVIRTUALSCREEN, SM_CXVIRTUALSCREEN, SM_CYVIRTUALSCREEN = 76, 77, 78, 79
RDW_INVALIDATE, RDW_ALLCHILDREN, RDW_UPDATENOW = 0x1, 0x80, 0x100
ULONG_PTR = ctypes.c_size_t


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _U(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _U)]


def wine_has_focus() -> bool:
    fg = user32.GetForegroundWindow()
    return bool(fg) and fg != user32.GetDesktopWindow()


def send_key(scan: int, ext: bool, up: bool) -> None:
    flags = KEYEVENTF_SCANCODE | (KEYEVENTF_EXTENDEDKEY if ext else 0) | (KEYEVENTF_KEYUP if up else 0)
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.u.ki = KEYBDINPUT(0, scan, flags, 0, 0)
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def send_button(button: int, down: bool, x: int, y: int) -> None:
    if button not in BUTTON_FLAGS:
        return
    # X root coords == offset from the top-left of Wine's virtual screen
    vw = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN) or 1
    vh = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN) or 1
    nx = min(65535, int((x + 0.5) * 65536 / vw))
    ny = min(65535, int((y + 0.5) * 65536 / vh))
    arr = (INPUT * 2)()
    arr[0].type = INPUT_MOUSE
    arr[0].u.mi = MOUSEINPUT(nx, ny, 0, MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK, 0, 0)
    arr[1].type = INPUT_MOUSE
    arr[1].u.mi = MOUSEINPUT(0, 0, 0, BUTTON_FLAGS[button][0 if down else 1], 0, 0)
    user32.SendInput(2, arr, ctypes.sizeof(INPUT))


def redraw_pet() -> None:
    """Make the out-of-process WebView repaint everything. Under Wine it doesn't
    repaint areas newly exposed when the app changes the window region (e.g. when the
    chest bubble appears), leaving them white/missing."""
    top = user32.FindWindowW(None, "Wuwa Tappo")
    if top:
        user32.RedrawWindow(top, None, None, RDW_INVALIDATE | RDW_ALLCHILDREN | RDW_UPDATENOW)


def handle_line(line: bytes) -> None:
    parts = line.split()
    if not parts:
        return
    try:
        if parts[0] == b"R":
            redraw_pet()
        elif parts[0] == b"B":
            _, button, down, x, y = parts
            send_button(int(button), down == b"1", int(x), int(y))
        elif parts[0] in (b"D", b"U"):
            kind, scan, ext = parts
            # key-ups are always forwarded so nothing stays "stuck"
            if kind == b"U" or not wine_has_focus():
                send_key(int(scan), ext == b"1", kind == b"U")
    except ValueError:
        pass


def handle(conn) -> None:
    buf = b""
    with conn:
        while True:
            try:
                chunk = conn.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                handle_line(line)


def serve() -> None:
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", PORT))
    srv.listen(4)
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    serve()
