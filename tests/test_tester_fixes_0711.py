"""A tester's report on 0.7.10 (Pierre Zammit, 24 Nov 2026, XBX A01+ on a Deck): a tap sensitivity slider, recentre
that takes the head's roll for lying on one side, and brightness that his XBX does not take."""
import json
import math
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import fusion as F  # noqa: E402
from pocketxr import hidimu  # noqa: E402
from pocketxr import taps as T  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from test_tester_fixes_075 import run  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def head(yaw, pitch, roll=0.0):
    """Turned yaw left, pitched up, then rolled about the line of sight (degrees)."""
    q = F.qmul(F.about_y(math.radians(yaw)), F.about_x(math.radians(pitch)))
    return F.qnorm(F.qmul(q, F.about_z(math.radians(roll))))


def recentred(q, follow_roll):
    h = F.HeadFusion("aura")
    h.q = q
    h.recentre(follow_tilt=True, follow_roll=follow_roll)
    h._apply_recentre()
    return h


def angle_deg(q):
    return math.degrees(2 * math.acos(min(1.0, abs(q[0]))))


class RecentreRoll(unittest.TestCase):
    def test_lying_on_one_side_lines_the_picture_up_with_the_eyes(self):
        for yaw, pitch, roll in ((0, 0, 90), (0, 0, -90), (30, 10, 80), (120, -30, 45), (-60, 25, -30)):
            h = recentred(head(yaw, pitch, roll), True)
            self.assertLess(angle_deg(h.view()), 0.01, (yaw, pitch, roll))
            self.assertAlmostEqual(math.degrees(h.ref_roll), roll, places=3)

    def test_off_keeps_the_horizon_level(self):
        h = recentred(head(30, 10, 80), False)
        self.assertEqual(h.ref_roll, 0.0)
        self.assertAlmostEqual(angle_deg(h.view()), 80.0, places=3)  # the roll is left in the view, as before

    def test_sitting_up_changes_nothing(self):
        for follow in (True, False):
            h = recentred(head(10, 20, 0), follow)
            self.assertLess(angle_deg(h.view()), 0.01)

    def test_the_fusions_own_recentres_keep_the_roll(self):
        h = recentred(head(0, 0, 70), True)
        h._apply_recentre()  # a recentre of its own (no new tilt asked for)
        self.assertAlmostEqual(math.degrees(h.ref_roll), 70.0, places=3)

    def test_head_roll_maths(self):
        self.assertAlmostEqual(math.degrees(F.head_roll(head(45, 20, 33), math.radians(45), math.radians(20))), 33,
                               places=4)


class TapSensitivity(unittest.TestCase):
    def test_default_keeps_the_values_he_likes(self):
        t = T.Taps(lambda n: None)
        self.assertEqual(t.sensitivity, 100)
        self.assertEqual((t.tap_g, t.jerk_g, t.log_g), (T.TAP_G, T.JERK_G, T.LOG_G))

    def test_scales_the_thresholds_within_its_range(self):
        t = T.Taps(lambda n: None)
        t.set_sensitivity(200)
        self.assertAlmostEqual(t.tap_g, T.TAP_G / 2)
        self.assertAlmostEqual(t.jerk_g, T.JERK_G / 2)
        self.assertLessEqual(t.log_g, t.tap_g)
        t.set_sensitivity(50)
        self.assertAlmostEqual(t.tap_g, T.TAP_G * 2)
        t.set_sensitivity(1000)
        self.assertEqual(t.sensitivity, T.SENSITIVITY[1])
        t.set_sensitivity("x")
        self.assertEqual(t.sensitivity, 100)

    def test_soft_taps_count_only_when_high(self):
        def runs(sens, g):
            got = []
            tp = T.Taps(got.append)
            tp.set_sensitivity(sens)
            hz = 1000.0
            for i in range(int(3.0 * hz)):
                t = i / hz
                az = g if any(at <= t < at + 0.004 for at in (1.0, 1.3)) else 0.0
                tp.feed(100 + t, (0.0, 0.0, 0.0), (0.0, T.G, az * T.G))
            return got
        self.assertEqual(runs(100, 0.2), [])  # too soft at the default
        self.assertEqual(runs(200, 0.2), [2])
        self.assertEqual(runs(50, 0.35), [])  # firm ones only when low
        self.assertEqual(runs(100, 0.35), [2])

    def test_his_recorded_style_taps_still_count_at_the_default(self):
        self.assertEqual(run(3.0, taps_at=(1.0, 1.32), tap_g=0.35, tap_s=0.005), [2])


