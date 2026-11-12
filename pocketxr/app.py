"""Pocket XR for the Steam Deck: the app.

Finds the glasses, opens a fullscreen view on them, and shows the Deck's screen or its app windows
in space: held by the app's head tracking (3DoF), or by the glasses themselves (Steady mode in 6DoF).
Copes with the glasses being unplugged and plugged back in, and puts them back as they were on quit.
"""
import ctypes
import fcntl
import json
import math
import os
import queue
import signal
import subprocess
import sys
import threading
import time

from . import fusion, glasses as gmod, hidimu, imu
from .deckpad import DeckButtons
from .gl import (GL_BGRA, GL_BLEND, GL_CLAMP_TO_EDGE, GL_COLOR_BUFFER_BIT, GL_LINEAR, GL_LINE_LOOP, GL_MODELVIEW,
                 GL_ONE_MINUS_SRC_ALPHA, GL_PROJECTION, GL_QUADS, GL_RGBA, GL_SRC_ALPHA, GL_TEXTURE_2D,
                 GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T,
                 GL_TRIANGLE_FAN, GL_UNPACK_ALIGNMENT, GL_UNSIGNED_BYTE, KMOD_CTRL, SDL_GL_DOUBLEBUFFER,
                 SDL_INIT_VIDEO, SDL_KEYDOWN, SDL_QUIT, SDL_WINDOW_ALWAYS_ON_TOP, SDL_WINDOW_BORDERLESS,
                 SDL_WINDOW_FULLSCREEN_DESKTOP, SDL_WINDOW_OPENGL, SDL_WINDOW_SKIP_TASKBAR, displays, gl, sdl,
                 split_displays)
from .settingsctl import SettingsControl
from .spaceview import SpaceView
from .xcapture import XCapture

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "pocket-xr-deck")
STATE = os.path.join(os.environ.get("XDG_STATE_HOME", os.path.expanduser("~/.local/state")), "pocket-xr-deck")
ACCENT = (0x5A / 255, 0x93 / 255, 1.0)

DEFAULTS = {"view": "3dof", "source": "deck", "distance": 2.0, "scale": 1.0, "canvas_scale": 0.8, "look": True,
            "snap": False, "locked": False, "cursor_speed": 5, "curve_default": 0.0, "cursor_follows_head": True, "sbs_3d": True,
            "viture_tracking": None}

# 3DoF: a window 1600 px wide is this wide at 1.0, in metres (the Deck's screen 1.28 m, an app's 1920 px screen 1.92 m:
# about 50 degrees at 2 m, a little narrower than the glasses' own view).
WINDOW_M_PER_1600 = 1.6
GAP_DEG = 3.0
GONE_GRACE_S = 12.0
DEV = os.environ.get("POCKETXR_DEV") == "1"
LOOK_DWELL_S = 0.6
FOV_V_DEG = 38.0  # the Aura's picture, vertical, per eye (about 70 degrees diagonal)


class Log:
    def __init__(self):
        os.makedirs(STATE, exist_ok=True)
        path = os.path.join(STATE, "pocket-xr.log")
        if os.path.exists(path):
            os.replace(path, path + ".1")
        self.f = open(path, "a", buffering=1)

    def __call__(self, msg):
        line = time.strftime("%H:%M:%S ") + msg
        print(line, flush=True)
        self.f.write(line + "\n")


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(os.path.join(CONFIG, "settings.json")) as f:
            s.update({k: v for k, v in json.load(f).items() if k in DEFAULTS})
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    os.makedirs(CONFIG, exist_ok=True)
    tmp = os.path.join(CONFIG, "settings.json.tmp")
    with open(tmp, "w") as f:
        json.dump(s, f, indent=1)
    os.replace(tmp, os.path.join(CONFIG, "settings.json"))


