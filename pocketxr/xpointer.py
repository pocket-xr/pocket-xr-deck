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

0.7.15 (the same tester, 25 Nov 2026: "a second unsynced arrow flickers into existence and out again as I move the
mouse", each time the pointer goes onto a link or button in a browser): a browser sets another cursor of its own (a hand
over a link) on its window each time, and gamescope drew it until the next look here blanked it, up to 1/30 s later. A
cursor an app loads from its theme carries the theme's name for it ("pointer", "text"), so the app's visible cursor is
now blanked by that name too (XFixesChangeCursorByName: every cursor of that name the app holds becomes an empty one,
so the next hover shows nothing), as well as on the window. Giving back loads each name from the cursor theme again
(XcursorLibraryLoadCursor) and puts it in their place. Names blanked are kept in a file until given back, so a reader
that ended without giving them back (stuck, killed) has the next one give them back. Written from Xorg's and
libXcursor's source; not yet tried on a Deck.

0.7.17 (the same tester's 0.7.16, 25 Nov 2026: with a second app open, gamescope's arrow stayed, "permanent and
follows my head"; and the flicker on links stayed): gamescope draws the arrow of the X screen that has its input
focus, which need not be the one the pointer is read from, so every X screen's cursor is blanked (hide_all), the root
window's when no window of the app's is under that screen's pointer; and a screen whose cursor changed is blanked the
moment it says so, before anything else is asked. A blank that does not take is said once ("hide <screen>'s cursor ...
still shown"). And 0.7.15's blanking by name and 0.7.16's cursor events never ran: _libs asked libXfixes for a
function it does not have and turned them off. Tried against two Xvfb screens (25 Nov 2026): 0.7.16 left both
cursors showing (the root's on one, an app's hand on the other) and showed the hand again on each of 40 hovers;
0.7.17 blanked both, showed it only the first time, and gave the hand back after "hide 0". Not yet tried on a Deck.

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
# 0.7.13: a look that takes longer than this is stuck (an X screen that stopped answering): the program prints where
# it was and ends, and gaming.py starts it again. A tester's 0.7.12 log (Pierre Zammit, 24 Nov 2026) has this reader
# say one line at start and then nothing for 17 minutes, never ending: no pointer of Pocket XR's own, gamescope's arrow
# never hidden, so the only arrow was gamescope's, off from where clicks land.
STUCK_S = 10.0
# 0.7.15: how long an X screen has to open. The same tester's 0.7.14 log (25 Nov 2026) has this reader stuck in
# XOpenDisplay every 10 s from the moment a game started: an X screen whose socket is there but whose server never
# answers. Each new reader tried it again and stuck again, so the pointer was never followed in the game ("the mouse
# started moving to follow" the head). 0.7.15 left such an open on a thread of its own, and his 0.7.15 log has the
# reader stuck all the same, now in the main thread's own X calls on the screen that did answer (XFixes, a bitmap):
# libX11 locks across the whole process, and the open that never ended held it. 0.7.16 asks each new screen over its
# socket first, without Xlib (Probe), and opens only one that answered, so nothing in Xlib ever waits on a silent one.
OPEN_WAIT_S = 2.0
PROBE_AGAIN_S = 15.0  # how soon a screen that did not answer is asked again
# 0.7.15: the cursor names blanked and not yet given back, one "<display> <name>" a line (see the module's docstring).
BLANKED = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "pocket-xr-deck",
                       "blanked-cursors")


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
        # 0.7.15: cursor names (XFixes 2). 0.7.17: libXfixes has no XFixesGetCursorImageAndName (the request's name
        # in the protocol; XFixesGetCursorImage already gives the name), so asking for it here failed and turned all
        # of this off: neither 0.7.15's blanking by name nor 0.7.16's cursor events ever ran (found against Xvfb, 25
        # Nov 2026, with the same tester's flicker unchanged in 0.7.16).
        try:
            xf.XFixesChangeCursorByName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p]
            xf.XFixesSetCursorName.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p]
            xf.XFixesSelectCursorInput.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
            xf.by_name = True
        except AttributeError:
            xf.by_name = False
    except OSError:
        xf = None
    global _XCURSOR
    try:
        _XCURSOR = ctypes.CDLL(ctypes.util.find_library("Xcursor") or "libXcursor.so.1")
        _XCURSOR.XcursorLibraryLoadCursor.restype = ctypes.c_ulong
        _XCURSOR.XcursorLibraryLoadCursor.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    except (OSError, AttributeError):
        _XCURSOR = None
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
    x11.XConnectionNumber.argtypes = [ctypes.c_void_p]
    x11.XPending.argtypes = [ctypes.c_void_p]
    x11.XNextEvent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
    x11.XSetErrorHandler.restype = ctypes.c_void_p
    x11.XSetErrorHandler.argtypes = [_ERROR_HANDLER]
    x11.XSetErrorHandler(_on_x_error)  # a window gone between looking it up and asking about it ends nothing
    return x11, xf


