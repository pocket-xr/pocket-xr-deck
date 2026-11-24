"""Hiding gamescope's own arrow while the screen is in space (a tester, Pierre Zammit, 24 Nov 2026: two arrows, the one
that moves with the head never where clicks land). xpointer.py blanks the app window's X cursor; gamescope draws no
arrow for an empty cursor image (steamcompmgr.cpp MouseCursor::paint, m_imageEmpty). No X server here: X is stood in."""
import io
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import xpointer as X  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


class Decision(unittest.TestCase):
    def test_the_apps_visible_cursor_is_blanked(self):
        self.assertEqual(X.cursor_decision(5, True, None, True), (True, True))
        self.assertEqual(X.cursor_decision(5, True, 9, False), (True, True))  # the app set a new one: blank it again

    def test_our_blank_says_nothing_new(self):
        self.assertEqual(X.cursor_decision(9, False, 9, True), (True, False))
        self.assertEqual(X.cursor_decision(9, False, 9, False), (False, False))

    def test_the_app_hiding_its_cursor(self):
        self.assertEqual(X.cursor_decision(7, False, 9, True), (False, False))  # an empty one not ours


class FakeScreen(X.Screen):
    """A Screen over a stand-in X: one window under the pointer whose cursor the "app" sets."""

    def __init__(self):
        self.dpy, self.root, self.fixes = 1, 100, True
        self.app_cursor = (5, True)  # serial, visible
        self.defined = {}
        self.calls = []
        test = self

        class X11:
            def XDefineCursor(self, dpy, win, cur):
                test.calls.append(("define", win, cur))
                test.defined[win] = cur

            def XUndefineCursor(self, dpy, win):
                test.calls.append(("undefine", win))
                test.defined.pop(win, None)

            def XSync(self, dpy, discard):
                pass

        self.x11 = X11()

    def cursor(self):
        return (99, False) if self.defined.get(200) == 7 else self.app_cursor

    def under_pointer(self):
        return 200

    def _blank(self):
        return 7


class HideStep(unittest.TestCase):
    def test_blanks_keeps_track_and_gives_back(self):
        s = FakeScreen()
        self.assertTrue(s.hide_step())  # the app shows a cursor: ours stays, gamescope's is blanked
        self.assertEqual(s.calls, [("define", 200, 7)])
        self.assertEqual(s.blank_serial, 99)
        self.assertTrue(s.hide_step())  # our blank: nothing new, still the app's wish
        self.assertEqual(len(s.calls), 1)
        s.defined.clear()
        s.app_cursor = (6, False)  # the app hid its cursor (a game in its own mouse look)
        self.assertFalse(s.hide_step())
        s.restore()
        self.assertIsNone(s.blank_serial)
        self.assertIn(("undefine", 200), s.calls)

    def test_without_xfixes_nothing_is_touched(self):
        s = FakeScreen()
        s.cursor = lambda: None
        self.assertTrue(s.hide_step())
        self.assertEqual(s.calls, [])


class Commands(unittest.TestCase):
    def test_read_from_a_pipe(self):
        if sys.platform == "win32":
            self.skipTest("select on pipes: Linux")
        r, w = os.pipe()
        rf, wf = os.fdopen(r), os.fdopen(w, "w")
        self.assertEqual(X.read_commands(rf), [])
        wf.write("hide 1\nhide 0\n")
        wf.flush()
        self.assertEqual(X.read_commands(rf, 0.5), ["hide 1", "hide 0"])
        wf.close()
        self.assertIsNone(X.read_commands(rf, 0.5))

    def test_a_part_line_waits_for_the_rest(self):
        if sys.platform == "win32":
            self.skipTest("select on pipes: Linux")
        r, w = os.pipe()
        buf = bytearray()
        os.write(w, b"hide ")
        self.addCleanup(os.close, r)
        self.addCleanup(os.close, w)
        self.assertEqual(X.read_commands(os.fdopen(r, closefd=False), 0.5, buf), [])
        os.write(w, b"1\n")
        self.assertEqual(X.read_commands(os.fdopen(r, closefd=False), 0.5, buf), ["hide 1"])

    def test_no_file_ends_reading(self):
        self.assertIsNone(X.read_commands(io.StringIO("")))


class GamingService(unittest.TestCase):
    def setUp(self):
        try:
            from pocketxr import gaming
        except (ImportError, OSError, AttributeError) as e:
            self.skipTest(f"gaming.py loads on Linux only ({e})")
        self.gaming = gaming

    def fake(self, effect, setting=True):
        class P:
            def __init__(self):
                self.stdin = io.StringIO()

            def poll(self):
                return None

        class G:
            pass
        g = G()
        g.pointer_proc = P()
        g.effect_on = effect
        g.settings = {"hide_gamescope_pointer": setting}
        g.pointer_hide_sent = None
        return g

    def test_hidden_only_with_the_screen_in_space(self):
        g = self.fake(True)
        self.gaming.Gaming._pointer_hide(g)
        self.gaming.Gaming._pointer_hide(g)  # said once
        self.assertEqual(g.pointer_proc.stdin.getvalue(), "hide 1\n")
        g.effect_on = False
        self.gaming.Gaming._pointer_hide(g)
        self.assertEqual(g.pointer_proc.stdin.getvalue(), "hide 1\nhide 0\n")

    def test_the_switch_off_keeps_it(self):
        g = self.fake(True, setting=False)
        g.pointer_hide_sent = True
        self.gaming.Gaming._pointer_hide(g)
        self.assertEqual(g.pointer_proc.stdin.getvalue(), "hide 0\n")

    def test_on_by_default(self):
        self.assertTrue(self.gaming.DEFAULTS["hide_gamescope_pointer"])

    def test_reader_gets_a_stdin(self):
        with open(os.path.join(ROOT, "pocketxr", "gaming.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("stdin=subprocess.PIPE", src)


class Panel(unittest.TestCase):
    def test_quick_access(self):
        with open(os.path.join(ROOT, "decky", "src", "index.tsx"), encoding="utf-8") as f:
            self.assertIn('op: "set_hide_pointer"', f.read())


if __name__ == "__main__":
    unittest.main()
