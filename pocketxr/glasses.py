"""Which glasses are plugged in, from the Deck's USB devices (sysfs), and what Pocket XR can do with them.

The model rules follow Pocket XR's GlassesProfile, HeadImuTransport and SteadyMode.
"""
import glob
import os
from dataclasses import dataclass

XREAL = 0x3318
VITURE = 0x35CA

AURA = {0x0439, 0x043A}
ONE_FAMILY = {0x0435: "XREAL One Pro", 0x0436: "XREAL One Pro", 0x0437: "XREAL One", 0x0438: "XREAL One",
              0x043D: "XREAL 1S", 0x043E: "XREAL 1S", 0x0443: "XREAL One Pro+", 0x0444: "XREAL One Pro+"}
VITURE_BEAST = 0x1211
VITURE_MICROPHONE = 0x1102
# The Air models Pocket XR reads (AirImuProtocol): Air, Air 2, Air 2 Pro, Air 2 Ultra.
AIR_IMU = {0x0424: "XREAL Air", 0x0428: "XREAL Air 2", 0x0432: "XREAL Air 2 Pro", 0x0426: "XREAL Air 2 Ultra"}
AIR_FAMILY = {0x0423, 0x0424, 0x0425, 0x0426, 0x0427, 0x0428, 0x0431, 0x0432, 0x043F, 0x0440, 0x0441, 0x0442}


@dataclass(frozen=True)
class Glasses:
    name: str
    family: str  # "aura", "one", "air", "viture", "xreal"
    vendor: int
    product: int
    eye: bool = False  # an XREAL Eye (or any XREAL camera) seen beside One-family glasses

    @property
    def network_imu(self):
        """Head tracking over the glasses' USB network (169.254.2.1:52998): the Aura and the One family."""
        return self.family in ("aura", "one")

    @property
    def imu(self):
        """Where head tracking comes from: "network", "air" (USB HID), "viture" (USB HID), or None."""
        if self.network_imu:
            return "network"
        if self.family == "air" and self.product in AIR_IMU:
            return "air"
        if self.family == "viture":
            return "viture"
        return None

    @property
    def beast(self):
        return self.family == "viture" and self.product == VITURE_BEAST

    @property
    def control_link(self):
        """XREAL's control link on 52999: settings Pocket XR can read and set."""
        return self.family in ("aura", "one")

    @property
    def axes(self):
        # The One family and the VITURE Beast send x right, y down, z front (Pocket XR GlassesProfile, GLASSES.md);
        # the Aura x right, y up, z back; the Air's reader already turns its axes into the head's.
        return "one" if self.family == "one" or self.beast else "aura"

    def viture_tracking_default(self):
        """On by default on the Beast, experimental and off on other VITURE models (Pocket XR 1.2.12)."""
        return self.beast

    @property
    def steady_6dof(self):
        """Steady mode in 6DoF: the Aura, or the One series with the XREAL Eye (Pocket XR SteadyMode.sixDofOn)."""
        return self.family == "aura" or (self.family == "one" and self.eye)

    @property
    def app_anchor(self):
        """Glasses whose 6DoF hold Pocket XR turns on and off itself (Spatial Anchor): the Aura only."""
        return self.family == "aura"

    @property
    def managed(self):
        """Glasses whose menu settings Pocket XR reads and puts right on every link: the Aura only."""
        return self.family == "aura"

    def why_no_6dof(self):
        if self.steady_6dof:
            return None
        if self.family == "one":
            return "The One series holds 6DoF only with the XREAL Eye attached."
        if self.family == "viture":
            return "6DoF on VITURE glasses waits on VITURE's SDK."
        return "These glasses have no 6DoF that Pocket XR can use."

    def why_no_tracking(self, viture_on=None):
        if self.family == "viture":
            on = self.viture_tracking_default() if viture_on is None else viture_on
            if on:
                return None if self.beast else "VITURE head tracking is experimental on this model."
            return "VITURE head tracking is off. Turn it on in the panel to try it."
        if self.imu:
            return None
        if self.family == "air":
            return "Head tracking for this Air model is not known yet. Windows are shown flat."
        return "Head tracking for these glasses is not known. Windows are shown flat, as on Pocket XR."


def _read_hex(path):
    try:
        with open(path) as f:
            return int(f.read().strip(), 16)
    except (OSError, ValueError):
        return None


def usb_devices(root="/sys/bus/usb/devices"):
    """(vendor, product, interface classes, product string) for each USB device."""
    out = []
    for d in glob.glob(os.path.join(root, "*")):
        vid = _read_hex(os.path.join(d, "idVendor"))
        pid = _read_hex(os.path.join(d, "idProduct"))
        if vid is None or pid is None:
            continue
        classes = [c for c in (_read_hex(i) for i in glob.glob(d + ":*/bInterfaceClass")) if c is not None]
        try:
            with open(os.path.join(d, "product")) as f:
                name = f.read().strip()
        except OSError:
            name = ""
        out.append((vid, pid, classes, name))
    return out


def detect(devices=None):
    devs = usb_devices() if devices is None else devices
    eye = any(v == XREAL and 0x0E in cls and p not in AURA for v, p, cls, _ in devs)
    for v, p, _, _ in devs:
        if v == XREAL and p in AURA:
            return Glasses("XREAL Aura", "aura", v, p)
    for v, p, _, _ in devs:
        if v == XREAL and p in ONE_FAMILY:
            return Glasses(ONE_FAMILY[p], "one", v, p, eye)
    for v, p, _, name in devs:
        if v == XREAL and p in AIR_FAMILY:
            return Glasses(AIR_IMU.get(p) or name or "XREAL Air", "air", v, p)
    vit = [(v, p, name) for v, p, _, name in devs if v == VITURE and p != VITURE_MICROPHONE]
    if vit:
        v, p, name = sorted(vit, key=lambda t: t[1] != VITURE_BEAST)[0]
        return Glasses(name or "VITURE glasses", "viture", v, p)
    for v, p, cls, name in devs:
        # Any other XREAL device with a CDC network interface takes the network path, as Pocket XR does.
        if v == XREAL and 0x02 in cls:
            return Glasses(name or "XREAL glasses", "one", v, p, eye)
    return None


def other_glasses():
    """Glasses Pocket XR does not know, seen only as a second display: shown flat, as Pocket XR's plain fallback."""
    return Glasses("Other glasses", "other", 0, 0)
