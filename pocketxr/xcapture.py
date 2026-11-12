"""Pictures of the Deck's desktop and its app windows, from X11 (Desktop Mode is KDE on X11).

One thread owns its own X connection and does all X work: the window list, each window's picture
(XComposite gives a window's own picture even when other windows cover it), and the pointer.
The renderer takes the newest frames from it.

Two sources, as the app's "Show" setting:
  "deck"  the Deck's own screen, as one panel
  "apps"  each app window as its own panel, on its own larger screen

App windows get a larger screen the way Pocket XR on Android gives each app a virtual display: each one is moved
onto the glasses' own output (a real 1920x1080 X screen nobody looks at directly, since the app's view covers it) at
that full size. The app's view there is click-through, so the pointer, moved right past the Deck's screen, reaches
the app in front. Switching back to the Deck screen, quitting or unplugging puts every window back as it was.
"""
import ctypes
import ctypes.util
import os
import threading
import time

x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
xc = ctypes.CDLL(ctypes.util.find_library("Xcomposite") or "libXcomposite.so.1")
xf = ctypes.CDLL(ctypes.util.find_library("Xfixes") or "libXfixes.so.3")
xt = ctypes.CDLL(ctypes.util.find_library("Xtst") or "libXtst.so.6")
xt.XTestFakeKeyEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_int, ctypes.c_ulong]
xi = ctypes.CDLL(ctypes.util.find_library("Xi") or "libXi.so.6")


class XIEventMask(ctypes.Structure):
    _fields_ = [("deviceid", ctypes.c_int), ("mask_len", ctypes.c_int), ("mask", ctypes.POINTER(ctypes.c_ubyte))]


class XGenericEventCookie(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("extension", ctypes.c_int), ("evtype", ctypes.c_int),
                ("cookie", ctypes.c_uint), ("data", ctypes.c_void_p)]


class XIValuatorState(ctypes.Structure):
    _fields_ = [("mask_len", ctypes.c_int), ("mask", ctypes.POINTER(ctypes.c_ubyte)),
                ("values", ctypes.POINTER(ctypes.c_double))]


class XIRawEvent(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("extension", ctypes.c_int), ("evtype", ctypes.c_int),
                ("time", ctypes.c_ulong), ("deviceid", ctypes.c_int), ("sourceid", ctypes.c_int),
                ("detail", ctypes.c_int), ("flags", ctypes.c_int), ("valuators", XIValuatorState),
                ("raw_values", ctypes.POINTER(ctypes.c_double))]


class _AnyEvent(ctypes.Union):
    _fields_ = [("cookie", XGenericEventCookie), ("pad", ctypes.c_long * 24)]


xi.XIQueryVersion.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
xi.XISelectEvents.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(XIEventMask), ctypes.c_int]
XI_RAW_MOTION = 17
GENERIC_EVENT = 35
XI_ALL_MASTER_DEVICES = 1

Display = ctypes.c_void_p
Window = ctypes.c_ulong
Atom = ctypes.c_ulong
P = ctypes.POINTER


class XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int), ("y", ctypes.c_int), ("width", ctypes.c_int), ("height", ctypes.c_int),
        ("border_width", ctypes.c_int), ("depth", ctypes.c_int), ("visual", ctypes.c_void_p), ("root", Window),
        ("c_class", ctypes.c_int), ("bit_gravity", ctypes.c_int), ("win_gravity", ctypes.c_int),
        ("backing_store", ctypes.c_int), ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong), ("map_installed", ctypes.c_int),
        ("map_state", ctypes.c_int), ("all_event_masks", ctypes.c_long), ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long), ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p),
    ]


class XClientMessageEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int), ("display", Display),
        ("window", Window), ("message_type", Atom), ("format", ctypes.c_int), ("data", ctypes.c_long * 5),
    ]


class XEvent(ctypes.Union):
    _fields_ = [("xclient", XClientMessageEvent), ("pad", ctypes.c_long * 24)]


ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, Display, ctypes.c_void_p)

x11.XInitThreads.restype = ctypes.c_int
x11.XOpenDisplay.restype = Display
x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
x11.XDefaultRootWindow.restype = Window
x11.XDefaultRootWindow.argtypes = [Display]
x11.XInternAtom.restype = Atom
x11.XInternAtom.argtypes = [Display, ctypes.c_char_p, ctypes.c_int]
x11.XGetWindowProperty.argtypes = [Display, Window, Atom, ctypes.c_long, ctypes.c_long, ctypes.c_int, Atom, P(Atom),
                                   P(ctypes.c_int), P(ctypes.c_ulong), P(ctypes.c_ulong), P(ctypes.c_void_p)]
