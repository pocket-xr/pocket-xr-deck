"""Share layouts and Import layouts: the window presets as one small JSON file that Pocket XR on Android reads and
writes too, so a layout made on the phone comes to the Deck and back. No server: the user moves the file themselves.

The file (both apps, version 1):
  {"format": "pocket-xr-layouts", "version": 1, "made_by": "deck", "app_version": "0.3.0",
   "presets": [{"name": "Workspace 1", "windows": [{"app": {"name": "Firefox", "android": null, "deck": "firefox"},
       "yaw_deg": 0.0, "pitch_deg": -5.0, "distance_m": 1.5, "width_deg": 40.0, "height_deg": 22.5, "curve": 0.0}]}]}

Angles in degrees, yaw left positive, pitch up positive, from the Space's front: the Deck's space.py keeps Android's
numbers, so nothing is converted. `deck` is the app's WM_CLASS class, as the Deck's presets keep it.

On import an app is found on this Deck by its `deck` id, then by its name (case and punctuation ignored), then by a
short table of names the same app has on Android and on Linux. A window whose app is not here is left out, and a
layout with no window left is left out. Imported layouts go on top, at most 8 kept, a name in use gets " (2)".
"""
import glob
import json
import math
import os
import time
import unicodedata

from . import space as S
from .i18n import tr

FORMAT = "pocket-xr-layouts"
VERSION = 1
PREFIX = "pocketxr-layouts"
NAME_MAX = 60

# Names the same app has on Android and on the Deck (its desktop entry's Name). Only the same app on both: a phone-only
# app (YouTube, Messages) is never swapped for something else.
ALIASES = (
    ("Chrome", "Google Chrome"),
    ("Edge", "Microsoft Edge"),
    ("Brave", "Brave Browser", "Brave Web Browser"),
    ("Firefox", "Firefox Web Browser", "Mozilla Firefox"),
    ("VLC", "VLC media player"),
    ("Telegram", "Telegram Desktop"),
)


class LayoutsError(Exception):
    """A file that cannot be imported; str() is the line to show the user."""


def norm(name):
    """A name to compare: lower case, letters and digits only ("Google-chrome" and "Google Chrome" are the same)."""
    s = unicodedata.normalize("NFKC", str(name or "")).casefold()
    return "".join(c for c in s if c.isalnum())


_ALIAS = {}
for _group in ALIASES:
    for _n in _group:
        _ALIAS[norm(_n)] = frozenset(norm(m) for m in _group)


class LocalApp:
    """An app on this Deck: the name the user sees, the WM_CLASS a preset keeps for it, and the ids it is known by."""
    __slots__ = ("name", "cls", "ids")

    def __init__(self, name, cls, ids=()):
        self.name, self.cls = name, cls
        self.ids = {i.lower() for i in (cls, *ids) if i}

    def __repr__(self):
        return f"LocalApp({self.name!r}, {self.cls!r})"


def _stem(desktop_id):
    return desktop_id[:-len(".desktop")] if desktop_id.endswith(".desktop") else desktop_id


def local_apps(installed=(), seen=()):
    """This Deck's apps. installed: apps.App from the app menu (its desktop entries); seen: WM_CLASS classes Pocket XR
    has already had windows of (saved places and presets), each its own app named by its class.

    A desktop entry's class is its StartupWMClass when it has one, else the class an app usually has: the entry's id
    without ".desktop", its last dotted part for ids like org.kde.dolphin. A class already seen that is one of those
    is taken over the guess, since that is what the app's windows really have."""
    seen = [c for c in seen if c]
    seen_lower = {c.lower(): c for c in seen}
    out = []
    for a in installed:
        stem = _stem(a.id)
        ids = [a.wm_class, stem, stem.rsplit(".", 1)[-1]]
        cls = next((seen_lower[i.lower()] for i in ids if i and i.lower() in seen_lower), None)
        if cls is None:  # a class seen that is the app's name: Google-chrome for Google Chrome
            cls = next((c for c in seen if norm(c) == norm(a.name)), None)
        if cls is None:
            cls = a.wm_class or stem.rsplit(".", 1)[-1]
        out.append(LocalApp(a.name, cls, ids))
    known = set().union(*(a.ids for a in out)) if out else set()
    for c in seen:
        if c.lower() not in known:
            out.append(LocalApp(_pretty(c), c))
            known.add(c.lower())
    return out