# 0.7.15: libXcursor, to give blanked cursor names back from the theme; None without it (nothing is blanked by name)
_XCURSOR = None


def blanked_names(path=None):
    """The (display, name) pairs blanked and not yet given back."""
    try:
        with open(path or BLANKED, encoding="utf-8") as f:
            return [tuple(x.split(" ", 1)) for x in f.read().splitlines() if " " in x]
    except OSError:
        return []


def note_blanked(display, names, path=None):
    """Keeps [display]'s blanked names (replacing what was kept for it); none removes it."""
    path = path or BLANKED
    rows = [r for r in blanked_names(path) if r[0] != display] + [(display, n) for n in sorted(names)]
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join(f"{d} {n}\n" for d, n in rows))
    except OSError:
        pass


class Probe:
    """0.7.16: whether an X server answers, asked without Xlib (see OPEN_WAIT_S): the X connection setup (12 bytes, no
    authorisation) sent over its socket, and any byte back counts, a refusal for want of authorisation included."""

    def __init__(self, name, now, root="/tmp/.X11-unix"):
        import socket
        import struct
        self.started, self.sock = now, None
        path = os.path.join(root, "X" + name[1:])
        for addr in ("\0" + path, path):  # Xwayland listens on both; the abstract one first
            try:
                sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            except (OSError, AttributeError):
                return
            try:
                sock.setblocking(False)
                sock.connect(addr)
                sock.send(b"l\0" + struct.pack("<HHHH", 11, 0, 0, 0) + b"\0\0")
                self.sock = sock
                return
            except OSError:
                sock.close()

    def poll(self, now, wait):
        """True once it answered, False when it has not in [wait] s (or could not be asked), None while waiting."""
        import select
        if self.sock is None:
            return False
        try:
            r, _, _ = select.select([self.sock], [], [], 0)
            if r:
                self.close()
                return True
        except (OSError, ValueError):
            self.close()
            return False
        if now - self.started >= wait:
            self.close()
            return False
        return None

    def close(self):
        if self.sock is not None:
            self.sock.close()
            self.sock = None


def open_screens(names, screens, probes, make, now, wait=OPEN_WAIT_S, again=PROBE_AGAIN_S, probe=Probe):
    """One round of opening. A name not yet open is first asked over its socket (Probe); only one that answered is
    opened with Xlib. One that does not answer in [wait] s is asked again [again] s later; nothing waits meanwhile.
    Returns (name, why) for each that would not open, or did not answer (once until it answers)."""
    said = []
    for name in names:
        if name in screens:
            continue
        st = probes.get(name)
        if st is None or (st.get("quiet_until") is not None and now >= st["quiet_until"]):
            st = probes[name] = {"probe": probe(name, now), "quiet_until": None, "said": (st or {}).get("said", False)}
        if st["probe"] is None:
            continue  # quiet until it is asked again
        answer = st["probe"].poll(now, wait)
        if answer is None:
            continue
        if answer is False:
            st["probe"], st["quiet_until"] = None, now + again
            if not st["said"]:
                st["said"] = True
                said.append((name, f"no answer in {wait:.0f} s: an X screen that is not answering; asked again every "
                                   f"{again:.0f} s, and the others are followed meanwhile"))
            continue
        del probes[name]
        try:
            screens[name] = make(name)
        except OSError as e:
            said.append((name, str(e)))
    return said


