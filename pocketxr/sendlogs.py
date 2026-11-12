"""Send logs to Mike, as Pocket XR on Android does: one zip of Pocket XR's logs and a glasses report, with personal
details taken out, saved in ~/Downloads, then an email to Mike that the user reads and sends. Nothing goes to any
server: the user's own email app sends it, or the user attaches the zip themselves.

Taken out of every text file in the zip: email addresses, Wi-Fi network names, IP addresses (not 127.0.0.1, ::1 or the
link-local fe80:: and 169.254.x.x the glasses use), MAC addresses, Bluetooth device names, the computer's name, and the
user's home folder and name.
"""
import glob
import ipaddress
import os
import re
import shutil
import socket
import subprocess
import time
import zipfile

from . import glasses as gmod
from . import i18n
from .i18n import N_, tr

EMAIL = "connect@mikehaye.com"
HERE = os.path.dirname(os.path.abspath(__file__))
KEEP = 2  # zips kept in Downloads, the newest
CAP = 18 * 1024 * 1024  # the zip's text at most; older logs are left out past this
PREFIX = "pocketxr-logs-"
# Email apps that xdg-email can hand an attachment to; with any other (or none) the user attaches the zip.
ATTACHING_MAIL_APPS = ("thunderbird", "betterbird", "kmail", "evolution", "claws-mail")
DECKS = {"Jupiter": "Steam Deck LCD (Jupiter)", "Galileo": "Steam Deck OLED (Galileo)"}


def _state_dir(home):
    return os.path.join(home, ".local", "state", "pocket-xr-deck")


def _run(cmd, timeout=3.0, both=False):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return ""
    return r.stdout + r.stderr if both else r.stdout


def _read(path):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return f.read().strip()
    except OSError:
        return ""


# ---------------- taking personal details out ----------------
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
MAC_RE = re.compile(r"(?<![0-9A-Fa-f:-])[0-9A-Fa-f]{2}(?:([:-])[0-9A-Fa-f]{2})(?:\1[0-9A-Fa-f]{2}){4}(?![0-9A-Fa-f:-])")
IPV4_RE = re.compile(r"(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])")
IPV6_RE = re.compile(r"(?<![\w:])(?:[0-9A-Fa-f]{0,4}:){2,7}[0-9A-Fa-f]{0,4}(?:%\w+)?(?![\w:])")
SSID_RE = re.compile(r"(?i)\b(ssid\s*[=:]\s*)(\"[^\"]*\"|'[^']*'|\S+)")


def _ip4(m):
    s = m.group(0)
    try:
        a = ipaddress.IPv4Address(s)
    except ValueError:
        return s
    return s if a.is_loopback or a.is_link_local or a.is_unspecified else "<ip>"


def _ip6(m):
    s = m.group(0)
    try:
        a = ipaddress.IPv6Address(s.split("%")[0])
    except ValueError:
        return s
    return s if a.is_loopback or a.is_link_local or a.is_unspecified else "<ip>"


class Scrubber:
    """Takes the personal details out of a text. The names to look for come from this computer (or are given)."""

    def __init__(self, home=None, user=None, hostname=None, wifi=None, bluetooth=None):
        self.home = home if home is not None else os.path.expanduser("~")
        self.user = user if user is not None else os.path.basename(self.home.rstrip("/"))
        self.hostname = hostname if hostname is not None else socket.gethostname()
        self.wifi = wifi_names() if wifi is None else wifi
        self.bluetooth = bluetooth_names() if bluetooth is None else bluetooth

    def __call__(self, text, ips=True):
        if self.home and self.home not in ("/", ""):
            text = text.replace(self.home.rstrip("/"), "~")
        text = re.sub(r"/home/[^/\s]+", "~", text)
        text = EMAIL_RE.sub("<email>", text)
        # Bluetooth and Wi-Fi names before the addresses, longest first, so one name inside another goes whole.
        for i, name in sorted(enumerate(self.bluetooth, 1), key=lambda t: -len(t[1])):
            text = text.replace(name, f"<bt-device-{i}>")
        for name in sorted(self.wifi, key=len, reverse=True):
            text = text.replace(name, "<wifi>")
        text = SSID_RE.sub(lambda m: m.group(1) + "<wifi>", text)
        text = MAC_RE.sub("<mac>", text)
        if ips:
            text = IPV6_RE.sub(_ip6, text)
            text = IPV4_RE.sub(_ip4, text)
        if self.hostname and len(self.hostname) >= 3:
            text = re.sub(r"\b%s\b" % re.escape(self.hostname), "<hostname>", text)
        # "deck" is every Steam Deck's user, and a word all through the logs: only other names are personal.
        if self.user and len(self.user) >= 3 and self.user != "deck":
            text = re.sub(r"\b%s\b" % re.escape(self.user), "<account>", text)
        return text


