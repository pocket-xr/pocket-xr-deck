"""0.7.15: Pierre Zammit's 0.7.14 logs (25 Nov 2026). The pointer reader stuck opening an X screen that never answered,
every 10 s from the moment a game started, so the pointer followed the head there; and a browser's hover cursor
flickered in as a second arrow before it was blanked. No X server here: X is stood in."""
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import xpointer as X  # noqa: E402


class OpeningWithATimeLimit(unittest.TestCase):
    def test_a_screen_that_never_answers_is_left_and_the_others_open(self):
        stuck = threading.Event()
        self.addCleanup(stuck.set)

        def make(name):
            if name == ":2":
                stuck.wait()  # XOpenDisplay on a server that accepts but never answers
            return "screen " + name

        screens, opening = {}, {}
        t0 = time.monotonic()
        said = X.open_screens([":0", ":1", ":2"], screens, opening, make, wait=0.2)
        self.assertLess(time.monotonic() - t0, 2.0)
        self.assertEqual(sorted(screens), [":0", ":1"])
        self.assertEqual([n for n, _ in said], [":2"])
        self.assertIn("not answering", said[0][1])
        # The next round neither waits for it nor says it again
        t0 = time.monotonic()
        self.assertEqual(X.open_screens([":0", ":1", ":2"], screens, opening, make, wait=0.2), [])
        self.assertLess(time.monotonic() - t0, 0.15)
        # Once it answers, it is taken
        stuck.set()
        opening[":2"].thread.join(1.0)
        self.assertEqual(X.open_screens([":0", ":1", ":2"], screens, opening, make, wait=0.2), [])
        self.assertIn(":2", screens)
        self.assertEqual(opening, {})

    def test_a_screen_that_refuses_says_why(self):
        def make(name):
            raise OSError("Authorization required")
        said = X.open_screens([":2"], {}, {}, make, wait=0.5)
        self.assertEqual(said, [(":2", "Authorization required")])


class BlankedNames(unittest.TestCase):
    def test_kept_and_given_back_per_display(self):
        path = os.path.join(tempfile.mkdtemp(), "state", "blanked-cursors")
        X.note_blanked(":1", {"pointer": 1, "text": 2}, path)
        X.note_blanked(":0", {"left_ptr": 3}, path)
        self.assertEqual(sorted(X.blanked_names(path)), [(":0", "left_ptr"), (":1", "pointer"), (":1", "text")])
        X.note_blanked(":1", (), path)
        self.assertEqual(X.blanked_names(path), [(":0", "left_ptr")])

    def test_our_blanks_say_nothing_new(self):
        self.assertEqual(X.cursor_decision(9, False, {8, 9}, True), (True, False))
        self.assertEqual(X.cursor_decision(5, True, {8, 9}, True), (True, True))


class ByName(unittest.TestCase):
    """The hand over a link is blanked by its name, and given back from the theme."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(), "blanked-cursors")
        self.saved = X.BLANKED, X._XCURSOR
        X.BLANKED = self.path
        calls = self.calls = []

        class XC:
            def XcursorLibraryLoadCursor(self, dpy, name):
                calls.append(("load", name))
                return 500

        X._XCURSOR = XC()

    def tearDown(self):
        X.BLANKED, X._XCURSOR = self.saved

    def screen(self):
        calls = self.calls

        class X11:
            def XCreateBitmapFromData(self, *a):
                return 11

            def XCreatePixmapCursor(self, *a):
                return 300

            def XDefineCursor(self, dpy, win, cur):
                calls.append(("define", win, cur))

            def XUndefineCursor(self, dpy, win):
                calls.append(("undefine", win))

            def XSync(self, *a):
                pass

        class XF:
            by_name = True

            def XFixesSetCursorName(self, dpy, cur, name):
                calls.append(("name", cur, name))

            def XFixesChangeCursorByName(self, dpy, cur, name):
                calls.append(("change", cur, name))

        s = X.Screen.__new__(X.Screen)
        s.x11, s.xf, s.dpy, s.root, s.name, s.fixes = X11(), XF(), 1, 100, ":1", True
        s.app = (5, True, "pointer")
        s.cursor = lambda: (s.__setattr__("cursor_name", s.app[2]), s.app[:2])[1]
        s.under_pointer = lambda: 200
        s._blank = lambda: 7
        return s

    def test_a_named_cursor_is_blanked_by_name_and_given_back(self):
        s = self.screen()
        self.assertTrue(s.hide_step())
        self.assertIn(("name", 300, b"pointer"), self.calls)
        self.assertIn(("change", 300, b"pointer"), self.calls)
        self.assertIn(("define", 200, 7), self.calls)
        self.assertEqual(X.blanked_names(self.path), [(":1", "pointer")])
        self.calls.clear()
        s.restore()
        self.assertEqual(self.calls[1:], [("load", b"pointer"), ("name", 500, b"pointer"), ("change", 500, b"pointer")])
        self.assertEqual(X.blanked_names(self.path), [])

    def test_without_libxcursor_nothing_is_blanked_by_name(self):
        X._XCURSOR = None
        s = self.screen()
        self.assertTrue(s.hide_step())
        self.assertFalse([c for c in self.calls if c[0] in ("name", "change")])

    def test_a_reader_that_ended_without_giving_back_is_tidied_by_the_next(self):
        X.note_blanked(":1", {"pointer": 300}, self.path)
        s = self.screen()
        s.named = dict.fromkeys([n for d, n in X.blanked_names(self.path) if d == ":1"], 0)
        s.restore()
        self.assertIn(("change", 500, b"pointer"), self.calls)
        self.assertEqual(X.blanked_names(self.path), [])


if __name__ == "__main__":
    unittest.main()
