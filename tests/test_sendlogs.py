"""Checks for Send logs to Mike: personal details come out, the zip holds what it should, and only two zips stay.
Everything happens in a temporary home folder; nothing opens an email."""
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import sendlogs  # noqa: E402


def scrubber(home="/home/sam"):
    return sendlogs.Scrubber(home=home, user="sam", hostname="sams-deck", wifi=["Sam's House 5G", "Cafe Lumiere"],
                             bluetooth=["Sam's Buds Pro", "DualSense Wireless Controller"])


def test_scrub_lines():
    s = scrubber()
    cases = [
        ("mail me at sam.smith+xr@example.co.uk now", "mail me at <email> now"),
        ("connected to Sam's House 5G (wlan0)", "connected to <wifi> (wlan0)"),
        ("ssid=MyNet signal 70", "ssid=<wifi> signal 70"),
        ("PC helper on gaming-pc (192.168.1.23)", "PC helper on gaming-pc (<ip>)"),
        ("glasses at 169.254.2.1:52998, local 127.0.0.1", "glasses at 169.254.2.1:52998, local 127.0.0.1"),
        ("addr 2a02:c7f:1234:5600::1a2b and fe80::1c2d:3e4f:5a6b:7c8d%wlan0 and ::1",
         "addr <ip> and fe80::1c2d:3e4f:5a6b:7c8d%wlan0 and ::1"),
        ("bt A4:C1:38:0B:2D:EF paired", "bt <mac> paired"),
        ("pad: DualSense Wireless Controller connected", "pad: <bt-device-2> connected"),
        ("audio to Sam's Buds Pro", "audio to <bt-device-1>"),
        ("file /home/sam/Videos/Pocket XR/a.mp4", "file ~/Videos/Pocket XR/a.mp4"),
        ("user sam on sams-deck", "user <account> on <hostname>"),
        ("12:34:56 recentre: heading straight ahead", "12:34:56 recentre: heading straight ahead"),
        ("glasses: XREAL Aura (aura, 3318:043a)", "glasses: XREAL Aura (aura, 3318:043a)"),
    ]
    for line, want in cases:
        got = s(line)
        assert got == want, (line, got, want)


def test_deck_user_kept():
    s = sendlogs.Scrubber(home="/home/deck", user="deck", hostname="steamdeck", wifi=[], bluetooth=[])
    assert s("source deck, /home/deck/.local") == "source deck, ~/.local"


def _home_with_logs(d):
    state = os.path.join(d, ".local", "state", "pocket-xr-deck")
    os.makedirs(state)
    for name, text in (("pocket-xr.log", "12:00:00 starting at /home/sam with 10.0.0.5\n"),
                       ("pocket-xr.log.1", "11:00:00 older run\n"), ("gaming.log", "12:00:01 gaming: started\n")):
        with open(os.path.join(state, name), "w") as f:
            f.write(text)
    return d


def test_zip_contents():
    with tempfile.TemporaryDirectory() as d:
        home = _home_with_logs(d)
        path = sendlogs.build(home=home, now=1_700_000_000, scrub=scrubber(home))
        assert os.path.dirname(path) == os.path.join(home, "Downloads")
        assert os.path.basename(path).startswith("pocketxr-logs-") and path.endswith(".zip")
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            assert names == {"info.txt", "glasses-report.txt", "pocket-xr.log", "pocket-xr.log.1", "gaming.log"}, names
            info = z.read("info.txt").decode()
            for head in ("Pocket XR for Steam Deck", "Device: ", "OS: ", "Glasses: ", "Made: "):
                assert head in info, (head, info)
            log = z.read("pocket-xr.log").decode()
            assert "/home/sam" not in log and "10.0.0.5" not in log and "<ip>" in log, log
        assert not [n for n in os.listdir(os.path.join(home, "Downloads")) if n.endswith(".part")]


def test_keeps_two_zips():
    with tempfile.TemporaryDirectory() as d:
        home = _home_with_logs(d)
        s = scrubber(home)
        first = sendlogs.build(home=home, now=1_700_000_000, scrub=s)
        os.utime(first, (1_700_000_000, 1_700_000_000))
        second = sendlogs.build(home=home, now=1_700_000_100, scrub=s)
        os.utime(second, (1_700_000_100, 1_700_000_100))
        zips = sorted(n for n in os.listdir(os.path.join(home, "Downloads")) if n.endswith(".zip"))
        assert len(zips) == 2, zips
        third = sendlogs.build(home=home, now=1_700_000_200, scrub=s)
        zips = sorted(os.path.join(home, "Downloads", n) for n in os.listdir(os.path.join(home, "Downloads"))
                      if n.endswith(".zip"))
        assert zips == sorted([second, third]), zips


def test_email_words():
    assert sendlogs.subject().startswith("Pocket XR logs ")
    b = sendlogs.body(now=1_700_000_000)
    assert b.startswith("Hi Mike,\n\nWhat happened (and roughly when):\n\n\n----\nPocket XR ")
    assert "\nDevice: " in b and "\nOS: " in b and "\nGlasses: " in b and " UTC\n" in b
    assert b.endswith("The logs are in the attached zip.\n")
    assert "Please attach pocketxr-logs-1.zip from your Downloads folder." in sendlogs.body("pocketxr-logs-1.zip")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
