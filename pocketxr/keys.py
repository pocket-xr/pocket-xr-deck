"""Keyboard keys for what the Deck's back buttons do, so any controller can do them through Steam Input.

The Deck's back buttons (L4, L5, R4, R5) are read from its own controller (deckpad.py). A Steam Controller or another
pad has no such buttons, but Steam Input can map any of its buttons to a keyboard key (a tester asked for this, November 2026: Pierre
Zammit, with a Steam Controller).

Where the keys are read: in Gaming Mode from gamescope's X screens (xpointer.py, which sees the keys Steam Input sends
there); this module's reader (KeyActions) is Desktop Mode's, from the kernel's input devices (evdev), whichever window
has focus. On a Deck (22 Nov 2026) the built-in keyboard and controller devices were readable by the user, but a new
virtual keyboard (uinput) was not ("Permission denied"), so a pad's keys may not reach Desktop Mode this way.

Actions and their default keys (the "keys" setting changes them: a Linux KEY_ name, a list of them, or "" for none):

- recentre       Stop, Pause          (L4 tap)
- switch_view    Next, Scroll Lock    (L4 hold: Window in space / Steady, or in Gaming Mode the next mode)
- next_app       none                 (R4 tap)
- deck_or_apps   none                 (R4 hold)
- launcher       none                 (L5 tap)
- lock           none                 (L5 hold)
- control_center none                 (R5 tap)
- adjust_all     none                 (R5 hold)

Stop and Next are media keys in Steam Input's keyboard, which games rarely use. Steam Input's keyboard has no Pause or
Scroll Lock (a tester's screenshots, Pierre Zammit, 22 Nov 2026: F1 to F12, letters, Insert, Home, Page Up, Delete,
End, Page Down, the arrows, Num Lock, the number pad, and Play, Stop, Next and Prev); they still work from a real
keyboard. A key press does the action at once; it is not passed on differently (the game still gets the key as usual).
"""
import glob
import os
import select
import struct
import threading
import time

ACTIONS = {
    "recentre": ("L4", "tap"),
    "switch_view": ("L4", "hold"),
    "next_app": ("R4", "tap"),
    "deck_or_apps": ("R4", "hold"),
    "launcher": ("L5", "tap"),
    "lock": ("L5", "hold"),
    "control_center": ("R5", "tap"),
    "adjust_all": ("R5", "hold"),
}
DEFAULT_KEYS = {"recentre": ["KEY_STOPCD", "KEY_PAUSE"], "switch_view": ["KEY_NEXTSONG", "KEY_SCROLLLOCK"]}

# Linux input-event-codes.h: the keys worth offering for this (rarely used ones first)
CODES = {
    "KEY_STOPCD": 166, "KEY_NEXTSONG": 163, "KEY_PREVIOUSSONG": 165, "KEY_PLAYPAUSE": 164,
    "KEY_PAUSE": 119, "KEY_SCROLLLOCK": 70, "KEY_SYSRQ": 99, "KEY_INSERT": 110, "KEY_MENU": 139,
    "KEY_F1": 59, "KEY_F2": 60, "KEY_F3": 61, "KEY_F4": 62, "KEY_F5": 63, "KEY_F6": 64, "KEY_F7": 65, "KEY_F8": 66,
    "KEY_F9": 67, "KEY_F10": 68, "KEY_F11": 87, "KEY_F12": 88,
    "KEY_F13": 183, "KEY_F14": 184, "KEY_F15": 185, "KEY_F16": 186, "KEY_F17": 187, "KEY_F18": 188,
    "KEY_F19": 189, "KEY_F20": 190, "KEY_F21": 191, "KEY_F22": 192, "KEY_F23": 193, "KEY_F24": 194,
    "KEY_HOME": 102, "KEY_END": 107, "KEY_PAGEUP": 104, "KEY_PAGEDOWN": 109,
    "KEY_KP0": 82, "KEY_KP1": 79, "KEY_KP2": 80, "KEY_KP3": 81, "KEY_KP4": 75, "KEY_KP5": 76, "KEY_KP6": 77,
    "KEY_KP7": 71, "KEY_KP8": 72, "KEY_KP9": 73,
}
EV_KEY = 1
EVENT = struct.Struct("llHHi")  # struct input_event on 64-bit Linux: time (two longs), type, code, value


