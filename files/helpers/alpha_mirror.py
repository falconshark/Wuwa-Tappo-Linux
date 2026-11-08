#!/usr/bin/env python3
"""Linux-side transparency fix for Wuwa Tappo under Wine (X11 + compositor).

Under Wine, WebView2 can't render with per-pixel alpha (no DirectComposition), so the
pet's transparent background comes out solid black inside the window region the app
sets with SetWindowRgn.

This helper:
  * makes the original Wine window invisible (_NET_WM_WINDOW_OPACITY = 0) -- it still
    renders normally into its offscreen pixmap, and the app keeps handling the mouse;
  * copies its pixels ~30x/s into a click-through 32-bit ARGB overlay window, turning
    the black background transparent and dropping thin artifact lines.

Limitation: true partial transparency is not recoverable (the content is already
composited on black), so edges are hard and semi-transparent parts look darker.
Restores the original window when it exits.
"""
import glob
import os
import re
import select
import signal
import socket
import sys
import time

import numpy as np
from scipy import ndimage
from Xlib import X, Xatom, display, error, protocol
from Xlib.ext import shape

TITLES = {"Wuwa Tappo", "Toast"}   # the pet window and the fullscreen toast layer
WM_CLASS = "steam_proton"
FPS = 30
BLACK_THRESHOLD = 12               # max(r,g,b) <= this counts as background
SMALL_HOLE = 4000                  # enclosed dark areas up to this many px are kept opaque
WHITE_BLOB = 100                   # pure-white blobs this big are repaint garbage

# The app's "opacity" setting is CSS opacity inside the WebView. Rendered over black,
# a pixel becomes color*a -- which is exactly premultiplied ARGB -- so setting the
# mirror's alpha to a restores real translucency. We read a from localStorage.
BASE = os.environ.get("WUWA_TAPPO_HOME", os.path.expanduser("~/.local/share/wuwa-tappo"))
# any Wine user name, any region build (com.kuro.wuwatappo.cn / .global / ...)
LOCAL_STORAGE_GLOB = os.path.join(
    glob.escape(BASE), "prefix/drive_c/users/*/AppData/Local/com.kuro.wuwatappo.*",
    "EBWebView/Default/Local Storage/leveldb")
OPACITY_RE = re.compile(rb'"windowOpacity":(\d{1,3})')


class OpacitySetting:
    def __init__(self):
        self.value = 1.0
        self._sig = None
        self._checked = 0.0

    def get(self) -> float:
        now = time.monotonic()
        if now - self._checked < 1:
            return self.value
        self._checked = now
        try:
            files = sorted(glob.glob(os.path.join(LOCAL_STORAGE_GLOB, "*.log")) +
                           glob.glob(os.path.join(LOCAL_STORAGE_GLOB, "*.ldb")),
                           key=os.path.getmtime, reverse=True)
            sig = tuple((f, os.path.getmtime(f)) for f in files)
            if sig == self._sig:
                return self.value
            self._sig = sig
            for f in files:  # newest file first; last match in it is the newest write
                hits = OPACITY_RE.findall(open(f, "rb").read())
                if hits:
                    self.value = min(max(int(hits[-1]), 1), 100) / 100
                    break
        except OSError:
            pass
        return self.value


OPACITY = OpacitySetting()


class RedrawRequester:
    """Asks key_injector.py (inside Wine) to RedrawWindow the pet whenever the app
    changes its window region; otherwise newly exposed areas stay white/missing."""
    def __init__(self, port: int):
        self.port, self.sock, self.due = port, None, []

    def schedule(self):
        now = time.monotonic()
        self.due = [now, now + 0.3, now + 1.0]  # Chromium sometimes paints late

    def tick(self):
        now = time.monotonic()
        if not self.due or self.due[0] > now:
            return
        while self.due and self.due[0] <= now:
            self.due.pop(0)
        try:
            if self.sock is None:
                self.sock = socket.create_connection(("127.0.0.1", self.port), timeout=0.5)
            self.sock.sendall(b"R\n")
        except OSError:
            self.sock = None


REDRAW = RedrawRequester(int(sys.argv[1]) if len(sys.argv) > 1 else 47811)


