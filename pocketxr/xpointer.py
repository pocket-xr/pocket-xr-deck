"""Where the mouse pointer is in Gaming Mode, for the pointer Pocket XR draws on the screen in space, and the keys
that do the back buttons' jobs (keys.py).

gamescope runs its ReShade effect (Pocket XR's PocketXR.fx) on the app's picture only: the mouse cursor is drawn after
it, on top, where the pointer really is on the Deck's screen (gamescope's src/rendervulkan.cpp, vulkan_composite: the
effect runs on layer 0). With the screen moved, shrunk or curved in the glasses, that cursor is no longer over what it
points at (a tester, Pierre Zammit, 22 Nov 2026: hovering looked like it was on a button but wasn't). So the effect
draws a pointer of its own, in the picture's coordinates, where it lines up.

gamescope's own arrow (MouseCursor::paint in steamcompmgr.cpp) is drawn at the pointer's place in the app's window,
scaled into the output, after the effect: where the pointer would be on a flat screen. So with the screen in space it
moves with the head and is never where a click lands; it only lines up when the screen is where a flat one would be.
The same tester kept seeing two arrows apart (24 Nov 2026: "the mouse pointer issue ... the only thing I can fault").
gamescope has no option or property to hide it, but it draws nothing when the X cursor's image is empty
(m_imageEmpty: every pixel transparent). So while the screen is in space ("hide 1" from gaming.py), this blanks the
cursor of the app's window under the pointer (XDefineCursor, which any X client may do to any window), keeping track of
whether the app itself wants a cursor (its own image, before it is blanked: cursor_decision), so Pocket XR's pointer
still shows and hides with the app's. "hide 0", the end of this program, or SIGTERM give the cursors back
(XUndefineCursor: the app's own comes back when it sets one again; until then the X screen's default arrow). Written
from gamescope's source; not yet tried on a Deck.

This runs as its own process (python3 -m pocketxr.xpointer), because Xlib ends the whole program when its X server
goes away (gamescope restarting), and prints one line each time something changes:

    pointer <u> <v> <shown>      u, v from 0 to 1 across and down the X screen; shown 1 or 0
    display <name> <w>x<h>       the X screen the pointer is on (gamescope's Xwayland), when it changes
    none <why>                   no X screen could be opened (and why), tried again every few seconds
    unopened <name> <why>        one X screen would not open; said once, then tried again quietly
    window <name> <id> at <x>,<y> <w>x<h>   the app's window u, v are measured in, when it changes (or "window none")
    key <code>                   a watched key went down (a Linux KEY_ code), with --keys 119,70
    hide on: ... / hide off: ...  gamescope's own arrow blanked or given back, after "hide 1" / "hide 0" on stdin
    click at <x>,<y> on <name> <w>x<h>: u <u>, v <v>   the left button went down (at most once a second), for a log

shown is 0 when the app's cursor is hidden or empty (a game that hides it), by XFixes' cursor image.

Which X screen: gamescope runs two Xwaylands in Gaming Mode, :0 (Steam, the output's size) and :1 (the game, the
game's size), and the effect works in the game picture's own pixels. 0.7.1 and 0.7.2 took the screen whose pointer
moved last, and a tester's log (Pierre Zammit, 22 Nov 2026) flips between :0 1920x1080 and :1 1280x800 with the game
running, so the pointer could be placed by the wrong screen's size. gamescope names the screen that has the mouse in
GAMESCOPE_MOUSE_FOCUS_DISPLAY on :0's root window (steamcompmgr.cpp), so that one is taken when it is set; the last
moved one otherwise. gamescope stores the name as 32 bit items, so the name's first 4 bytes are in the first item.
When the app with the mouse is a Wayland window (Nested Desktop runs Plasma as one), gamescope names its Wayland
display there (gamescope-0) instead, and no X screen sees that pointer: 0.7.5 then took the last moved X screen, so
its pointer was somewhere else. Now Pocket XR's pointer is hidden then (a tester, Pierre Zammit, 23 Nov 2026, saw it
off in Nested Desktop). Written from gamescope's source; not yet tried on a Deck.

Which part of it: the effect runs on gamescope's first layer, the focused app's window, not the whole X screen, so a
game whose window is smaller than its X screen (a 1280x720 game on the Deck's 1280x800, say) put 0.7.4's pointer off.
The same tester still saw it off with 0.7.4, where his log shows the game's screen (:1 1280x800) in use. gamescope
names that window in GAMESCOPE_FOCUSED_WINDOW and its display in GAMESCOPE_FOCUS_DISPLAY (steamcompmgr.cpp), so u, v
are now measured across that window when it is on the screen the pointer is on, the whole screen otherwise. Written
from gamescope's source; not yet tried on a Deck.

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
BUTTON1_MASK = 1 << 8  # X's Button1Mask in XQueryPointer's mask
HIDE_CHECK_S = 1 / 30  # while gamescope's arrow is hidden: how soon a cursor the app sets again is blanked


class _XColor(ctypes.Structure):
    _fields_ = [("pixel", ctypes.c_ulong), ("red", ctypes.c_ushort), ("green", ctypes.c_ushort),
                ("blue", ctypes.c_ushort), ("flags", ctypes.c_char), ("pad", ctypes.c_char)]


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
    x11.XGetGeometry.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                                 ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                 ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint),
                                 ctypes.POINTER(ctypes.c_uint), ctypes.POINTER(ctypes.c_uint)]
    x11.XTranslateCoordinates.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_int, ctypes.c_int,
                                          ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int),
                                          ctypes.POINTER(ctypes.c_ulong)]
    x11.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    x11.XCreateBitmapFromData.restype = ctypes.c_ulong
    x11.XCreateBitmapFromData.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p, ctypes.c_uint,
                                          ctypes.c_uint]
    x11.XCreatePixmapCursor.restype = ctypes.c_ulong
    x11.XCreatePixmapCursor.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.POINTER(_XColor),
                                        ctypes.POINTER(_XColor), ctypes.c_uint, ctypes.c_uint]
    x11.XDefineCursor.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
    x11.XUndefineCursor.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
    x11.XFlush.argtypes = [ctypes.c_void_p]
    x11.XSetErrorHandler.restype = ctypes.c_void_p
    x11.XSetErrorHandler.argtypes = [_ERROR_HANDLER]
    x11.XSetErrorHandler(_on_x_error)  # a window gone between looking it up and asking about it ends nothing
    return x11, xf


# Xlib's own error handler ends the program on any error, such as asking about a window that just closed
_ERRORS = [0]
_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)


def _on_x_error_py(dpy, event):
    _ERRORS[0] += 1
    return 0


_on_x_error = _ERROR_HANDLER(_on_x_error_py)


def to_uv(p, size, area=None):
    """Where the pointer p (x, y on the X screen) is on the picture gamescope's effect works in: the focused window
    (area: x, y, w, h) when known, else the whole X screen (size: w, h), from 0 to 1 across and down."""
    if area:
        x, y, w, h = area
        return round((p[0] - x) / max(1, w), 4), round((p[1] - y) / max(1, h), 4)
    return round(p[0] / max(1, size[0]), 4), round(p[1] / max(1, size[1]), 4)


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


def wayland_focus(items):
    """Whether gamescope's GAMESCOPE_MOUSE_FOCUS_DISPLAY names a Wayland display (gamescope-0, say) rather than an X
    one: the app with the mouse is a Wayland window (Nested Desktop, for example), whose pointer no X screen shows.
    Only the name's first 4 bytes are read (see the module's docstring)."""
    if not items:
        return False
    raw = (int(items[0]) & 0xFFFFFFFF).to_bytes(4, "little").split(b"\0")[0]
    return bool(raw) and not raw.startswith(b":")


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


def cursor_decision(serial, visible, blank_serial, game_shown):
    """While gamescope's arrow is being hidden: (whether the app wants a cursor, whether to blank the window under the
    pointer now), from the X screen's cursor now (its serial, whether it has a visible pixel). Our own blank cursor
    (blank_serial) says nothing new about the app; a visible one is the app's, to blank; an empty one not ours is the
    app hiding its cursor."""
    if blank_serial is not None and serial == blank_serial:
        return game_shown, False
    if visible:
        return True, True
    return False, False


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
        self.atoms = {}

    def _items(self, name):
        """A 32 bit property of this screen's root window (gamescope sets its own on its first Xwayland's), or []."""
        atom = self.atoms.get(name)
        if not atom:
            atom = self.atoms[name] = self.x11.XInternAtom(self.dpy, name.encode(), 1)  # 0 if nobody made it
            if not atom:
                return []
        kind, fmt = ctypes.c_ulong(), ctypes.c_int()
        n, left, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        if self.x11.XGetWindowProperty(self.dpy, self.root, atom, 0, 4, 0, 0, ctypes.byref(kind),
                                       ctypes.byref(fmt), ctypes.byref(n), ctypes.byref(left), ctypes.byref(data)):
            return []
        try:
            if not data.value or fmt.value != 32 or not n.value:
                return []
            return list(ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[:n.value])
        finally:
            if data.value:
                self.x11.XFree(data)

    def mouse_focus(self):
        """(the X display gamescope says has the mouse or None, whether that is a Wayland window instead)."""
        items = self._items("GAMESCOPE_MOUSE_FOCUS_DISPLAY")
        return focus_name(items), wayland_focus(items)

    def focused_window(self):
        """(display name, X window) of the window gamescope shows as the app (its first layer), or (None, 0)."""
        win = self._items("GAMESCOPE_FOCUSED_WINDOW")
        return focus_name(self._items("GAMESCOPE_FOCUS_DISPLAY")), (int(win[0]) & 0xFFFFFFFF) if win else 0

    def window_area(self, win):
        """(x, y, w, h) of an X window on this screen, in the root window's pixels, or None (gone, or no such
        window: X errors are caught, see _quiet_errors)."""
        root, child = ctypes.c_ulong(), ctypes.c_ulong()
        x, y, rx, ry = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        w, h, bw, depth = ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint(), ctypes.c_uint()
        _ERRORS[0] = 0
        if not self.x11.XGetGeometry(self.dpy, win, ctypes.byref(root), ctypes.byref(x), ctypes.byref(y),
                                     ctypes.byref(w), ctypes.byref(h), ctypes.byref(bw), ctypes.byref(depth)):
            return None
        if not self.x11.XTranslateCoordinates(self.dpy, win, self.root, 0, 0, ctypes.byref(rx), ctypes.byref(ry),
                                              ctypes.byref(child)):
            return None
        self.x11.XSync(self.dpy, 0)
        if _ERRORS[0] or w.value < 16 or h.value < 16:
            return None
        return rx.value, ry.value, w.value, h.value

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
        self.buttons = m.value
        return rx.value, ry.value

    def cursor(self):
        """(serial, has a visible pixel) of the X screen's cursor now, or None without XFixes."""
        if not self.fixes:
            return None
        img = self.xf.XFixesGetCursorImage(self.dpy)
        if not img:
            return None
        try:
            return int(img.contents.cursor_serial), cursor_shown(img.contents)
        finally:
            self.x11.XFree(img)

    def shown(self):
        c = self.cursor()
        return True if c is None else c[1]

    # ---- hiding gamescope's own arrow (see the module's docstring) ----
    def under_pointer(self):
        """The deepest X window under the pointer, or 0."""
        win, found = self.root, 0
        for _ in range(16):
            r, c = ctypes.c_ulong(), ctypes.c_ulong()
            rx, ry, wx, wy, m = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_uint()
            if not self.x11.XQueryPointer(self.dpy, win, ctypes.byref(r), ctypes.byref(c), ctypes.byref(rx),
                                          ctypes.byref(ry), ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(m)):
                break
            if not c.value:
                break
            win = found = c.value
        return found

    def _blank(self):
        if not getattr(self, "blank", 0):
            bits = self.x11.XCreateBitmapFromData(self.dpy, self.root, b"\0", 1, 1)
            black = _XColor()
            self.blank = self.x11.XCreatePixmapCursor(self.dpy, bits, bits, ctypes.byref(black), ctypes.byref(black),
                                                      0, 0)
        return self.blank

    def hide_step(self):
        """One look while gamescope's arrow is hidden: blanks the window under the pointer when the app shows a cursor
        there. Returns whether the app wants a cursor (for Pocket XR's own pointer)."""
        c = self.cursor()
        if c is None:
            return True
        serial, visible = c
        if not hasattr(self, "game_shown"):
            self.game_shown, self.blank_serial, self.blanked = True, None, set()
        self.game_shown, blank_now = cursor_decision(serial, visible, self.blank_serial, self.game_shown)
        if blank_now:
            win = self.under_pointer()
            if win:
                _ERRORS[0] = 0
                self.x11.XDefineCursor(self.dpy, win, self._blank())
                self.x11.XSync(self.dpy, 0)
                if not _ERRORS[0]:
                    self.blanked.add(win)
                    after = self.cursor()
                    if after and not after[1]:
                        self.blank_serial = after[0]
        return self.game_shown

    def restore(self):
        """Gives back the cursors blanked (the app's own come back when it sets them again; until then the screen's)."""
        for win in list(getattr(self, "blanked", ())):
            self.x11.XUndefineCursor(self.dpy, win)
        if getattr(self, "blanked", None):
            self.x11.XSync(self.dpy, 0)
            self.blanked.clear()
        self.blank_serial = None


