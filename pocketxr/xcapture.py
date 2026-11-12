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
xc.XCompositeNameWindowPixmap.restype = ctypes.c_ulong
xc.XCompositeNameWindowPixmap.argtypes = [Display, Window]
xc.XCompositeQueryExtension.argtypes = [Display, P(ctypes.c_int), P(ctypes.c_int)]
xc.XCompositeRedirectWindow.argtypes = [Display, Window, ctypes.c_int]
COMPOSITE_REDIRECT_AUTOMATIC = 0
xf.XFixesCreateRegion.restype = ctypes.c_ulong
xf.XFixesCreateRegion.argtypes = [Display, ctypes.c_void_p, ctypes.c_int]
xf.XFixesSetWindowShapeRegion.argtypes = [Display, Window, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_ulong]
xf.XFixesDestroyRegion.argtypes = [Display, ctypes.c_ulong]
SHAPE_INPUT = 2
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
        self.restored = True
        self._handler = ERROR_HANDLER(self._on_error)
        self.own_pid = os.getpid()
        self.panel_pid = None

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

    def restore_all(self):
        """Put every window back where it was (on quit). Sets .restored when done."""
        self.restored = not self._placed
        self.closing = True  # from now on nothing is moved onto the glasses again
        with self.lock:
            self.requests.append(("restore", None))

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
        self.atoms = {n: x11.XInternAtom(self.dpy, n.encode(), 0) for n in (
            "_NET_CLIENT_LIST", "_NET_ACTIVE_WINDOW", "_NET_WM_NAME", "UTF8_STRING", "WM_NAME", "_NET_WM_PID",
            "_NET_WM_WINDOW_TYPE", "_NET_WM_WINDOW_TYPE_NORMAL", "_NET_WM_WINDOW_TYPE_DIALOG", "_NET_WM_STATE",
            "_NET_WM_STATE_HIDDEN", "_NET_WM_STATE_SKIP_TASKBAR", "WM_CLASS", "_NET_CLIENT_LIST_STACKING",
            "_NET_MOVERESIZE_WINDOW", "_NET_WM_STATE_MAXIMIZED_VERT", "_NET_WM_STATE_MAXIMIZED_HORZ")}
        last_list = 0.0
        while not self.stop:
            now = time.monotonic()
            with self.lock:
                reqs, self.requests = self.requests, []
            for kind, key in reqs:
                if kind == "activate" and isinstance(key, int):
                    self._activate(key)
                elif kind == "restore":
                    self._restore_all()
                    self.restored = True
            self.install_handler()
            if now - last_list > 0.5:
                self._refresh_list()
                last_list = now
            self._pointer_and_frames(now)
            time.sleep(0.008)

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
        x11.XFlush(self.dpy)

    def _find_view(self):
        """The app's own view on the glasses: clicks go through it to the app screens beneath."""
        for w in self._longs(self.root, "_NET_CLIENT_LIST"):
            pid = self._longs(w, "_NET_WM_PID")
            if pid and pid[0] == self.own_pid and self._title(w) == VIEW_TITLE:
                if w != self._view_win:
                    region = xf.XFixesCreateRegion(self.dpy, None, 0)
                    for win in {w, self._frame_of(w)}:
                        if win:
                            xf.XFixesSetWindowShapeRegion(self.dpy, win, SHAPE_INPUT, 0, 0, region)
                    xf.XFixesDestroyRegion(self.dpy, region)
                    x11.XFlush(self.dpy)
                    self._view_win = w
                    self.log("capture: the view on the glasses lets clicks through to the app screens")
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
        if not on_glasses and not (dx <= px < dx + dw and dy <= py < dy + dh):
            px, py = min(max(px, dx), dx + dw - 1), min(max(py, dy), dy + dh - 1)
            x11.XWarpPointer(self.dpy, 0, self.root, 0, 0, 0, 0, px, py)
            x11.XFlush(self.dpy)
        self.pointer_root = (px, py)
        self.pointer_on_glasses = on_glasses
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
