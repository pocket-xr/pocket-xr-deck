"""A tester's reports on 0.7.2 (Pierre Zammit, 22 Nov 2026 evening, XBX A01+ on a Deck): a 6 second wait for motion
after the glasses appear, the pointer read from the wrong X screen, libX11's message every 3 seconds, and stick-click
shortcuts that work in every game."""
import json
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import deckpad as D  # noqa: E402
from pocketxr import xpointer as X  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
L3, R3 = D.STICKS["L3"], D.STICKS["R3"]


def play(steps, dt=0.004):
    """Feeds Sticks [(bits, seconds)] at a report every dt; returns the events."""
    events = []
    s = D.Sticks(lambda n, k: events.append((n, k)))
    t = 0.0
    for bits, seconds in steps:
        end = t + seconds
        while t < end:
            s.feed(bits, t)
            t += dt
    return events


def clicks(mask, n, down=0.1, gap=0.15):
    out = []
    for _ in range(n):
        out += [(mask, down), (0, gap)]
    return out


class Sticks(unittest.TestCase):
    def test_bits_match_linux_hid_steam(self):
        # hid-steam: BTN_THUMBL is byte 10 bit 6, BTN_THUMBR byte 11 bit 2, of the u64 from byte 8
        self.assertEqual(L3, 1 << ((10 - 8) * 8 + 6))
        self.assertEqual(R3, 1 << ((11 - 8) * 8 + 2))
        self.assertFalse(set(D.STICKS.values()) & set(D.BUTTONS.values()))

    def test_a_long_hold(self):
        self.assertEqual(play([(L3, 1.2), (0, 1.0)]), [("L3", "hold")])
        self.assertEqual(play([(R3, 1.2), (0, 1.0)]), [("R3", "hold")])

    def test_a_short_press_or_one_click_does_nothing(self):
        self.assertEqual(play(clicks(L3, 1) + [(0, 1.0)]), [])
        self.assertEqual(play([(L3, 0.6), (0, 1.0)]), [])  # longer than a click, shorter than a hold

    def test_runs_of_clicks(self):
        self.assertEqual(play(clicks(L3, 2) + [(0, 1.0)]), [("L3", "double")])
        self.assertEqual(play(clicks(L3, 3) + [(0, 1.0)]), [("L3", "triple")])
        self.assertEqual(play(clicks(L3, 4) + [(0, 1.0)]), [])
        self.assertEqual(play(clicks(R3, 3) + [(0, 1.0)]), [("R3", "triple")])

    def test_slow_clicks_are_not_a_run(self):
        self.assertEqual(play(clicks(L3, 3, gap=0.7) + [(0, 1.0)]), [])

    def test_clicks_then_a_hold_is_the_hold(self):
        self.assertEqual(play(clicks(L3, 2) + [(L3, 1.2), (0, 1.0)]), [("L3", "hold")])

    def test_the_other_buttons_are_left_alone(self):
        self.assertEqual(play([(D.BUTTONS["L4"], 1.2), (0, 1.0)]), [])


class PointerScreen(unittest.TestCase):
    def test_focus_name_from_gamescopes_items(self):
        self.assertEqual(X.focus_name([int.from_bytes(b":1\0\0", "little")]), ":1")
        self.assertEqual(X.focus_name([int.from_bytes(b":10\0", "little")]), ":10")
        self.assertEqual(X.focus_name([0xFFFFFFFF00000000 | int.from_bytes(b":0\0x", "little")]), ":0")
        self.assertIsNone(X.focus_name([]))
        self.assertIsNone(X.focus_name([int.from_bytes(b"abc\0", "little")]))

    def test_the_screen_with_the_mouse_wins(self):
        class S:
            def __init__(self, moved_at):
                self.moved_at = moved_at
        screens = {":0": S(10.0), ":1": S(5.0)}
        self.assertIs(X.pick(screens, ":1"), screens[":1"])  # gamescope says :1, though :0 moved last
        self.assertIs(X.pick(screens, None), screens[":0"])
        self.assertIs(X.pick(screens, ":2"), screens[":0"])  # a screen not open here

    def test_libx11s_message_is_caught(self):
        if not hasattr(os, "dup2"):
            return
        result, said = X.quietly(lambda: (os.write(2, b"Authorization required, but no authorization protocol "
                                                       b"specified\n"), 7)[1])
        self.assertEqual(result, 7)
        self.assertEqual(said, "Authorization required, but no authorization protocol specified")

    def test_an_unopened_screen_is_said_once(self):
        with open(os.path.join(ROOT, "pocketxr", "xpointer.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("if name not in unopened:", src)
        self.assertIn("GAMESCOPE_MOUSE_FOCUS_DISPLAY", src)


class GamingSticks(unittest.TestCase):
    def setUp(self):
        try:
            from pocketxr import gaming
        except (ImportError, OSError, AttributeError) as e:
            self.skipTest(f"gaming.py loads on Linux only ({e})")
        self.gaming = gaming

    def fake(self, sticks=True):
        class G:
            pass
        g = G()
        g.lines, g.done = [], []
        g.log = g.lines.append
        g.lock = threading.Lock()
        g.settings = {"sticks": sticks}
        g.reshade, g.glasses = object(), object()
        g.cal_due, g.cal_text = None, "old"
        g.recentre = lambda: g.done.append("recentre")
        g.next_mode = lambda: g.done.append("next_mode")
        g._stick = lambda n, k: self.gaming.Gaming._stick(g, n, k)
        return g

    def test_hold_and_three_clicks(self):
        g = self.fake()
        for name, kind in (("L3", "hold"), ("R3", "hold"), ("L3", "double"), ("R3", "triple"), ("L3", "tap")):
            self.gaming.Gaming._button(g, name, kind)
        self.assertEqual(g.done, ["recentre", "next_mode"])
        self.assertIsNone(g.cal_due)
        self.gaming.Gaming._button(g, "L3", "triple")
        self.assertIsNotNone(g.cal_due)
        self.assertIn("gaming: L3 clicked three times: calibration in 5 s", g.lines)

    def test_off_or_outside_gaming_mode_does_nothing(self):
        g = self.fake(sticks=False)
        self.gaming.Gaming._button(g, "L3", "hold")
        self.gaming.Gaming._button(g, "L3", "triple")
        self.assertEqual(g.done, [])
        self.assertIsNone(g.cal_due)
        g = self.fake()
        g.reshade = None
        self.gaming.Gaming._button(g, "L3", "hold")
        self.assertEqual(g.done, [])

    def test_on_by_default(self):
        self.assertTrue(self.gaming.DEFAULTS["sticks"])


class Panel(unittest.TestCase):
    def test_stick_switch_in_quick_access(self):
        with open(os.path.join(ROOT, "decky", "src", "index.tsx"), encoding="utf-8") as f:
            tsx = f.read()
        self.assertIn('op: "set_sticks"', tsx)
        self.assertIn("st.sticks_label", tsx)

    def test_new_lines_in_every_language(self):
        for lang in ("ko", "ja", "zh_CN", "zh_TW", "es", "pt_BR", "fr", "de", "it", "ru"):
            with open(os.path.join(ROOT, "pocketxr", "locale", lang + ".json"), encoding="utf-8") as f:
                t = json.load(f)
            self.assertIn("Stick clicks", t, lang)
            self.assertTrue(any(k.startswith("In every game: hold L3 to recentre") for k in t), lang)


if __name__ == "__main__":
    unittest.main()
