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
R4 to switch between the screen in space and Steady (or off, on glasses without Steady), two modes only. The choice is kept in
~/.config/pocket-xr-deck/gaming.json.

In Desktop Mode there is no gamescope socket, so this service does nothing and the desktop app has the glasses.
"""
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import threading
import time

from . import fusion, glasses as gmod, hidimu, imu, readability
from . import i18n, keys, sendlogs, taps, wlreshade
from .deckpad import DeckButtons
from .settingsctl import SettingsControl

EFFECT = "PocketXR.fx"
EFFECT_DIR = os.path.expanduser("~/.local/share/gamescope/reshade/Shaders")
CONFIG = os.path.expanduser("~/.config/pocket-xr-deck/gaming.json")
LOG = os.path.expanduser("~/.local/state/pocket-xr-deck/gaming.log")
RAW_IMU = os.path.expanduser("~/.local/state/pocket-xr-deck/imu-raw.log")  # the Air family's first seconds, in full
HEAD_LOG_S = 60.0  # the head's direction goes in the log once a second this long after glasses, a mode or a recentre
FOV_V_DEG = 38.0  # the glasses' picture, vertical (as the desktop app)
ASPECT = 16 / 9
DEFAULTS = {"mode": "space", "size": 0.8, "curve": 0.0, "readability": False, "readability_saved": None,
            "keys": {},  # keys.py: {"recentre": "KEY_STOPCD", ...} over its defaults
            "sticks": True,  # the Deck's stick clicks: hold L3 recentres, hold R3 switches view, L3 three times calibrates
            "taps": False,  # taps on the glasses (taps.py): two recentre, three switch view; off until tried with glasses
            "tap_sensitivity": 100,  # percent (taps.SENSITIVITY); 100 is the values a tester liked
            "recentre_roll": False,
            "hide_gamescope_pointer": True}  # Screen in space: gamescope's own arrow blanked (xpointer.py)  # Recentre includes head tilt: the head's roll too (fusion.recentre follow_roll)
STICK_CAL_DELAY_S = 5.0  # a calibration from the stick clicks starts this long after, to take the glasses off first
# The Quick Access panel (decky/ plugin) talks to the service here: one JSON request per line, one JSON answer per line
CONTROL_SOCKET = os.path.join(os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}", "pocket-xr-gaming.sock")
SEND_HZ = 500  # how often the loop looks; updates go out as fast as gamescope takes them (paced)
PREDICT_S = 0.020  # head prediction: gamescope's composite and the glasses' display
GONE_GRACE_S = 12.0
EDGE = 0.004  # the screen's soft edge, in screen widths
VERSION_CHECK_S = 5.0  # how often the service looks for a new Pocket XR installed over it
RESTART_EXIT = 75  # ends with this, so systemd starts it again (Restart=on-failure)
CURVE_MAX = 1.0  # the screen bent round the eye (PocketXR.fx)


def curve_of(value):
    """A curve the effect takes: 0 (flat) to CURVE_MAX; anything else is flat."""
    try:
        c = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(CURVE_MAX, c)) if c == c else 0.0


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
        self.version = sendlogs.version()  # the Pocket XR this service was started from
        self.version_checked = 0.0
        self.glasses = None
        self.missing_since = None
        self.head = None
        self.reader = None
        self.control = None
        self.reshade = None
        self.effect_on = False
        self.lock = threading.Lock()
        self.head_log_until = 0.0
        self.cal_text = ""
        self.cal_due = None  # when a calibration asked for with the stick clicks starts
        self.buttons_released = False  # "Use the glasses' buttons" (Quick Access)
        self.taps = taps.Taps(self._tapped, on_log=lambda line: self.log("gaming: " + line))
        self.taps.set_sensitivity(self.settings.get("tap_sensitivity", 100))
        self.head_logged = 0.0
        self.other_driver = []  # XR Gaming's driver, looked for every few seconds
        self.xr_gaming_enabled = False
        self.session = None  # SteamOS's default Desktop Mode session
        self.other_checked = 0.0
        self.pointer = None  # (u, v, shown) from xpointer.py: where the mouse pointer is on the picture
        self.pointer_sent = None
        self.pointer_proc = None
        self.pointer_started = 0.0
        self.panel_version = False  # none heard yet
        self.buttons = DeckButtons(self._button, log=log)
        self.buttons.start()
        # Keys for the back buttons' jobs come through xpointer.py (gamescope's X screens), where Steam Input sends a
        # controller's keyboard bindings: {Linux key code: action}
        self.key_actions = keys.key_map(self.settings.get("keys"))
        threading.Thread(target=self._control_server, name="control", daemon=True).start()
        threading.Thread(target=self._watch_other, name="other-driver", daemon=True).start()

    # ---- the Quick Access panel ----
    def status(self):
        self._check_calibration()
        return {
            "version": self.version,
            "gaming": self.reshade is not None,
            "glasses": self.glasses.name if self.glasses else None,
            "tracking": self.reader is not None,
            "steady_ok": self.steady_ok(),
            "mode": self.mode() if self.glasses else self.settings.get("mode", "space"),
            "chosen": self.settings.get("mode", "space"),
            "size": float(self.settings.get("size", 0.8)),
            "curve": curve_of(self.settings.get("curve", 0.0)),
            "readability": bool(self.settings.get("readability")),
            "calibrating": bool(self.head and self.head.cal is not None),
            "calibrate_label": i18n.tr("Calibrate (hold still)"),
            "calibrate_line": i18n.tr("Lay the glasses down on something still for 4 seconds. It stops a slow drift "
                                      "to one side and is saved for these glasses."),
            "calibration_text": self.cal_text,
            # The panel shows this as a toast when a calibration starts, and calibration_text when it ends
            "calibrate_start_text": i18n.tr("Calibrating: take the glasses off and lay them on something still for "
                                            "4 seconds."),
            "keys_line": i18n.tr("Another controller: in Steam Input, map a button to the Stop media key to recentre "
                                 "and to Next to switch view."),
            # The glasses' brightness, 0 to 7, while their MCU is open (the XBX's heartbeat): None hides the slider
            "brightness": self._brightness(),
            "brightness_max": hidimu.BRIGHTNESS_MAX,
            "brightness_label": i18n.tr("Glasses brightness"),
            "brightness_line": i18n.tr("Sets the glasses' brightness while Pocket XR has them, so you don't need "
                                       "their buttons. New: say if it does nothing on your glasses."),
            # Only for the Air family's reader (hidimu.AirReader): None hides the switch
            "glasses_buttons": (self.buttons_released if isinstance(self.reader, hidimu.AirReader) else None),
            "glasses_buttons_label": i18n.tr("Use the glasses' buttons"),
            # His buttons came back 1 to 4 minutes after letting go, when the glasses reset themselves
            # (hidimu.USBDEVFS_RESET); the steps are the ones he found work (Pierre Zammit, 23 Nov 2026)
            "glasses_buttons_line": i18n.tr("Lets go of the glasses so their own buttons work (brightness, for "
                                            "example). Head tracking pauses until you turn this off. Set the mode to "
                                            "Off, turn this on and wait for the glasses to blink off and on (up to a "
                                            "few minutes), adjust them, turn this off, then pick a mode."),
            "taps": bool(self.settings.get("taps", False)),
            "tap_sensitivity": self.taps.sensitivity,
            "tap_sensitivity_range": list(taps.SENSITIVITY),
            "tap_sensitivity_label": i18n.tr("Tap sensitivity"),
            "tap_sensitivity_line": i18n.tr("Higher catches softer taps, lower only firm ones. Pressing the glasses' "
                                            "buttons can count as a tap, more so when it is high."),
            "hide_pointer": bool(self.settings.get("hide_gamescope_pointer", True)),
            "hide_pointer_label": i18n.tr("Hide the moving pointer"),
            "hide_pointer_line": i18n.tr("With the screen in space, hides gamescope's own arrow, which moves with your "
                                         "head and is not where clicks land. Pocket XR's pointer stays."),
            "recentre_roll": bool(self.settings.get("recentre_roll")),
            "recentre_roll_label": i18n.tr("Recentre includes head tilt"),
            "recentre_roll_line": i18n.tr("For lying on one side: Recentre lines the picture up with your eyes, not "
                                          "the room's horizon."),
            "taps_label": i18n.tr("Taps on the glasses"),
            # taps.py takes taps 0.2 to 0.7 s apart: about 1.5 to 5 a second
            "taps_line": i18n.tr("Tap the glasses' frame twice to recentre, three times to switch view, at about 2 "
                                 "taps a second (1.5 to 5 a second work). Hold your head still while you tap. New: "
                                 "say if it misses taps or reacts on its own."),
            "sticks": bool(self.settings.get("sticks", True)),
            "sticks_label": i18n.tr("Stick clicks"),
            "sticks_line": i18n.tr("In every game: hold L3 to recentre, hold R3 to switch view, click L3 three times "
                                   "to calibrate (lay the glasses down within 5 seconds)."),
            "readability_label": i18n.tr("Readability"),
            "readability_line": i18n.tr("The game screen 30 degrees wide: sharpest for a game drawn 1280 pixels "
                                        "wide. For larger text, pick a larger text or interface size in the game."),
            "lang": i18n.lang(),  # the Quick Access panel speaks the same language
            "notice": gmod.xr_gaming_text() if (self.glasses and self.other_driver) else "",
            # Buttons the panel shows only when they would do something: [{"op", "label"}]
            "actions": self._actions(),
        }

    @staticmethod
    def _glasses_key(g):
        return f"{g.vendor:04x}:{g.product:04x}"

    def _start_calibration(self):
        if not (self.head and self.reader):
            self.cal_text = i18n.tr("Plug in glasses with head tracking first.")
            self.log("gaming: calibration asked for, but no glasses with head tracking")
            return
        self.head.start_calibration()
        self.cal_text = ""
        self.log("gaming: hold-still calibration started")

    def _check_calibration(self):
        """Once a calibration ends: saved for these glasses if nothing moved, and a line for the panel."""
        h = self.head
        if h is None or h.cal_result is None:
            return
        res, mean, sd = h.cal_result
        h.cal_result = None
        if res == "ok":
            key = self._glasses_key(self.glasses)
            try:
                fusion.save_bias(key, h.bias)
                saved = "saved"
            except OSError as e:
                saved = f"not saved ({e})"
            self.log(f"gaming: calibrated: gyro bias {mean} deg/s, spread {sd} deg/s; {saved} for {key}")
            self.cal_text = i18n.tr("Calibrated. Saved for these glasses.")
        else:
            self.log(f"gaming: calibration not taken, the glasses moved: mean {mean} deg/s, spread {sd} deg/s")
            self.cal_text = i18n.tr("The glasses moved. Lay them on something still and try again.")

    def _actions(self):
        out = []
        if self.other_driver or self.xr_gaming_enabled:
            out.append({"op": "stop_xr_gaming", "label": i18n.tr("Stop XR Gaming's driver")})
        if self.session == gmod.X11_SESSION:
            out.append({"op": "wayland_back", "label": i18n.tr("Put the desktop back to Wayland")})
        return out

    def _do_action(self, op):
        """Runs a panel button's command: the text the panel shows after it."""
        if op == "stop_xr_gaming":
            ok, out = gmod.stop_xr_gaming()
            self.log(f"gaming: stop XR Gaming's driver ({gmod.XR_GAMING_STOP}): {'done' if ok else 'failed'}"
                     + (f": {out}" if out else ""))
            self._check_other_driver(time.monotonic())
            if ok:
                return i18n.tr("Done. XR Gaming's driver is stopped and won't start again. Unplug the glasses "
                               "and plug them back in.")
        elif op == "wayland_back":
            ok, out = gmod.wayland_back()
            self.log(f"gaming: desktop session set to {gmod.WAYLAND_SESSION}: {'done' if ok else 'failed'}"
                     + (f": {out}" if out else ""))
            self._check_other_driver(time.monotonic())
            if ok:
                return i18n.tr("Done. It applies the next time you switch to Desktop.")
        else:
            return ""
        return i18n.tr("That didn't work: {error}", error=(out or "?").splitlines()[-1][:200])

    def _watch_other(self):
        """Every 5 s, off the head-update loop: XR Gaming's driver and SteamOS's desktop session (commands that take
        a moment)."""
        while True:
            try:
                self._check_other_driver(time.monotonic())
            except Exception as e:  # noqa: BLE001
                self.log(f"gaming: checking for XR Gaming failed ({e})")
            time.sleep(5.0)

    def _check_other_driver(self, now):
        self.other_checked = now
        found = gmod.xr_gaming_running()
        self.xr_gaming_enabled = bool(gmod.xr_gaming_installed()) and gmod.xr_gaming_enabled()
        self.session = gmod.desktop_session() if shutil.which("steamosctl") else None
        if found != self.other_driver:
            if found:
                self.log("gaming: XR Gaming's driver is running (" +
                         ", ".join(f"{name}, pid {pid}" for pid, name in found) + "); it talks to the same glasses")
            elif self.other_driver:
                self.log("gaming: XR Gaming's driver stopped")
            self.other_driver = found

    def _request(self, req):
        op = req.get("op")
        panel = req.get("panel")  # the Quick Access panel's version, added by its backend (decky/main.py)
        if panel != self.panel_version:
            self.panel_version = panel
            self.log(f"gaming: Quick Access panel {panel or 'from before 0.7.2'}")
        if op == "send_logs":
            # No email app opens in Gaming Mode: the zip goes in Downloads and the panel says where.
            try:
                path = sendlogs.build()
                self.log(f"gaming: logs saved in {path}")
                return dict(self.status(), logs=os.path.basename(path))
            except OSError as e:
                self.log(f"gaming: could not make the logs ({e})")
                return dict(self.status(), logs_error=str(e))
        if op in ("stop_xr_gaming", "wayland_back"):  # commands that take a moment: not under the lock
            return dict(self.status(), action_result=self._do_action(op))
        with self.lock:
            if op == "set_mode" and req.get("mode") in ("space", "steady", "off"):
                self.settings["mode"] = req["mode"]
                save_settings(self.settings)
                self.log(f"gaming: mode {req['mode']} (Quick Access)")
                self._apply_mode()
            elif op == "set_size":
                self.settings["size"] = max(0.3, min(1.2, float(req.get("size", 0.8))))
                save_settings(self.settings)
                if self.reshade is not None:
                    try:
                        self._send_view()
                    except OSError as e:
                        self._lost_gamescope(e)
            elif op == "calibrate":
                self._start_calibration()
            elif op == "set_readability":
                self._set_readability(bool(req.get("on")))
            elif op == "set_brightness":
                r = self.reader
                level = int(req.get("level", 0))
                if isinstance(r, hidimu.AirReader) and r.set_brightness(level):
                    self.log(f"gaming: glasses brightness {level} asked for (Quick Access)")
            elif op == "glasses_buttons":
                self._glasses_buttons(bool(req.get("on")))
            elif op == "set_tap_sensitivity":
                self.taps.set_sensitivity(req.get("percent", 100))
                self.settings["tap_sensitivity"] = self.taps.sensitivity
                save_settings(self.settings)
                self.log(f"gaming: tap sensitivity {self.taps.sensitivity}%: a tap needs {self.taps.tap_g:.2f} g "
                         f"and a {self.taps.jerk_g:.2f} g jump (Quick Access)")
            elif op == "set_hide_pointer":
                self.settings["hide_gamescope_pointer"] = bool(req.get("on"))
                save_settings(self.settings)
                self.log("gaming: hide the moving pointer " + ("on" if self.settings["hide_gamescope_pointer"] else "off")
                         + " (Quick Access)")
                self._pointer_hide()
            elif op == "set_recentre_roll":
                self.settings["recentre_roll"] = bool(req.get("on"))
                save_settings(self.settings)
                self.log("gaming: recentre includes head tilt " + ("on" if self.settings["recentre_roll"] else "off")
                         + " (Quick Access)")
            elif op == "set_taps":
                self.settings["taps"] = bool(req.get("on"))
                save_settings(self.settings)
                self.log(f"gaming: taps on the glasses {'on' if self.settings['taps'] else 'off'} (Quick Access)")
                self._update_paused()
            elif op == "set_sticks":
                self.settings["sticks"] = bool(req.get("on"))
                save_settings(self.settings)
                self.log(f"gaming: stick clicks {'on' if self.settings['sticks'] else 'off'} (Quick Access)")
            elif op == "set_curve":
                self.settings["curve"] = curve_of(req.get("curve", 0.0))
                save_settings(self.settings)
                self.log(f"gaming: curve {self.settings['curve']:.2f} (Quick Access)")
                if self.reshade is not None:
                    try:
                        self._send_mode()
                    except OSError as e:
                        self._lost_gamescope(e)
            elif op == "recentre":
                self.recentre()
            return self.status()

    def _control_server(self):
        try:
            os.unlink(CONTROL_SOCKET)
        except OSError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(CONTROL_SOCKET)
        os.chmod(CONTROL_SOCKET, 0o600)
        srv.listen(4)
        while True:
            conn, _ = srv.accept()
            try:
                f = conn.makefile("rw")
                for line in f:
                    try:
                        answer = self._request(json.loads(line))
                    except (ValueError, TypeError) as e:
                        answer = {"error": str(e)}
                    f.write(json.dumps(answer) + "\n")
                    f.flush()
            except OSError:
                pass
            finally:
                conn.close()

    # ---- the back buttons ----
    def _button(self, name, kind):
        if self.reshade is None or self.glasses is None:
            return  # only in Gaming Mode with glasses: in Desktop Mode the desktop app has the buttons
        if name in ("L3", "R3"):
            self._stick(name, kind)
            return
        if kind != "hold":
            return
        with self.lock:
            if name == "L4":
                self.recentre()
            elif name == "R4":
                self.next_mode()

    def _brightness(self):
        r = self.reader
        # Only with a level the glasses read out and while their MCU is open; hidden once they turn out not to take
        # the commands (an XBX A01+, 24 Nov 2026)
        if isinstance(r, hidimu.AirReader) and r.brightness is not None and not r.brightness_unsupported                 and r._mcu_running():
            return r.brightness
        return None

    def _glasses_buttons(self, on):
        """Lets go of the glasses (no stream, no heartbeat, their files closed) so their own buttons work once the
        glasses reset themselves, or takes them back. Kept while the service runs, also when the glasses come back;
        not kept when the service starts again."""
        r = self.reader
        if not isinstance(r, hidimu.AirReader) or self.buttons_released == on:
            return
        self.buttons_released = on
        r.released = on
        self.log("gaming: glasses let go for their own buttons; head tracking paused (Quick Access)" if on
                 else "gaming: glasses taken back from their own buttons (Quick Access)")

    def _report(self, ts_ns, gyro, accel):
        """Each motion report: to the head's fusion, and to the tap reader when taps are on."""
        head = self.head
        if head is None:
            return
        head.report(ts_ns, gyro, accel)
        if self.settings.get("taps") and head.cal is None:
            self.taps.feed(ts_ns / 1e9, gyro, accel)

    def _tapped(self, n):
        """Taps on the glasses (taps.py), from the motion reader's thread."""
        if self.reshade is None or self.glasses is None:
            return
        with self.lock:
            if n == 2:
                self.log("gaming: glasses tapped twice")
                self.recentre()
            elif n == 3:
                self.log("gaming: glasses tapped three times")
                self.next_mode()

    def _stick(self, name, kind):
        """The stick clicks (deckpad.Sticks), when "sticks" is on: games use the clicks, so only a long hold or three
        clicks do anything here."""
        if not self.settings.get("sticks", True) or kind not in ("hold", "triple"):
            return
        with self.lock:
            if (name, kind) == ("L3", "hold"):
                self.log("gaming: L3 held")
                self.recentre()
            elif (name, kind) == ("R3", "hold"):
                self.log("gaming: R3 held")
                self.next_mode()
            elif (name, kind) == ("L3", "triple"):
                self.cal_due = time.monotonic() + STICK_CAL_DELAY_S
                self.cal_text = ""
                self.log(f"gaming: L3 clicked three times: calibration in {STICK_CAL_DELAY_S:g} s")

    def _key(self, action):
        """A key from keys.py (any controller, through Steam Input): recentre, or the next mode."""
        if self.reshade is None or self.glasses is None:
            return  # only in Gaming Mode with glasses, as the back buttons
        self.log(f"gaming: key for {action}")
        with self.lock:
            if action == "recentre":
                self.recentre()
            elif action == "switch_view":
                self.next_mode()

    def _log_head(self, now):
        """Once a second for a while: where the head points, what the motion sensor reads, so a log shows motion."""
        if self.head is None or now > self.head_log_until or now - self.head_logged < 1.0:
            return
        self.head_logged = now
        w, x, y, z = self.head.view()
        f = fusion.qrot((w, x, y, z), (0.0, 0.0, -1.0))
        yaw = math.degrees(math.atan2(-f[0], -f[2])) + 0.0  # no "-0.0" in the log
        pitch = math.degrees(math.asin(max(-1.0, min(1.0, f[1])))) + 0.0
        g = self.head.last_gyro
        turn = math.degrees(math.sqrt(g[0] ** 2 + g[1] ** 2 + g[2] ** 2))
        self.log(f"gaming: head yaw {yaw:.1f}, pitch {pitch:.1f} degrees; turning {turn:.1f} deg/s; "
                 f"gravity {self.head.g_mag or 0:.2f} m/s2; still-bias {'ready' if self.head.bias_ready else 'not yet'}; "
                 f"{self.head.count} reports")

    def recentre(self):
        self.head_log_until = time.monotonic() + HEAD_LOG_S
        if self.head:
            self.head.recentre(follow_tilt=True, follow_roll=bool(self.settings.get("recentre_roll")))
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
        # Two modes on the button, so it's always clear which one you're in (Mike, 12 Nov 2026: a third, "off",
        # left him unsure where he was). Off for glasses with Steady comes with the Quick Access menu's switch.
        order = ["space", "steady"] if self.steady_ok() else ["space", "off"]
        cur = self.settings.get("mode", "space")
        nxt = order[(order.index(cur) + 1) % len(order)] if cur in order else "space"
        self.settings["mode"] = nxt
        save_settings(self.settings)
        self.log(f"gaming: mode {nxt}")
        self._apply_mode()

    def _update_paused(self):
        """Off stops the Air family's motion stream (the XBX heartbeat keeps going), unless taps on the glasses are on:
        then the stream goes on, for the taps only (the screen is off), so three taps can bring the screen back. With
        0.7.8 a tester's triple tap turned it off but never on again (Pierre Zammit, 23 Nov 2026)."""
        if not isinstance(self.reader, hidimu.AirReader):
            return
        off = self.settings.get("mode", "space") == "off"
        paused = off and not self.settings.get("taps")
        if paused != self.reader.paused:
            self.reader.paused = paused
            self.log("gaming: head tracking paused (off)" if paused
                     else ("gaming: motion read for the taps only (off)" if off else "gaming: head tracking on"))

    def _apply_mode(self):
        m = self.mode()
        self.head_log_until = time.monotonic() + HEAD_LOG_S
        self._update_paused()
        if self.control:
            self.control.want("steady" if m == "steady" else "3dof")
        if self.head:
            self.head.recentre(follow_tilt=True, follow_roll=bool(self.settings.get("recentre_roll")))
        self._effect(m == "space")

    # ---- gamescope ----
    def _pointer_hide(self):
        """Tells xpointer.py whether to blank gamescope's own arrow: while the screen is in space (the arrow is drawn
        after Pocket XR's effect, where the pointer would be on a flat screen, so it moves with the head and is never
        where a click lands) and "hide_gamescope_pointer" is on. Pocket XR's own pointer stays."""
        p = self.pointer_proc
        want = bool(self.effect_on and self.settings.get("hide_gamescope_pointer", True))
        if p is None or p.poll() is not None or p.stdin is None or want == getattr(self, "pointer_hide_sent", None):
            return
        try:
            p.stdin.write("hide %d\n" % want)
            p.stdin.flush()
            self.pointer_hide_sent = want
        except (OSError, ValueError):
            pass

    def _effect(self, on):
        if self.reshade is None:
            return
        try:
            if on and not self.effect_on:
                self._send_view()
                self._send_mode()
                self.reshade.enable()
                self.effect_on = True
                self.log("gaming: screen in space on")
                self._pointer_hide()
            elif not on and self.effect_on:
                self.reshade.disable()
                self.effect_on = False
                self.log("gaming: screen in space off")
                self._pointer_hide()
        except OSError as e:
            self._lost_gamescope(e)

    def _send_mode(self, r=None):
        (r or self.reshade).set_floats("pxr_mode", (1.0, EDGE, curve_of(self.settings.get("curve", 0.0)), 0.0))

    def _set_readability(self, on):
        """Readability (readability.py): the game screen 30 degrees wide. Off puts the size back."""
        if on == bool(self.settings.get("readability")):
            return
        if on:
            changes, before, after = readability.gaming_on(self.settings, FOV_V_DEG, ASPECT)
        else:
            before = {"size": self.settings.get("size")}
            changes = readability.gaming_off(self.settings)
            after = {"size": changes.get("size", before["size"])}
        self.settings.update(changes)
        save_settings(self.settings)
        self.log(f"gaming: readability {'on' if on else 'off'} (Quick Access): before {before}; after {after}")
        if self.reshade is not None:
            try:
                self._send_view()
            except OSError as e:
                self._lost_gamescope(e)

    # ---- the mouse pointer (xpointer.py) ----
    def _watch_pointer(self, now):
        """Keeps xpointer.py running while gamescope is connected, started again (every 10 s at most) if it ends."""
        p = self.pointer_proc
        if p is not None and p.poll() is None:
            return
        if now - self.pointer_started < 10.0:
            return
        self.pointer_started = now
        try:
            args = [sys.executable, "-m", "pocketxr.xpointer"]
            if self.key_actions:
                args += ["--keys", ",".join(str(c) for c in sorted(self.key_actions))]
            p = subprocess.Popen(args, stdout=subprocess.PIPE, stdin=subprocess.PIPE,
                                 stderr=subprocess.STDOUT, text=True, bufsize=1,
                                 cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        except OSError as e:
            self.log(f"gaming: pointer reader did not start ({e})")
            return
        self.pointer_proc = p
        self.pointer_hide_sent = None  # a new reader starts with gamescope's arrow shown
        self._pointer_hide()
        threading.Thread(target=self._read_pointer, args=(p,), name="pointer", daemon=True).start()

    def _read_pointer(self, p):
        said_none = False
        for line in p.stdout:
            parts = line.split()
            if parts[:1] == ["pointer"] and len(parts) == 4:
                try:
                    self.pointer = (float(parts[1]), float(parts[2]), parts[3] == "1")
                except ValueError:
                    pass
            elif parts[:1] == ["key"] and len(parts) == 2 and parts[1].isdigit():
                action = self.key_actions.get(int(parts[1]))
                if action:
                    self._key(action)
            elif parts[:1] == ["none"]:
                if not said_none:
                    self.log("gaming: pointer: " + line.strip())
                    said_none = True
            elif line.strip():
                self.log("gaming: pointer: " + line.strip())
        self.log(f"gaming: pointer reader ended ({p.wait()})")
        self.pointer = None

    def _stop_pointer(self):
        p, self.pointer_proc = self.pointer_proc, None
        if p is not None and p.poll() is None:
            p.terminate()
        self.pointer = None
        self.pointer_sent = None

    def _send_pointer(self):
        """The pointer to the effect when it changes: drawn while the screen is in space and the app's own cursor is
        showing. It stays when the pointer is still: 0.7.1 hid it after 3 seconds still, as gamescope hides its own
        (SteamOS starts gamescope with --hide-cursor-delay 3000), but a tester (Pierre Zammit, 22 Nov 2026) then saw
        only gamescope's arrow, which is not over what it points at on a moved screen. From 0.7.12 gamescope's own
        arrow is blanked while the screen is in space (_pointer_hide, xpointer.py), so only this one shows."""
        ptr = self.pointer
        shown = bool(ptr and ptr[2])
        value = (ptr[0], ptr[1], 1.0 if shown else 0.0, 0.0) if ptr else (0.0, 0.0, 0.0, 0.0)
        if value != self.pointer_sent:
            self.reshade.set_floats("pxr_cursor", value)
            self.pointer_sent = value

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
        self._send_mode(r)
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
        self.pointer_sent = None

    # ---- glasses ----
    def _start_glasses(self, g):
        self.glasses = g
        self.log(f"gaming: glasses {g.name} ({g.family}, {g.vendor:04x}:{g.product:04x})")
        self.head = fusion.HeadFusion(g.axes, bias=fusion.load_bias(self._glasses_key(g)))
        if self.head.bias_ready:
            self.log(f"gaming: gyro calibration loaded for these glasses ({self._glasses_key(g)})")
        if g.imu == "network":
            self.reader = imu.ImuReader(self._report, log=self.log)
        elif g.imu == "air":
            self.reader = hidimu.AirReader(self._report, g.product, log=self.log, record_path=RAW_IMU)
            self.reader.released = self.buttons_released  # still let go, when the glasses come back after a reset
        elif g.imu == "viture" and g.viture_tracking_default():
            self.reader = hidimu.VitureReader(self._report, g.product, log=self.log)
        if self.reader:
            self.reader.start()
        if g.control_link:
            self.control = SettingsControl(g, self.log, self._glasses_state, lambda text: self.log("gaming: " + text))
            self.control.want_3d = lambda: False  # the effect draws one picture: the glasses stay 2D
            self.control.steady_wide = False
            self.control.start()
        self._apply_mode()

    def _glasses_state(self, st):
        """The glasses' own settings as their control link reads them, logged when they change."""
        shown = {k: st.get(k) for k in ("space", "stereo", "anchor", "ultrawide")}
        if shown != getattr(self, "_last_glasses_state", None):
            self._last_glasses_state = shown
            self.log(f"gaming: glasses state {shown}")

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

    def _predicted_view(self):
        """The head a little ahead (PREDICT_S), from the gyro, to make up for the time to the glasses' picture."""
        q = self.head.view()
        g = fusion.qrot(q, self.head.last_gyro)  # the turn rate in the room's axes
        ang = math.sqrt(g[0] ** 2 + g[1] ** 2 + g[2] ** 2) * PREDICT_S
        if ang < 1e-6:
            return q
        k = math.sin(ang / 2) / (ang / PREDICT_S)
        return fusion.qnorm(fusion.qmul((math.cos(ang / 2), g[0] * k, g[1] * k, g[2] * k), q))

    def _restart_if_updated(self):
        """Another Pocket XR installed over this one: end, so systemd starts the new one (Restart=on-failure).
        A tester's update of 0.7.5 (Pierre Zammit, 23 Nov 2026) left 0.7.3's service running all afternoon: the
        installer restarted Decky but its restart of this service did not take, and its error was hidden. Whichever
        way Pocket XR is updated, the service now loads the new files within a few seconds."""
        now_installed = sendlogs.version()
        if now_installed in ("unknown", self.version):
            return
        self.log(f"gaming: Pocket XR {now_installed} was installed over this {self.version}; starting again to load it")
        sys.exit(RESTART_EXIT)

    # ---- the loop ----
    def run(self):
        self.log(f"gaming: Pocket XR's Gaming Mode service started (Pocket XR {self.version})")
        next_check = 0.0
        last_stats = time.monotonic()
        last_reports = 0
        step = 1.0 / SEND_HZ
        while True:
            now = time.monotonic()
            if now - self.version_checked >= VERSION_CHECK_S:
                self.version_checked = now
                self._restart_if_updated()
            if now >= next_check:
                next_check = now + 1.0
                in_gaming = wlreshade.socket_path() is not None
                with self.lock:
                    if in_gaming:
                        if self.reshade is None:
                            self._connect_gamescope()
                        self._check_glasses()
                        if self.reshade is not None:
                            self._watch_pointer(now)
                        self._log_head(now)
                        if self.cal_due is not None and now >= self.cal_due:
                            self.cal_due = None
                            self._start_calibration()
                        self._check_calibration()
                        if self.glasses and self.reshade and not self.effect_on and self.mode() == "space":
                            self._effect(True)
                    else:
                        if self.reshade is not None:
                            self._lost_gamescope("Gaming Mode ended")
                        self._stop_pointer()
                        if self.glasses is not None:
                            self._stop_glasses(put_back=True)
            if self.reshade is not None:
                try:
                    self.reshade.pump()
                    if self.effect_on and self.head is not None:
                        w, x, y, z = self._predicted_view()
                        self.reshade.paced_floats("pxr_quat", (x, y, z, w))
                        self._send_pointer()
                    if now - last_stats >= 10.0 and self.reshade is not None and self.reshade.pace_ms:
                        ms = sorted(self.reshade.pace_ms)
                        reports = self.head.count if self.head else 0
                        imu_rate = (reports - last_reports) / (now - last_stats)
                        last_reports = reports
                        self.log(f"gaming: {len(ms) / (now - last_stats):.0f} head updates a second, gamescope took "
                                 f"{ms[len(ms) // 2]:.1f} ms (median), {ms[-1]:.1f} ms (longest); "
                                 f"motion {imu_rate:.0f} reports a second")
                        self.reshade.pace_ms = []
                        last_stats = now
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
