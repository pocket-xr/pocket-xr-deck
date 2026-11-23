"""A tester's reports on 0.7.4 and 0.7.3 (Pierre Zammit, 23 Nov 2026, XBX A01+ on a Deck): taps on the glasses, and
the pointer measured across the game's window. The heartbeat's pacing is in test_offline.py."""
import json
import math
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import taps as T  # noqa: E402
from pocketxr import xpointer as X  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
HZ = 1000.0  # the XBX sends about 1000 reports a second (his imu-raw.log)


def run(seconds, accel=lambda t: (0.0, 0.0, 0.0), gyro=lambda t: (0.0, 0.0, 0.0), taps_at=(), tap_g=2.0,
        tap_s=0.004, t0=100.0, ring_g=0.1, lines=None):
    """Feeds Taps a head at rest (gravity along y) plus accel(t) (in g) and gyro(t) (deg/s), with a tap of tap_g for
    tap_s at each time in taps_at, ringing down after it; returns the runs it reported."""
    got = []
    tp = T.Taps(got.append, None if lines is None else lines.append)
    n = int(seconds * HZ)
    for i in range(n):
        t = i / HZ
        ax, ay, az = accel(t)
        ay += 1.0
        for at in taps_at:
            if at <= t < at + tap_s:
                az += tap_g
            elif at + tap_s <= t < at + 0.04:  # the frame ringing on after the tap
                az += ring_g * math.sin((t - at) * 2 * math.pi * 150)
        g = tuple(math.radians(x) for x in gyro(t))
        tp.feed(t0 + t, g, (ax * T.G, ay * T.G, az * T.G))
    return got


class Taps(unittest.TestCase):
    def test_two_and_three_taps(self):
        self.assertEqual(run(2.5, taps_at=(1.0, 1.25)), [2])
        self.assertEqual(run(2.5, taps_at=(1.0, 1.3, 1.6)), [3])

    def test_one_or_four_taps_do_nothing(self):
        self.assertEqual(run(2.5, taps_at=(1.0,)), [])
        self.assertEqual(run(3.0, taps_at=(1.0, 1.25, 1.5, 1.75)), [])

    def test_slow_taps_are_not_a_run(self):
        self.assertEqual(run(3.0, taps_at=(1.0, 1.9)), [])

    def test_soft_or_long_jolts_are_not_taps(self):
        self.assertEqual(run(2.5, taps_at=(1.0, 1.25), tap_g=0.2), [])
        self.assertEqual(run(2.5, taps_at=(1.0, 1.25), tap_s=0.12), [])  # a push, not a tap

    def test_the_first_half_second_is_skipped(self):
        # his recordings start with one junk report (3.5 g): it is not a tap
        self.assertEqual(run(1.5, taps_at=(0.05, 0.25)), [])

    def test_head_turns_alone_and_taps_while_turning(self):
        turning = lambda t: (0.0, 150.0 * math.sin(t * 2 * math.pi * 0.7), 0.0)  # side to side, up to 150 deg/s
        tilt = lambda t: (0.2 * math.sin(t * 2 * math.pi * 0.7), 0.0, 0.1 * math.cos(t * 2 * math.pi * 0.7))
        self.assertEqual(run(6.0, accel=tilt, gyro=turning), [])
        fast = lambda t: (0.0, 120.0, 0.0)
        self.assertEqual(run(2.5, gyro=fast, taps_at=(1.0, 1.25)), [])  # a jolt during a fast turn is left out

    def test_walking(self):
        def steps(t):
            # 2 steps a second: a sway of 0.3 g and a heel strike of 0.7 g over 20 ms at each step
            p = t % 0.5
            strike = 0.7 * math.sin(math.pi * p / 0.02) if p < 0.02 else 0.0
            return (0.05 * math.sin(t * 2 * math.pi), 0.3 * math.sin(t * 4 * math.pi) + strike, 0.0)
        self.assertEqual(run(10.0, accel=steps, gyro=lambda t: (0.0, 20.0 * math.sin(t * 2 * math.pi), 0.0)), [])

    def test_hard_steps_over_the_tap_level_stay_out(self):
        def stomps(t):  # 1.0 g heel strikes lasting 100 ms, every half second: longer than a tap
            p = t % 0.5
            return (0.0, 1.0 * math.sin(math.pi * p / 0.1) if p < 0.1 else 0.0, 0.0)
        self.assertEqual(run(6.0, accel=stomps), [])

    def test_a_gap_in_the_reports_starts_again(self):
        got = []
        tp = T.Taps(got.append)
        for i in range(800):
            tp.feed(i / HZ, (0.0, 0.0, 0.0), (0.0, T.G, 0.0))
        tp.feed(5.0, (0.0, 0.0, 0.0), (0.0, T.G, 3 * T.G))  # after a 4 s gap: no tap from the jump
        self.assertIsNone(tp.jolt)
        self.assertEqual(got, [])