def wifi_names():
    """The Wi-Fi networks this computer knows (nmcli), but not ones so short they would match ordinary words."""
    names = []
    for line in _run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"]).splitlines():
        name, _, kind = line.rpartition(":")
        name = name.replace("\\:", ":")
        if "wireless" in kind and len(name) >= 4:
            names.append(name)
    if not names:  # an older nmcli, or no TYPE column: every connection's name
        names = [n.replace("\\:", ":") for n in _run(["nmcli", "-t", "-f", "NAME", "connection", "show"]).splitlines()
                 if len(n) >= 4 and n not in ("lo", "Wired connection 1")]
    return names


def bluetooth_names():
    """The paired Bluetooth devices' names (bluetoothctl devices: "Device AA:BB:CC:DD:EE:FF Name")."""
    out = []
    for line in _run(["bluetoothctl", "devices"]).splitlines():
        parts = line.strip().split(" ", 2)
        if len(parts) == 3 and parts[0] == "Device" and len(parts[2]) >= 3 and parts[2] not in out:
            out.append(parts[2])
    return out


# ---------------- what goes in the zip ----------------
def version():
    return _read(os.path.join(HERE, "..", "VERSION")) or "unknown"


def device():
    product = _read("/sys/class/dmi/id/product_name")
    if product in DECKS:
        return DECKS[product]
    vendor = _read("/sys/class/dmi/id/sys_vendor")
    return " ".join(x for x in (vendor, product) if x) or "unknown"


def os_name():
    info = {}
    for line in _read("/etc/os-release").splitlines():
        k, _, v = line.partition("=")
        info[k] = v.strip().strip('"')
    name = info.get("PRETTY_NAME") or info.get("NAME") or "Linux"
    ver = info.get("VERSION_ID")
    return f"{name} ({ver})" if ver and ver not in name else name


def gamescope_version():
    if not shutil.which("gamescope"):
        return None
    m = re.search(r"gamescope version (\S+)", _run(["gamescope", "--version"], both=True))
    return m.group(1) if m else None


def glasses_line(devices=None):
    g = gmod.detect(devices)
    if g is None:
        return "none found on USB"
    return f"{g.name} ({g.family}, {g.vendor:04x}:{g.product:04x}{', XREAL Eye' if g.eye else ''})"


def decky_version(home):
    return _read(os.path.join(home, "homebrew", "services", ".loader.version")) or None


def info_text(home, now):
    lines = [f"Pocket XR for Steam Deck {version()}",
             f"Device: {device()}",
             f"OS: {os_name()}"]
    gs = gamescope_version()
    lines.append(f"gamescope: {gs}" if gs else "gamescope: not found")
    lines.append(f"Glasses: {glasses_line()}")
    dv = decky_version(home)
    lines.append(f"Decky: {dv}" if dv else "Decky: not installed")
    lines.append(f"Language: {i18n.lang()}")
    lines.append("Made: " + time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now)) + " UTC")
    return "\n".join(lines) + "\n"


def glasses_report(root="/sys/bus/usb/devices"):
    """Every USB device from a glasses maker: ids, names, interfaces and their HID report descriptors, for new glasses
    and models that behave differently. No serial numbers."""
    out = []
    for d in sorted(glob.glob(os.path.join(root, "*"))):
        if ":" in os.path.basename(d):
            continue
        vid, pid = _read(os.path.join(d, "idVendor")), _read(os.path.join(d, "idProduct"))
        try:
            v = int(vid, 16)
        except ValueError:
            continue
        if v not in (gmod.XREAL, gmod.VITURE):
            continue
        out.append(f"== {os.path.basename(d)}  {vid}:{pid}  {_read(os.path.join(d, 'manufacturer'))} "
                   f"{_read(os.path.join(d, 'product'))}".rstrip())
        out.append(f"   speed {_read(os.path.join(d, 'speed'))} Mb/s, version {_read(os.path.join(d, 'version'))}, "
                   f"bcdDevice {_read(os.path.join(d, 'bcdDevice'))}")
        for i in sorted(glob.glob(d + ":*")):
            drv = os.path.basename(os.path.realpath(os.path.join(i, "driver"))) if os.path.exists(
                os.path.join(i, "driver")) else "none"
            out.append(f"   interface {os.path.basename(i)}: class {_read(os.path.join(i, 'bInterfaceClass'))} "
                       f"subclass {_read(os.path.join(i, 'bInterfaceSubClass'))} "
                       f"protocol {_read(os.path.join(i, 'bInterfaceProtocol'))}, driver {drv}")
            for rd in sorted(glob.glob(os.path.join(i, "*:*:*.*", "report_descriptor"))):
                try:
                    with open(rd, "rb") as f:
                        data = f.read()
                except OSError:
                    continue
                out.append(f"     HID report descriptor ({len(data)} bytes):")
                for k in range(0, len(data), 32):
                    out.append("       " + data[k:k + 32].hex(" "))
    if not out:
        out.append("No XREAL or VITURE device on USB.")
    return "\n".join(out) + "\n"