class Mirror:
    def __init__(self, d, screen, visual, cmap, src):
        self.d, self.src = d, src
        self.geom = None
        self.win = screen.root.create_window(
            0, 0, 1, 1, 0, 32, X.InputOutput, visual,
            colormap=cmap, background_pixel=0, border_pixel=0,
            override_redirect=True, event_mask=0)
        self.win.set_wm_name("WuwaTappo alpha mirror")
        self.win.shape_rectangles(shape.SO.Set, shape.SK.Input, X.Unsorted, 0, 0, [])
        self.gc = self.win.create_gc(foreground=0, background=0)
        self.mapped = False
        self.hidden_src = False

    def hide_src(self, hide: bool):
        op = self.d.intern_atom("_NET_WM_WINDOW_OPACITY")
        try:
            if hide:
                self.src.change_property(op, Xatom.CARDINAL, 32, [0])
            else:
                self.src.delete_property(op)
            self.hidden_src = hide
        except error.XError:
            pass

    def destroy(self):
        self.hide_src(False)
        try:
            self.win.destroy()
        except error.XError:
            pass

    def src_is_hidden(self) -> bool:
        op = self.d.intern_atom("_NET_WM_WINDOW_OPACITY")
        p = self.src.get_full_property(op, Xatom.CARDINAL)
        return p is not None and len(p.value) and p.value[0] == 0

    def update(self):
        src = self.src
        # Wine rewrites/deletes the opacity property when the app touches layered
        # attributes, so keep re-applying it while we're mirroring
        if self.mapped and not self.src_is_hidden():
            # whatever Wine just wrote is the app's own window opacity setting
            # (deleted = 100%); carry it over to the mirror, then hide the source again
            op = self.d.intern_atom("_NET_WM_WINDOW_OPACITY")
            p = src.get_full_property(op, Xatom.CARDINAL)
            if p is not None and len(p.value):
                self.win.change_property(op, Xatom.CARDINAL, 32, [int(p.value[0])])
            else:
                self.win.delete_property(op)
            self.hide_src(True)
        rects = src.shape_get_rectangles(shape.SK.Bounding).rectangles
        attrs = src.get_attributes()
        if attrs.map_state != X.IsViewable or not rects:
            if self.mapped:
                self.win.unmap(); self.mapped = False
            return
        g = src.get_geometry()
        sx = min(r.x for r in rects); sy = min(r.y for r in rects)
        ex = max(r.x + r.width for r in rects); ey = max(r.y + r.height for r in rects)
        sx, sy = max(sx, 0), max(sy, 0)
        ex, ey = min(ex, g.width), min(ey, g.height)
        w, h = ex - sx, ey - sy
        if w <= 0 or h <= 0:
            return
        img = src.get_image(sx, sy, w, h, X.ZPixmap, 0xFFFFFFFF)
        a = OPACITY.get()
        rect_key = tuple((r.x, r.y, r.width, r.height) for r in rects)
        if rect_key != getattr(self, "_last_rects", None):
            self._last_rects = rect_key
            REDRAW.schedule()
        key = (sx, sy, w, h, a, rect_key)
        if self.mapped and key == getattr(self, "_last_key", None) and img.data == getattr(self, "_last_data", None):
            if time.monotonic() - getattr(self, "_last_raise", 0) > 1:
                self.win.configure(stack_mode=X.Above)  # stay on top of other windows
                self._last_raise = time.monotonic()
            return  # nothing changed: skip the image processing
        self._last_key, self._last_data = key, img.data
        px = np.frombuffer(img.data, dtype=np.uint8)
        stride = len(px) // h
        px = px.reshape(h, stride)[:, : w * 4].reshape(h, w, 4)

        region = np.zeros((h, w), bool)
        for r in rects:
            region[max(r.y - sy, 0): r.y - sy + r.height, max(r.x - sx, 0): r.x - sx + r.width] = True
        fg = px[:, :, :3].max(axis=2) > max(3, BLACK_THRESHOLD * a)
        fg = ndimage.binary_opening(fg, structure=np.ones((3, 3), bool))  # drop 1-2px lines
        # Areas the out-of-process WebView hasn't repainted (frame edges, the box that
        # appears with the chest) show the window's pure-white (255,255,255) background.
        # The pet art's whites are near-white (<255) or tiny specks, so drop every
        # pure-white blob of >= WHITE_BLOB px.
        white = (px[:, :, :3].min(axis=2) == 255) & fg
        lab, n = ndimage.label(white)
        if n:
            sizes = ndimage.sum_labels(white, lab, np.arange(1, n + 1))
            big = np.concatenate(([False], sizes >= WHITE_BLOB))
            fg &= ~big[lab]
        # fill holes (dark parts inside the art, e.g. hair) up to a size limit, so a
        # large enclosed gap between separate sprites still stays transparent
        holes = ndimage.binary_fill_holes(fg) & ~fg
        hl, hn = ndimage.label(holes)
        if hn:
            sizes = ndimage.sum_labels(holes, hl, np.arange(1, hn + 1))
            small = np.concatenate(([False], sizes <= SMALL_HOLE))
            fg |= small[hl]
        fg &= region

        out = px.copy()
        alpha = round(255 * a)
        out[:, :, 3] = np.where(fg, alpha, 0)  # colour is already premultiplied by a
        np.minimum(out[:, :, :3], alpha, out=out[:, :, :3])  # keep premultiplied valid
        out[~fg] = 0  # premultiplied alpha

        # position: translate source-window coords to root coords
        tr = self.d.screen().root.translate_coords(src, sx, sy)
        rx, ry = tr.x, tr.y
        if self.geom != (rx, ry, w, h):
            self.win.configure(x=rx, y=ry, width=w, height=h)
            self.geom = (rx, ry, w, h)
        data = out.tobytes()
        band = max(1, 60000 // (w * 4))
        for y0 in range(0, h, band):
            hh = min(band, h - y0)
            self.win.put_image(self.gc, 0, y0, w, hh, X.ZPixmap, 32, 0,
                               data[y0 * w * 4:(y0 + hh) * w * 4])
        if not self.mapped:
            self.win.map(); self.mapped = True
        self.win.configure(stack_mode=X.Above)
        self._last_raise = time.monotonic()
        if not self.hidden_src:
            self.hide_src(True)


def find_targets(d, titles=TITLES):
    out = {}
    def walk(w):
        try:
            for c in w.query_tree().children:
                try:
                    cls = c.get_wm_class()
                    name = c.get_wm_name()
                except error.XError:
                    continue
                if cls and cls[1] == WM_CLASS and name in titles:
                    out[c.id] = c
                walk(c)
        except error.XError:
            pass
    walk(d.screen().root)
    return out


# The app's clicks go through "DesktopCatInput" (a near-invisible window whose shape
# is the clickable spots). Under Wine it isn't kept on top, so other windows cover it
# while the mirror still *shows* the pet on top -> clicks hit the other window.
ABOVE_TITLES = {"DesktopCatInput", "Wuwa Tappo"}


def ensure_above(d, w):
    state = d.intern_atom("_NET_WM_STATE")
    above = d.intern_atom("_NET_WM_STATE_ABOVE")
    try:
        p = w.get_full_property(state, Xatom.ATOM)
        if p is not None and above in p.value:
            return
        ev = protocol.event.ClientMessage(window=w, client_type=state,
                                          data=(32, [1, above, 0, 1, 0]))  # _NET_WM_STATE_ADD
        d.screen().root.send_event(
            ev, event_mask=X.SubstructureRedirectMask | X.SubstructureNotifyMask)
    except error.XError:
        pass


def argb_visual(screen):
    for depth in screen.allowed_depths:
        if depth.depth == 32:
            for v in depth.visuals:
                if v.visual_class == X.TrueColor:
                    return v.visual_id
    return None


def main():
    d = display.Display()
    d.set_error_handler(lambda *a: None)
    screen = d.screen()
    vis = argb_visual(screen)
    if vis is None:
        sys.exit("alpha_mirror: no 32-bit visual (is a compositor running?)")
    cmap = screen.root.create_colormap(vis, X.AllocNone)
    mirrors = {}
    running = True

    def stop(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    last_scan = 0.0
    last_seen = time.monotonic()  # grace period while the app starts up
    try:
        while running:
            t0 = time.monotonic()
            if t0 - last_scan > 2:
                last_scan = t0
                for w in find_targets(d, ABOVE_TITLES).values():
                    ensure_above(d, w)
                targets = find_targets(d)
                # exit on our own once the app has been gone for a while
                if targets:
                    last_seen = t0
                elif t0 - last_seen > 30:
                    break
                for wid in list(mirrors):
                    if wid not in targets:
                        mirrors.pop(wid).destroy()
                for wid, w in targets.items():
                    if wid not in mirrors:
                        mirrors[wid] = Mirror(d, screen, vis, cmap, w)
            for wid, m in list(mirrors.items()):
                try:
                    m.update()
                except error.XError:
                    mirrors.pop(wid).destroy()
            REDRAW.tick()
            d.flush()
            while d.pending_events():
                d.next_event()
            dt = 1 / FPS - (time.monotonic() - t0)
            if dt > 0:
                select.select([d.fileno()], [], [], dt)
    finally:
        for m in mirrors.values():
            m.destroy()
        d.flush()
        d.close()


if __name__ == "__main__":
    main()
