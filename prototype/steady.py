#!/usr/bin/env python3
"""Steady mode in 6DoF, as Pocket XR 1.4 does it on the phone.

The glasses hold the picture, not the app: in Ultrawide at its largest size, the Aura's own Spatial
Anchor keeps its wide canvas in place in the room as the head moves and turns. The app then draws
flat on that canvas (deckxr.py --canvas).

  steady.py status   read the glasses' settings, change nothing
  steady.py on       2D, Ultrawide on, largest size, then Spatial Anchor on (last)
  steady.py off      Spatial Anchor off (first), then Ultrawide off

Per glasses (from Pocket XR's SteadyMode):
  XREAL Aura                    Pocket XR turns Spatial Anchor on and off itself (proven 10 Nov 2026).
  XREAL One series + XREAL Eye  Pocket XR sets up the canvas; you turn 6DoF on in the glasses' menu
                                (no confirmed command for it, so it is never guessed). Untested.
  VITURE                        not yet: 6DoF waits on VITURE's SDK.
  Others                        no 6DoF source.
"""
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import control as c  # noqa: E402

XREAL = 0x3318
VITURE = 0x35CA
AURA = {0x0439, 0x043A}
ONE_FAMILY = {0x0435, 0x0436, 0x0437, 0x0438, 0x043D, 0x043E, 0x0443, 0x0444}
SIZE_SAME = 0.005
# As Pocket XR (GlassesDisplayCommands): one set at a time, at least 3 s apart, so each is read back and the display's
# re-plug has passed; Spatial Anchor tried twice. On the Deck (11 Nov 2026) an anchor set sent within a second of
# Ultrawide was refused with 5001.
SET_GAP_S = 3.0
ANCHOR_TRIES = 2

TURN_ON_6DOF = "Steady mode in 6DoF: turn on 6DoF in your glasses' menu (Spatial Display) so the screen stays put as you move."
TURN_OFF_6DOF = "Steady mode is off: turn 6DoF off again in your glasses' menu."


def log(msg):
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


def usb_devices():
    """(vendor, product, [interface classes]) for each USB device, from sysfs."""
    out = []
    for d in glob.glob("/sys/bus/usb/devices/*"):
        try:
            vid = int(open(os.path.join(d, "idVendor")).read(), 16)
            pid = int(open(os.path.join(d, "idProduct")).read(), 16)
        except (OSError, ValueError):
            continue
        classes = []
        for i in glob.glob(d + ":*/bInterfaceClass"):
            try:
                classes.append(int(open(i).read(), 16))
            except (OSError, ValueError):
                pass
        out.append((vid, pid, classes))
    return out


def which_glasses():
    devs = usb_devices()
    eye = any(v == XREAL and 0x0E in cls for v, p, cls in devs if p not in AURA)
    for v, p, _ in devs:
        if v == XREAL and p in AURA:
            return "aura", eye
    for v, p, _ in devs:
        if v == XREAL and p in ONE_FAMILY:
            return "one", eye
    for v, p, _ in devs:
        if v == VITURE:
            return "viture", eye
        if v == XREAL:
            return "xreal-other", eye
    return None, eye


def flag(a):
    return 0 if a is None or a.value is None else int(a.value)


def read_until(link, mtype, want, seconds):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        a = link.get(mtype)
        if a is not None and flag(a) == want:
            return True
        time.sleep(0.7)
    return False


def status(link):
    stereo = flag(link.get(c.STEREO_GET))
    wide = flag(link.get(c.ULTRAWIDE_GET))
    anchor = flag(link.get(c.ANCHOR_GET))
    size = link.get(c.SIZE_GET)
    rng = link.get(c.SIZE_RANGE)
    log(f"glasses: {'3D' if stereo == 1 else '2D'}, Ultrawide {'on' if wide else 'off'}, Spatial Anchor {'on' if anchor else 'off'}, "
        f"size {size.value if size else '?'} of {rng.value if rng else '?'} to {rng.value3 if rng else '?'}")
    return stereo, wide, anchor


def canvas_on(link):
    """2D, Ultrawide on, the largest size Ultrawide offers. Each step is read back."""
    stereo, wide, _ = status(link)
    if stereo == 1:
        log("leaving 3D")
        link.request(c.stereo_set, False)
        if not read_until(link, c.STEREO_GET, 0, 8):
            log("the glasses stayed in 3D; stopping")
            return False
        time.sleep(SET_GAP_S)
    if wide != 1:
        log("Ultrawide on (the glasses' display re-plugs, a few seconds)")
        link.request(c.ultrawide_set, True)
        if not read_until(link, c.ULTRAWIDE_GET, 1, 10):
            log("Ultrawide did not come on; stopping")
            return False
        time.sleep(SET_GAP_S)
    rng = link.get(c.SIZE_RANGE)
    size = link.get(c.SIZE_GET)
    top = rng.value3 if rng else None
    if top is not None and size is not None and size.value is not None and size.value < top - SIZE_SAME:
        log(f"screen size {size.value:.2f} -> {top:.2f}")
        link.request(c.size_set, float(top))
        time.sleep(1.0)
        link.get(c.SIZE_GET)
        time.sleep(SET_GAP_S)
    return True


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    model, eye = which_glasses()
    log(f"glasses: {model or 'none found'}{', XREAL Eye seen' if eye else ''}")
    if model == "viture":
        log("VITURE: 6DoF waits on VITURE's SDK. Nothing sent.")
        return 1
    if model not in ("aura", "one"):
        log("These glasses have no 6DoF that Pocket XR can use. Nothing sent.")
        return 1
    app_anchor = model == "aura"
    if cmd in ("on", "off") and model == "one" and not eye:
        log("The One series holds 6DoF only with the XREAL Eye attached, and none is seen. Nothing sent.")
        return 1

    link = c.Link(log=log)
    hold = 2.0
    try:
        if cmd == "status":
            status(link)
        elif cmd == "on":
            hold = 20.0
            if not canvas_on(link):
                return 1
            if app_anchor:
                for attempt in range(1, ANCHOR_TRIES + 1):
                    log(f"Spatial Anchor on (try {attempt})")
                    link.request(c.anchor_set, True)
                    if read_until(link, c.ANCHOR_GET, 1, SET_GAP_S):
                        break
                else:
                    log("Spatial Anchor did not read back on")
                    return 1
            else:
                log(TURN_ON_6DOF)
            status(link)
            log("Steady mode in 6DoF is on.")
        elif cmd == "off":
            hold = 20.0
            if app_anchor:
                for attempt in range(1, ANCHOR_TRIES + 1):
                    log(f"Spatial Anchor off (try {attempt})")
                    link.request(c.anchor_set, False)
                    if read_until(link, c.ANCHOR_GET, 0, SET_GAP_S):
                        break
                time.sleep(SET_GAP_S)
            log("Ultrawide off")
            link.request(c.ultrawide_set, False)
            read_until(link, c.ULTRAWIDE_GET, 0, 10)
            if not app_anchor:
                log(TURN_OFF_6DOF)
            status(link)
            log("Steady mode is off.")
        else:
            print(__doc__)
            return 2
    finally:
        # Held open after a change, as Pocket XR does: the One dropped an app-set mode when the link closed
        # within a few seconds of the display re-plugging (30 Oct 2026); 20 s fixed it there.
        log(f"holding the link {hold:.0f} s")
        time.sleep(hold)
        link.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