def key_map(settings_keys=None):
    """{key code: action} from the "keys" setting over the defaults; unknown names are left out. A setting replaces
    that action's default keys: one name, a list of names, or "" (or []) for none."""
    keys = {a: list(n) for a, n in DEFAULT_KEYS.items()}
    for action, names in (settings_keys or {}).items():
        if action in ACTIONS:
            keys[action] = [names] if isinstance(names, str) else list(names or [])
    out = {}
    for action, names in keys.items():
        for name in names:
            code = CODES.get(name)
            if code is not None:
                out[code] = action
    return out


def has_keys(caps_hex, codes):
    """Whether an input device's key capability bitmap (sysfs capabilities/key, hex words, highest first) has any
    of these codes."""
    words = caps_hex.split()
    if not words:
        return False
    bits = 0
    for w in words:
        bits = (bits << 64) | int(w, 16)
    return any(bits >> c & 1 for c in codes)


def keyboards(codes, root="/sys/class/input"):
    """[/dev/input/eventN] of the devices that have one of these keys."""
    out = []
    for d in sorted(glob.glob(os.path.join(root, "event*"))):
        try:
            with open(os.path.join(d, "device", "capabilities", "key")) as f:
                caps = f.read()
        except OSError:
            continue
        try:
            if has_keys(caps, codes):
                out.append("/dev/input/" + os.path.basename(d))
        except ValueError:
            continue
    return out


class KeyActions(threading.Thread):
    """Calls on_action(action) for each configured key pressed (key down; auto-repeat is left out)."""

    def __init__(self, on_action, settings_keys=None, log=print):
        super().__init__(daemon=True, name="keys")
        self.on_action = on_action
        self.log = log
        self.map = key_map(settings_keys)
        self.stop = False
        self.devices = {}  # path -> fd
        self.unreadable = set()

    def _rescan(self):
        found = keyboards(self.map)
        for path in list(self.devices):
            if path not in found:
                os.close(self.devices.pop(path))
        for path in found:
            if path in self.devices or path in self.unreadable:
                continue
            try:
                self.devices[path] = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
                self.log(f"keys: reading {path} ({_name(path)})")
            except OSError as e:
                self.unreadable.add(path)
                self.log(f"keys: {path} ({_name(path)}) not readable ({e})")

    def run(self):
        if not self.map:
            return
        names = ", ".join(f"{a} {n}" for a, n in sorted(
            (a, next(k for k, c in CODES.items() if c == code)) for code, a in self.map.items()))
        self.log(f"keys: {names}")
        next_scan = 0.0
        while not self.stop:
            now = time.monotonic()
            if now >= next_scan:
                self._rescan()
                next_scan = now + 5.0
            fds = list(self.devices.values())
            if not fds:
                time.sleep(1.0)
                continue
            r, _, _ = select.select(fds, [], [], 1.0)
            for fd in r:
                try:
                    data = os.read(fd, EVENT.size * 64)
                except OSError:
                    for p, f in list(self.devices.items()):
                        if f == fd:
                            os.close(self.devices.pop(p))
                    continue
                for i in range(0, len(data) - EVENT.size + 1, EVENT.size):
                    _, _, etype, code, value = EVENT.unpack_from(data, i)
                    if etype == EV_KEY and value == 1 and code in self.map:
                        try:
                            self.on_action(self.map[code])
                        except Exception as e:  # noqa: BLE001
                            self.log(f"keys: {self.map[code]} failed ({e})")


def _name(path):
    try:
        with open(f"/sys/class/input/{os.path.basename(path)}/device/name") as f:
            return f.read().strip()
    except OSError:
        return "?"
