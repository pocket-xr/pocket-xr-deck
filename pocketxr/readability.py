"""Readability: one screen, drawn about one screen pixel to one glasses pixel, so text is sharp on 1080p glasses.

The same switch as Pocket XR for Mac and Windows (from a Mac tester's change, November 2026: one 1440x810 screen
shown 30 degrees wide). On the Deck:

- Desktop Mode: the Deck's own screen alone ("Deck screen"), 30 degrees wide and in front. Its resolution stays the
  Deck's 1280x800: that is already below 1440x810, so its text is already as large, and changing the built-in
  panel's mode is not worth the risk. 1280 px across 30 degrees is about 43 px a degree, close to the 44 px a degree
  the Space draws app windows at (space.PIXELS_PER_DEGREE). In Steady mode, where the glasses hold a flat canvas, the
  screen is drawn at exactly its own pixels (the canvas scale that makes 800 px tall 800 canvas px).
- Gaming Mode: the game screen 30 degrees wide. The game picks its own resolution, so this cannot make its text
  larger (that is the game's resolution or interface size); it makes a game drawn 1280 px wide, the Deck's own,
  about one pixel to one glasses pixel.

Off puts back exactly what on changed, from the values saved when it was turned on (in the settings file, so a quit
or a crash in between changes nothing: it is still on at the next start, and off still puts them back).
"""
import json
import math
import os

WIDTH_DEG = 30.0
DECK_SCREEN = (1280, 800)
SAVED = "readability_saved"


def deck_size_deg(distance, screen=DECK_SCREEN):
    """(width, height) in degrees of the Deck screen 30 degrees wide at this distance (a flat window's height)."""
    w_m = 2 * distance * math.tan(math.radians(WIDTH_DEG) / 2)
    h_m = w_m * screen[1] / screen[0]
    return WIDTH_DEG, math.degrees(2 * math.atan(h_m / 2 / distance))


def flat_canvas_scale(out_h, screen_h=DECK_SCREEN[1]):
    """Steady mode's canvas scale (space.flat_layout) that draws the screen at its own pixels."""
    return max(0.3, min(1.0, screen_h / float(out_h or 1080)))


def gaming_size(fov_v_deg, aspect):
    """Gaming Mode's size (gaming._send_view: width = 2 atan(tan(fov_v / 2) * aspect * size)) for 30 degrees wide."""
    th = math.tan(math.radians(fov_v_deg) / 2) * aspect
    return max(0.3, min(1.2, math.tan(math.radians(WIDTH_DEG) / 2) / th))


def desktop_on(settings, deck_pose, out_h):
    """Desktop Mode, on: (what to set in settings, the Deck screen's new pose or None, before, after). deck_pose is the
    Deck screen's pose now (space.Pose) or None when it has none yet."""
    before = {"source": settings.get("source"), "canvas_scale": settings.get("canvas_scale"),
              "deck_pose": deck_pose.to_json() if deck_pose is not None else None}
    changes = {"readability": True, SAVED: before, "source": "deck", "canvas_scale": round(flat_canvas_scale(out_h), 3)}
    pose = None
    if deck_pose is not None:
        pose = deck_pose.copy()
        pose.wdeg, pose.hdeg = deck_size_deg(pose.distance)
    after = {"source": "deck", "canvas_scale": changes["canvas_scale"],
             "deck_pose": pose.to_json() if pose is not None else "30 degrees wide when it appears"}
    return changes, pose, before, after


def desktop_off(settings):
    """Desktop Mode, off: (what to set in settings, the Deck screen's pose to put back as JSON, or None to let it be
    made afresh, or False when nothing was saved and it stays as it is)."""
    saved = settings.get(SAVED) or {}
    changes = {"readability": False, SAVED: None}
    for k in ("source", "canvas_scale"):
        if saved.get(k) is not None:
            changes[k] = saved[k]
    pose = saved.get("deck_pose", False) if saved else False
    return changes, pose