class SoftTaps(unittest.TestCase):
    """0.7.6's values, from his taps on the top of the frame (23 Nov 2026): 0.33 to 0.51 g, about 320 ms apart."""

    def test_soft_taps_like_his(self):
        self.assertEqual(run(3.0, taps_at=(1.0, 1.32), tap_g=0.35, tap_s=0.005), [2])
        self.assertEqual(run(3.0, taps_at=(1.0, 1.32, 1.64), tap_g=0.35, tap_s=0.005), [3])

    def test_two_a_second(self):
        self.assertEqual(run(3.0, taps_at=(1.0, 1.5), tap_g=0.35), [2])
        self.assertEqual(run(3.5, taps_at=(1.0, 1.5, 2.0), tap_g=0.35), [3])

    def test_ringing_does_not_eat_the_next_tap(self):
        # the frame ringing at 0.3 g for 40 ms after each tap: one tap each, and the second still counts
        self.assertEqual(run(3.0, taps_at=(1.0, 1.25), tap_g=0.4, ring_g=0.3), [2])
        self.assertEqual(run(3.0, taps_at=(1.0, 1.3, 1.6), tap_g=0.4, ring_g=0.3), [3])

    def test_too_close_together(self):
        # putting the glasses on gave two sharp jolts 134 ms apart: not a run
        self.assertEqual(run(3.0, taps_at=(1.0, 1.134), tap_g=0.4), [])

    def test_every_jolt_is_logged_with_why(self):
        lines = []
        run(3.0, taps_at=(1.0, 1.3), tap_g=0.35, lines=lines)
        taps = [x for x in lines if x.startswith("taps: jolt ")]
        self.assertEqual(len(taps), 2, lines)
        self.assertIn("a tap, 1 in this run", taps[0])
        self.assertIn("last tap 300 ms before: a tap, 2 in this run", taps[1])
        self.assertIn("head turning", taps[0])
        lines = []
        run(3.0, taps_at=(1.0,), tap_g=0.2, lines=lines)
        self.assertTrue(any("not a tap: too soft" in x for x in lines), lines)
        lines = []
        run(3.0, taps_at=(1.0,), tap_g=0.4, lines=lines)
        self.assertIn("taps: a run of 1 ended: only two or three do something", lines)

    def test_the_log_is_capped(self):
        lines = []
        run(100.0, taps_at=[1.0 + 0.9 * i for i in range(100)], tap_g=0.4, lines=lines)
        self.assertLessEqual(len(lines), 2 * T.LOG_MAX + 2)


class Pointer(unittest.TestCase):
    def test_measured_across_the_games_window(self):
        # a 1280x720 game on a 1280x800 X screen, at the top: the bottom of the window is v = 1, not 0.9
        self.assertEqual(X.to_uv((640, 720), (1280, 800), (0, 0, 1280, 720)), (0.5, 1.0))
        self.assertEqual(X.to_uv((640, 720), (1280, 800)), (0.5, 0.9))
        self.assertEqual(X.to_uv((660, 50), (1280, 800), (20, 40, 1280, 720)), (0.5, round(10 / 720, 4)))

    def test_the_helper_uses_gamescopes_focused_window(self):
        with open(os.path.join(ROOT, "pocketxr", "xpointer.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("GAMESCOPE_FOCUSED_WINDOW", src)
        self.assertIn("GAMESCOPE_FOCUS_DISPLAY", src)
        self.assertIn("XSetErrorHandler", src)


class GamingTaps(unittest.TestCase):
    def setUp(self):
        try:
            from pocketxr import gaming
        except (ImportError, OSError, AttributeError) as e:
            self.skipTest(f"gaming.py loads on Linux only ({e})")
        self.gaming = gaming

    def fake(self, on=True):
        class G:
            pass
        g = G()
        g.lines, g.done, g.fed = [], [], []
        g.log = g.lines.append
        g.lock = threading.Lock()
        g.settings = {"taps": on}
        g.reshade, g.glasses = object(), object()
        g.recentre = lambda: g.done.append("recentre")
        g.next_mode = lambda: g.done.append("next_mode")

        class Head:
            cal = None

            def report(self, *a):
                g.fed.append("head")
        g.head = Head()

        class Tp:
            def feed(self, *a):
                g.fed.append("taps")
        g.taps = Tp()
        return g

    def test_two_and_three(self):
        g = self.fake()
        self.gaming.Gaming._tapped(g, 2)
        self.gaming.Gaming._tapped(g, 3)
        self.assertEqual(g.done, ["recentre", "next_mode"])
        self.assertIn("gaming: glasses tapped twice", g.lines)

    def test_reports_reach_the_taps_only_when_on(self):
        g = self.fake(on=False)
        self.gaming.Gaming._report(g, 1, (0, 0, 0), (0, 9.8, 0))
        self.assertEqual(g.fed, ["head"])
        g = self.fake(on=True)
        self.gaming.Gaming._report(g, 1, (0, 0, 0), (0, 9.8, 0))
        self.assertEqual(g.fed, ["head", "taps"])
        g.head.cal = {}  # lying still for a calibration: no taps
        self.gaming.Gaming._report(g, 1, (0, 0, 0), (0, 9.8, 0))
        self.assertEqual(g.fed, ["head", "taps", "head"])

    def test_off_by_default(self):
        self.assertFalse(self.gaming.DEFAULTS["taps"])


class Panel(unittest.TestCase):
    def test_taps_switch_in_quick_access(self):
        with open(os.path.join(ROOT, "decky", "src", "index.tsx"), encoding="utf-8") as f:
            tsx = f.read()
        self.assertIn('op: "set_taps"', tsx)

    def test_new_lines_in_every_language(self):
        for lang in ("ko", "ja", "zh_CN", "zh_TW", "es", "pt_BR", "fr", "de", "it", "ru"):
            with open(os.path.join(ROOT, "pocketxr", "locale", lang + ".json"), encoding="utf-8") as f:
                t = json.load(f)
            self.assertIn("Taps on the glasses", t, lang)
            self.assertTrue(any(k.startswith("Tap the glasses' frame twice") for k in t), lang)


if __name__ == "__main__":
    unittest.main()
