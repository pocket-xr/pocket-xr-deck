"""0.7.19 (Pierre Zammit, 26 Nov 2026): the head's direction went in the log for a minute after glasses, a mode or a
recentre, then never, so a slow drift over minutes of watching never reached a log. Now every 10 s after that minute."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import fusion, gaming  # noqa: E402


class HeadLog(unittest.TestCase):
    def setUp(self):
        self.lines = []

        class G:
            pass
        g = G()
        g.log = self.lines.append
        g.head = fusion.HeadFusion("aura")
        g.head_log_until = 100.0
        g.head_logged = 0.0
        self.g = g

    def test_once_a_second_in_the_first_minute(self):
        for t in (50.0, 50.5, 51.0, 52.0):
            gaming.Gaming._log_head(self.g, t)
        self.assertEqual(len(self.lines), 3)

    def test_every_ten_seconds_after_it_for_as_long_as_it_runs(self):
        t = 200.0
        while t < 200.0 + 3600.0:
            gaming.Gaming._log_head(self.g, t)
            t += 1.0
        self.assertEqual(len(self.lines), 360)
        self.assertTrue(self.lines[-1].startswith("gaming: head yaw "))


if __name__ == "__main__":
    unittest.main()