def pending(probes):
    """Whether a probe is waiting for its answer (the next round then comes sooner)."""
    return any(st.get("probe") is not None for st in probes.values())


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
    ours = serial in blank_serial if isinstance(blank_serial, (set, frozenset)) else serial == blank_serial
    if blank_serial is not None and ours:
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
        # 0.7.16: told the moment the cursor changes (XFixesDisplayCursorNotify), so a new one the app sets is blanked
        # at once rather than at the next look, up to 1/30 s later (see the module's docstring)
        self.fd, self.events = None, ctypes.create_string_buffer(192)
        if self.fixes and getattr(xf, "by_name", False):
            try:
                xf.XFixesSelectCursorInput(self.dpy, self.root, 1)
                x11.XFlush(self.dpy)
                self.fd = x11.XConnectionNumber(self.dpy)
            except (AttributeError, OSError):
                self.fd = None
        self.last = None
        self.moved_at = 0.0
        self.keymap = ctypes.create_string_buffer(32)
        self.down = set()
        self.atoms = {}
        # 0.7.15: names a reader before this one blanked here and never gave back
        left = [n for d, n in blanked_names() if d == name]
        if left:
            self.named = dict.fromkeys(left, 0)
            self.restore()

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
        named = getattr(self.xf, "by_name", False) and _XCURSOR is not None
        img = self.xf.XFixesGetCursorImage(self.dpy)
        if not img:
            return None
        try:
            raw = img.contents.name if named else None
            self.cursor_name = raw.decode(errors="replace") if raw else ""
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
        serials = getattr(self, "blank_serials", set())
        self.game_shown, blank_now = cursor_decision(serial, visible, serials or self.blank_serial, self.game_shown)
        if blank_now:
            name = getattr(self, "cursor_name", "")
            if name:
                self._blank_name(name)
            # 0.7.17: with no window of the app's under the pointer, the root window's cursor is the one shown (an X
            # screen whose app is not under its pointer, gamescope's focus on it all the same: see the module's
            # docstring), so that one is blanked
            win = self.under_pointer() or self.root
            if win:
                _ERRORS[0] = 0
                self.x11.XDefineCursor(self.dpy, win, self._blank())
                self.x11.XSync(self.dpy, 0)
                if not _ERRORS[0]:
                    self.blanked.add(win)
                    after = self.cursor()
                    if after and not after[1]:
                        self.blank_serial = after[0]
                        self.blank_serials = serials | {after[0]}
                    elif after:
                        # 0.7.17: said once a hide (see _main), so a log shows a cursor the blanking did not reach
                        self.not_taken = f"{self.name}'s cursor {getattr(self, 'cursor_name', '') or '(no name)'} " \
                                         f"still shown after blanking window 0x{win:x}"
        return self.game_shown

    def root_size(self):
        """0.7.17: the X screen's size now, (w, h), or None. gamescope sizes a game's Xwayland to the game after it
        opens; libX11's own size (XDisplayWidth) stays the one at the open. A tester's 0.7.16 log has ":1 1280x800"
        with the pointer at 1916,1065 on it."""
        a = self.window_area(self.root)
        return (a[2], a[3]) if a else None

    def changed(self):
        """0.7.16: whether the cursor changed since the last call (its events read and dropped)."""
        if getattr(self, "fd", None) is None:
            return False
        n = 0
        while self.x11.XPending(self.dpy):
            self.x11.XNextEvent(self.dpy, self.events)
            n += 1
        return n > 0

    def _blank_name(self, name):
        """0.7.15: every cursor the app holds by [name] made an empty one (see the module's docstring)."""
        if _XCURSOR is None or not getattr(self.xf, "by_name", False):
            return
        if not hasattr(self, "named"):
            self.named = {}
        blank = self.named.get(name)
        if not blank:
            bits = self.x11.XCreateBitmapFromData(self.dpy, self.root, b"\0", 1, 1)
            black = _XColor()
            blank = self.x11.XCreatePixmapCursor(self.dpy, bits, bits, ctypes.byref(black), ctypes.byref(black), 0, 0)
            # Named as the app's, so giving back finds it by that name
            self.xf.XFixesSetCursorName(self.dpy, blank, name.encode())
            self.named[name] = blank
            note_blanked(self.name, self.named)
        _ERRORS[0] = 0
        self.xf.XFixesChangeCursorByName(self.dpy, blank, name.encode())
        self.x11.XSync(self.dpy, 0)

    def restore(self):
        """Gives back the cursors blanked (the app's own come back when it sets them again; until then the screen's)."""
        for win in list(getattr(self, "blanked", ())):
            self.x11.XUndefineCursor(self.dpy, win)
        if getattr(self, "blanked", None):
            self.x11.XSync(self.dpy, 0)
            self.blanked.clear()
        self.blank_serial = None
        self.blank_serials = set()
        # 0.7.15: the names blanked, given back from the cursor theme
        names = getattr(self, "named", None)
        if names:
            if _XCURSOR is not None and getattr(self.xf, "by_name", False):
                for name in list(names):
                    cur = _XCURSOR.XcursorLibraryLoadCursor(self.dpy, name.encode())
                    if cur:
                        self.xf.XFixesSetCursorName(self.dpy, cur, name.encode())
                        self.xf.XFixesChangeCursorByName(self.dpy, cur, name.encode())
                self.x11.XSync(self.dpy, 0)
            names.clear()
            note_blanked(self.name, ())


