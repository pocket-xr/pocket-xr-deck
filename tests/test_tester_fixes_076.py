"""A tester's report on 0.7.5 (Pierre Zammit, 23 Nov 2026, XBX A01+ on a Deck): an update that left the old Gaming
Mode service running, a way to use the glasses' own buttons, and the pointer in Nested Desktop."""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import hidimu  # noqa: E402
from pocketxr import xpointer as X  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as f:
        return f.read()


def item(text):
    """The first 32 bit item gamescope writes for a display name (its first 4 bytes)."""
    return int.from_bytes(text.encode()[:4].ljust(4, b"\0"), "little")


class Installer(unittest.TestCase):
    def test_restarts_without_steams_environment_and_says_when_it_could_not(self):
        sh = read("install.sh")
        self.assertIn("env -u LD_PRELOAD -u LD_LIBRARY_PATH", sh)
        self.assertIn("if out=$(user_systemctl restart pocket-xr-gaming.service 2>&1); then", sh)
        self.assertNotIn("systemctl --user restart pocket-xr-gaming.service >/dev/null 2>&1 || true", sh)
        self.assertIn("could not be restarted", sh)

    def test_reopens_the_desktop_app(self):
        sh = read("install.sh")
        self.assertIn("pgrep -u \"$(id -u)\" -f -- '-m pocketxr( |$)'", sh)
        self.assertIn('setsid "$BIN/pocket-xr"', sh)

    def test_the_app_pattern_leaves_the_services_alone(self):
        pat = re.compile(r"-m pocketxr( |$)")
        self.assertTrue(pat.search("python3 -m pocketxr"))
        self.assertTrue(pat.search("python3 -m pocketxr --panel"))
        self.assertFalse(pat.search("/usr/bin/python3 -m pocketxr.gaming"))
        self.assertFalse(pat.search("python3 -m pocketxr.xpointer --keys 166"))

    def test_user_systemctl_runs_without_steams_libraries(self):
        if not os.path.exists("/bin/bash") or sys.platform == "win32":
            self.skipTest("bash on Linux only")
        sh = read("install.sh")
        fn = sh[sh.index("user_systemctl() {"):]
        fn = fn[:fn.index("\n}\n") + 3]
        d = tempfile.mkdtemp()
        fake = os.path.join(d, "systemctl")
        with open(fake, "w") as f:
            f.write('#!/bin/sh\necho "LD_PRELOAD=${LD_PRELOAD-unset} LD_LIBRARY_PATH=${LD_LIBRARY_PATH-unset} $*"\n')
        os.chmod(fake, 0o755)
        out = subprocess.run(["bash", "-c", fn + "user_systemctl restart x"], capture_output=True, text=True,
                             env=dict(os.environ, PATH=d + ":/usr/bin:/bin", LD_PRELOAD="gameoverlayrenderer.so",
                                      LD_LIBRARY_PATH="/steam/runtime")).stdout
        self.assertEqual(out.strip(), "LD_PRELOAD=unset LD_LIBRARY_PATH=unset --user restart x")


class ServiceVersion(unittest.TestCase):
    def setUp(self):
        try:
            from pocketxr import gaming
        except (ImportError, OSError, AttributeError) as e:
            self.skipTest(f"gaming.py loads on Linux only ({e})")
        self.gaming = gaming

    def fake(self, running, installed):
        class G:
            pass
        g = G()
        g.lines = []
        g.log = g.lines.append
        g.version = running
        self.gaming.sendlogs.version, self.saved = (lambda: installed), self.gaming.sendlogs.version
        return g

    def tearDown(self):
        if hasattr(self, "saved"):
            self.gaming.sendlogs.version = self.saved

    def test_ends_to_be_started_again_when_a_new_version_is_installed(self):
        g = self.fake("0.7.6", "0.7.7")
        with self.assertRaises(SystemExit) as e:
            self.gaming.Gaming._restart_if_updated(g)
        self.assertEqual(e.exception.code, self.gaming.RESTART_EXIT)
        self.assertIn("gaming: Pocket XR 0.7.7 was installed over this 0.7.6; starting again to load it", g.lines)

    def test_stays_on_the_same_version_or_none(self):
        for installed in ("0.7.6", "unknown"):
            g = self.fake("0.7.6", installed)
            self.gaming.Gaming._restart_if_updated(g)
            self.assertEqual(g.lines, [])

    def test_restart_code_brings_it_back(self):
        self.assertNotEqual(self.gaming.RESTART_EXIT, 0)  # the unit has Restart=on-failure
        self.assertIn("Restart=on-failure", read("install.sh"))

    def test_logs_and_reports_its_version(self):
        src = read("pocketxr", "gaming.py")
        self.assertIn('service started (Pocket XR {self.version})', src)
        self.assertIn('"version": self.version,', src)


