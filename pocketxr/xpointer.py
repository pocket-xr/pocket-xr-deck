"""Where the mouse pointer is in Gaming Mode, for the pointer Pocket XR draws on the screen in space, and the keys
that do the back buttons' jobs (keys.py).

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
    unopened <name> <why>        one X screen would not open; said once, then tried again quietly
    key <code>                   a watched key went down (a Linux KEY_ code), with --keys 119,70

shown is 0 when the app's cursor is hidden or empty (a game that hides it), by XFixes' cursor image.

Which X screen: gamescope runs two Xwaylands in Gaming Mode, :0 (Steam, the output's size) and :1 (the game, the
game's size), and the effect works in the game picture's own pixels. 0.7.1 and 0.7.2 took the screen whose pointer
moved last, and a tester's log (Pierre Zammit, 22 Nov 2026) flips between :0 1920x1080 and :1 1280x800 with the game
running, so the pointer could be placed by the wrong screen's size. gamescope names the screen that has the mouse in
GAMESCOPE_MOUSE_FOCUS_DISPLAY on :0's root window (steamcompmgr.cpp), so that one is taken when it is set; the last
moved one otherwise. gamescope stores the name as 32 bit items, so the name's first 4 bytes are in the first item.

The keys are read here, not from the input devices: Steam Input sends a controller's keyboard bindings into gamescope's
X screen (XTest), and a new keyboard device is not readable by the user on SteamOS (checked on a Deck, 22 Nov 2026: a
uinput keyboard's event node gave "Permission denied"; an XTest key on :0 showed in XQueryKeymap). Each X screen's
key state is read 120 times a second; a key pressed on any of them counts.
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
    x11.XQueryKeymap.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    x11.XInternAtom.restype = ctypes.c_ulong
    x11.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x11.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long, ctypes.c_long,
                                       ctypes.c_int, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                       ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_ulong),
                                       ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p)]
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


def focus_name(items):
    """The X display name in gamescope's GAMESCOPE_MOUSE_FOCUS_DISPLAY (a list of 32 bit items), or None."""
    if not items:
        return None
    raw = (int(items[0]) & 0xFFFFFFFF).to_bytes(4, "little").split(b"\0")[0]
    name = raw.decode("ascii", errors="replace")
    return name if name.startswith(":") and name[1:].isdigit() else None


def pick(screens, focus):
    """The screen the pointer is read from: the one gamescope says has the mouse, else the one moved last."""
    if focus in screens:
        return screens[focus]
    return max(screens.values(), key=lambda q: q.moved_at)


def quietly(call):
    """Runs call() with libX11's messages to stderr caught: (its result, what it printed)."""
    import tempfile
    sys.stderr.flush()
    saved = os.dup(2)
    with tempfile.TemporaryFile() as f:
        os.dup2(f.fileno(), 2)
        try:
            result = call()
        finally:
            os.dup2(saved, 2)
            os.close(saved)
        f.seek(0)
        said = f.read().decode(errors="replace")
    return result, " ".join(dict.fromkeys(x.strip() for x in said.splitlines() if x.strip()))


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
        said = ""
        for auth in [os.environ.get("XAUTHORITY")] + xauthority_candidates():
            if auth:
                os.environ["XAUTHORITY"] = auth
            self.dpy, said = quietly(lambda: x11.XOpenDisplay(name.encode()))
            if self.dpy:
                break
        if not self.dpy:
            raise OSError(said or "would not open")
        scr = x11.XDefaultScreen(self.dpy)
        self.root = x11.XDefaultRootWindow(self.dpy)
        self.size = (x11.XDisplayWidth(self.dpy, scr), x11.XDisplayHeight(self.dpy, scr))
        self.fixes = False
        if xf:
            a, b = ctypes.c_int(), ctypes.c_int()
            self.fixes = bool(xf.XFixesQueryExtension(self.dpy, ctypes.byref(a), ctypes.byref(b)))
        self.last = None
        self.moved_at = 0.0
        self.keymap = ctypes.create_string_buffer(32)
        self.down = set()
        self.focus_atom = x11.XInternAtom(self.dpy, b"GAMESCOPE_MOUSE_FOCUS_DISPLAY", 1)  # 0 if gamescope set none

    def mouse_focus(self):
        """The display gamescope says has the mouse (set on its first Xwayland's root window), or None."""
        if not self.focus_atom:
            self.focus_atom = self.x11.XInternAtom(self.dpy, b"GAMESCOPE_MOUSE_FOCUS_DISPLAY", 1)
            if not self.focus_atom:
                return None
        kind, fmt = ctypes.c_ulong(), ctypes.c_int()
        n, left, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        if self.x11.XGetWindowProperty(self.dpy, self.root, self.focus_atom, 0, 4, 0, 0, ctypes.byref(kind),
                                       ctypes.byref(fmt), ctypes.byref(n), ctypes.byref(left), ctypes.byref(data)):
            return None
        try:
            if not data.value or fmt.value != 32 or not n.value:
                return None
            return focus_name(ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[:n.value])
        finally:
            if data.value:
                self.x11.XFree(data)

    def pressed(self, codes):
        """The watched keys (Linux codes) that went down since the last look."""
        self.x11.XQueryKeymap(self.dpy, self.keymap)
        raw = self.keymap.raw
        now = {c for c in codes if raw[(c + 8) // 8] >> ((c + 8) % 8) & 1}  # X keycodes are Linux codes + 8
        new = now - self.down
        self.down = now
        return new

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


def watched_keys(argv):
    """The Linux key codes after --keys (comma-separated), or none."""
    if "--keys" in argv:
        i = argv.index("--keys")
        if i + 1 < len(argv):
            return sorted({int(c) for c in argv[i + 1].split(",") if c.strip().isdigit() and 0 < int(c) < 248})
    return []


def main(argv=None):
    out = sys.stdout
    codes = watched_keys(sys.argv[1:] if argv is None else argv)
    try:
        x11, xf = _libs()
    except OSError as e:
        print(f"none no libX11 ({e})", flush=True)
        return 1
    screens = {}
    current, said, shown, next_cursor = None, None, True, 0.0
    next_open = 0.0
    unopened = set()
    focus = None
    while True:
        now = time.monotonic()
        if now >= next_open:
            next_open = now + 3.0
            names = display_names()
            for name in names:
                if name not in screens:
                    try:
                        screens[name] = Screen(x11, xf, name)
                        unopened.discard(name)
                    except OSError as e:
                        if name not in unopened:  # libX11 says why on stderr each try: said here once
                            unopened.add(name)
                            print(f"unopened {name} ({e}); tried again quietly", flush=True)
            if not screens:
                print("none no X screen opened (" + (", ".join(names) or "no sockets") + ")", flush=True)
        for s in screens.values():
            p = s.pointer()
            if p is not None and p != s.last:
                if s.last is not None:
                    s.moved_at = now
                s.last = p
        if codes:
            for q in screens.values():
                for c in sorted(q.pressed(codes)):
                    out.write(f"key {c}\n")
                    out.flush()
        if screens:
            if now >= next_cursor:
                first = screens[min(screens, key=lambda n: int(n[1:]) if n[1:].isdigit() else 99)]
                focus = first.mouse_focus()
            s = pick(screens, focus)
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
