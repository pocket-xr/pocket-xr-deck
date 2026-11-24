"""0.7.13, from a tester's 0.7.12 log (Pierre Zammit, 24 Nov 2026): the pointer reader said one line at start and then
nothing for 17 minutes without ending, so Pocket XR drew no pointer of its own and never hid gamescope's arrow. A
reader stuck in one look now prints where it was and ends, and gaming.py starts it again. No X server here: the X
screen is stood in by one whose pointer never answers."""
import os
import subprocess
import sys
import time
import unittest

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")

STUCK = r'''
import sys, time
sys.path.insert(0, sys.argv[1])
from pocketxr import xpointer as X
X.STUCK_S = 0.5
X._libs = lambda: (None, None)
X.display_names = lambda root=None: [":0"]
class Stuck:
    def __init__(self, x11, xf, name):
        self.name, self.size, self.last, self.moved_at = name, (1280, 800), None, 0.0
    def pointer(self):
        time.sleep(30)  # an X screen that stopped answering
    def restore(self):
        pass
X.Screen = Stuck
sys.exit(X.main([]))
'''


class StuckReader(unittest.TestCase):
    def test_a_stuck_look_says_where_and_ends(self):
        t0 = time.monotonic()
        p = subprocess.run([sys.executable, "-c", STUCK, ROOT], stdin=subprocess.PIPE, capture_output=True, text=True,
                           timeout=20)
        took = time.monotonic() - t0
        self.assertLess(took, 10, "the reader should end soon after STUCK_S, not wait for the look")
        self.assertNotEqual(p.returncode, 0)
        self.assertIn("Timeout (", p.stdout)
        self.assertIn("in pointer", p.stdout)  # where it was stuck

    def test_gaming_logs_the_stuck_line(self):
        with open(os.path.join(ROOT, "pocketxr", "gaming.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn('line.startswith("Timeout (")', src)
        self.assertIn("pointer reader stuck", src)


if __name__ == "__main__":
    unittest.main()
