#!/usr/bin/env python3
"""Receive key/click *counts* from other computers on the LAN and feed them to the
pet, so typing/clicking there is counted here too.

Only counts travel over the network -- never which key was pressed. Each counted
key press is replayed as F24 (a key no keyboard has, so it triggers nothing), each
click as a left click at the current pointer position, but only while the pointer
is NOT over one of the pet's own windows (otherwise we'd click the pet).

Auth: shared token from remote.conf, HMAC-SHA256 challenge/response (the token is
never sent). Protocol (one line each):
  server -> "WUWA1 <nonce-hex>"     client -> "AUTH <hmac-hex>"     server -> "OK"
  client -> "K <n>" / "C <n>"       (n = presses / clicks since the last line)

usage: remote_receiver.py <remote.conf> <injector-port>
"""
import hashlib
import hmac
import os
import socket
import sys
import threading
import time

from Xlib import display, error

WINE_CLASS = "steam_proton"
F24_SCANCODE = 0x76
MAX_PER_LINE = 50           # ignore absurd counts
MAX_PER_SECOND = 40         # global replay rate limit
CLICK_QUEUE_LIMIT = 200


def load_conf(path):
    conf = {}
    for line in open(path):
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip()
    return conf["token"].encode(), conf.get("bind", "0.0.0.0"), int(conf.get("port", "47812"))


class Injector:
    """Feeds the replayed input to key_injector.py inside Wine, rate-limited."""
    def __init__(self, port):
        self.port, self.sock = port, None
        self.keys = 0
        self.clicks = 0
        self.lock = threading.Lock()
        self.d = display.Display()

    def add(self, keys=0, clicks=0):
        with self.lock:
            self.keys += keys
            self.clicks = min(self.clicks + clicks, CLICK_QUEUE_LIMIT)

    def send(self, line):
        for _ in range(2):
            try:
                if self.sock is None:
                    self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=2)
                self.sock.sendall(line.encode())
                return True
            except OSError:
                self.sock = None
        return False

    def pointer_free(self):
        """Current pointer position if it is not over a Wine window, else None."""
        try:
            w = self.d.screen().root
            p = w.query_pointer()
            x, y = p.root_x, p.root_y
            while p.child:
                w = p.child
                cls = w.get_wm_class()
                if cls and cls[1] == WINE_CLASS:
                    return None
                p = w.query_pointer()
            return x, y
        except error.XError:
            return None

    def run(self):
        interval = 1.0 / MAX_PER_SECOND
        while True:
            with self.lock:
                do_key = self.keys > 0
                do_click = not do_key and self.clicks > 0
            if do_key:
                if self.send(f"D {F24_SCANCODE} 0\nU {F24_SCANCODE} 0\n"):
                    with self.lock:
                        self.keys -= 1
            elif do_click:
                pos = self.pointer_free()
                if pos is None:          # pointer is over the pet: try again later
                    time.sleep(0.5)
                    continue
                x, y = pos
                if self.send(f"B 1 1 {x} {y}\nB 1 0 {x} {y}\n"):
                    with self.lock:
                        self.clicks -= 1
            else:
                time.sleep(0.05)
                continue
            time.sleep(interval)


def handle(conn, addr, token, injector):
    try:
        conn.settimeout(5)
        nonce = os.urandom(16).hex()
        conn.sendall(f"WUWA1 {nonce}\n".encode())
        f = conn.makefile("rb")
        line = f.readline(200).decode(errors="replace").split()
        expected = hmac.new(token, nonce.encode(), hashlib.sha256).hexdigest()
        if len(line) != 2 or line[0] != "AUTH" or not hmac.compare_digest(line[1], expected):
            print(f"remote_receiver: rejected {addr[0]} (bad auth)", file=sys.stderr)
            return
        conn.sendall(b"OK\n")
        conn.settimeout(None)
        print(f"remote_receiver: {addr[0]} connected", file=sys.stderr)
        for raw in f:
            parts = raw.decode(errors="replace").split()
            if len(parts) != 2 or parts[0] not in ("K", "C") or not parts[1].isdigit():
                continue
            n = min(int(parts[1]), MAX_PER_LINE)
            injector.add(keys=n) if parts[0] == "K" else injector.add(clicks=n)
    except OSError:
        pass
    finally:
        conn.close()


def main():
    token, bind, port = load_conf(sys.argv[1])
    injector = Injector(int(sys.argv[2]) if len(sys.argv) > 2 else 47811)
    threading.Thread(target=injector.run, daemon=True).start()
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((bind, port))
    srv.listen(8)
    print(f"remote_receiver: listening on {bind}:{port}", file=sys.stderr)
    while True:
        conn, addr = srv.accept()
        threading.Thread(target=handle, args=(conn, addr, token, injector), daemon=True).start()


if __name__ == "__main__":
    main()
