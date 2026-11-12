"""Pocket XR in Gaming Mode: the whole Gaming Mode picture (games, Steam, everything) as a screen held still in space.

In Gaming Mode, gamescope owns the screen, so Pocket XR can't draw its own window over a game. Instead this service,
started with the user's session, waits for Gaming Mode (gamescope's Wayland socket) and glasses, then:

- Screen in space (all glasses with head tracking): loads Pocket XR's effect (reshade/PocketXR.fx) into gamescope and
  sends it the head's turn about 250 times a second (wlreshade.py). The effect redraws the picture as a screen that
  stays put while the head turns.
- Steady (glasses that hold the picture themselves, like the XREAL Aura): the effect is off and the glasses' own
  Spatial Anchor holds the picture in place in 6DoF, through the same proven commands as the desktop's Steady mode,
  without Ultrawide so the game stays 16:9.

Controls, for now on the Deck's back buttons (held, so a quick tap still reaches the game): hold L4 to recentre, hold
R4 to switch between the screen in space and Steady (or off, on glasses without Steady). The choice is kept in
~/.config/pocket-xr-deck/gaming.json.

In Desktop Mode there is no gamescope socket, so this service does nothing and the desktop app has the glasses.
"""
import json
import math
import os
import shutil
import sys
import threading
import time

from . import fusion, glasses as gmod, hidimu, imu
from . import wlreshade
from .deckpad import DeckButtons
from .settingsctl import SettingsControl

EFFECT = "PocketXR.fx"
EFFECT_DIR = os.path.expanduser("~/.local/share/gamescope/reshade/Shaders")
CONFIG = os.path.expanduser("~/.config/pocket-xr-deck/gaming.json")
LOG = os.path.expanduser("~/.local/state/pocket-xr-deck/gaming.log")
FOV_V_DEG = 38.0  # the glasses' picture, vertical (as the desktop app)
ASPECT = 16 / 9
DEFAULTS = {"mode": "space", "size": 0.8}
SEND_HZ = 250
GONE_GRACE_S = 12.0
EDGE = 0.004  # the screen's soft edge, in screen widths


def _log_to_file():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    f = open(LOG, "a", buffering=1)

    def log(msg):
        line = time.strftime("%H:%M:%S ") + msg
        f.write(line + "\n")
        print(line, flush=True)

    return log


def load_settings():
    s = dict(DEFAULTS)
    try:
        with open(CONFIG) as f:
            s.update(json.load(f))
    except (OSError, ValueError):
        pass
    return s


def save_settings(s):
    os.makedirs(os.path.dirname(CONFIG), exist_ok=True)
    with open(CONFIG, "w") as f:
        json.dump(s, f)


def install_effect(log):
    """Our effect where gamescope looks for effects (copied each start, so an update brings the new one)."""
    src = os.path.join(os.path.dirname(__file__), "reshade", EFFECT)
    os.makedirs(EFFECT_DIR, exist_ok=True)
    dst = os.path.join(EFFECT_DIR, EFFECT)
    try:
        with open(src, "rb") as a:
            new = a.read()
        try:
            with open(dst, "rb") as b:
                same = b.read() == new
        except OSError:
            same = False
        if not same:
            shutil.copyfile(src, dst)
            log(f"gaming: effect installed in {EFFECT_DIR}")
    except OSError as e:
        log(f"gaming: could not install the effect ({e})")