def gaming_on(settings, fov_v_deg, aspect):
    before = {"size": settings.get("size")}
    size = round(gaming_size(fov_v_deg, aspect), 3)
    return {"readability": True, SAVED: before, "size": size}, before, {"size": size}


def gaming_off(settings):
    saved = settings.get(SAVED) or {}
    changes = {"readability": False, SAVED: None}
    if saved.get("size") is not None:
        changes["size"] = saved["size"]
    return changes


# ---- Text size, and both for the PC screens a phone streams from this computer (pocketxr/host) ----
# As Pocket XR for Mac (SpaceSettings: normalScreenSize, readabilityScreenSize, textScales, screenSize(textScale:)):
# Standard screens are 1920x1080; Text size 125% and 150% lay each one out as 1536x864 and 1280x720 (1920x1080 over
# the scale, kept 16:9 and a multiple of 16 wide), so everything is drawn larger at the same width as seen; Readability
# lays it out as 1440x810 and takes the place of Text size.
#
# A PC screen here is a KWin virtual output at the size the phone asks for (its window's shape, often 1920x1080). The
# phone decides how wide it is seen, so this side changes how the desktop is drawn into it: KWin's scale on that output,
# as Plasma's own Display settings set it. The output keeps all its pixels and KWin and its apps draw at that scale, so
# text stays sharp (on the Mac, the same comes from HiDPI virtual displays). Plasma's Wayland session only: on X11 KDE
# has one scale for every screen, and GNOME on Ubuntu shows only the main screen, which Pocket XR does not make.
NORMAL_SCREEN = (1920, 1080)
READABILITY_SCREEN = (1440, 810)
TEXT_SCALES = (100, 125, 150)
TEXT_SCALE_KEY = "text_scale"
SCALE_MAX = 3.0


def text_scale_of(value):
    """A Text size the app offers: the nearest of TEXT_SCALES, Standard (100) for anything else."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 100
    if v != v:
        return 100
    return min(TEXT_SCALES, key=lambda s: (abs(s - v), s))


def screen_size(text_scale):
    """A screen's layout size for a Text size, as the Mac's: 1920x1080 over it, 16:9 and a multiple of 16 wide."""
    s = min(max(float(text_scale), 100.0), 400.0) / 100.0
    w = int(round(NORMAL_SCREEN[0] / s / 16.0)) * 16
    return w, w * 9 // 16


def label(text_scale):
    return "Standard" if text_scale_of(text_scale) == 100 else f"{text_scale_of(text_scale)}%"


def host_scale(width, readability_on, text_scale):
    """KWin's scale for a PC screen [width] pixels wide: Readability lays it out READABILITY_SCREEN wide, else Text
    size draws everything larger by its scale. 1 (none) at Standard; never below 1, so a small screen is not made
    smaller; rounded to 1/120, the steps Wayland's fractional scaling uses."""
    if readability_on:
        s = float(width) / READABILITY_SCREEN[0]
    else:
        s = text_scale_of(text_scale) / 100.0
    s = max(1.0, min(SCALE_MAX, s))
    return round(round(s * 120) / 120.0, 4)


def host_line(name, output, width, height, readability_on, text_scale, scale):
    """The log's line for what a PC screen was made at."""
    lw, lh = int(round(width / scale)), int(round(height / scale))
    why = "Readability" if readability_on else f"Text size {label(text_scale)}"
    return (f"host: {name} ({output}) made at {width}x{height}, scale {scale:g} ({why}): apps see {lw}x{lh}")


DESKTOP_SETTINGS = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "pocket-xr-deck",
                                "settings.json")  # the desktop app's (app.CONFIG)


def desktop_choice(path=None):
    """(Readability on, Text size) from the desktop app's settings file, which the host service reads when a PC
    screen is made; (False, 100) without one."""
    try:
        with open(path or DESKTOP_SETTINGS) as f:
            s = json.load(f)
    except (OSError, ValueError):
        return False, 100
    if not isinstance(s, dict):
        return False, 100
    return bool(s.get("readability")), text_scale_of(s.get(TEXT_SCALE_KEY, 100))
