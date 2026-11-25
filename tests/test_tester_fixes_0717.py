"""0.7.17: Pierre Zammit's 0.7.16 log (25 Nov 2026). With a second app open, gamescope's arrow stayed, "permanent and
follows my head": gamescope draws the arrow of the X screen with its input focus, and 0.7.16 blanked only the screen
the pointer was read from. And a slow drift to the right: once calibrated lying still, the gyro's zero was still
learnt from a worn head's sway. No X server here: X is stood in."""
import math
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import fusion as F  # noqa: E402
from pocketxr import xpointer as X  # noqa: E402


class FakeScreen:
    def __init__(self, wants):
        self.wants, self.looked = wants, 0

    def hide_step(self):
        self.looked += 1
        return self.wants


class EveryScreen(unittest.TestCase):
    def test_every_screen_is_blanked_and_the_pointer_follows_the_current_one(self):
        a, b = FakeScreen(False), FakeScreen(True)
        screens = {":0": a, ":1": b}
        self.assertFalse(X.hide_all(screens, a))
        self.assertEqual((a.looked, b.looked), (1, 1))
        self.assertTrue(X.hide_all(screens, b))
        self.assertEqual((a.looked, b.looked), (2, 2))


class FakeX11:
    """An X screen with one cursor shown: the app's visible one until a blank is defined on the window it shows."""

    def __init__(self, child, shows_on):
        self.child, self.shows_on, self.defined = child, shows_on, {}

    def XQueryPointer(self, dpy, win, r, c, rx, ry, wx, wy, m):
        c._obj.value = self.child if win == 1 else 0
        return 1

    def XDefineCursor(self, dpy, win, cur):
        self.defined[win] = cur

    def XUndefineCursor(self, dpy, win):
        self.defined.pop(win, None)

    def XSync(self, dpy, discard):
        pass


class RootFallback(unittest.TestCase):
    def screen(self, child, shows_on):
        s = X.Screen.__new__(X.Screen)
        s.name, s.dpy, s.root, s.xf = ":1", 1, 1, None
        s.x11 = FakeX11(child, shows_on)
        s._blank = lambda: 99
        serial = [10]

        def cursor():
            if s.x11.defined.get(s.x11.shows_on) == 99:
                return 50, False
            serial[0] += 1
            return serial[0], True
        s.cursor = cursor
        return s

    def test_with_no_window_under_the_pointer_the_root_is_blanked(self):
        s = self.screen(0, 1)
        self.assertTrue(s.hide_step())
        self.assertIn(1, s.blanked)
        self.assertEqual(s.blank_serial, 50)
        self.assertFalse(getattr(s, "not_taken", None))
        s.restore()
        self.assertEqual(s.x11.defined, {})

    def test_a_window_under_the_pointer_is_still_the_one_blanked(self):
        s = self.screen(7, 7)
        s.hide_step()
        self.assertEqual(s.blanked, {7})
        self.assertEqual(s.blank_serial, 50)

    def test_a_blank_that_does_not_take_is_told(self):
        s = self.screen(7, 8)  # the cursor shown comes from somewhere else (a grab, say)
        s.hide_step()
        self.assertIn("still shown after blanking window 0x7", s.not_taken)


def _have_xfixes():
    import ctypes.util
    return sys.platform.startswith("linux") and bool(ctypes.util.find_library("X11")) and bool(
        ctypes.util.find_library("Xfixes"))


@unittest.skipUnless(_have_xfixes(), "libX11 and libXfixes: Linux")
class NamesAndEventsOn(unittest.TestCase):
    def test_the_real_libxfixes_turns_names_and_events_on(self):
        # 0.7.15 and 0.7.16 asked for XFixesGetCursorImageAndName, which libXfixes does not have: both were off
        x11, xf = X._libs()
        self.assertTrue(xf.by_name)


class SizeNow(unittest.TestCase):
    def test_the_screen_size_comes_from_the_root_window_now(self):
        s = X.Screen.__new__(X.Screen)
        s.root = 1
        s.window_area = lambda win: (0, 0, 1920, 1080)
        self.assertEqual(s.root_size(), (1920, 1080))
        s.window_area = lambda win: None
        self.assertIsNone(s.root_size())


def feed(h, seconds, mean_deg, sd_deg, seed=1, t0=0):
    """[seconds] of 1 kHz reports with each gyro axis at [mean_deg] deg/s and [sd_deg] of noise, level."""
    rnd = random.Random(seed)
    ts = t0
    for _ in range(int(seconds * 1000)):
        ts += 1_000_000
        g = tuple(math.radians(m + rnd.gauss(0.0, sd_deg)) for m in mean_deg)
        h.report(ts, g, (0.0, 9.81, 0.0))
    return ts


class WornHeadNotLearnt(unittest.TestCase):
    CAL = [math.radians(x) for x in (-0.199, 0.047, -0.012)]  # his 20:53:34 calibration

    def test_a_worn_head_s_sway_is_not_taken_as_the_zero_once_calibrated(self):
        h = F.HeadFusion("aura", bias=list(self.CAL))
        self.assertTrue(h.calibrated)
        # His raw reports worn and still: spread about 0.3 to 0.45 deg/s, means a few tenths off
        feed(h, 20.0, (-0.5, 0.15, 0.05), 0.35)
        self.assertEqual(h.rest_blocks, 0)
        self.assertEqual(h.bias, self.CAL)

    def test_before_0_7_17_the_same_sway_was_learnt(self):
        h = F.HeadFusion("aura", bias=list(self.CAL))
        h.calibrated = False  # the old rule
        feed(h, 20.0, (-0.5, 0.15, 0.05), 0.35)
        self.assertGreater(h.rest_blocks, 0)
        self.assertGreater(abs(math.degrees(h.bias[1] - self.CAL[1])), 0.03)

    def test_lying_still_still_refines_it(self):
        h = F.HeadFusion("aura", bias=list(self.CAL))
        feed(h, 10.0, (-0.25, 0.08, -0.012), 0.055)
        self.assertGreater(h.rest_blocks, 0)
        self.assertAlmostEqual(math.degrees(h.bias[1]), 0.08, delta=0.02)

    def test_a_calibration_makes_the_glasses_calibrated(self):
        h = F.HeadFusion("aura")
        self.assertFalse(h.calibrated)
        h.start_calibration(1.0)
        feed(h, 1.2, (-0.2, 0.05, 0.0), 0.05)
        self.assertEqual(h.cal_result[0], "ok")
        self.assertTrue(h.calibrated)


if __name__ == "__main__":
    unittest.main()
