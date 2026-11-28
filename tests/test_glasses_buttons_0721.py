"""0.7.21 (Pierre Zammit, 28 Nov 2026, XBX A01+ on a Deck: "If you ever think of a way to make the buttons usable"): each
press of the glasses' buttons gets a job, and Picture brightness dims the picture in the effect, in every mode."""
import os
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import gaming, hidimu  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def frame(msg, data):
    """An MCU frame as the glasses send one (header 0xFD, the message at 15, data from 22), via the module's own builder."""
    f = bytearray(hidimu.mcu_command(msg, bytes(data)))
    return bytes(f)


class Presses(unittest.TestCase):
    def reader(self):
        self.now = [100.0]
        self.pressed = []
        lines = []
        r = hidimu.AirReader(lambda *a: None, 0x0442, log=lines.append, nodes=lambda: [],
                             on_button=self.pressed.append, clock=lambda: self.now[0])
        return r, lines

    def press(self, r, phys):
        # His log: each press is three reports, actions 16, 17 and 1, within milliseconds
        for action in (16, 17, 1):
            r._mcu_frame(frame(hidimu.MCU_P_BUTTON, [phys, 0, 0, 0, action, 0, 0, 0, 0]))
            self.now[0] += 0.004

    def test_one_job_a_press(self):
        r, lines = self.reader()
        self.press(r, 2)
        self.assertEqual(self.pressed, [2])
        self.assertIn("imu: glasses button 2, action 16, value 0", lines)  # still logged, every report

    def test_presses_apart_count_each_and_buttons_apart(self):
        r, _ = self.reader()
        self.press(r, 3)
        self.now[0] += 0.5
        self.press(r, 3)
        self.press(r, 1)  # another button straight after
        self.assertEqual(self.pressed, [3, 3, 1])

    def test_a_job_going_wrong_does_not_stop_the_heartbeat(self):
        lines = []

        def boom(phys):
            raise RuntimeError("no")
        r = hidimu.AirReader(lambda *a: None, 0x0442, log=lines.append, nodes=lambda: [], on_button=boom)
        r._mcu_frame(frame(hidimu.MCU_P_BUTTON, [1, 0, 0, 0, 1, 0, 0, 0, 0]))
        self.assertTrue(any("its job failed" in x for x in lines))

    def test_no_writes_to_the_glasses(self):
        r, _ = self.reader()
        self.press(r, 1)
        self.assertEqual(r._mcu_out, [])


class Settings(unittest.TestCase):
    def test_picture_brightness_is_kept_in_range(self):
        self.assertEqual(gaming.picture_brightness(100), 100)
        self.assertEqual(gaming.picture_brightness(5), 20)
        self.assertEqual(gaming.picture_brightness(250), 100)
        self.assertEqual(gaming.picture_brightness(67), 65)
        self.assertEqual(gaming.picture_brightness("x"), 100)
        self.assertEqual(gaming.DEFAULTS["picture_brightness"], 100)

    def test_jobs_over_the_defaults(self):
        self.assertEqual(gaming.button_jobs({}), {"1": "recentre", "2": "brighter", "3": "dimmer"})
        jobs = gaming.button_jobs({"glasses_button_jobs": {"2": "dimmer", "3": "brighter", "9": "x", "1": "bad"}})
        self.assertEqual(jobs, {"1": "recentre", "2": "dimmer", "3": "brighter"})


class FakeReshade:
    def __init__(self):
        self.sent = []
        self.enabled = False

    def set_floats(self, key, values):
        self.sent.append((key, tuple(values)))

    def enable(self):
        self.enabled = True

    def disable(self):
        self.enabled = False


class Service(unittest.TestCase):
    def setUp(self):
        self._save = gaming.save_settings
        gaming.save_settings = lambda s: None
        g = gaming.Gaming.__new__(gaming.Gaming)
        g.log = self.lines = []
        g.log = self.lines.append
        g.settings = dict(gaming.DEFAULTS)
        g.reshade = FakeReshade()
        g.effect_on = False
        g.space_on = False
        g.glasses = object()
        g.reader = None
        g.head = None
        g.control = None
        g.lock = threading.Lock()
        g.buttons_released = False
        g.head_log_until = 0.0
        g.pointer_proc = None
        g._send_view = lambda: None
        g.mode = lambda: g.settings.get("mode", "space") if g.reader else "off"
        self.recentred = []
        g.recentre = lambda: self.recentred.append(True)
        self.g = g

    def tearDown(self):
        gaming.save_settings = self._save

    def mode_sent(self):
        return [v for k, v in self.g.reshade.sent if k == "pxr_mode"][-1]

    def test_dimmer_in_off_mode_loads_the_effect_to_pass_through(self):
        g = self.g
        g._do_glasses_button(3)
        self.assertEqual(g.settings["picture_brightness"], 90)
        self.assertTrue(g.reshade.enabled and g.effect_on and not g.space_on)
        x, _, _, w = (self.mode_sent()[0], 0, 0, self.mode_sent()[3])
        self.assertEqual(x, 0.0)  # the picture as it is
        self.assertAlmostEqual(w, 0.1)
        self.assertIn("gaming: glasses button 3 pressed: dimmer", self.lines)

    def test_back_to_full_brightness_unloads_it(self):
        g = self.g
        g._do_glasses_button(3)
        g._do_glasses_button(2)
        self.assertEqual(g.settings["picture_brightness"], 100)
        self.assertFalse(g.reshade.enabled or g.effect_on)

    def test_in_space_it_dims_the_moved_screen(self):
        g = self.g
        g.reader = object()  # head tracking: the mode is "space"
        g._effect(True)
        self.assertTrue(g.space_on)
        g._set_picture_brightness(50, "test")
        self.assertEqual(self.mode_sent()[0], 1.0)
        self.assertAlmostEqual(self.mode_sent()[3], 0.5)
        self.assertTrue(g.effect_on)

    def test_not_below_twenty(self):
        g = self.g
        for _ in range(12):
            g._do_glasses_button(3)
        self.assertEqual(g.settings["picture_brightness"], 20)

    def test_recentre_and_nothing(self):
        g = self.g
        g._do_glasses_button(1)
        self.assertEqual(self.recentred, [True])
        g.settings["glasses_button_jobs"] = {"1": "nothing"}
        g._do_glasses_button(1)
        self.assertEqual(self.recentred, [True])

    def test_glasses_gone_turns_dimming_off(self):
        g = self.g
        g._do_glasses_button(3)
        g._effect(False, keep_dim=False)
        self.assertFalse(g.reshade.enabled)


class Wiring(unittest.TestCase):
    def test_effect_dims_both_ways(self):
        with open(os.path.join(ROOT, "pocketxr", "reshade", "PocketXR.fx"), encoding="utf-8") as f:
            fx = f.read()
        self.assertIn("float bright = 1.0 - saturate(pxr_mode.w);", fx)
        self.assertIn("tex2D(PxrBackBuffer, texcoord).rgb * bright", fx)
        self.assertIn("colour * fade * bright", fx)

    def test_reader_gets_the_jobs_and_the_panel_sends_them(self):
        with open(os.path.join(ROOT, "pocketxr", "gaming.py"), encoding="utf-8") as f:
            self.assertIn("on_button=self._glasses_button", f.read())
        with open(os.path.join(ROOT, "decky", "src", "index.tsx"), encoding="utf-8") as f:
            tsx = f.read()
        self.assertIn('op: "set_picture_brightness"', tsx)
        self.assertIn('op: "set_glasses_button"', tsx)


if __name__ == "__main__":
    unittest.main()