def watched_keys(argv):
    """The Linux key codes after --keys (comma-separated), or none."""
    if "--keys" in argv:
        i = argv.index("--keys")
        if i + 1 < len(argv):
            return sorted({int(c) for c in argv[i + 1].split(",") if c.strip().isdigit() and 0 < int(c) < 248})
    return []


def read_commands(stream, timeout=0.0, pending=None):
    """Lines waiting on [stream] (gaming.py's commands: "hide 1", "hide 0"), [] when none; None once it has ended.
    Read from the file descriptor itself, so lines that came in one write are all seen (a text stream's own buffer
    would hide them from select); [pending] (a bytearray) keeps a part line between calls."""
    import select
    pending = bytearray() if pending is None else pending
    try:
        fd = stream.fileno()
    except (OSError, ValueError, AttributeError):
        return None
    try:
        r, _, _ = select.select([fd], [], [], timeout)
        if r:
            data = os.read(fd, 4096)
            if not data:
                return None
            pending.extend(data)
    except (OSError, ValueError):
        return None
    *lines, rest = bytes(pending).split(b"\n")
    pending[:] = rest
    return [x.decode(errors="replace").strip() for x in lines if x.strip()]


def main(argv=None):
    out = sys.stdout
    import signal
    signal.signal(signal.SIGTERM, lambda n, f: sys.exit(0))  # so the cursors blanked are given back (finally below)
    screens = {}
    try:
        return _main(out, argv, screens)
    finally:
        for q in screens.values():
            try:
                q.restore()
            except Exception:  # noqa: BLE001
                pass


