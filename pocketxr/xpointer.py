"""Where the mouse pointer is in Gaming Mode, for the pointer Pocket XR draws on the screen in space.

gamescope runs its ReShade effect (Pocket XR's PocketXR.fx) on the app's picture only: the mouse cursor is drawn after
it, on top, where the pointer really is on the Deck's screen (gamescope's src/rendervulkan.cpp, vulkan_composite: the
effect runs on layer 0). With the screen moved, shrunk or curved in the glasses, that cursor is no longer over what it
points at (a tester, Pierre Zammit, 22 Nov 2026: hovering looked like it was on a button but wasn't). So the effect
draws a pointer of its own, in the picture's coordinates, where it lines up. gamescope's own cursor still shows; no
outside program can move or hide it.

This runs as its own process (python3 -m pocketxr.xpointer), because Xlib ends the whole program when its X server
goes away (gamescope restarting), and prints one line each time something changes:

    pointer <u> <v> <shown>      u, v from 0 to 1 across and down the X screen; shown 1 or 0
    display <name> <w>x<h>       the X screen the pointer is on (gamescope's Xwayland), when it changes
    none <why>                   no X screen could be opened (and why), tried again every few seconds

shown is 0 when the app's cursor is hidden or empty (a game that hides it), by XFixes' cursor image.
"""
import ctypes
import ctypes.util
import glob
import os
import sys
import time

POLL_S = 1 / 120
CURSOR_CHECK_S = 0.25


class _CursorImage(ctypes.Structure):
    _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short), ("width", ctypes.c_ushort),
                ("height", ctypes.c_ushort), ("xhot", ctypes.c_ushort), ("yhot", ctypes.c_ushort),
                ("cursor_serial", ctypes.c_ulong), ("pixels", ctypes.POINTER(ctypes.c_ulong)),
                ("atom", ctypes.c_ulong), ("name", ctypes.c_char_p)]


def _libs():
    x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
    x11.XOpenDisplay.restype = ctypes.c_void_p
    x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x11.XDefaultRootWindow.restype = ctypes.c_ulong
    x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x11.XDefaultScreen.argtypes = [ctypes.c_void_p]
    x11.XDisplayWidth.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XDisplayHeight.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XQueryPointer.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                  ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                                  ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                  ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_uint)]
    x11.XFree.argtypes = [ctypes.c_void_p]
    xf = None
    try:
        xf = ctypes.CDLL(ctypes.util.find_library("Xfixes") or "libXfixes.so.3")
        xf.XFixesGetCursorImage.restype = ctypes.POINTER(_CursorImage)
        xf.XFixesGetCursorImage.argtypes = [ctypes.c_void_p]
        xf.XFixesQueryExtension.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
    except OSError:
        xf = None
    return x11, xf


def xauthority_candidates(proc="/proc", names=("gamescope", "steam", "gamescope-wl")):
    """XAUTHORITY values from the session's own programs (the same user), to try when none is set here."""
    out = []
    for d in glob.glob(os.path.join(proc, "[0-9]*")):
        try:
            with open(os.path.join(d, "comm")) as f:
                if f.read().strip() not in names:
                    continue
            with open(os.path.join(d, "environ"), "rb") as f:
                env = f.read().split(b"\0")
        except OSError:
            continue
        for e in env:
            if e.startswith(b"XAUTHORITY="):
                v = e.split(b"=", 1)[1].decode(errors="replace")
                if v and v not in out:
                    out.append(v)
    return out


def display_names(root="/tmp/.X11-unix"):
    return [":" + os.path.basename(p)[1:] for p in sorted(glob.glob(os.path.join(root, "X[0-9]*")))]


def cursor_shown(image):
    """Whether an XFixes cursor image has any pixel that isn't fully transparent."""
    n = image.width * image.height
    if n <= 0 or not image.pixels:
        return False
    return any((image.pixels[i] >> 24) & 0xFF for i in range(min(n, 128 * 128)))


class Screen:
    def __init__(self, x11, xf, name):
        self.x11, self.xf, self.name = x11, xf, name
        self.dpy = None
        for auth in [os.environ.get("XAUTHORITY")] + xauthority_candidates():
            if auth:
                os.environ["XAUTHORITY"] = auth
            self.dpy = x11.XOpenDisplay(name.encode())
            if self.dpy:
                break
        if not self.dpy:
            raise OSError(f"{name} would not open")
        scr = x11.XDefaultScreen(self.dpy)
        self.root = x11.XDefaultRootWindow(self.dpy)
        self.size = (x11.XDisplayWidth(self.dpy, scr), x11.XDisplayHeight(self.dpy, scr))
        self.fixes = False
        if xf:
            a, b = ctypes.c_int(), ctypes.c_int()
            self.fixes = bool(xf.XFixesQueryExtension(self.dpy, ctypes.byref(a), ctypes.byref(b)))
        self.last = None
        self.moved_at = 0.0

    def pointer(self):
        r, c = ctypes.c_ulong(), ctypes.c_ulong()
        rx, ry, wx, wy = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        m = ctypes.c_uint()
        if not self.x11.XQueryPointer(self.dpy, self.root, ctypes.byref(r), ctypes.byref(c), ctypes.byref(rx),
                                      ctypes.byref(ry), ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(m)):
            return None
        return rx.value, ry.value

    def shown(self):
        if not self.fixes:
            return True
        img = self.xf.XFixesGetCursorImage(self.dpy)
        if not img:
            return True
        try:
            return cursor_shown(img.contents)
        finally:
            self.x11.XFree(img)


def main():
    out = sys.stdout
    try:
        x11, xf = _libs()
    except OSError as e:
        print(f"none no libX11 ({e})", flush=True)
        return 1
    screens = {}
    current, said, shown, next_cursor = None, None, True, 0.0
    next_open = 0.0
    while True:
        now = time.monotonic()
        if now >= next_open:
            next_open = now + 3.0
            names = display_names()
            for name in names:
                if name not in screens:
                    try:
                        screens[name] = Screen(x11, xf, name)
                    except OSError:
                        pass
            if not screens:
                print("none no X screen opened (" + (", ".join(names) or "no sockets") + ")", flush=True)
        for s in screens.values():
            p = s.pointer()
            if p is not None and p != s.last:
                if s.last is not None:
                    s.moved_at = now
                s.last = p
        if screens:
            s = max(screens.values(), key=lambda q: q.moved_at)
            if s is not current:
                current = s
                print(f"display {s.name} {s.size[0]}x{s.size[1]}", flush=True)
            if now >= next_cursor:
                next_cursor = now + CURSOR_CHECK_S
                shown = s.shown()
            if s.last is not None:
                line = (round(s.last[0] / max(1, s.size[0]), 4), round(s.last[1] / max(1, s.size[1]), 4), int(shown))
                if line != said:
                    said = line
                    out.write(f"pointer {line[0]} {line[1]} {line[2]}\n")
                    out.flush()
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
