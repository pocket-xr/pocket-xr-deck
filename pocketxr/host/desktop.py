"""The Plasma desktop around the host: where the PC screens' virtual outputs sit (kscreen-doctor), the clipboard
(Klipper over D-Bus), a sound sink per stream (pactl) and the mDNS announcement (avahi-publish).
"""
import json
import shutil
import subprocess
import threading
import time

VIRTUAL_PREFIX = "Virtual-pxr-"  # each stream's KWin output: Virtual-pxr-<port>


def _run(args, timeout=10, text_in=None):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout, input=text_in)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError) as e:
        return -1, str(e)


def logical_size(o):
    """An output's size on the desktop: its size over its scale, rounded up as KWin does. kscreen-doctor gives the size
    as laid out, already turned for a rotated panel (the Deck, 20 Nov 2026: 1280x800 at 1.35, rotation 8, is
    949x593)."""
    scale = float(o.get("scale") or 1)
    w, h = o["size"]["width"], o["size"]["height"]
    s = int(round(scale * 100))
    return -(-w * 100 // s), -(-h * 100 // s)


def outputs():
    """The enabled outputs: [{"name", "x", "y", "w", "h"}] in logical pixels, or [] without kscreen-doctor."""
    code, out = _run(["kscreen-doctor", "-j"])
    if code != 0:
        return []
    try:
        data = json.loads(out).get("outputs", [])
    except ValueError:
        return []
    found = []
    for o in data:
        if o.get("enabled") and o.get("pos") and o.get("size"):
            w, h = logical_size(o)
            found.append({"name": str(o.get("name", "")), "x": o["pos"]["x"], "y": o["pos"]["y"], "w": w, "h": h})
    return found


def bounds(outs):
    """The whole desktop's (x, y, w, h): what an absolute pointer device covers."""
    if not outs:
        return 0, 0, 1920, 1080
    x0 = min(o["x"] for o in outs)
    y0 = min(o["y"] for o in outs)
    x1 = max(o["x"] + o["w"] for o in outs)
    y1 = max(o["y"] + o["h"] for o in outs)
    return x0, y0, x1 - x0, y1 - y0


def _port_of(o):
    """The PC screen's base port in a virtual output's name (Virtual-pxr-<port>), for sorting; 0 when not a number."""
    tail = o["name"][len(VIRTUAL_PREFIX):]
    return int(tail) if tail.isdigit() else 0


def arrange(outs):
    """kscreen-doctor arguments that put the PC screens' virtual outputs side by side, right of the real screens, in
    port order (PC screen 1 to 6). KWin remembers where outputs were for each set of outputs and puts them back there, so two
    virtual outputs can land on the same place (the Deck, 20 Nov 2026: both at 949,0, and PC screen 2 showed PC screen
    1's picture)."""
    virtual = sorted((o for o in outs if o["name"].startswith(VIRTUAL_PREFIX)), key=lambda o: (_port_of(o), o["name"]))
    real = [o for o in outs if o not in virtual]
    x = max((o["x"] + o["w"] for o in real), default=0)
    moves = []
    for o in virtual:
        if (o["x"], o["y"]) != (x, 0):
            moves.append("output.%s.position.%d,0" % (o["name"], x))
        x += o["w"]
    return moves


def set_scale(name, scale):
    """Sets KWin's scale on an output (as Plasma's Display settings do); None when done, else why not."""
    code, out = _run(["kscreen-doctor", "output.%s.scale.%s" % (name, ("%.4f" % scale).rstrip("0").rstrip("."))])
    return None if code == 0 else (out.strip() or "kscreen-doctor ended with %s" % code)


class Layout:
    """The outputs, cached and refreshed when a stream starts or ends."""

    def __init__(self, log=print):
        self.log = log
        self.lock = threading.Lock()
        self.outs = []
        self.box = (0, 0, 1920, 1080)

    def refresh(self, place=True):
        outs = outputs()
        if place:
            moves = arrange(outs)
            if moves:
                _run(["kscreen-doctor"] + moves)
                self.log("host: outputs: " + " ".join(moves))
                time.sleep(0.3)
                outs = outputs()
        with self.lock:
            self.outs = outs
            self.box = bounds(outs)
        return outs

    def area(self, name):
        """(x, y, w, h) of the output [name], or None."""
        with self.lock:
            for o in self.outs:
                if o["name"] == name:
                    return o["x"], o["y"], o["w"], o["h"]
        return None

    def desktop(self):
        with self.lock:
            return self.box


# ---- KDE's display-switch pop-up ----

OSD_SERVICE = "org.kde.kscreen.osdService"
OSD_WATCH = 6.0  # seconds after a PC screen's output appears


def _bus_has(name):
    code, out = _run(["busctl", "--user", "call", "org.freedesktop.DBus", "/org/freedesktop/DBus",
                      "org.freedesktop.DBus", "NameHasOwner", "s", name], timeout=3)
    return code == 0 and out.strip() == "b true"


def close_display_switch(log=print, seconds=OSD_WATCH, poll=0.1):
    """Close KDE's display-switch pop-up ("Only use external screen" and the other layouts) if it opens just after a PC
    screen's output appears. KWin 6.7 opens it itself when it meets a set of exactly two outputs, one built in, with no
    stored setup (workspace.cpp, updateOutputConfiguration). The Deck's own screen with one PC screen is such a set
    the first time each PC screen is used, and the pop-up then stays on the Deck's screen until a choice is made
    (seen on the Deck, 20 Nov 2026). hideOsd ends kscreen's pop-up service. The watch lasts a few seconds from the
    output's appearance, so other uses of the pop-up are left alone."""
    if not shutil.which("busctl"):
        return None

    def watch():
        end = time.time() + seconds
        while time.time() < end:
            if _bus_has(OSD_SERVICE):
                _run(["busctl", "--user", "call", OSD_SERVICE, "/org/kde/kscreen/osdService", OSD_SERVICE, "hideOsd"],
                     timeout=3)
                log("host: closed KDE's display-switch pop-up for the new PC screen")
                return
            time.sleep(poll)

    t = threading.Thread(target=watch, daemon=True, name="display-switch")
    t.start()
    return t


# ---- clipboard ----

def _qdbus():
    return shutil.which("qdbus6") or shutil.which("qdbus")


def clipboard_get():
    q = _qdbus()
    if not q:
        return None
    code, out = _run([q, "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.getClipboardContents"], timeout=5)
    if code != 0:
        return None
    return out[:-1] if out.endswith("\n") else out


def clipboard_set(text):
    q = _qdbus()
    if not q:
        return False
    code, _ = _run([q, "org.kde.klipper", "/klipper", "org.kde.klipper.klipper.setClipboardContents", text],
                   timeout=5)
    return code == 0


# ---- sound ----

class Sink:
    """A sound sink of its own for one stream, made the default while it streams, so the PC's sound goes to the phone
    and not out of the Deck (as Sunshine does). Its monitor is what the host records."""

    def __init__(self, port, description, log=print):
        self.log = log
        self.name = "pocketxr_host_%d" % port
        self.module = None
        self.before = None
        code, out = _run(["pactl", "get-default-sink"], timeout=5)
        self.before = out.strip() if code == 0 else None
        code, out = _run(["pactl", "load-module", "module-null-sink", "sink_name=" + self.name,
                          "sink_properties=device.description=\"%s\"" % description.replace('"', "")], timeout=5)
        if code == 0 and out.strip().isdigit():
            self.module = out.strip()
            _run(["pactl", "set-default-sink", self.name], timeout=5)
        else:
            self.log("host: no sound sink of its own (%s): recording the default one" % out.strip()[:80])

    def monitor(self):
        return (self.name if self.module else "@DEFAULT_SINK@") + ".monitor"

    def close(self):
        if not self.module:
            return
        code, out = _run(["pactl", "get-default-sink"], timeout=5)
        if code == 0 and out.strip() == self.name and self.before and self.before != self.name:
            _run(["pactl", "set-default-sink", self.before], timeout=5)
        _run(["pactl", "unload-module", self.module], timeout=5)
        self.module = None


# ---- mDNS ----

class Announcement:
    """"_nvstream._tcp" on mDNS, as Moonlight finds hosts, through avahi-publish. SteamOS refuses it ("Not permitted",
    20 Nov 2026); the phone then learns the PC screens from the helper's UDP answer."""

    def __init__(self, name, port, log=print):
        self.proc = None
        if not shutil.which("avahi-publish"):
            return
        try:
            self.proc = subprocess.Popen(["avahi-publish", "-s", name, "_nvstream._tcp", str(port)],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        except OSError:
            self.proc = None
            return
        time.sleep(0.5)
        if self.proc.poll() is not None:
            why = (self.proc.stderr.read() or "").strip().splitlines()
            log("host: mDNS not announced for %s (%s); the helper's answer lists it" % (name, why[-1] if why else "?"))
            self.proc = None

    def close(self):
        if self.proc:
            self.proc.terminate()
            self.proc = None
