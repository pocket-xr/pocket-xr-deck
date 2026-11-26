"""0.7.18 (Pierre Zammit, 26 Nov 2026, on 0.7.17: in a game "the mouse was invisible, yet present"; in Stremio it showed
only over pictures). A cursor blanked by name has a serial Pocket XR did not note, so the app showing that named cursor
again read as the app hiding its cursor, and Pocket XR's own pointer went too. Against Xvfb (scratch run, 26 Nov 2026):
0.7.17 "POINTER HIDDEN", 0.7.18 "pointer kept"."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import xpointer as X  # noqa: E402


class NamedBlank(unittest.TestCase):
    def test_a_name_blanked_here_is_ours(self):
        self.assertTrue(X.blanked_by_name("default", {"default": 5}))
        self.assertFalse(X.blanked_by_name("default", {}))
        self.assertFalse(X.blanked_by_name("", {"default": 5}))
        self.assertFalse(X.blanked_by_name("pointer", {"default": 5}))

    def test_the_decision_keeps_the_pointer_for_our_named_blank(self):
        # serial 8: the app's "default" cursor, now empty by our name blanking; known as ours, the app still wants one
        self.assertEqual(X.cursor_decision(8, False, {9, 8}, True), (True, False))
        # not known: read as the app hiding it (0.7.17's mistake for our own blank)
        self.assertEqual(X.cursor_decision(8, False, {9}, True), (False, False))


if __name__ == "__main__":
    unittest.main()