def _pretty(cls):
    """A name for a class no desktop entry names: "org.kde.dolphin" -> "Dolphin", "Google-chrome" -> "Google-chrome"."""
    s = cls.rsplit(".", 1)[-1] if "." in cls else cls
    return s[:1].upper() + s[1:]


def name_of(cls, apps):
    """The name the user sees for a preset's app."""
    c = (cls or "").lower()
    return next((a.name for a in apps if c in a.ids), None) or _pretty(cls or "")


def find(app, apps):
    """The class to keep in a preset for a file's app on this Deck, or None when it is not here."""
    if not isinstance(app, dict):
        return None
    deck = app.get("deck")
    if isinstance(deck, str) and deck.strip():
        d = deck.strip().lower()
        if any(d in a.ids for a in apps):
            return deck.strip()
    n = norm(app.get("name"))
    if not n:
        return None
    for a in apps:
        if norm(a.name) == n:
            return a.cls
    for a in apps:  # a window seen but not in the app menu: its class is all the name there is
        if norm(a.cls) == n:
            return a.cls
    group = _ALIAS.get(n)
    if group:
        for a in apps:
            if norm(a.name) in group:
                return a.cls
    return None


# ---------------- writing ----------------
def export(presets, apps, app_version):
    """The file's content for the Deck's presets (newest first, as the Store keeps them)."""
    out = []
    for pr in presets:
        wins = []
        for w in pr.get("windows", []):
            cls = w.get("app") or ""
            p = S.Pose.from_json(w.get("pose", {}))
            wins.append({
                "app": {"name": name_of(cls, apps), "android": None, "deck": cls},
                "yaw_deg": round(p.yaw, 3), "pitch_deg": round(p.pitch, 3), "distance_m": round(p.distance, 3),
                "width_deg": round(p.wdeg, 3), "height_deg": round(p.hdeg, 3), "curve": round(p.curve, 3),
            })
        out.append({"name": pr.get("name", ""), "windows": wins})
    return {"format": FORMAT, "version": VERSION, "made_by": "deck", "app_version": app_version, "presets": out}


def file_name(now=None):
    return time.strftime(f"{PREFIX}-%Y-%m-%d.json", time.localtime(time.time() if now is None else now))


def write(path, data):
    """UTF-8, LF, written whole or not at all."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".part"
    with open(tmp, "w", encoding="utf-8", newline="\n") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)
    return path


def newest(downloads):
    """The newest pocketxr-layouts*.json in a folder, or None."""
    files = [f for f in glob.glob(os.path.join(downloads, PREFIX + "*.json")) if os.path.isfile(f)]
    return max(files, key=os.path.getmtime) if files else None


# ---------------- reading ----------------
def check(data, file=""):
    """The file's presets when it is a layouts file this Pocket XR can read, else LayoutsError."""
    if not isinstance(data, dict) or data.get("format") != FORMAT:
        raise LayoutsError(tr("{file} is not a Pocket XR layouts file.", file=file))
    v = data.get("version")
    if isinstance(v, bool) or not isinstance(v, (int, float)) or v != int(v) or v < 1:
        raise LayoutsError(tr("{file} is not a Pocket XR layouts file.", file=file))
    if v > VERSION:
        raise LayoutsError(tr("{file} is from a newer Pocket XR. Update Pocket XR to import it.", file=file))
    presets = data.get("presets")
    if not isinstance(presets, list):
        raise LayoutsError(tr("{file} is not a Pocket XR layouts file.", file=file))
    return presets


def read(path):
    name = os.path.basename(path)
    try:
        with open(path, encoding="utf-8-sig") as f:
            data = json.load(f)
    except (OSError, ValueError):
        raise LayoutsError(tr("{file} is not a Pocket XR layouts file.", file=name)) from None
    return check(data, name)


def _num(w, key, default):
    v = w.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return default
    return float(v)