def log_files(home):
    """Pocket XR's logs, newest first: the app's, the Gaming Mode service's, then rotated copies."""
    state = _state_dir(home)
    main = [os.path.join(state, n) for n in ("pocket-xr.log", "gaming.log")]
    rotated = sorted(glob.glob(os.path.join(state, "*.log.*")), key=lambda p: -os.path.getmtime(p))
    return [p for p in main if os.path.isfile(p)] + rotated


def build(home=None, now=None, scrub=None):
    """Makes the zip in ~/Downloads and returns its path. Keeps only the newest KEEP of them."""
    home = home or os.path.expanduser("~")
    now = time.time() if now is None else now
    scrub = scrub or Scrubber(home=home)
    downloads = os.path.join(home, "Downloads")
    os.makedirs(downloads, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now))
    path = os.path.join(downloads, f"{PREFIX}{stamp}.zip")
    n = 2
    while os.path.exists(path):
        path = os.path.join(downloads, f"{PREFIX}{stamp}-{n}.zip")
        n += 1
    tmp = path + ".part"
    total = 0
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for name, text in (("info.txt", scrub(info_text(home, now), ips=False)),
                           ("glasses-report.txt", scrub(glasses_report()))):
            data = text.encode("utf-8")
            total += len(data)
            z.writestr(name, data)
        for i, lp in enumerate(log_files(home)):
            data = scrub(_read(lp) + "\n").encode("utf-8")
            if i >= 2 and total + len(data) > CAP:
                continue  # an older log past the cap: left out
            if total + len(data) > CAP:
                data = data[-(CAP - total):]  # one of today's logs alone past the cap: its newest part
            total += len(data)
            z.writestr(os.path.basename(lp), data)
    os.replace(tmp, path)
    for old in sorted(glob.glob(os.path.join(downloads, PREFIX + "*.zip")), key=os.path.getmtime)[:-KEEP]:
        try:
            os.remove(old)
        except OSError:
            pass
    return path


# ---------------- the email ----------------
def subject():
    return f"Pocket XR logs {version()} {device()}"


def body(zip_name=None, now=None):
    now = time.time() if now is None else now
    text = ("Hi Mike,\n\nWhat happened (and roughly when):\n\n\n----\n"
            f"Pocket XR {version()}\nDevice: {device()}\nOS: {os_name()}\nGlasses: {glasses_line()}\n"
            "Made: " + time.strftime("%Y-%m-%d %H:%M", time.gmtime(now)) + " UTC\n")
    if zip_name:
        return text + f"Please attach {zip_name} from your Downloads folder.\n"
    return text + "The logs are in the attached zip.\n"


def mail_app_attaches():
    app = _run(["xdg-mime", "query", "default", "x-scheme-handler/mailto"]).strip().lower()
    return bool(app) and any(a in app for a in ATTACHING_MAIL_APPS)


def open_email(path):
    """Opens an email to Mike with the zip: attached by the email app when it can, else a mailto: with the zip shown in
    the file manager for the user to attach. Returns "attached" or "attach_yourself"."""
    from urllib.parse import quote
    if shutil.which("xdg-email") and mail_app_attaches():
        subprocess.Popen(["xdg-email", "--subject", subject(), "--body", body(), "--attach", path, EMAIL])
        return "attached"
    url = f"mailto:{EMAIL}?subject={quote(subject())}&body={quote(body(os.path.basename(path)))}"
    subprocess.Popen(["xdg-open", url])
    if shutil.which("dolphin"):
        subprocess.Popen(["dolphin", "--select", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])
    return "attach_yourself"


def send():
    """The Desktop Mode button: the zip, then the email. Returns the line to show the user."""
    path = build()
    how = open_email(path)
    name = os.path.basename(path)
    if how == "attached":
        return tr("Saved {name} in Downloads. Your email app has it attached: tap send when you're ready.", name=name)
    return tr("Saved {name} in Downloads. Attach it to the email that just opened, then send it.", name=name)


BUTTON = N_("Send logs to Mike")
EXPLAIN = N_("Emails Mike one zip of Pocket XR's logs and glasses diagnostics, with your Pocket XR version, device, "
           "OS version and glasses. Emails, account, Wi-Fi and Bluetooth device names and IP addresses are taken out. "
           "Nothing goes until you tap send.")
GETTING_READY = N_("Getting the logs ready...")
COULD_NOT = N_("Could not make the logs: {error}")
SAVED_FOR_DESKTOP = N_("Saved {name} in Downloads. Send it to connect@mikehaye.com from Desktop Mode, or attach it to "
                       "an issue on GitHub.")