def single_instance():
    os.makedirs(STATE, exist_ok=True)
    fd = os.open(os.path.join(STATE, "running.lock"), os.O_CREAT | os.O_RDWR)
    try:
        fcntl.lockf(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        return None
    return fd


def notify(text):
    try:
        subprocess.Popen(["notify-send", "-a", "Pocket XR", "-i", "pocket-xr", "Pocket XR", text])
    except OSError:
        pass


class App:
    def __init__(self):
        self.log = Log()
        self.settings = load_settings()
        self.space_path = os.path.join(CONFIG, "space.json")
        self.space = SpaceView(self)
        self.events = queue.Queue()
        self.glasses = None
        self.window = None
        self.ctx = None
        self.textures = {}
        self.head = None
        self.reader = None
        self.control = None
        self.control_state = {}
        self.message = ""
        self.quitting = False
        self.done = False
        self.fps = 0.0
        self.win_size = (0, 0)
        self.win_display = None
        self.look_target = None
        self.look_since = 0.0
        self.edge_since = None
        self.last_layout = []
        self.missing_since = None  # when the glasses stopped showing on USB
        self.known_seen = 0.0  # when known glasses were last seen, so a re-plug is not taken for unknown glasses

    # ---------- start ----------
    def run(self):
        lock = single_instance()
        if lock is None:
            notify("Pocket XR is already running.")
            return 0
        self.log(f"Pocket XR for Steam Deck starting, settings {self.settings}")
        sdl.SDL_SetHint(b"SDL_VIDEO_MINIMIZE_ON_FOCUS_LOSS", b"0")
        # Only a real close quits: a closing terminal or SSH session must not take the view down.
        sdl.SDL_SetHint(b"SDL_NO_SIGNAL_HANDLERS", b"1")
        # Xlib from several threads (SDL here, the capture thread): must come before any other Xlib call.
        from .xcapture import x11
        x11.XInitThreads()
        if sdl.SDL_Init(SDL_INIT_VIDEO) != 0:
            self.log("SDL_Init failed: " + sdl.SDL_GetError().decode())
            return 1
        _, deck = split_displays(displays())
        deck_rect = (deck[2], deck[3], deck[4], deck[5]) if deck else (0, 0, 1280, 800)
        self.capture = XCapture(deck_rect, log=self.log)
        self.capture.source = self.settings["source"]
        self.capture.install_handler()
        self.capture.start()
        DeckButtons(lambda n, k: self.events.put(("button", n, k)), log=self.log).start()
        self.panel = self._start_panel()
        self.capture.panel_pid = self.panel.pid if self.panel else None
        # Asked to stop (log out, shut down, systemctl): put the glasses back first, as with Quit.
        for sig in (signal.SIGTERM, signal.SIGINT, signal.SIGHUP):
            signal.signal(sig, lambda n, f: self.request_quit(f"signal {n}"))
        try:
            self._loop()
            # Windows back on the Deck's screen before the view goes (the capture thread does it).
            end = time.monotonic() + 3.0
            while not self.capture.restored and time.monotonic() < end:
                time.sleep(0.05)
        finally:
            self._close_window()
            if self.reader:
                self.reader.stop = True
            if self.control:
                self.control.close()
            if self.panel and self.panel.poll() is None:
                try:
                    self.panel.stdin.close()
                except OSError:
                    pass
            sdl.SDL_Quit()
            self.log("bye")
        return 0

    def _start_panel(self):
        try:
            p = subprocess.Popen([sys.executable, "-m", "pocketxr.panel", os.path.join(HERE, "..", "assets", "pocket-xr.png")],
                                 cwd=os.path.join(HERE, ".."), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
        except OSError as e:
            self.log(f"panel: could not start ({e})")
            return None

        def read():
            for line in p.stdout:
                try:
                    m = json.loads(line)
                    self.events.put(("panel", m.get("cmd"), m.get("value")))
                except ValueError:
                    pass
            self.events.put(("panel", "closed", None))
        threading.Thread(target=read, daemon=True).start()
        return p

    # ---------- the loop ----------
    def _loop(self):
        last_check = 0.0
        last_status = 0.0
        frames, t_fps = 0, time.monotonic()
        last_health = time.monotonic()
        while not self.done:
            now = time.monotonic()
            self._handle_events()
            if now - last_check > 1.0:
                last_check = now
                self._check_glasses()
            if self.window:
                try:
                    self._draw(now)
                except Exception:  # noqa: BLE001
                    # A drawing mistake must cost a frame, not the app (and the glasses' settings with it).
                    import traceback
                    tb = traceback.format_exc()
                    if tb != getattr(self, "_last_tb", None):
                        self._last_tb = tb
                        self.log("draw failed, carrying on: " + tb)
                frames += 1
            else:
                self._pump()
                time.sleep(0.05)
            if now - t_fps >= 2.0:
                self.fps = frames / (now - t_fps)
                frames, t_fps = 0, now
            if now - last_health >= 30.0:
                last_health = now
                self._health()
            if now - last_status > 0.5:
                last_status = now
                self._send_status()
                if DEV:
                    self._dev_commands()

    def _dev_commands(self):
        """POCKETXR_DEV=1 only: panel commands from a file, one JSON per line, for testing without the Deck's hands."""
        path = os.path.join(STATE, "dev-cmd")
        try:
            with open(path) as f:
                lines = f.read().splitlines()
            os.remove(path)
        except OSError:
            return
        for line in lines:
            try:
                m = json.loads(line)
                self._panel_cmd(m.get("cmd"), m.get("value"))
            except (ValueError, AttributeError):
                pass

    def _health(self):
        h = self.head
        imu_n = h.count if h else 0
        rate = max(0, imu_n - getattr(self, "_last_imu", 0)) / 30.0
        self._last_imu = imu_n
        bias = ", ".join(f"{math.degrees(b):.2f}" for b in h.bias) if h else "-"
        panels = self.capture.snapshot()
        self.log(f"health: {self.fps:.0f} fps, imu {rate:.0f}/s, gyro zero {bias} deg/s ({h.rest_blocks if h else 0} rests), "
                 f"{self._view()}, {self.settings['source']} ({len(panels)} panels), x errors {self.capture.errors} {self.capture.error_kinds}")

    def _pump(self):
        ev = (ctypes.c_ubyte * 64)()
        while sdl.SDL_PollEvent(ctypes.byref(ev)):
            etype = int.from_bytes(bytes(ev[0:4]), "little")
            if etype == SDL_QUIT:
                self.request_quit("window closed")
            elif etype == SDL_KEYDOWN:
                sym = int.from_bytes(bytes(ev[20:24]), "little")
                mod = int.from_bytes(bytes(ev[24:26]), "little")
                if sym == ord("q") and mod & KMOD_CTRL:
                    self.request_quit("Ctrl+Q")
            elif etype in (0x401, 0x402) and not self.capture.space_pointer:
                self.log(f"view: a click came while the space pointer is off")
            elif etype in (0x401, 0x402) and self.capture.space_pointer:  # mouse button down / up
                self.space.mouse(ev[16], etype == 0x401, time.monotonic())
            elif etype == 0x403 and self.capture.space_pointer:  # wheel
                dy = int.from_bytes(bytes(ev[20:24]), "little", signed=True)
                if dy:
                    self.space.wheel(dy)

    # ---------- glasses come and go ----------
    def _viture_on(self):
        v = self.settings.get("viture_tracking")
        return self.glasses.viture_tracking_default() if v is None else bool(v)

    def _start_tracking(self):
        g = self.glasses
        if self.reader:
            self.reader.stop = True
            self.reader = None
        self.head = fusion.HeadFusion(g.axes)
        kind = g.imu
        if kind == "network":
            self.reader = imu.ImuReader(self.head.report, log=self.log)
        elif kind == "air":
            self.reader = hidimu.AirReader(self.head.report, g.product, log=self.log)
        elif kind == "viture" and self._viture_on():
            self.reader = hidimu.VitureReader(self.head.report, g.product, log=self.log)
        if self.reader:
            self.reader.start()
        self.message = g.why_no_tracking(self._viture_on() if g.family == "viture" else None) or ""

    def _tracking(self):
        return self.reader is not None

    def _check_glasses(self):
        g = gmod.detect()
        now = time.monotonic()
        if g is not None and g.family != "other":
            self.known_seen = now
            self.missing_since = None
        elif self.glasses is not None and self.glasses.family != "other":
            # The Aura drops off USB for a few seconds when its glasses service restarts or a mode re-plugs it.
            # Keep everything for GONE_GRACE_S, so the link and the view come straight back.
            if self.missing_since is None:
                self.missing_since = now
                self.log(f"glasses not on USB; waiting up to {GONE_GRACE_S:.0f} s for them to come back")
            if now - self.missing_since < GONE_GRACE_S:
                g = self.glasses
        if g is None and now - self.known_seen < GONE_GRACE_S + 5:
            pass  # known glasses only just left: not "other glasses"
        elif g is None:
            # Glasses Pocket XR does not know: a second display is enough to show the windows flat.
            if self.glasses is not None and self.glasses.family == "other" and self.window is not None:
                g = self.glasses
            elif self.window is None:
                gd, _ = split_displays(displays())
                if gd is not None:
                    g = gmod.other_glasses()
                    if "xreal" in gd[1].lower() or "ultra" in gd[1].lower():
                        # The Aura's picture without its USB side: its glasses service has stopped (seen on the
                        # phone too); a replug brings it back.
                        g = gmod.Glasses("XREAL glasses, no USB link", "other", 0, 0)
                        self.usb_down_hint = True
        if g != self.glasses:
            if self.glasses is not None:
                self.log(f"glasses gone: {self.glasses.name}")
                self._close_window()
                if self.reader:
                    self.reader.stop = True
                    self.reader = None
                if self.control:
                    self.control.close()
                    self.control = None
                self.control_state = {}
            self.glasses = g
            if g is not None:
                self.log(f"glasses: {g.name} ({g.family}, {g.vendor:04x}:{g.product:04x}{', XREAL Eye' if g.eye else ''})")
                self._start_tracking()
                if getattr(self, "usb_down_hint", False) and g.family == "other":
                    self.usb_down_hint = False
                    self.message = ("Your XREAL glasses show a picture but their USB link is down, so there is no head "
                                    "tracking. Unplug them and plug them back in.")
                    notify(self.message)
                if g.control_link:
                    self.control = SettingsControl(g, self.log, self._on_control_state, self._on_message)
                    self.control.want_3d = lambda: bool(self.settings.get("sbs_3d", True))
                    self.control.start()
                    self.control.want(self._view())
            else:
                self.message = "Plug your glasses into the Deck's USB-C port."
        if self.glasses is None:
            return
        # The glasses' display: open the view on it, or open it again when its size changes (Ultrawide, 3D).
        if self.window is None:
            sdl.SDL_QuitSubSystem(SDL_INIT_VIDEO)
            sdl.SDL_InitSubSystem(SDL_INIT_VIDEO)
            self.capture.install_handler()
            self._open_window()
            self.capture.install_handler()
        else:
            gd, deck = split_displays(displays())
            if gd is None or (gd[4], gd[5]) != self.win_size:
                self.log(f"glasses' display changed to {gd[4] if gd else 0}x{gd[5] if gd else 0}; opening the view again")
                self._close_window()
            elif deck:
                self.capture.deck_rect = (deck[2], deck[3], deck[4], deck[5])
                self.capture.glasses_rect = (gd[2], gd[3], gd[4], gd[5])

    def _open_window(self):
        gd, deck = split_displays(displays())
        if gd is None:
            return
        di, name, x, y, w, h = gd
        if deck:
            self.capture.deck_rect = (deck[2], deck[3], deck[4], deck[5])
        self.capture.glasses_rect = (x, y, w, h)
        sdl.SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1)
        pos = 0x2FFF0000 | di
        win = sdl.SDL_CreateWindow(b"Pocket XR Deck", pos, pos, w, h,
                                   SDL_WINDOW_OPENGL | SDL_WINDOW_BORDERLESS | SDL_WINDOW_FULLSCREEN_DESKTOP |
                                   SDL_WINDOW_ALWAYS_ON_TOP | SDL_WINDOW_SKIP_TASKBAR)
        if not win:
            self.log("view: window failed: " + sdl.SDL_GetError().decode())
            return
        ctx = sdl.SDL_GL_CreateContext(win)
        if not ctx:
            self.log("view: GL failed: " + sdl.SDL_GetError().decode())
            sdl.SDL_DestroyWindow(win)
            return
        sdl.SDL_GL_SetSwapInterval(1)
        sdl.SDL_ShowCursor(0)
        gl.glPixelStorei(GL_UNPACK_ALIGNMENT, 4)
        self.window, self.ctx = win, ctx
        self.win_size = (w, h)
        self.textures = {}
        self.log(f"view: open on '{name}' {w}x{h}")

    def _close_window(self):
        self.space.forget_textures()
        if self.window:
            for tex, *_ in self.textures.values():
                t = ctypes.c_uint(tex)
                gl.glDeleteTextures(1, ctypes.byref(t))
            self.textures = {}
            sdl.SDL_GL_DeleteContext(self.ctx)
            sdl.SDL_DestroyWindow(self.window)
            self.window = self.ctx = None
            self.win_size = (0, 0)
            self.log("view: closed")

    # ---------- what the user asks ----------
    def _view(self):
        v = self.settings["view"]
        if v == "steady" and not (self.glasses and self.glasses.steady_6dof):
            return "3dof"
        return v

    def _handle_events(self):
        while True:
            try:
                ev = self.events.get_nowait()
            except queue.Empty:
                return
            kind, a, b = ev
            if kind == "button":
                self._button(a, b)
            elif kind == "panel":
                self._panel_cmd(a, b)

    def _button(self, name, how):
        self.log(f"button {name} {how}")
        if name == "L4" and how == "tap":
            self.recentre()
        elif name == "L4" and how == "hold":
            self.set_view("3dof" if self._view() == "steady" else "steady")
        elif name == "R4" and how == "tap":
            self.next_app()
        elif name == "R4" and how == "hold":
            self.set_source("apps" if self.settings["source"] == "deck" else "deck")
        elif name == "L5" and how == "tap":
            self.space.toggle_launcher()
        elif name == "R5" and how == "tap":
            self.space.toggle_cc(time.monotonic())
        elif name == "L5" and how == "hold":
            self.set_setting("locked", not self.settings.get("locked", False))
            self.message = "Screens are locked." if self.settings["locked"] else "Screens are unlocked."
        elif name == "R5" and how == "hold":
            self.space.start_adjust_all()

    def _panel_cmd(self, cmd, value):
        if cmd == "view":
            self.set_view(value)
        elif cmd == "source":
            self.set_source(value)
        elif cmd == "recentre":
            self.recentre()
        elif cmd == "size":
            if self._flat():
                self.resize(int(value))
            else:
                self.space.scale_all_or_focused(int(value))
        elif cmd == "distance":
            key = self.space.focus if self.space.focus in self.space.poses else next(iter(self.space.poses), None)
            if key is not None and not self.settings.get("locked", False):
                self.space.depth(key, 2 * int(value))
                self.space.save_places()
        elif cmd == "launcher":
            self.space.toggle_launcher()
        elif cmd == "cc":
            self.space.toggle_cc(time.monotonic())
        elif cmd in ("snap", "locked", "cursor_follows_head", "sbs_3d"):
            self.set_setting(cmd, bool(value))
        elif cmd == "look":
            self.settings["look"] = bool(value)
            save_settings(self.settings)
        elif cmd == "viture":
            self.settings["viture_tracking"] = bool(value)
            save_settings(self.settings)
            if self.glasses and self.glasses.family == "viture":
                self._start_tracking()
        elif cmd == "quit":
            self.request_quit("panel")
        elif cmd == "closed":
            # The panel was closed some other way: start a new one, the app keeps going.
            if not self.quitting:
                self.panel = self._start_panel()
                self.capture.panel_pid = self.panel.pid if self.panel else None

    def set_view(self, view):
        if view == "steady" and not (self.glasses and self.glasses.steady_6dof):
            self.message = (self.glasses.why_no_6dof() if self.glasses else "Plug your glasses in first.")
            return
        self.settings["view"] = view
        save_settings(self.settings)
        self.message = ""
        if self.control:
            self.control.want(view)
        if self.head:
            self.head.recentre()

    def set_setting(self, key, value):
        self.settings[key] = value
        save_settings(self.settings)
        if key == "sbs_3d" and self.control:
            self.control.want(self._view())
        if key == "locked" and value:
            # Anything being moved or resized is dropped where it is.
            self.space.drag = None
            self.space.resize = None
            self.space.adjust_all = None

    def set_source(self, source):
        self.settings["source"] = source
        self.capture.source = source
        save_settings(self.settings)

    def recentre(self):
        if self.head:
            self.head.recentre()
        if self._flat() and self.control:
            self.control.recentre()

    def resize(self, step):
        if self._flat():
            self.settings["canvas_scale"] = min(1.0, max(0.3, self.settings["canvas_scale"] + 0.05 * step))
        else:
            self.settings["scale"] = min(2.5, max(0.4, self.settings["scale"] * (1.1 if step > 0 else 1 / 1.1)))
        save_settings(self.settings)

    def next_app(self):
        panels = sorted(self.capture.snapshot(), key=lambda p: p.first_seen)
        apps = [p for p in panels if p.key != "deck"]
        if not apps:
            return
        i = next((k for k, p in enumerate(apps) if p.active), -1)
        self.capture.activate(apps[(i + 1) % len(apps)].key)

    def request_quit(self, why):
        if self.quitting:
            return
        self.quitting = True
        self.log(f"quit: {why}")
        self.message = "Putting your glasses back..."
        self._send_status()
        self.space.save_places()
        self.capture.restore_all()
        if self.control and self.control.link and not self.control.link.closed:
            self.control.restore(lambda: setattr(self, "done", True))
            t = threading.Timer(20.0, lambda: setattr(self, "done", True))
            t.daemon = True
            t.start()
        else:
            self.done = True

    def _on_control_state(self, st):
        self.control_state = st

    def _on_message(self, text):
        self.message = text
        if "menu" in text:
            notify(text)

    # ---------- status for the panel ----------
    def _send_status(self):
        if not self.panel or self.panel.poll() is not None:
            return
        g = self.glasses
        hint = ""
        if self.capture.virtual and self.window:
            hint = "Move the pointer off the right of the Deck's screen to use the Space."
        if g is None:
            status = "No glasses found."
        else:
            parts = [g.name]
            if self.reader:
                parts.append("head tracking " + ("on" if self.reader.connected_to else "starting"))
            if self.window:
                parts.append(f"{self.win_size[0]}x{self.win_size[1]}, {self.fps:.0f} fps")
            else:
                parts.append("waiting for its display")
            cs = self.control_state
            if cs.get("link"):
                bits = []
                if cs.get("ultrawide") == 1:
                    bits.append("Ultrawide")
                elif cs.get("stereo") == 1:
                    bits.append("3D")
                if cs.get("anchor") == 1:
                    bits.append("Spatial Anchor on")
                if cs.get("busy"):
                    bits.append("changing settings...")
                if bits:
                    parts.append(", ".join(bits))
            status = " · ".join(parts)
        st = {
            "status": status,
            "message": self.message or hint,
            "view": self._view(),
            "source": self.settings["source"],
            "look": self.settings["look"],
            "snap": self.settings.get("snap", False),
            "locked": self.settings.get("locked", False),
            "cursor_follows_head": self.settings.get("cursor_follows_head", True),
            "sbs_3d": self.settings.get("sbs_3d", True),
            "sbs_ok": bool(g and g.control_link),
            "steady_ok": bool(g and g.steady_6dof),
            "flat": self._flat(),
            "viture": bool(g and g.family == "viture"),
            "viture_on": bool(g and g.family == "viture" and self._viture_on()),
            "viture_label": ("VITURE head tracking" if g and g.beast else "Experimental VITURE head tracking"),
        }
        try:
            self.panel.stdin.write(json.dumps(st) + "\n")
            self.panel.stdin.flush()
        except (OSError, ValueError):
            pass

    # ---------- drawing ----------
    def _flat(self):
        """Drawn flat with no head tracking from the app: Steady mode (the glasses hold it), or no tracking known."""
        if self.glasses is None:
            return False
        if self._view() == "steady" or not self._tracking():
            return True
        # Glasses left in Ultrawide by their own menu: a wide canvas, not two eyes.
        return self.control_state.get("ultrawide") == 1

    def _texture(self, p):
        f = p.frame
        if f is None:
            return None
        t = self.textures.get(p.key)
        if t is None or t[1] != f.w or t[2] != f.h:
            if t is not None:
                old = ctypes.c_uint(t[0])
                gl.glDeleteTextures(1, ctypes.byref(old))
            tex = ctypes.c_uint(0)
            gl.glGenTextures(1, ctypes.byref(tex))
            gl.glBindTexture(GL_TEXTURE_2D, tex)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
            gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, f.w, f.h, 0, GL_BGRA, GL_UNSIGNED_BYTE, f.data)
            t = (tex.value, f.w, f.h, f.serial)
            self.textures[p.key] = t
        elif t[3] != f.serial:
            gl.glBindTexture(GL_TEXTURE_2D, t[0])
            gl.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, f.w, f.h, GL_BGRA, GL_UNSIGNED_BYTE, f.data)
            t = (t[0], t[1], t[2], f.serial)
            self.textures[p.key] = t
        return t[0]

    def _layout_arc(self, panels):
        """3DoF: panels side by side on a circle around the head, the group centred in front."""
        d = self.settings["distance"]
        s = self.settings["scale"]
        items = []
        for p in panels:
            f = p.frame
            if f is None:
                continue
            wm = WINDOW_M_PER_1600 * s * f.w / 1600.0
            hm = wm * f.h / f.w
            ang = math.degrees(2 * math.atan(wm / 2 / d))
            items.append([p, wm, hm, ang, 0.0])
        total = sum(i[3] for i in items) + GAP_DEG * max(0, len(items) - 1)
        a = total / 2
        for it in items:
            it[4] = a - it[3] / 2  # yaw of its centre, degrees, left positive
            a -= it[3] + GAP_DEG
        return items

    def _draw(self, now):
        self._pump()
        if not self.window:
            return
        w = ctypes.c_int()
        h = ctypes.c_int()
        sdl.SDL_GL_GetDrawableSize(self.window, ctypes.byref(w), ctypes.byref(h))
        w, h = w.value, h.value
        flat = self._flat()
        panels = sorted(self.capture.snapshot(), key=lambda p: p.first_seen)
        for p in panels:
            self._texture(p)

        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(GL_COLOR_BUFFER_BIT)
        if flat:
            self._draw_flat(panels, w, h)
        else:
            self._draw_space(panels, w, h, now)
        sdl.SDL_GL_SwapWindow(self.window)

    def _draw_flat(self, panels, w, h):
        """Steady mode: panels side by side across the glasses' canvas, drawn flat; the glasses hold the canvas."""
        gl.glViewport(0, 0, w, h)
        gl.glMatrixMode(GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glMatrixMode(GL_MODELVIEW)
        gl.glLoadIdentity()
        shown = [p for p in panels if p.frame is not None]
        if not shown:
            return
        gap_px = 40
        total_w = sum(p.frame.w for p in shown) + gap_px * (len(shown) - 1)
        max_h = max(p.frame.h for p in shown)
        k = min(self.settings["canvas_scale"] * h / max_h, 0.96 * w / total_w)  # canvas pixels per window pixel
        x = -total_w * k / w  # left edge, -1..1 units
        for p in shown:
            pw = 2 * p.frame.w * k / w
            ph = 2 * p.frame.h * k / h
            self._quad(p, x, ph / 2, pw, ph, 0.0, 2 * k / w, 2 * k / h)
            x += pw + 2 * gap_px * k / w

    def _draw_space(self, panels, w, h, now):
        sbs = w >= 3 * h
        eyes = [(-0.032, 0, w // 2), (0.032, w // 2, w // 2)] if sbs else [(0.0, 0, w)]
        view = self.head.view() if self.head else (1.0, 0.0, 0.0, 0.0)
        m = (ctypes.c_float * 16)(*fusion.matrix(fusion.qconj(view)))
        live = self.capture.virtual
        self.capture.space_pointer = live
        g = self.capture.glasses_rect
        self.space.frame(now, view, panels, (g[2], g[3]) if g else None, live and self.capture.pointer_on_glasses)
        self._edge_recentre(now)
        tex = lambda p: (self.textures.get(p.key) or (None,))[0]  # noqa: E731
        for eye_x, vx, vw in eyes:
            gl.glViewport(vx, 0, vw, h)
            gl.glMatrixMode(GL_PROJECTION)
            gl.glLoadIdentity()
            near = 0.05
            top = near * math.tan(math.radians(FOV_V_DEG) / 2)
            gl.glFrustum(-top * vw / h, top * vw / h, -top, top, near, 100.0)
            gl.glMatrixMode(GL_MODELVIEW)
            gl.glLoadIdentity()
            gl.glTranslatef(-eye_x, 0.0, 0.0)
            gl.glMultMatrixf(m)
            self.space.draw(panels, now, tex)
        self._edge_fade(w, h, sbs)

    def _edge_fade(self, w, h, sbs):
        """EdgeFade "Soft", Pocket XR's default: a smooth fade to black at each eye's edges (96 px outer, 48 inner,
        48 top and bottom; with one picture both sides are outer)."""
        gl.glViewport(0, 0, w, h)
        gl.glMatrixMode(GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glMatrixMode(GL_MODELVIEW)
        gl.glLoadIdentity()
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        eyes = [(0, w // 2, 96, 48), (w // 2, w // 2, 48, 96)] if sbs else [(0, w, 96, 96)]
        for x0, ew, left_px, right_px in eyes:
            for (ax, bx, ay, by, fade_at) in (
                    (x0, x0 + left_px, 0, h, "left"), (x0 + ew - right_px, x0 + ew, 0, h, "right"),
                    (x0, x0 + ew, 0, 48, "bottom"), (x0, x0 + ew, h - 48, h, "top")):
                X0, X1 = 2 * ax / w - 1, 2 * bx / w - 1
                Y0, Y1 = 2 * ay / h - 1, 2 * by / h - 1
                a = {"left": (1, 0, 0, 1), "right": (0, 1, 1, 0), "bottom": (1, 1, 0, 0), "top": (0, 0, 1, 1)}[fade_at]
                gl.glBegin(GL_QUADS)
                for (vx, vy), al in zip(((X0, Y0), (X1, Y0), (X1, Y1), (X0, Y1)), a):
                    gl.glColor4f(0.0, 0.0, 0.0, al)
                    gl.glVertex3f(vx, vy, 0.0)
                gl.glEnd()
        gl.glDisable(GL_BLEND)

    def _quad(self, p, left, top, pw, ph, z, sx, sy):
        """One panel with its top left at (left, top), size pw x ph; sx, sy: units per window pixel (for the pointer)."""
        if p.active and p.key != "deck":
            b = 6 * sx
            gl.glColor3f(*ACCENT)
            gl.glBegin(GL_QUADS)
            gl.glVertex3f(left - b, top + b * sy / sx, z - 0.001)
            gl.glVertex3f(left + pw + b, top + b * sy / sx, z - 0.001)
            gl.glVertex3f(left + pw + b, top - ph - b * sy / sx, z - 0.001)
            gl.glVertex3f(left - b, top - ph - b * sy / sx, z - 0.001)
            gl.glEnd()
        tex = self.textures.get(p.key)
        if tex is None:
            return
        gl.glEnable(GL_TEXTURE_2D)
        gl.glBindTexture(GL_TEXTURE_2D, tex[0])
        gl.glColor3f(1.0, 1.0, 1.0)
        gl.glBegin(GL_QUADS)
        gl.glTexCoord2f(0, 1); gl.glVertex3f(left, top - ph, z)  # noqa: E702
        gl.glTexCoord2f(1, 1); gl.glVertex3f(left + pw, top - ph, z)  # noqa: E702
        gl.glTexCoord2f(1, 0); gl.glVertex3f(left + pw, top, z)  # noqa: E702
        gl.glTexCoord2f(0, 0); gl.glVertex3f(left, top, z)  # noqa: E702
        gl.glEnd()
        gl.glDisable(GL_TEXTURE_2D)
        if p.pointer is not None:
            px, py = p.pointer
            pts = [(left + (px + x * 1.6) * sx, top - (py + y * 1.6) * sy) for x, y in ((0, 0), (0, 17), (4.5, 13), (12, 12))]
            gl.glColor3f(1.0, 1.0, 1.0)
            gl.glBegin(GL_TRIANGLE_FAN)
            for x, y in pts:
                gl.glVertex3f(x, y, z + 0.002)
            gl.glEnd()
            gl.glColor3f(0.0, 0.0, 0.0)
            gl.glBegin(GL_LINE_LOOP)
            for x, y in pts:
                gl.glVertex3f(x, y, z + 0.003)
            gl.glEnd()

    def _look(self, items, view, now):
        """Look at an app window for a moment and it comes to the front on the Deck's screen."""
        if not self.settings["look"] or self.settings["source"] != "apps" or len(items) < 2:
            self.look_target = None
            return
        fwd = fusion.qrot(view, (0.0, 0.0, -1.0))
        yaw = math.degrees(math.atan2(-fwd[0], -fwd[2]))
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, fwd[1]))))
        d = self.settings["distance"]
        hit = None
        for p, wm, hm, ang, cy in items:
            half_v = math.degrees(math.atan(hm / 2 / d))
            if abs(yaw - cy) <= ang / 2 and abs(pitch) <= half_v:
                hit = p
        if hit is None or hit.active:
            self.look_target = None
            return
        if hit.key != self.look_target:
            self.look_target, self.look_since = hit.key, now
        elif now - self.look_since >= LOOK_DWELL_S:
            self.capture.activate(hit.key)
            self.look_target = None

    def _edge_recentre(self, now):
        """Pointer pushed against the right edge of the Deck's screen for a second: recentre (no keyboard needed)."""
        if getattr(self.capture, "pointer_at_right_edge", False):
            if self.edge_since is None:
                self.edge_since = now
            elif now - self.edge_since > 1.0:
                self.recentre()
                self.log("recentred (pointer held at the right edge)")
                self.edge_since = now + 1e9
        else:
            self.edge_since = None


def main():
    os.environ.setdefault("DISPLAY", ":0")
    sys.exit(App().run())


if __name__ == "__main__":
    main()