def hide_all(screens, current):
    """0.7.17: one look on every X screen while gamescope's arrow is hidden; whether [current]'s app wants a cursor.
    gamescope draws the arrow of the X screen its input focus is on (steamcompmgr.cpp, determine_and_apply_focus:
    pFocus->cursor is the focused window's Xwayland's), which need not be the one the pointer is read from (the
    screen GAMESCOPE_MOUSE_FOCUS_DISPLAY names). 0.7.16 blanked only that one, and a tester (Pierre Zammit, 25 Nov
    2026) saw gamescope's arrow stay, "permanent and follows my head", with a second app open: his log has the pointer
    read from :0 and :1 in turn. So each X screen's cursor is blanked."""
    shown = True
    for q in screens.values():
        r = q.hide_step()
        if q is current:
            shown = r
    return shown


def blank_changed(screens, current):
    """0.7.17: blanks each X screen whose cursor changed since the last look (Screen.changed); whether [current]'s app
    wants a cursor when it was one of them, else None."""
    got = None
    for q in screens.values():
        if q.changed():
            r = q.hide_step()
            if q is current:
                got = r
    return got


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
        import faulthandler
        faulthandler.cancel_dump_traceback_later()
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
    probes = {}
    focus = None
    app_display, app_win, area = None, 0, None
    in_wayland, said_wayland = False, False
    said_not_taken = set()
    import faulthandler
    while True:
        # Each turn starts the watch again: only a turn stuck for STUCK_S prints its stack (to stdout, which
        # quietly() never redirects) and ends the program.
        faulthandler.dump_traceback_later(STUCK_S, exit=True, file=sys.stdout)
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
                    said_not_taken = set()
                    print("hide " + ("on: gamescope's own arrow is blanked on the app's window" if hide
                                     else "off: the app's cursors are given back"), flush=True)
        if now >= next_open:
            names = display_names()
            # 0.7.16: each asked over its socket first (see OPEN_WAIT_S)
            for name, why in open_screens(names, screens, probes, lambda n: Screen(x11, xf, n), now):
                if name not in unopened:  # libX11 says why on stderr each try: said here once
                    unopened.add(name)
                    print(f"unopened {name} ({why}); tried again quietly", flush=True)
            unopened.difference_update(screens)
            next_open = now + (0.1 if pending(probes) else 3.0)
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
                shown = (hide_all(screens, s) if hide else s.shown()) and not in_wayland
                for q in screens.values():
                    msg = getattr(q, "not_taken", None)
                    q.not_taken = None
                    if msg and msg not in said_not_taken:
                        said_not_taken.add(msg)
                        print("hide " + msg, flush=True)
                size = s.root_size()
                if size and size != s.size:
                    s.size = size
                    print(f"display {s.name} {s.size[0]}x{s.size[1]}", flush=True)
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
        # 0.7.16: while hiding, woken the moment a cursor changes on an X screen (never ran: see _libs).
        # 0.7.17: a screen whose cursor changed is blanked then, before anything else is asked: gamescope reads a
        # changed cursor's image when it next draws (MouseCursor::getTexture), so a blank set before then is all it
        # sees. The change may already be in Xlib's queue, read off the socket by this turn's other calls, where
        # select would not see it, so the queue is looked at first. Measured against Xvfb (25 Nov 2026): a new cursor
        # blanked after 0.2 ms (median; 0.7 ms at most), where 0.7.16 took 6.7 ms (median; 34 ms at most).
        if hide:
            r = blank_changed(screens, current)  # changes Xlib already read
            if r is not None:
                shown = r and not in_wayland
        watch = [q.fd for q in screens.values() if hide and getattr(q, "fd", None) is not None]
        if watch:
            import select
            try:
                select.select(watch, [], [], POLL_S)
            except (OSError, ValueError):
                time.sleep(POLL_S)
        else:
            time.sleep(POLL_S)
        if hide:
            r = blank_changed(screens, current)
            if r is not None:
                shown = r and not in_wayland


if __name__ == "__main__":
    sys.exit(main())