class Gaming:
    def __init__(self, log):
        self.log = log
        self.settings = load_settings()
        self.glasses = None
        self.missing_since = None
        self.head = None
        self.reader = None
        self.control = None
        self.reshade = None
        self.effect_on = False
        self.lock = threading.Lock()
        self.buttons = DeckButtons(self._button, log=log)
        self.buttons.start()

    # ---- the back buttons ----
    def _button(self, name, kind):
        if kind != "hold" or self.reshade is None or self.glasses is None:
            return  # only in Gaming Mode with glasses: in Desktop Mode the desktop app has the buttons
        with self.lock:
            if name == "L4":
                self.recentre()
            elif name == "R4":
                self.next_mode()

    def recentre(self):
        if self.head:
            self.head.recentre()
        if self.control and self.mode() == "steady":
            self.control.recentre()
        self.log("gaming: recentred")

    def steady_ok(self):
        return bool(self.glasses and self.glasses.steady_6dof and self.glasses.app_anchor)

    def mode(self):
        m = self.settings.get("mode", "space")
        if m == "steady" and not self.steady_ok():
            return "space"
        if m == "space" and not self.reader:
            return "off"  # no head tracking on these glasses: show the picture as it is
        return m

    def next_mode(self):
        order = ["space", "steady", "off"] if self.steady_ok() else ["space", "off"]
        cur = self.settings.get("mode", "space")
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "space"
        self.settings["mode"] = nxt
        save_settings(self.settings)
        self.log(f"gaming: mode {nxt}")
        self._apply_mode()

    def _apply_mode(self):
        m = self.mode()
        if self.control:
            self.control.want("steady" if m == "steady" else "3dof")
        if self.head:
            self.head.recentre()
        self._effect(m == "space")

    # ---- gamescope ----
    def _effect(self, on):
        if self.reshade is None:
            return
        try:
            if on and not self.effect_on:
                self._send_view()
                self.reshade.set_floats("pxr_mode", (1.0, EDGE, 0.0, 0.0))
                self.reshade.enable()
                self.effect_on = True
                self.log("gaming: screen in space on")
            elif not on and self.effect_on:
                self.reshade.disable()
                self.effect_on = False
                self.log("gaming: screen in space off")
        except OSError as e:
            self._lost_gamescope(e)

    def _send_view(self):
        tv = math.tan(math.radians(FOV_V_DEG) / 2)
        th = tv * ASPECT
        size = max(0.3, min(1.2, float(self.settings.get("size", 0.8))))
        self.reshade.set_floats("pxr_view", (th, tv, th * size, tv * size))

    def _connect_gamescope(self):
        path = wlreshade.socket_path()
        if path is None:
            return
        try:
            r = wlreshade.Reshade(path, log=self.log)
        except OSError as e:
            self.log(f"gaming: gamescope's reshade interface is not available ({e})")
            return
        install_effect(self.log)
        r.set_effect(EFFECT)
        r.set_floats("pxr_quat", (0.0, 0.0, 0.0, 1.0))
        r.set_floats("pxr_mode", (1.0, EDGE, 0.0, 0.0))
        self.reshade = r
        self.effect_on = False
        self._send_view()
        self.log(f"gaming: connected to gamescope ({path})")

    def _lost_gamescope(self, e):
        self.log(f"gaming: lost gamescope ({e})")
        try:
            self.reshade.close()
        except Exception:  # noqa: BLE001
            pass
        self.reshade = None
        self.effect_on = False

    # ---- glasses ----
    def _start_glasses(self, g):
        self.glasses = g
        self.log(f"gaming: glasses {g.name} ({g.family}, {g.vendor:04x}:{g.product:04x})")
        self.head = fusion.HeadFusion(g.axes)
        if g.imu == "network":
            self.reader = imu.ImuReader(self.head.report, log=self.log)
        elif g.imu == "air":
            self.reader = hidimu.AirReader(self.head.report, g.product, log=self.log)
        elif g.imu == "viture" and g.viture_tracking_default():
            self.reader = hidimu.VitureReader(self.head.report, g.product, log=self.log)
        if self.reader:
            self.reader.start()
        if g.control_link:
            self.control = SettingsControl(g, self.log, lambda st: None, lambda text: self.log("gaming: " + text))
            self.control.want_3d = lambda: False  # the effect draws one picture: the glasses stay 2D
            self.control.steady_wide = False
            self.control.start()
        self._apply_mode()

    def _stop_glasses(self, put_back=True):
        self.log(f"gaming: glasses gone: {self.glasses.name}" if self.glasses else "gaming: glasses off")
        self._effect(False)
        if self.reader:
            self.reader.stop = True
            self.reader = None
        if self.control:
            if put_back:
                done = threading.Event()
                self.control.restore(done.set)
                done.wait(8.0)
            self.control.close()
            self.control = None
        self.head = None
        self.glasses = None

    def _check_glasses(self):
        g = gmod.detect()
        now = time.monotonic()
        if g is not None and g.family == "other":
            g = None
        if g is None and self.glasses is not None:
            if self.missing_since is None:
                self.missing_since = now
            if now - self.missing_since < GONE_GRACE_S:
                return
        if g is not None:
            self.missing_since = None
        if g != self.glasses:
            if self.glasses is not None:
                self._stop_glasses(put_back=g is not None)
            if g is not None:
                self._start_glasses(g)

    # ---- the loop ----
    def run(self):
        self.log("gaming: Pocket XR's Gaming Mode service started")
        next_check = 0.0
        step = 1.0 / SEND_HZ
        while True:
            now = time.monotonic()
            if now >= next_check:
                next_check = now + 1.0
                in_gaming = wlreshade.socket_path() is not None
                with self.lock:
                    if in_gaming:
                        if self.reshade is None:
                            self._connect_gamescope()
                        self._check_glasses()
                        if self.glasses and self.reshade and not self.effect_on and self.mode() == "space":
                            self._effect(True)
                    else:
                        if self.reshade is not None:
                            self._lost_gamescope("Gaming Mode ended")
                        if self.glasses is not None:
                            self._stop_glasses(put_back=True)
            if self.reshade is not None:
                try:
                    self.reshade.pump()
                    if self.effect_on and self.head is not None:
                        w, x, y, z = self.head.view()
                        self.reshade.set_floats("pxr_quat", (x, y, z, w))
                except OSError as e:
                    with self.lock:
                        self._lost_gamescope(e)
            time.sleep(step)


def main():
    log = _log_to_file()
    try:
        Gaming(log).run()
    except KeyboardInterrupt:
        pass
    except Exception as e:  # noqa: BLE001
        import traceback
        log("gaming: stopped by an error: " + "".join(traceback.format_exception(e)))
        sys.exit(1)


if __name__ == "__main__":
    main()
