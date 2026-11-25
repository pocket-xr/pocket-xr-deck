"""How many PC screens the host serves, and on which ports: the one place the count is set.

PC screen k (1, 2, ...) has its base port P = 47989 + 1000 * (k - 1), as the PC Screens app's Sunshines had for the
first three: 47989, 48989, 49989, then 50989, 51989 and 52989. Each screen uses P-5 to P+21 (HTTPS P-5, HTTP P,
video P+9, control P+10, sound P+11, RTSP P+21), so the six screens' ports never meet.

Three at first, as before. The control panel's "PC screens for a phone" (the desktop app's settings file,
"host_screens") asks for up to six; the host service reads it every few seconds, so a change needs no restart.
"""
import json
import os

FIRST_PORT = 47989
PORT_STEP = 1000
DEFAULT = 3
MAX = 6
SETTING = "host_screens"
# The desktop app's settings file (readability.DESKTOP_SETTINGS; not imported, so the host stays light)
DESKTOP_SETTINGS = os.path.join(os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "pocket-xr-deck",
                                "settings.json")


def count_of(value):
    """A count the host offers: DEFAULT for anything not a whole number, else held to 1 to MAX."""
    try:
        if isinstance(value, bool):
            raise TypeError
        n = int(value)
        if n != float(value):
            raise ValueError
    except (TypeError, ValueError, OverflowError):
        return DEFAULT
    return max(1, min(MAX, n))


def ports(count=DEFAULT):
    """The base ports of PC screens 1 to [count]."""
    return tuple(FIRST_PORT + PORT_STEP * k for k in range(count_of(count)))


def wanted(path=None):
    """The count from the desktop app's settings file; DEFAULT without one or without the setting."""
    try:
        with open(path or DESKTOP_SETTINGS, encoding="utf-8") as f:
            s = json.load(f)
    except (OSError, ValueError):
        return DEFAULT
    return count_of(s.get(SETTING, DEFAULT)) if isinstance(s, dict) else DEFAULT
