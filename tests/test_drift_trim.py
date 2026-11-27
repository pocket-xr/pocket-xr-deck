"""0.7.20 (Pierre Zammit, 27 Nov 2026, XBX A01+ on a Deck, 0.7.19: "apart from the slow drift ... can a LH/RH trim
be added"): the drift trim, and calibrations taken while Air-family glasses moved no longer saved."""
import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import fusion as F  # noqa: E402

G = 9.81


def run(h, seconds, gyro=(0.0, 0.0, 0.0), sway_deg=0.0):
    """[seconds] of 1 kHz reports, level and still apart from [gyro] (radians a second) and a worn head's sway: the
    pitch axis rocking [sway_deg] a second either way, every report, which the still-learning never takes."""
    ts = 0
    s = math.radians(sway_deg)
    for k in range(int(seconds * 1000)):
        h.report(ts, (gyro[0] + (s if k % 2 else -s), gyro[1], gyro[2]), (0.0, G, 0.0))
        ts += 1_000_000
    return ts


class DriftTrimTest(unittest.TestCase):
    def test_a_positive_trim_turns_the_screen_left(self):
        # Left positive: the head is seen turning right (its yaw falls), so the room, and the screen, turn left.
        h = F.HeadFusion("aura", bias=[0.0, 0.0, 0.0], trim_deg_min=1.0)
        y0 = F.yaw_of(h.q)
        run(h, 60.0)
        self.assertAlmostEqual(math.degrees(F.yaw_of(h.q) - y0), -1.0, delta=0.02)

    def test_it_cancels_a_steady_creep(self):
        # A gyro that reads 0.7 degrees a minute of turning left, as Pierre's worn heading crept, under a worn head's
        # sway (so it is not learnt as the gyro's zero), and the trim set against it: the heading stays put.
        creep = math.radians(0.7) / 60.0
        h = F.HeadFusion("aura", bias=[0.0, 0.0, 0.0], trim_deg_min=0.7)
        y0 = F.yaw_of(h.q)
        run(h, 60.0, gyro=(0.0, creep, 0.0), sway_deg=0.5)
        self.assertAlmostEqual(math.degrees(F.yaw_of(h.q) - y0), 0.0, delta=0.02)

    def test_the_trim_is_held_to_three_degrees_a_minute_and_leaves_tilt_alone(self):
        h = F.HeadFusion("aura", bias=[0.0, 0.0, 0.0])
        self.assertEqual(h.set_trim(10), 3.0)
        self.assertEqual(h.set_trim(-10), -3.0)
        self.assertEqual(h.set_trim(None), 0.0)
        h.set_trim(3.0)
        run(h, 10.0)
        up = F.qrot(F.qconj(h.q), (0.0, 1.0, 0.0))
        self.assertAlmostEqual(up[1], 1.0, places=6)


class CalibrationGateTest(unittest.TestCase):
    def calibrate(self, family, sd_deg):
        """A 4 s calibration on gyro noise of about [sd_deg] each axis; its result."""
        h = F.HeadFusion("one", family=family)
        h.start_calibration()
        a = math.radians(sd_deg)
        ts = 0
        for k in range(4200):
            s = a if k % 2 else -a
            h.report(ts, (s, s, s), (0.0, G, 0.0))
            ts += 1_000_000
        return h.cal_result

    def test_air_glasses_lying_still_are_taken(self):
        self.assertEqual(self.calibrate("air", 0.05)[0], "ok")

    def test_air_glasses_that_moved_are_not(self):
        # His log: spreads of 0.19 to 0.58 deg/s were saved before.
        self.assertEqual(self.calibrate("air", 0.19)[0], "moved")
        self.assertEqual(self.calibrate("air", 0.58)[0], "moved")

    def test_other_glasses_keep_the_old_gate(self):
        self.assertEqual(self.calibrate("aura", 0.58)[0], "ok")


if __name__ == "__main__":
    unittest.main()