x11.XFree.argtypes = [ctypes.c_void_p]
x11.XQueryTree.argtypes = [Display, Window, P(Window), P(Window), P(ctypes.c_void_p), P(ctypes.c_uint)]
x11.XGetWindowAttributes.argtypes = [Display, Window, P(XWindowAttributes)]
x11.XTranslateCoordinates.argtypes = [Display, Window, Window, ctypes.c_int, ctypes.c_int, P(ctypes.c_int),
                                      P(ctypes.c_int), P(Window)]
x11.XGetImage.restype = ctypes.c_void_p
x11.XGetImage.argtypes = [Display, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                          ctypes.c_ulong, ctypes.c_int]
x11.XDestroyImage.argtypes = [ctypes.c_void_p]
x11.XFreePixmap.argtypes = [Display, ctypes.c_ulong]
x11.XQueryPointer.argtypes = [Display, Window, P(Window), P(Window), P(ctypes.c_int), P(ctypes.c_int),
                              P(ctypes.c_int), P(ctypes.c_int), P(ctypes.c_uint)]
x11.XWarpPointer.argtypes = [Display, Window, Window, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                             ctypes.c_int, ctypes.c_int]
x11.XFlush.argtypes = [Display]
x11.XSync.argtypes = [Display, ctypes.c_int]
x11.XSendEvent.argtypes = [Display, Window, ctypes.c_int, ctypes.c_long, P(XEvent)]
x11.XSetErrorHandler.restype = ctypes.c_void_p
x11.XSetErrorHandler.argtypes = [ERROR_HANDLER]
x11.XMoveWindow.argtypes = [Display, Window, ctypes.c_int, ctypes.c_int]
x11.XQueryExtension.argtypes = [Display, ctypes.c_char_p, P(ctypes.c_int), P(ctypes.c_int), P(ctypes.c_int)]
x11.XPending.argtypes = [Display]
x11.XNextEvent.argtypes = [Display, ctypes.c_void_p]
x11.XGetEventData.argtypes = [Display, ctypes.c_void_p]
x11.XFreeEventData.argtypes = [Display, ctypes.c_void_p]
xc.XCompositeNameWindowPixmap.restype = ctypes.c_ulong
xc.XCompositeNameWindowPixmap.argtypes = [Display, Window]
xc.XCompositeQueryExtension.argtypes = [Display, P(ctypes.c_int), P(ctypes.c_int)]
xc.XCompositeRedirectWindow.argtypes = [Display, Window, ctypes.c_int]
COMPOSITE_REDIRECT_AUTOMATIC = 0
xf.XFixesCreateRegion.restype = ctypes.c_ulong
xf.XFixesCreateRegion.argtypes = [Display, ctypes.c_void_p, ctypes.c_int]
xf.XFixesSetWindowShapeRegion.argtypes = [Display, Window, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
xf.XFixesDestroyRegion.argtypes = [Display, ctypes.c_ulong]
xf.XFixesHideCursor.argtypes = [Display, Window]
xf.XFixesShowCursor.argtypes = [Display, Window]
SHAPE_INPUT = 2
# The one spot of the view on the glasses that takes clicks: the space pointer parks the real pointer here whenever
# it is over Pocket XR's own things (title bars, handles, buttons, empty space), so those clicks come to the app.
CHROME_SPOT = (948, 528, 24, 24)  # the middle of a 1920x1080 output, away from its edges


class XRectangle(ctypes.Structure):
    _fields_ = [("x", ctypes.c_short), ("y", ctypes.c_short), ("width", ctypes.c_ushort), ("height", ctypes.c_ushort)]
VIEW_TITLE = "Pocket XR Deck"
# Each app's own screen: the glasses' output, at most this big (on Ultrawide's 3840 wide output, one 1920 wide screen).
APP_SCREEN = (1920, 1080)

ZPIXMAP = 2
ALL_PLANES = 0xFFFFFFFF
IS_VIEWABLE = 2
# A window this app or its panel shows is never captured.
OWN_TITLES = ("Pocket XR Deck", "Pocket XR")
SKIP_CLASSES = ("plasmashell", "krunner", "steamwebhelper-notification")


class Frame:
    """One picture: BGRA bytes, width, height, and a number that changes with each new picture."""
    __slots__ = ("data", "w", "h", "serial")

    def __init__(self, data, w, h, serial):
        self.data, self.w, self.h, self.serial = data, w, h, serial


class Panel:
    """A thing shown in space: the Deck's screen, or one app window."""

    def __init__(self, key, title):
        self.key = key  # "deck" or the X client window id
        self.title = title
        self.frame = None
        self.root_x = self.root_y = 0  # where its picture's top left is on the X screen
        self.w = self.h = 0
        self.pointer = None  # (x, y) in its picture, when the pointer is on it and nothing covers it there
        self.active = False
        self.frame_win = None  # KWin's frame around it, found with the list
        self.cls = ""  # the app's WM_CLASS class, to keep its place across runs
        self.first_seen = time.monotonic()


class XCapture(threading.Thread):
    def __init__(self, deck_rect, log=print):
        super().__init__(daemon=True)
        self.log = log
        self.deck_rect = deck_rect  # (x, y, w, h) of the Deck's own screen on the X screen
        self.glasses_rect = None  # (x, y, w, h) of the glasses' output, to keep the pointer and windows off it
        self.source = "deck"
        self.lock = threading.Lock()
        self.panels = []  # newest list, swapped whole under the lock
        self.stop = False
        self.requests = []  # ("activate", key) and the like, run on this thread
        self.fps_active = 30.0
        self.fps_other = 6.0
        self.errors = 0
        self.error_kinds = {}  # (request, minor, error code) -> count, for the log
        self._serial = 0
        self._panels = {}
        self._last_grab = {}
        self._moved = set()
        self._redirected = set()
        self._placed = {}  # client window -> (frame x, frame y, client w, client h, maximized) before it was moved
        self._stack = []  # client windows, bottom to top
        self._view_win = None  # the app's own view on the glasses, made click-through
        # The space pointer: while the real pointer is on the glasses' output its moves are summed into .motion and
        # it is put back on .warp_target (inside the app under the space pointer, or on the chrome spot).
        self.space_pointer = False
        self.warp_target = None
        self.motion = [0, 0]
        self._last_warp = None
        self.raise_wanted = None
        self.pointer_on_glasses = False
        self._raw_ok = False
        self._left_space = False
        self._cursor_hidden = False
        self.restored = True
        self._handler = ERROR_HANDLER(self._on_error)
        self.own_pid = os.getpid()
        self.panel_pid = None

    def _listen_raw(self):
        """XInput 2 raw motion: the trackpad's own movement, which no screen edge clips (the pointer's place would)."""
        op, ev, er = ctypes.c_int(), ctypes.c_int(), ctypes.c_int()
        if not x11.XQueryExtension(self.dpy, b"XInputExtension", ctypes.byref(op), ctypes.byref(ev), ctypes.byref(er)):
            self.log("capture: no XInput; the space pointer uses the pointer's place")
            return False
        major, minor = ctypes.c_int(2), ctypes.c_int(0)
        if xi.XIQueryVersion(self.dpy, ctypes.byref(major), ctypes.byref(minor)) != 0:
            return False
        self._xi_op = op.value
        bits = (ctypes.c_ubyte * 4)()
        bits[XI_RAW_MOTION >> 3] |= 1 << (XI_RAW_MOTION & 7)
        m = XIEventMask(XI_ALL_MASTER_DEVICES, 4, ctypes.cast(bits, ctypes.POINTER(ctypes.c_ubyte)))
        xi.XISelectEvents(self.dpy, self.root, ctypes.byref(m), 1)
        x11.XFlush(self.dpy)
        self._ev = _AnyEvent()
        return True

    def _raw_motion(self):
        """The motion summed from the raw events waiting: (dx, dy) in the pointer's own (accelerated) units."""
        dx = dy = 0.0
        while x11.XPending(self.dpy):
            x11.XNextEvent(self.dpy, ctypes.byref(self._ev))
            c = self._ev.cookie
            if c.type != GENERIC_EVENT or c.extension != self._xi_op:
                continue
            if not x11.XGetEventData(self.dpy, ctypes.byref(self._ev.cookie)):
                continue
            try:
                if c.evtype == XI_RAW_MOTION and self._ev.cookie.data:
                    r = XIRawEvent.from_address(self._ev.cookie.data)
                    vs = r.valuators
                    k = 0
                    for axis in range(min(2, vs.mask_len * 8)):
                        if vs.mask[axis >> 3] & (1 << (axis & 7)):
                            if axis == 0:
                                dx += vs.values[k]
                            else:
                                dy += vs.values[k]
                            k += 1
            finally:
                x11.XFreeEventData(self.dpy, ctypes.byref(self._ev.cookie))
        return dx, dy

    def leave_space(self):
        """Back to the Deck's screen on purpose (the space pointer pushed past the left edge of the view)."""
        with self.lock:
            self.requests.append(("leave", None))

    def install_handler(self):
        """Xlib has one error handler for the whole process, and SDL puts in its own "safety net" (which exits) each
        time its video starts. Called after every SDL video start and before each capture pass: a window closing
        between the list and its picture must cost one picture, not the app."""
        x11.XSetErrorHandler(self._handler)

    def _on_error(self, dpy, ev):
        # A window closing between the list and its picture is normal: note it and carry on (the default would exit).
        self.errors += 1
        try:
            # XErrorEvent: error_code at 32, request_code at 33, minor_code at 34.
            b = ctypes.string_at(ev, 35)
            k = (b[33], b[34], b[32])
            self.error_kinds[k] = self.error_kinds.get(k, 0) + 1
        except Exception:  # noqa: BLE001
            pass
        return 0

    # ---- for the app ----
    def snapshot(self):
        with self.lock:
            return list(self.panels)

    def activate(self, key):
        with self.lock:
            self.requests.append(("activate", key))

    def raise_window(self, key):
        """Put an app screen on top (no focus change), so the real pointer over it reaches it."""
        with self.lock:
            self.requests.append(("raise", key))

    def close_window(self, key):
        """Close an app window, as its own close button would (_NET_CLOSE_WINDOW)."""
        with self.lock:
            self.requests.append(("close", key))

    def key_to(self, key, combo):
        """Send a key combination ("alt+Left") to an app window: it is made active first."""
        with self.lock:
            self.requests.append(("key", (key, combo)))

    def resize_app(self, key, cw, ch):
        """Change an app's own screen size (its pixels), within the glasses' output."""
        with self.lock:
            self.requests.append(("resize", (key, cw, ch)))

    def restore_all(self):
        """Put every window back where it was (on quit). Sets .restored when done."""
        self.restored = not self._placed
        self.closing = True  # from now on nothing is moved onto the glasses again
        with self.lock:
            self.requests.append(("restore", None))

    def take_motion(self):
        with self.lock:
            m = self.motion
            self.motion = [0, 0]
        return m

    def chrome_spot(self):
        g = self.glasses_rect
        if not g:
            return None
        return (g[0] + min(CHROME_SPOT[0], g[2] - 24) + CHROME_SPOT[2] // 2,
                g[1] + min(CHROME_SPOT[1], g[3] - 24) + CHROME_SPOT[3] // 2)

    @property
    def virtual(self):
        """App windows on their own larger screens: the apps source with the glasses' output there."""
        return (self.source == "apps" and self.composite and self.glasses_rect is not None
                and not getattr(self, "closing", False))

    # ---- the thread ----
    def run(self):
        self.dpy = x11.XOpenDisplay(None)
        if not self.dpy:
            self.log("capture: no X display")
            return
        x11.XSetErrorHandler(self._handler)
        self.root = x11.XDefaultRootWindow(self.dpy)
        ev, er = ctypes.c_int(), ctypes.c_int()
        self.composite = bool(xc.XCompositeQueryExtension(self.dpy, ctypes.byref(ev), ctypes.byref(er)))
        if not self.composite:
            self.log("capture: no XComposite; app windows cannot be shown, only the Deck's screen")
        self._raw_ok = self._listen_raw()
        self.atoms = {n: x11.XInternAtom(self.dpy, n.encode(), 0) for n in (
            "_NET_CLIENT_LIST", "_NET_ACTIVE_WINDOW", "_NET_WM_NAME", "UTF8_STRING", "WM_NAME", "_NET_WM_PID",
            "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_NORMAL", "_NET_WM_WINDOW_TYPE_DIALOG", "_NET_WM_STATE",
            "_NET_WM_STATE_HIDDEN", "_NET_WM_STATE_SKIP_TASKBAR", "WM_CLASS", "_NET_CLIENT_LIST_STACKING",
            "_NET_MOVERESIZE_WINDOW", "_NET_RESTACK_WINDOW", "_NET_CLOSE_WINDOW", "_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ")}
        last_list = 0.0
        while not self.stop:
            now = time.monotonic()
            with self.lock:
                reqs, self.requests = self.requests, []
            for kind, key in reqs:
                if kind == "activate" and isinstance(key, int):
                    self._activate(key)
                elif kind == "raise" and isinstance(key, int):
                    self._client_message(key, "_NET_RESTACK_WINDOW", [2, 0, 0, 0, 0])  # from a pager, to the top
                    x11.XFlush(self.dpy)
                elif kind == "resize":
                    w, cw, ch = key
                    p = self._panels.get(w)
                    g = self.glasses_rect
                    if p is not None and g is not None:
                        fx, fy = self._origin(p.frame_win) if p.frame_win else (g[0], g[1])
                        self._move_resize(w, g[0], g[1], min(cw, g[2]), min(ch, g[3]))
                        x11.XFlush(self.dpy)
                elif kind == "close" and isinstance(key, int):
                    self._client_message(key, "_NET_CLOSE_WINDOW", [0, 2, 0, 0, 0])
                    x11.XFlush(self.dpy)
                elif kind == "key":
                    w, combo = key
                    self._activate(w)
                    x11.XSync(self.dpy, 0)
                    time.sleep(0.05)
                    self._send_keys(combo)
                elif kind == "leave":
                    dx, dy, dw, dh = self.deck_rect
                    x11.XWarpPointer(self.dpy, 0, self.root, 0, 0, 0, 0, dx + dw - 60, dy + dh // 2)
                    x11.XFlush(self.dpy)
                    self._last_warp = None
                    self._left_space = True
                elif kind == "restore":
                    self._restore_all()
                    self.restored = True
            self.install_handler()
            if now - last_list > 0.5:
                self._refresh_list()
                last_list = now
            self._pointer_and_frames(now)
            time.sleep(0.004)

    # ---- X helpers ----
    def _prop(self, w, atom, kind=0, length=1024):
        at, af, n, after, data = Atom(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        ok = x11.XGetWindowProperty(self.dpy, w, atom, 0, length, 0, kind, ctypes.byref(at), ctypes.byref(af),
                                    ctypes.byref(n), ctypes.byref(after), ctypes.byref(data))
        if ok != 0 or not data.value:
            return None, 0, 0
        return data, af.value, n.value

    def _longs(self, w, name):
        data, fmt, n = self._prop(w, self.atoms[name])
        if data is None:
            return []
        out = list((ctypes.c_ulong * n).from_address(data.value)) if fmt == 32 else []
        x11.XFree(data)
        return out

    def _text(self, w, name, kind=0):
        data, fmt, n = self._prop(w, self.atoms[name], kind)
        if data is None:
            return ""
        s = ctypes.string_at(data.value, n).decode("utf-8", "replace") if fmt == 8 else ""
        x11.XFree(data)
        return s

    def _title(self, w):
        return self._text(w, "_NET_WM_NAME", self.atoms["UTF8_STRING"]) or self._text(w, "WM_NAME")

    def _frame_of(self, w):
        """The window's top-level parent (KWin's frame), the one XComposite redirects."""
        root, parent = Window(), Window()
        children, n = ctypes.c_void_p(), ctypes.c_uint()
        cur = w
        for _ in range(8):
            if not x11.XQueryTree(self.dpy, cur, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(children), ctypes.byref(n)):
                return None
            if children.value:
                x11.XFree(children)
            if parent.value == root.value or parent.value == 0:
                return cur
            cur = parent.value
        return cur

    def _attrs(self, w):
        a = XWindowAttributes()
        if not x11.XGetWindowAttributes(self.dpy, w, ctypes.byref(a)):
            return None
        return a

    def _origin(self, w):
        x, y, child = ctypes.c_int(), ctypes.c_int(), Window()
        x11.XTranslateCoordinates(self.dpy, w, self.root, 0, 0, ctypes.byref(x), ctypes.byref(y), ctypes.byref(child))
        return x.value, y.value

    def _is_app(self, w):
        types = self._longs(w, "_NET_WM_WINDOW_TYPE")
        if types and not ({self.atoms["_NET_WM_WINDOW_TYPE_NORMAL"], self.atoms["_NET_WM_WINDOW_TYPE_DIALOG"]} & set(types)):
            return False
        state = set(self._longs(w, "_NET_WM_STATE"))
        if self.atoms["_NET_WM_STATE_HIDDEN"] in state or self.atoms["_NET_WM_STATE_SKIP_TASKBAR"] in state:
            return False
        pid = self._longs(w, "_NET_WM_PID")
        if pid and pid[0] in (self.own_pid, self.panel_pid):
            return False
        title = self._title(w)
        if title in OWN_TITLES:
            return False
        cls = self._text(w, "WM_CLASS").lower()
        if any(s in cls for s in SKIP_CLASSES):
            return False
        return True

    # ---- the list ----
    def _refresh_list(self):
        self._find_view()
        self._stack = self._longs(self.root, "_NET_CLIENT_LIST_STACKING")
        if not self.virtual and self._placed:
            self._restore_all()
        if self.source == "deck" or not self.composite:
            p = self._panels.get("deck") or Panel("deck", "Deck screen")
            p.root_x, p.root_y, p.w, p.h = self.deck_rect
            p.active = True
            self._panels = {"deck": p}
        else:
            active = (self._longs(self.root, "_NET_ACTIVE_WINDOW") or [0])[0]
            keep = {}
            for w in self._longs(self.root, "_NET_CLIENT_LIST"):
                if not self._is_app(w):
                    continue
                a = self._attrs(w)
                if a is None or a.map_state != IS_VIEWABLE or a.width < 32 or a.height < 32:
                    continue
                p = self._panels.get(w) or Panel(w, "")
                p.title = self._title(w)
                if not p.cls:
                    raw = self._text(w, "WM_CLASS")
                    p.cls = raw.split("\0")[1] if "\0" in raw and len(raw.split("\0")) > 1 else raw
                p.root_x, p.root_y = self._origin(w)
                p.w, p.h = a.width, a.height
                p.active = w == active
                fw = self._frame_of(w)
                if fw and fw not in self._redirected:
                    # With KWin's compositing off (as in the Deck's Desktop Mode), nothing keeps a window's own
                    # picture, so ask X for it: automatic redirection, which still shows the window as normal.
                    xc.XCompositeRedirectWindow(self.dpy, fw, COMPOSITE_REDIRECT_AUTOMATIC)
                    self._redirected.add(fw)
                p.frame_win = fw
                keep[w] = p
                if self.virtual:
                    self._place(w, p)
                else:
                    self._keep_off_glasses(w, p)
            if not keep:
                # No app windows open: show the Deck's screen rather than nothing.
                p = self._panels.get("deck") or Panel("deck", "Deck screen")
                p.root_x, p.root_y, p.w, p.h = self.deck_rect
                p.active = True
                keep = {"deck": p}
            self._panels = keep
        with self.lock:
            self.panels = list(self._panels.values())

    def _client_message(self, w, atom, data):
        ev = XEvent()
        ev.xclient.type = 33  # ClientMessage
        ev.xclient.window = w
        ev.xclient.message_type = self.atoms[atom]
        ev.xclient.format = 32
        for i, v in enumerate(data):
            ev.xclient.data[i] = v
        x11.XSendEvent(self.dpy, self.root, 0, (1 << 20) | (1 << 19), ctypes.byref(ev))

    def _maximize(self, w, on):
        self._client_message(w, "_NET_WM_STATE", [1 if on else 0, self.atoms["_NET_WM_STATE_MAXIMIZED_VERT"],
                                                  self.atoms["_NET_WM_STATE_MAXIMIZED_HORZ"], 2, 0])

    def _move_resize(self, w, x, y, cw, ch):
        """Frame's top left at (x, y), the client cw x ch: _NET_MOVERESIZE_WINDOW, as a pager asks it."""
        flags = 1 | (0xF << 8) | (2 << 12)  # north-west gravity, x y w h given, from a pager
        self._client_message(w, "_NET_MOVERESIZE_WINDOW", [flags, x, y, cw, ch])

    def _place(self, w, p):
        """Give the app its own larger screen: the glasses' output, at its full size (centred on a wider one)."""
        if w in self._placed:
            return
        g = self.glasses_rect
        fa = self._attrs(p.frame_win) if p.frame_win else None
        fx, fy = self._origin(p.frame_win) if p.frame_win else (p.root_x, p.root_y)
        deco_w = (fa.width - p.w) if fa else 0
        deco_h = (fa.height - p.h) if fa else 0
        state = set(self._longs(w, "_NET_WM_STATE"))
        was_max = self.atoms["_NET_WM_STATE_MAXIMIZED_VERT"] in state
        if g[0] <= fx + 10 < g[0] + g[2] and g[1] <= fy + 10 < g[1] + g[3]:
            # Already on the glasses' output (left there before): its home is the Deck's screen, at a size that fits.
            dx, dy, dw, dh = self.deck_rect
            cw, ch = min(p.w, dw - deco_w - 40), min(p.h, dh - deco_h - 40)
            self._placed[w] = (dx + (dw - cw - deco_w) // 2, dy + (dh - ch - deco_h) // 2, cw, ch, was_max)
        else:
            self._placed[w] = (fx, fy, p.w, p.h, was_max)
        sw, sh = min(APP_SCREEN[0], g[2]), min(APP_SCREEN[1], g[3])
        if was_max:
            self._maximize(w, False)
        self._move_resize(w, g[0] + (g[2] - sw) // 2, g[1] + (g[3] - sh) // 2, sw - deco_w, sh - deco_h)
        x11.XFlush(self.dpy)
        self.restored = False
        self.log(f"capture: '{p.title}' gets its own {sw}x{sh} screen")

    def _restore_all(self):
        for w, (fx, fy, cw, ch, was_max) in list(self._placed.items()):
            self._move_resize(w, fx, fy, cw, ch)
            if was_max:
                self._maximize(w, True)
            self._moved.add(w)  # back where the user had it: leave it there
        if self._placed:
            self.log(f"capture: {len(self._placed)} windows put back on the Deck's screen")
        self._placed = {}
        if self._cursor_hidden:
            xf.XFixesShowCursor(self.dpy, self.root)
            self._cursor_hidden = False
        x11.XFlush(self.dpy)

    def _send_keys(self, combo):
        x11.XStringToKeysym.restype = ctypes.c_ulong
        x11.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x11.XKeysymToKeycode.restype = ctypes.c_ubyte
        x11.XKeysymToKeycode.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        names = {"alt": "Alt_L", "ctrl": "Control_L", "shift": "Shift_L", "super": "Super_L"}
        codes = [x11.XKeysymToKeycode(self.dpy, x11.XStringToKeysym(names.get(k.lower(), k).encode()))
                 for k in combo.split("+")]
        for c in codes:
            xt.XTestFakeKeyEvent(self.dpy, c, 1, 0)
        for c in reversed(codes):
            xt.XTestFakeKeyEvent(self.dpy, c, 0, 0)
        x11.XFlush(self.dpy)

    def _find_view(self):
        """The app's own view on the glasses: clicks go through it to the app screens beneath."""
        for w in self._longs(self.root, "_NET_CLIENT_LIST"):
            pid = self._longs(w, "_NET_WM_PID")
            if pid and pid[0] == self.own_pid and self._title(w) == VIEW_TITLE:
                if w != self._view_win:
                    rect = XRectangle(*CHROME_SPOT)
                    region = xf.XFixesCreateRegion(self.dpy, ctypes.byref(rect), 1)
                    for win in {w, self._frame_of(w)}:
                        if win:
                            xf.XFixesSetWindowShapeRegion(self.dpy, win, SHAPE_INPUT, 0, 0, region)
                    xf.XFixesDestroyRegion(self.dpy, region)
                    x11.XFlush(self.dpy)
                    self._view_win = w
                    self.log("capture: the view on the glasses lets clicks through to the app screens, but for its chrome spot")
                return

    def _keep_off_glasses(self, w, p):
        """A window that opens on the glasses' output cannot be used there: move it onto the Deck's screen once."""
        g = self.glasses_rect
        if g is None or w in self._moved:
            return
        cx, cy = p.root_x + p.w // 2, p.root_y + p.h // 2
        if g[0] <= cx < g[0] + g[2] and g[1] <= cy < g[1] + g[3]:
            dx, dy, dw, dh = self.deck_rect
            x11.XMoveWindow(self.dpy, w, dx + max(0, (dw - p.w) // 2), dy + max(0, (dh - p.h) // 2))
            x11.XFlush(self.dpy)
            self._moved.add(w)
            self.log(f"capture: moved '{p.title}' from the glasses' output to the Deck's screen")

    def _activate(self, w):
        """Bring a window to the front on the Deck's screen (as a pager would), so touch and trackpad act on it."""
        ev = XEvent()
        ev.xclient.type = 33  # ClientMessage
        ev.xclient.window = w
        ev.xclient.message_type = self.atoms["_NET_ACTIVE_WINDOW"]
        ev.xclient.format = 32
        ev.xclient.data[0] = 2  # from a pager: the user asked for it
        ev.xclient.data[1] = 0
        x11.XSendEvent(self.dpy, self.root, 0, (1 << 20) | (1 << 19), ctypes.byref(ev))
        x11.XFlush(self.dpy)

    # ---- pointer and pictures ----
    def _pointer_and_frames(self, now):
        r, child = Window(), Window()
        rx, ry, wx, wy, mask = ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_int(), ctypes.c_uint()
        x11.XQueryPointer(self.dpy, self.root, ctypes.byref(r), ctypes.byref(child), ctypes.byref(rx), ctypes.byref(ry),
                          ctypes.byref(wx), ctypes.byref(wy), ctypes.byref(mask))
        px, py = rx.value, ry.value
        # The pointer stays on the Deck's screen, or with app screens also on the glasses' output where they are.
        dx, dy, dw, dh = self.deck_rect
        g = self.glasses_rect
        on_glasses = self.virtual and g[0] <= px < g[0] + g[2] and g[1] <= py < g[1] + g[3]
        raw = self._raw_motion() if self._raw_ok else (0.0, 0.0)
        if self._left_space and on_glasses:
            self._left_space = False
        # A small move off the glasses' output while the space pointer is on is still the space pointer (the real
        # pointer sat near the edge); only a jump (a touch on the Deck's screen) or leave_space() leaves it.
        if not on_glasses and self.space_pointer and self._last_warp is not None and not self._left_space and \
                abs(px - self._last_warp[0]) + abs(py - self._last_warp[1]) < 160:
            on_glasses = True
        if on_glasses and self.space_pointer:
            if self._last_warp is not None:
                with self.lock:
                    if self._raw_ok:
                        self.motion[0] += raw[0]
                        self.motion[1] += raw[1]
                    else:
                        self.motion[0] += px - self._last_warp[0]
                        self.motion[1] += py - self._last_warp[1]
            t = self.warp_target or self.chrome_spot()
            if t is not None and (t[0], t[1]) != (px, py):
                x11.XWarpPointer(self.dpy, 0, self.root, 0, 0, 0, 0, int(t[0]), int(t[1]))
                x11.XFlush(self.dpy)
                px, py = int(t[0]), int(t[1])
            self._last_warp = (px, py)
        else:
            self._last_warp = None
        if not on_glasses and not (dx <= px < dx + dw and dy <= py < dy + dh):
            px, py = min(max(px, dx), dx + dw - 1), min(max(py, dy), dy + dh - 1)
            x11.XWarpPointer(self.dpy, 0, self.root, 0, 0, 0, 0, px, py)
            x11.XFlush(self.dpy)
        self.pointer_root = (px, py)
        self.pointer_on_glasses = on_glasses
        # X draws its own arrow wherever the real pointer is, and on the glasses' output that shows in the glasses
        # beside the space pointer's ring: hidden while the space pointer is in use, back on the Deck's screen.
        hide = bool(on_glasses and self.space_pointer)
        if hide != self._cursor_hidden:
            (xf.XFixesHideCursor if hide else xf.XFixesShowCursor)(self.dpy, self.root)
            x11.XFlush(self.dpy)
            self._cursor_hidden = hide
        self.pointer_at_right_edge = not self.virtual and px >= dx + dw - 1
        # The window the pointer is over: the top one there in the stacking order (the view itself is above all of
        # them on the glasses' output, so asking X for the window under the pointer would answer the view).
        top = None
        for w in reversed(self._stack):
            p = self._panels.get(w)
            if p is not None and p.root_x <= px < p.root_x + p.w and p.root_y <= py < p.root_y + p.h:
                top = w
                break
        for key, p in list(self._panels.items()):
            if key == "deck":
                p.pointer = (px - p.root_x, py - p.root_y)
            else:
                p.pointer = (px - p.root_x, py - p.root_y) if key == top else None
            rate = self.fps_active if p.active else self.fps_other
            if now - self._last_grab.get(key, 0.0) >= 1.0 / rate:
                self._last_grab[key] = now
                f = self._grab(p)
                if f is not None:
                    p.frame = f

    def _grab(self, p):
        if p.key == "deck":
            img = x11.XGetImage(self.dpy, self.root, p.root_x, p.root_y, p.w, p.h, ALL_PLANES, ZPIXMAP)
            return self._take(img, p.w, p.h)
        frame = p.frame_win
        if frame is None:
            return None
        fa = self._attrs(frame)
        if fa is None or fa.map_state != IS_VIEWABLE:
            return None
        fx, fy = self._origin(frame)
        # The client's area inside the frame (no title bar, as Pocket XR shows windows), kept inside the frame's
        # picture: asking for anything outside it is a BadMatch.
        ox, oy = max(0, p.root_x - fx), max(0, p.root_y - fy)
        cw, ch = min(p.w, fa.width - ox), min(p.h, fa.height - oy)
        if cw < 8 or ch < 8:
            return None
        pix = xc.XCompositeNameWindowPixmap(self.dpy, frame)
        if not pix:
            return None
        try:
            img = x11.XGetImage(self.dpy, pix, ox, oy, cw, ch, ALL_PLANES, ZPIXMAP)
            return self._take(img, cw, ch)
        finally:
            x11.XFreePixmap(self.dpy, pix)

    def _take(self, img, w, h):
        if not img:
            return None
        try:
            # struct XImage: data at 16, bytes_per_line at 44, bits_per_pixel at 48.
            data = ctypes.c_void_p.from_address(img + 16).value
            bpl = ctypes.c_int.from_address(img + 44).value
            bpp = ctypes.c_int.from_address(img + 48).value
            if bpp != 32 or not data:
                return None
            if bpl == w * 4:
                raw = ctypes.string_at(data, bpl * h)
            else:
                raw = b"".join(ctypes.string_at(data + y * bpl, w * 4) for y in range(h))
        finally:
            x11.XDestroyImage(img)
        self._serial += 1
        return Frame(raw, w, h, self._serial)
