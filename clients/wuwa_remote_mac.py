#!/usr/bin/env python3
"""Wuwa Tappo for Linux — macOS remote input counter.

Counts key presses and mouse clicks on this Mac and sends ONLY THE COUNTS to the
Linux machine running the pet (never which keys), so they're counted there too.

  python3 wuwa_remote_mac.py --host <linux-ip> --token <token> [--port 47812]
  python3 wuwa_remote_mac.py --host ... --token ... --test 5   # send 5 key presses + 5 clicks, then exit

macOS needs permission to observe input: System Settings → Privacy & Security →
Input Monitoring → enable the app you run this from (Terminal, iTerm, ...).
Uses only the Python standard library (ctypes + CoreGraphics), nothing to install.
"""
import argparse
import hashlib
import hmac
import socket
import sys
import threading
import time

FLUSH_INTERVAL = 0.2
MAX_PENDING = 10_000


class Counter:
    def __init__(self):
        self.lock = threading.Lock()
        self.keys = 0
        self.clicks = 0

    def add(self, keys=0, clicks=0):
        with self.lock:
            self.keys = min(self.keys + keys, MAX_PENDING)
            self.clicks = min(self.clicks + clicks, MAX_PENDING)

    def take(self):
        with self.lock:
            k, c = self.keys, self.clicks
            self.keys = self.clicks = 0
            return k, c

    def give_back(self, k, c):
        self.add(k, c)


def connect(host, port, token):
    s = socket.create_connection((host, port), timeout=10)
    f = s.makefile("rb")
    hello = f.readline(200).decode().split()
    if len(hello) != 2 or hello[0] != "WUWA1":
        raise OSError("unexpected server greeting")
    mac = hmac.new(token.encode(), hello[1].encode(), hashlib.sha256).hexdigest()
    s.sendall(f"AUTH {mac}\n".encode())
    if f.readline(20).strip() != b"OK":
        raise OSError("authentication failed (wrong token?)")
    s.settimeout(None)
    return s


def sender(args, counter, stop=None):
    sock, backoff = None, 1
    while stop is None or not stop.is_set():
        time.sleep(FLUSH_INTERVAL)
        k, c = counter.take()
        if not (k or c):
            continue
        try:
            if sock is None:
                sock = connect(args.host, args.port, args.token)
                print(f"connected to {args.host}:{args.port}", file=sys.stderr)
                backoff = 1
            msg = (f"K {k}\n" if k else "") + (f"C {c}\n" if c else "")
            sock.sendall(msg.encode())
        except OSError as e:
            counter.give_back(k, c)          # keep counts until we can deliver them
            if sock is None or backoff == 1:
                print(f"cannot reach {args.host}:{args.port}: {e}", file=sys.stderr)
            if sock:
                sock.close()
            sock = None
            time.sleep(min(backoff, 30))
            backoff *= 2


def run_event_tap(counter):
    import ctypes
    from ctypes import c_bool, c_int64, c_long, c_uint32, c_uint64, c_void_p

    cg = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
    cf = ctypes.cdll.LoadLibrary(
        "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

    kCGSessionEventTap, kCGHeadInsertEventTap, kCGEventTapOptionListenOnly = 1, 0, 1
    kCGEventLeftMouseDown, kCGEventRightMouseDown, kCGEventKeyDown, kCGEventOtherMouseDown = 1, 3, 10, 25
    kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput = 0xFFFFFFFE, 0xFFFFFFFF
    kCGKeyboardEventAutorepeat = 8
    mask = (1 << kCGEventKeyDown) | (1 << kCGEventLeftMouseDown) | \
           (1 << kCGEventRightMouseDown) | (1 << kCGEventOtherMouseDown)

    CALLBACK = ctypes.CFUNCTYPE(c_void_p, c_void_p, c_uint32, c_void_p, c_void_p)
    cg.CGEventTapCreate.restype = c_void_p
    cg.CGEventTapCreate.argtypes = [c_uint32, c_uint32, c_uint32, c_uint64, CALLBACK, c_void_p]
    cg.CGEventTapEnable.argtypes = [c_void_p, c_bool]
    cg.CGEventGetIntegerValueField.restype = c_int64
    cg.CGEventGetIntegerValueField.argtypes = [c_void_p, c_uint32]
    cf.CFMachPortCreateRunLoopSource.restype = c_void_p
    cf.CFMachPortCreateRunLoopSource.argtypes = [c_void_p, c_void_p, c_long]
    cf.CFRunLoopGetCurrent.restype = c_void_p
    cf.CFRunLoopAddSource.argtypes = [c_void_p, c_void_p, c_void_p]

    # macOS 10.15+: ask for Input Monitoring permission (shows the system prompt once)
    if hasattr(cg, "CGPreflightListenEventAccess"):
        cg.CGPreflightListenEventAccess.restype = c_bool
        if not cg.CGPreflightListenEventAccess():
            cg.CGRequestListenEventAccess()

    tap_ref = [None]

    def on_event(proxy, etype, event, refcon):
        if etype in (kCGEventTapDisabledByTimeout, kCGEventTapDisabledByUserInput):
            cg.CGEventTapEnable(tap_ref[0], True)
        elif etype == kCGEventKeyDown:
            if not cg.CGEventGetIntegerValueField(event, kCGKeyboardEventAutorepeat):
                counter.add(keys=1)
        elif etype in (kCGEventLeftMouseDown, kCGEventRightMouseDown, kCGEventOtherMouseDown):
            counter.add(clicks=1)
        return event

    callback = CALLBACK(on_event)  # keep a reference for the lifetime of the tap
    tap = cg.CGEventTapCreate(kCGSessionEventTap, kCGHeadInsertEventTap,
                              kCGEventTapOptionListenOnly, mask, callback, None)
    if not tap:
        sys.exit("無法監聽輸入：請到「系統設定 → 隱私權與安全性 → 輸入監控」"
                 "允許你用來執行本程式的 App（例如「終端機」），然後重新執行。")
    tap_ref[0] = tap
    source = cf.CFMachPortCreateRunLoopSource(None, tap, 0)
    modes = c_void_p.in_dll(cf, "kCFRunLoopCommonModes")
    cf.CFRunLoopAddSource(cf.CFRunLoopGetCurrent(), source, modes)
    cg.CGEventTapEnable(tap, True)
    print("正在計算按鍵與點擊次數（Ctrl+C 結束）", file=sys.stderr)
    cf.CFRunLoopRun()


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", required=True, help="Linux 那台的 IP")
    ap.add_argument("--port", type=int, default=47812)
    ap.add_argument("--token", required=True, help="wuwa-tappo remote-setup 顯示的密鑰")
    ap.add_argument("--test", type=int, metavar="N", help="只送出 N 次按鍵與 N 次點擊後結束（測試連線用）")
    args = ap.parse_args()

    counter = Counter()
    if args.test:
        try:
            s = connect(args.host, args.port, args.token)
            s.sendall(f"K {args.test}\nC {args.test}\n".encode())
            time.sleep(0.5)
            s.close()
            print(f"已送出 {args.test} 次按鍵與 {args.test} 次點擊")
        except OSError as e:
            sys.exit(f"連線失敗: {e}")
        return

    if sys.platform != "darwin":
        sys.exit("輸入監聽只支援 macOS（其他系統請用 --test 測試連線）")
    threading.Thread(target=sender, args=(args, counter), daemon=True).start()
    try:
        run_event_tap(counter)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
