"""Text size and Readability for the PC screens a phone streams from this computer, as Pocket XR for Mac's
(SpaceSettings, Checks/SettingsChecks.swift textSizeChecks and readability checks)."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import readability as R  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


class MacSizes(unittest.TestCase):
    def test_same_as_the_mac(self):
        self.assertEqual(R.TEXT_SCALES, (100, 125, 150))
        self.assertEqual(R.screen_size(100), (1920, 1080))  # "Standard is 1920 x 1080"
        self.assertEqual(R.screen_size(125), (1536, 864))  # "125% is 1536 x 864"
        self.assertEqual(R.screen_size(150), (1280, 720))  # "150% is 1280 x 720"
        self.assertEqual(R.READABILITY_SCREEN, (1440, 810))

    def test_a_size_not_offered_goes_to_the_nearest(self):
        self.assertEqual(R.text_scale_of(140), 150)
        self.assertEqual(R.text_scale_of(10), 100)
        self.assertEqual(R.text_scale_of("x"), 100)
        self.assertEqual(R.text_scale_of(None), 100)
        self.assertEqual(R.text_scale_of(float("nan")), 100)
        self.assertEqual(R.label(100), "Standard")
        self.assertEqual(R.label(125), "125%")


class HostScale(unittest.TestCase):
    def test_text_size(self):
        self.assertEqual(R.host_scale(1920, False, 100), 1.0)
        self.assertEqual(R.host_scale(1920, False, 125), 1.25)
        self.assertEqual(R.host_scale(1920, False, 150), 1.5)

    def test_readability_takes_its_place(self):
        s = R.host_scale(1920, True, 150)
        self.assertAlmostEqual(1920 / s, 1440, delta=1)  # laid out 1440 wide
        self.assertAlmostEqual(R.host_scale(2880, True, 100), 2.0, places=3)

    def test_never_below_one_and_in_wayland_steps(self):
        self.assertEqual(R.host_scale(1280, True, 100), 1.0)  # a small screen is not made smaller
        self.assertLessEqual(R.host_scale(9000, True, 100), R.SCALE_MAX)
        s = R.host_scale(1920, True, 100)
        self.assertAlmostEqual(s * 120, round(s * 120), places=2)

    def test_log_line(self):
        self.assertEqual(R.host_line("PC screen 1", "Virtual-pxr-47989", 1920, 1080, False, 125, 1.25),
                         "host: PC screen 1 (Virtual-pxr-47989) made at 1920x1080, scale 1.25 (Text size 125%): "
                         "apps see 1536x864")
        line = R.host_line("PC screen 2", "Virtual-pxr-48989", 1920, 1080, True, 100, R.host_scale(1920, True, 100))
        self.assertIn("(Readability): apps see 1440x810", line)


class DesktopChoice(unittest.TestCase):
    def test_from_the_desktop_apps_settings(self):
        d = tempfile.mkdtemp()
        p = os.path.join(d, "settings.json")
        self.assertEqual(R.desktop_choice(p), (False, 100))  # no file
        with open(p, "w") as f:
            json.dump({"readability": True, "text_scale": 125}, f)
        self.assertEqual(R.desktop_choice(p), (True, 125))
        with open(p, "w") as f:
            f.write("[1, 2]")
        self.assertEqual(R.desktop_choice(p), (False, 100))


class Host(unittest.TestCase):
    def test_kscreen_doctor_argument(self):
        from pocketxr.host import desktop
        calls = []
        saved = desktop._run
        desktop._run = lambda args, **k: (calls.append(args), (0, ""))[1]
        try:
            self.assertIsNone(desktop.set_scale("Virtual-pxr-47989", 1.25))
            desktop.set_scale("Virtual-pxr-47989", R.host_scale(1920, True, 100))
            desktop.set_scale("Virtual-pxr-47989", 1.0)
            desktop._run = lambda args, **k: (1, "no such output")
            self.assertEqual(desktop.set_scale("x", 1.5), "no such output")
        finally:
            desktop._run = saved
        self.assertEqual(calls, [["kscreen-doctor", "output.Virtual-pxr-47989.scale.1.25"],
                                 ["kscreen-doctor", "output.Virtual-pxr-47989.scale.1.3333"],
                                 ["kscreen-doctor", "output.Virtual-pxr-47989.scale.1"]])

    def test_each_pc_screen_is_scaled_and_logged(self):
        try:
            from pocketxr.host import server
        except (ImportError, OSError) as e:
            self.skipTest(f"the host loads on Linux only ({e})")

        class S:
            width, height = 1920, 1080

        class Fake:
            name = "PC screen 1"
        f = Fake()
        f.lines = []
        f.log = f.lines.append
        asked = []
        saved = server.desktop.set_scale, R.desktop_choice
        server.desktop.set_scale = lambda name, scale: asked.append((name, scale))
        R.desktop_choice = lambda path=None: (False, 150)
        try:
            server.Screen._scale(f, S(), "Virtual-pxr-47989")
        finally:
            server.desktop.set_scale, R.desktop_choice = saved
        self.assertEqual(asked, [("Virtual-pxr-47989", 1.5)])
        self.assertEqual(f.lines, ["host: PC screen 1 (Virtual-pxr-47989) made at 1920x1080, scale 1.5 "
                                   "(Text size 150%): apps see 1280x720"])


class DesktopApp(unittest.TestCase):
    def read(self, *p):
        with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
            return f.read()

    def test_setting_panel_and_log(self):
        app = self.read("pocketxr", "app.py")
        self.assertIn('"text_scale": 100,', app)
        self.assertIn('elif cmd == "text_size":', app)
        self.assertIn("text size: {old}% -> {new}%, PC screens laid out at {w}x{h}", app)
        panel = self.read("pocketxr", "panel.py")
        self.assertIn('send("text_size", step)', panel)


if __name__ == "__main__":
    unittest.main()