def _main(out, argv, screens):
    codes = watched_keys(sys.argv[1:] if argv is None else argv)
    try:
        x11, xf = _libs()
    except OSError as e:
        print(f"none no libX11 ({e})", flush=True)
        return 1
    current, said, shown, next_cursor = None, None, True, 0.0
    hide, commands_open, commands_buf = False, True, bytearray()
    last_click = 0.0
    next_open = 0.0
    unopened = set()
    focus = None
    app_display, app_win, area = None, 0, None
    in_wayland, said_wayland = False, False
    while True:
        now = time.monotonic()
        if commands_open:
            got = read_commands(sys.stdin, 0.0, commands_buf)
            if got is None:
                commands_open = False
            for cmd in got or ():
                if cmd in ("hide 1", "hide 0") and (cmd == "hide 1") != hide:
                    hide = cmd == "hide 1"
                    if not hide:
                        for q in screens.values():
                            q.restore()
                    next_cursor = 0.0
                    print("hide " + ("on: gamescope's own arrow is blanked on the app's window" if hide
                                     else "off: the app's cursors are given back"), flush=True)
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
                focus, in_wayland = first.mouse_focus()
                if in_wayland != said_wayland:
                    said_wayland = in_wayland
                    print("focus the app with the mouse is a Wayland window: no X screen has its pointer, so "
                          "Pocket XR's pointer is hidden" if in_wayland else "focus the app with the mouse is on an "
                          "X screen", flush=True)
                app_display, app_win = first.focused_window()
            s = pick(screens, focus)
            if s is not current:
                current = s
                print(f"display {s.name} {s.size[0]}x{s.size[1]}", flush=True)
            if now >= next_cursor:
                next_cursor = now + (HIDE_CHECK_S if hide else CURSOR_CHECK_S)
                shown = (s.hide_step() if hide else s.shown()) and not in_wayland
                new_area = s.window_area(app_win) if (app_win and app_display == s.name) else None
                if new_area != area:
                    area = new_area
                    print(f"window {s.name} 0x{app_win:x} at {area[0]},{area[1]} {area[2]}x{area[3]}" if area
                          else f"window none on {s.name}: the whole X screen", flush=True)
            left = bool(getattr(s, "buttons", 0) & BUTTON1_MASK)
            if left and not getattr(s, "left_down", False) and s.last is not None and now - last_click >= 1.0:
                last_click = now
                u, v = to_uv(s.last, s.size, area)
                # For a log to show where a click landed: the X screen, the pointer there, and where Pocket XR draws
                # it on the picture (u, v), at most once a second
                print(f"click at {s.last[0]},{s.last[1]} on {s.name} {s.size[0]}x{s.size[1]}: u {u}, v {v}", flush=True)
            s.left_down = left
            if s.last is not None:
                line = to_uv(s.last, s.size, area) + (int(shown),)
                if line != said:
                    said = line
                    out.write(f"pointer {line[0]} {line[1]} {line[2]}\n")
                    out.flush()
        time.sleep(POLL_S)


if __name__ == "__main__":
    sys.exit(main())