class BrightnessReadBack(unittest.TestCase):
    def reader(self):
        lines = []
        r = hidimu.AirReader(lambda *a: None, 0x0442, log=lines.append, nodes=lambda: [])
        r._mcu_running = lambda: True
        return r, lines

    def frame(self, msg, data):
        return hidimu.mcu_command(msg, bytes(data))

    def test_a_set_that_does_not_take_hides_it(self):
        r, lines = self.reader()
        r._mcu_frame(self.frame(hidimu.MCU_R_BRIGHTNESS, [0, 4]))
        self.assertEqual(r.brightness, 4)
        r.set_brightness(6)
        r._mcu_frame(self.frame(hidimu.MCU_W_BRIGHTNESS, [0]))
        r._mcu_frame(self.frame(hidimu.MCU_R_BRIGHTNESS, [0, 4]))  # still 4
        self.assertIsNone(r.brightness)
        self.assertIn("imu: these glasses don't take the brightness commands (set to 6, it reads back 4); "
                      "the slider is hidden", lines)

    def test_his_answers_hide_it(self):
        r, lines = self.reader()
        r._mcu_frame(self.frame(hidimu.MCU_W_BRIGHTNESS, [4]))  # 0.7.10's log: every set answered 04
        self.assertTrue(r.brightness_unsupported)
        self.assertEqual(sum("don't take the brightness commands" in x for x in lines), 1)  # said once
        r._mcu_frame(self.frame(hidimu.MCU_W_BRIGHTNESS, [4]))
        self.assertEqual(sum("don't take the brightness commands" in x for x in lines), 1)


class GamingService(unittest.TestCase):
    def setUp(self):
        try:
            from pocketxr import gaming
        except (ImportError, OSError, AttributeError) as e:
            self.skipTest(f"gaming.py loads on Linux only ({e})")
        self.gaming = gaming

    def test_defaults(self):
        self.assertEqual(self.gaming.DEFAULTS["tap_sensitivity"], 100)
        self.assertFalse(self.gaming.DEFAULTS["recentre_roll"])

    def test_recentre_passes_the_option(self):
        class G:
            pass
        g = G()
        g.lines = []
        g.log = g.lines.append
        g.head_log_until = 0
        g.control = None
        g.settings = {"recentre_roll": True}
        asked = []

        class Head:
            def recentre(self, **k):
                asked.append(k)
        g.head = Head()
        g.mode = lambda: "space"
        self.gaming.Gaming.recentre(g)
        self.assertEqual(asked, [{"follow_tilt": True, "follow_roll": True}])


class Panel(unittest.TestCase):
    def test_quick_access(self):
        with open(os.path.join(ROOT, "decky", "src", "index.tsx"), encoding="utf-8") as f:
            tsx = f.read()
        self.assertIn('op: "set_tap_sensitivity"', tsx)
        self.assertIn('op: "set_recentre_roll"', tsx)
        for lang in ("ko", "ja", "zh_CN", "zh_TW", "es", "pt_BR", "fr", "de", "it", "ru"):
            with open(os.path.join(ROOT, "pocketxr", "locale", lang + ".json"), encoding="utf-8") as f:
                t = json.load(f)
            self.assertIn("Tap sensitivity", t, lang)
            self.assertIn("Recentre includes head tilt", t, lang)


if __name__ == "__main__":
    unittest.main()