class Panel(unittest.TestCase):
    def test_warns_when_service_and_panel_differ(self):
        tsx = read("decky", "src", "index.tsx")
        self.assertIn("st.version !== st.panel", tsx)
        self.assertIn('answer["panel"] = PANEL_VERSION', read("decky", "main.py"))
        words = read("decky", "src", "words.ts")
        self.assertEqual(words.count("versionMismatch:"), 12)  # the type and 11 languages
        for line in words.splitlines():
            if line.strip().startswith("versionMismatch:") and "string" not in line:
                self.assertIn("{service}", line)
                self.assertIn("{panel}", line)

    def test_glasses_buttons_switch(self):
        self.assertIn('op: "glasses_buttons"', read("decky", "src", "index.tsx"))
        for lang in ("ko", "ja", "zh_CN", "zh_TW", "es", "pt_BR", "fr", "de", "it", "ru"):
            t = json.loads(read("pocketxr", "locale", lang + ".json"))
            self.assertIn("Use the glasses' buttons", t, lang)
            self.assertTrue(any(k.startswith("Lets go of the glasses so their own buttons work") for k in t), lang)


class GlassesButtons(unittest.TestCase):
    def test_let_go_closes_everything_then_takes_them_back(self):
        import socket
        if not hasattr(socket, "AF_UNIX") or not hasattr(socket, "SOCK_SEQPACKET"):
            self.skipTest("needs Unix sockets")
        sys.path.insert(0, os.path.join(ROOT, "tests"))
        from test_offline import FakeXbx
        fake = FakeXbx(lambda num, awake: num == 1 and awake)
        lines, got = [], []
        r = hidimu.AirReader(lambda *a: got.append(a), 0x0442, log=lines.append, nodes=fake.nodes, opener=fake.open)
        r.WAIT_S = 0.4
        r.start()
        end = time.monotonic() + 10
        while time.monotonic() < end and len(got) < 20:
            time.sleep(0.05)
        r.released = True
        time.sleep(1.5)
        n, beats = len(got), fake.beats
        time.sleep(0.8)
        self.assertLessEqual(len(got), n + 2)  # no stream
        self.assertEqual(fake.beats, beats)  # no heartbeat
        self.assertIsNone(r._mcu)
        self.assertIsNone(r.connected_to)
        self.assertIn("imu: MCU heartbeat stopped (let go for the glasses' own buttons)", lines)
        r.released = False
        end = time.monotonic() + 10
        while time.monotonic() < end and len(got) < n + 20:
            time.sleep(0.05)
        r.stop = True
        r.join(3)
        self.assertGreaterEqual(len(got), n + 20)
        self.assertEqual(sum("MCU heartbeat running" in x for x in lines), 2)  # woken again when taken back

    def test_gaming_switch(self):
        try:
            from pocketxr import gaming
        except (ImportError, OSError, AttributeError) as e:
            self.skipTest(f"gaming.py loads on Linux only ({e})")

        class G:
            pass
        g = G()
        g.lines = []
        g.log = g.lines.append
        g.reader = hidimu.AirReader(lambda *a: None, 0x0442, nodes=lambda: [])
        gaming.Gaming._glasses_buttons(g, True)
        self.assertTrue(g.reader.released and g.reader.held)
        gaming.Gaming._glasses_buttons(g, True)
        gaming.Gaming._glasses_buttons(g, False)
        self.assertFalse(g.reader.released)
        self.assertEqual(len(g.lines), 2)


class NestedDesktopPointer(unittest.TestCase):
    def test_wayland_focus(self):
        self.assertTrue(X.wayland_focus([item("gamescope-0")]))
        self.assertFalse(X.wayland_focus([item(":1")]))
        self.assertFalse(X.wayland_focus([]))
        self.assertFalse(X.wayland_focus([0]))
        self.assertIsNone(X.focus_name([item("gamescope-0")]))

    def test_pointer_hidden_for_a_wayland_app(self):
        src = read("pocketxr", "xpointer.py")
        self.assertIn("shown = s.shown() and not in_wayland", src)


if __name__ == "__main__":
    unittest.main()
