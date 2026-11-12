"""The Deck's apps for the launcher in space: desktop entries, their icons, and starting them."""
import configparser
import glob
import os
import subprocess

DIRS = [
    os.path.expanduser("~/.local/share/applications"),
    os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
    "/var/lib/flatpak/exports/share/applications",
    "/usr/share/applications",
]
ICON_DIRS = [
    os.path.expanduser("~/.local/share/icons"),
    os.path.expanduser("~/.local/share/flatpak/exports/share/icons"),
    "/var/lib/flatpak/exports/share/icons",
    "/usr/share/icons",
]
ICON_SIZES = ["256x256", "192x192", "128x128", "96x96", "64x64", "48x48"]
THEMES = ["breeze", "hicolor", "Adwaita"]


class App:
    __slots__ = ("id", "name", "icon", "path", "wm_class")

    def __init__(self, id_, name, icon, path, wm_class):
        self.id, self.name, self.icon, self.path, self.wm_class = id_, name, icon, path, wm_class


def _icon_path(name):
    """A PNG or SVG for an icon name, best first; None when there is nothing (the launcher draws a letter)."""
    if not name:
        return None
    if os.path.isabs(name):
        return name if os.path.exists(name) and name.endswith((".png", ".svg")) else None
    for base in ICON_DIRS:
        for theme in THEMES:
            for size in ICON_SIZES:
                p = os.path.join(base, theme, size, "apps", name + ".png")
                if os.path.exists(p):
                    return p
            for p in (os.path.join(base, theme, "scalable", "apps", name + ".svg"),
                      os.path.join(base, theme, "apps", "48", name + ".svg"),
                      os.path.join(base, theme, "apps", "64", name + ".svg")):
                if os.path.exists(p):
                    return p
    for ext in (".png", ".svg"):
        p = os.path.join("/usr/share/pixmaps", name + ext)
        if os.path.exists(p):
            return p
    return None


# System plumbing the app menu lists that nobody opens from a launcher in space.
HIDE_IDS = ("avahi-", "org.kde.drkonqi", "bssh", "bvnc", "org.freedesktop.IBus", "qv4l2", "qvidcap", "lstopo",
            "electron", "jshell", "jconsole")


def list_apps():
    """Apps that show in the app menu, by name, once each."""
    seen = {}
    for d in DIRS:
        for f in sorted(glob.glob(os.path.join(d, "*.desktop"))):
            id_ = os.path.basename(f)
            if id_ in seen:
                continue
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except (configparser.Error, KeyError, UnicodeDecodeError):
                continue
            if e.get("Type", "Application") != "Application":
                continue
            if e.get("NoDisplay", "false").lower() == "true" or e.get("Hidden", "false").lower() == "true":
                continue
            if "OnlyShowIn" in e and "KDE" not in e.get("OnlyShowIn", ""):
                continue
            name = e.get("Name")
            if not name or not e.get("Exec") or id_ == "pocket-xr.desktop":
                continue
            if e.get("Terminal", "false").lower() == "true" or "ConsoleOnly" in e.get("Categories", ""):
                continue
            if id_.lower().startswith(HIDE_IDS):
                continue
            seen[id_] = App(id_, name, _icon_path(e.get("Icon", "")), f, e.get("StartupWMClass", ""))
    return sorted(seen.values(), key=lambda a: a.name.lower())


def launch(app, log=print):
    """Start an app as the app menu would."""
    try:
        subprocess.Popen(["gio", "launch", app.path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        log(f"launcher: started {app.name}")
    except OSError as e:
        log(f"launcher: could not start {app.name} ({e})")
