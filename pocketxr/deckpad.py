"""The Steam Deck's back buttons, read straight from its controller (hidraw), alongside Steam.

Steam keeps the controller for the desktop (trackpad mouse, buttons as keys), and the back buttons
are free there by default, so Pocket XR uses them. Reading hidraw does not take the controller from Steam.

Reports are 64 bytes: a 4 byte header (version u16, type 0x09, length 0x40), a u32 packet number,
then the buttons as a u64 little endian at byte 8. Bits checked by pressing each button on Mike's
Deck (11 Nov 2026): L4 bit 41, R4 bit 42, L5 bit 15, R5 bit 16, A bit 7.

The stick clicks (L3, R3) are bits 22 and 26: byte 10 bit 6 and byte 11 bit 2, as Linux's hid-steam driver reads them
(steam_do_deck_input_event). Not yet checked by pressing them on a Deck. They are used by games, so they do Pocket
XR's jobs only held long (HOLD_STICK_S) or clicked three times (STICK_TAPS), and Gaming Mode lets them be turned off.
"""
import glob
import os
import struct
import threading
import time

VALVE = "000028DE"
DECK = "00001205"
REPORT_STATE = 0x09

BUTTONS = {
    "L4": 1 << 41,
    "R4": 1 << 42,
    "L5": 1 << 15,
    "R5": 1 << 16,
}
HOLD_S = 0.8
STICKS = {
    "L3": 1 << 22,
    "R3": 1 << 26,
}
HOLD_STICK_S = 1.0   # a stick held down this long is a "hold"
TAP_S = 0.35         # a stick click let go within this is one click of a run
TAP_GAP_S = 0.45     # the next click of a run starts within this of the last one ending; then the run is counted


def find_device():
    """The Deck controller's hidraw that sends 64 byte state reports (its third interface)."""
    found = []
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        try:
            with open(os.path.join(h, "device", "uevent")) as f:
                ev = f.read()
        except OSError:
            continue
        if f"HID_ID=0003:{VALVE}:{DECK}" in ev:
            iface = os.path.basename(os.path.realpath(os.path.join(h, "device", "..")))
            found.append((iface, "/dev/" + os.path.basename(h)))
    # Interface x.2 carries the gamepad state; try it first, then the others.
    found.sort(key=lambda t: (not t[0].endswith(".2"), t[0]))
    return [dev for _, dev in found]


class DeckButtons(threading.Thread):
    """Calls on_event(name, kind) with kind "tap" (pressed and let go before HOLD_S) or "hold" (held HOLD_S), and
    "down" and "up" as each button goes down and comes up (for PC VR's hold to leave, which shows its own ring).
    For the stick clicks (STICKS): "hold" (held HOLD_STICK_S), and "double" or "triple" for a quick run of clicks."""

    def __init__(self, on_event, log=print):
        super().__init__(daemon=True)
        self.on_event = on_event
        self.log = log
        self.stop = False
        self.device = None
        self.report = None  # the newest state report (bytes), for PC VR's controllers

    def run(self):
        while not self.stop:
            for dev in find_device():
                try:
                    fd = os.open(dev, os.O_RDONLY)
                except OSError as e:
                    self.log(f"buttons: {dev} not readable ({e})")
                    continue
                try:
                    if self._read(fd, dev):
                        break
                finally:
                    os.close(fd)
            self.device = None
            time.sleep(3.0)

    def _read(self, fd, dev):
        down_at = {}
        held = set()
        prev = 0
        seen = False
        self.sticks = Sticks(self.on_event)
        while not self.stop:
            try:
                d = os.read(fd, 64)
            except OSError:
                return seen
            if len(d) < 16 or d[2] != REPORT_STATE:
                continue
            if not seen:
                seen = True
                self.device = dev
                self.log(f"buttons: reading {dev}")
            self.report = d
            bits = struct.unpack_from("<Q", d, 8)[0]
            now = time.monotonic()
            for name, mask in BUTTONS.items():
                is_down = bool(bits & mask)
                was_down = bool(prev & mask)
                if is_down and not was_down:
                    down_at[name] = now
                    self.on_event(name, "down")
                elif is_down and name not in held and now - down_at.get(name, now) >= HOLD_S:
                    held.add(name)
                    self.on_event(name, "hold")
                elif not is_down and was_down:
                    self.on_event(name, "up")
                    if name in held:
                        held.discard(name)
                    else:
                        self.on_event(name, "tap")
            self.sticks.feed(bits, now)
            prev = bits
        return seen


class Sticks:
    """Turns the stick clicks' bits, fed with each report (about 250 a second on a Deck), into "hold", "double" and
    "triple" events. A run of clicks is counted once no new click starts within TAP_GAP_S; a run that ends in a hold
    counts as the hold alone."""

    def __init__(self, on_event):
        self.on_event = on_event
        self.prev = 0
        self.down_at = {}
        self.held = set()
        self.taps = {}     # name -> clicks in the run so far
        self.up_at = {}    # name -> when the last click of the run ended

    def feed(self, bits, now):
        for name, mask in STICKS.items():
            is_down, was_down = bool(bits & mask), bool(self.prev & mask)
            if is_down and not was_down:
                self.down_at[name] = now
            elif is_down and name not in self.held and now - self.down_at.get(name, now) >= HOLD_STICK_S:
                self.held.add(name)
                self.taps.pop(name, None)
                self.on_event(name, "hold")
            elif not is_down and was_down:
                if name in self.held:
                    self.held.discard(name)
                elif now - self.down_at.get(name, now) <= TAP_S:
                    self.taps[name] = self.taps.get(name, 0) + 1
                    self.up_at[name] = now
                else:
                    self.taps.pop(name, None)  # a press longer than a click and shorter than a hold: nothing
            elif not is_down and name in self.taps and now - self.up_at[name] > TAP_GAP_S:
                n = self.taps.pop(name)
                if n in (2, 3):
                    self.on_event(name, "double" if n == 2 else "triple")
        self.prev = bits