def pose_of(w):
    """A file's window as the Deck's Pose, kept within the Deck's limits."""
    wdeg = S.clamp(_num(w, "width_deg", S.DEFAULT_WIDTH_DEG), S.DEPTH_MIN_SIZE_DEG, S.MAX_WIDTH_DEG)
    hdeg = S.clamp(_num(w, "height_deg", S.DEFAULT_HEIGHT_DEG), S.DEPTH_MIN_SIZE_DEG, S.MAX_HEIGHT_DEG)
    return S.Pose(
        yaw=S.wrap(_num(w, "yaw_deg", 0.0)),
        pitch=S.clamp(_num(w, "pitch_deg", 0.0), -S.MAX_PITCH, S.MAX_PITCH),
        distance=S.clamp(_num(w, "distance_m", S.DEFAULT_DISTANCE), S.MIN_DISTANCE, S.MAX_DISTANCE),
        wdeg=wdeg, hdeg=hdeg,
        curve=S.clamp(_num(w, "curve", 0.0), 0.0, min(S.CURVE_MAX, S.max_curve(wdeg))),
    )


def _free_name(name, used):
    if name not in used:
        return name
    n = 2
    while f"{name} ({n})" in used:
        n += 1
    return f"{name} ({n})"


def merge(store_presets, file_presets, apps):
    """Imported presets on top of the Deck's own, as saving one does. Returns (presets, added, left_out) where added is
    how many imported layouts are kept and left_out the names of the apps whose windows were left out, one a window."""
    new, left_out = [], []
    used = {p.get("name") for p in store_presets}
    for pr in file_presets:
        if not isinstance(pr, dict):
            continue
        wins = []
        for w in pr.get("windows") or []:
            if not isinstance(w, dict):
                continue
            app = w.get("app")
            cls = find(app, apps)
            if cls is None:
                nm = app.get("name") if isinstance(app, dict) else None
                left_out.append(nm if isinstance(nm, str) and nm.strip() else "?")
                continue
            wins.append({"app": cls, "pose": pose_of(w).to_json()})
        if not wins:
            continue
        name = pr.get("name")
        name = name.strip()[:NAME_MAX] if isinstance(name, str) and name.strip() else ""
        if not name:
            k = 1
            while tr("Workspace {n}", n=k) in used:
                k += 1
            name = tr("Workspace {n}", n=k)
        name = _free_name(name, used)
        used.add(name)
        new.append({"name": name, "windows": wins})
    merged = (new + list(store_presets))[:S.PRESETS_MAX]
    return merged, min(len(new), S.PRESETS_MAX), left_out


def _and(names):
    if len(names) == 1:
        return names[0]
    return tr("{first} and {last}", first=", ".join(names[:-1]), last=names[-1])


def summary(added, left_out):
    """"Added 3 layouts. 2 windows were left out: Messages and Phone aren't on this Deck." """
    if added == 0:
        parts = [tr("No layouts were added.")]
    elif added == 1:
        parts = [tr("Added 1 layout.")]
    else:
        parts = [tr("Added {n} layouts.", n=added)]
    if left_out:
        names = list(dict.fromkeys(left_out))
        apps = _and(names)
        if len(left_out) == 1:
            parts.append(tr("1 window was left out: {apps} isn't on this Deck.", apps=apps))
        elif len(names) == 1:
            parts.append(tr("{n} windows were left out: {apps} isn't on this Deck.", n=len(left_out), apps=apps))
        else:
            parts.append(tr("{n} windows were left out: {apps} aren't on this Deck.", n=len(left_out), apps=apps))
    return " ".join(parts)


# ---------------- the buttons ----------------
def downloads_dir(home=None):
    return os.path.join(home or os.path.expanduser("~"), "Downloads")


def share(store, apps, app_version, home=None, now=None):
    """Share layouts: the file in ~/Downloads. Returns its path, or None when there is no layout to share."""
    if not store.presets:
        return None
    path = os.path.join(downloads_dir(home), file_name(now))
    return write(path, export(store.presets, apps, app_version))


def import_newest(store, apps, home=None):
    """Import layouts: the newest pocketxr-layouts*.json in ~/Downloads into the store. Returns (which file it took,
    what happened), each a line to show; the first is "" when there was no file."""
    path = newest(downloads_dir(home))
    if path is None:
        return "", tr("No {pattern} file in Downloads. Put one there, then try again.", pattern=PREFIX + "*.json")
    took = tr("Took {file} from Downloads.", file=os.path.basename(path))
    try:
        file_presets = read(path)
    except LayoutsError as e:
        return "", str(e)
    presets, added, left_out = merge(store.presets, file_presets, apps)
    if added:
        store.presets = presets
        store.save()
    return took, summary(added, left_out)
