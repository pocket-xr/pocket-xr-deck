"""A tester's report on 0.7.8 (Pierre Zammit, 23 Nov 2026, XBX A01+ on a Deck): three taps turned the screen off but
never on again, and the brightness slider never showed."""
import os
import struct
import sys
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import hidimu  # noqa: E402


def his_answer():
    """His glasses' answer to R_BRIGHTNESS at 20:32:29, as the log's first 16 bytes show it (fd, CRC, length 0x12,
    timestamp, message 0x03), then the one data byte the length allows (the log's "04 00 00 00 ... (42 bytes)") and the
    report's padding to 64 bytes."""
    head = bytes.fromhex("fd e8 50 d1 8c 12 00 00 00 00 00 8f 4f 81 01 03".replace(" ", ""))
    return head + b"\x00" + bytes(5) + bytes([4]) + bytes(64 - 23)


class BrightnessAnswer(unittest.TestCase):
    def test_his_frame_is_level_4(self):
        msg, data = hidimu.mcu_parse(his_answer())
        self.assertEqual(msg, hidimu.MCU_R_BRIGHTNESS)
        self.assertEqual(data, bytes([4]))  # the length field (18 = 17 + 1) leaves the padding out
        self.assertEqual(hidimu.brightness_answer(data), 4)

    def test_monados_layout_still_read(self):
        self.assertEqual(hidimu.brightness_answer(bytes([0, 6])), 6)

    def test_nonsense_is_not_a_level(self):
        self.assertIsNone(hidimu.brightness_answer(bytes([9])))
        self.assertIsNone(hidimu.brightness_answer(bytes([1, 3])))
        self.assertIsNone(hidimu.brightness_answer(b""))

    def test_parse_with_a_bad_length_keeps_the_frame(self):
        f = bytearray(his_answer())
        f[5:7] = struct.pack("<H", 200)
        self.assertEqual(len(hidimu.mcu_parse(bytes(f))[1]), 64 - 22)

    def test_reader_logs_and_keeps_the_level(self):
        lines = []
        r = hidimu.AirReader(lambda *a: None, 0x0442, log=lines.append, nodes=lambda: [])
        r._mcu_frame(his_answer())
        self.assertEqual(r.brightness, 4)
        self.assertTrue(r.brightness_answered)
        self.assertIn("imu: the glasses' brightness is 4 of 7 (answer 04)", lines)
        r2 = hidimu.AirReader(lambda *a: None, 0x0442, log=lines.append, nodes=lambda: [])
        f = bytearray(his_answer())
        f[22] = 9
        r2._mcu_frame(bytes(f))
        self.assertIsNone(r2.brightness)
        self.assertTrue(r2.brightness_answered)
        self.assertIn("imu: brightness answer not understood (09)", lines)


class GamingService(unittest.TestCase):
    def setUp(self):
        try:
            from pocketxr import gaming
        except (ImportError, OSError, AttributeError) as e:
            self.skipTest(f"gaming.py loads on Linux only ({e})")
        self.gaming = gaming

    def fake(self, mode, taps):
        class G:
            pass
        g = G()
        g.lines = []
        g.log = g.lines.append
        g.settings = {"mode": mode, "taps": taps}
        g.reader = hidimu.AirReader(lambda *a: None, 0x0442, nodes=lambda: [])
        return g

    def test_off_keeps_reading_for_the_taps(self):
        g = self.fake("off", True)
        self.gaming.Gaming._update_paused(g)
        self.assertFalse(g.reader.paused)
        g.settings["taps"] = False
        self.gaming.Gaming._update_paused(g)
        self.assertTrue(g.reader.paused)
        self.assertEqual(g.lines, ["gaming: head tracking paused (off)"])
        g.settings["taps"] = True
        self.gaming.Gaming._update_paused(g)
        self.assertFalse(g.reader.paused)
        self.assertEqual(g.lines[-1], "gaming: motion read for the taps only (off)")

    def test_space_is_never_paused(self):
        g = self.fake("space", False)
        self.gaming.Gaming._update_paused(g)
        self.assertFalse(g.reader.paused)

    def test_three_taps_from_off_bring_the_screen_back(self):
        g = self.fake("off", True)
        g.lock = threading.Lock()
        g.reshade, g.glasses = object(), object()
        g.steady_ok = lambda: False
        g._apply_mode = lambda: None
        saved = self.gaming.save_settings
        self.gaming.save_settings = lambda s: None
        try:
            g.next_mode = lambda: self.gaming.Gaming.next_mode(g)
            self.gaming.Gaming._tapped(g, 3)
        finally:
            self.gaming.save_settings = saved
        self.assertEqual(g.settings["mode"], "space")

    def test_slider_shows_once_the_glasses_answered(self):
        g = self.fake("space", False)
        g.reader._mcu_running = lambda: True
        self.assertIsNone(self.gaming.Gaming._brightness(g))
        g.reader.brightness_answered = True
        self.assertEqual(self.gaming.Gaming._brightness(g), 0)
        g.reader.brightness = 4
        self.assertEqual(self.gaming.Gaming._brightness(g), 4)
        g.reader._mcu_running = lambda: False
        self.assertIsNone(self.gaming.Gaming._brightness(g))

    def test_switching_taps_rechecks_off(self):
        with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pocketxr", "gaming.py"),
                  encoding="utf-8") as f:
            src = f.read()
        i = src.index('elif op == "set_taps":')
        self.assertIn("self._update_paused()", src[i:i + 400])


if __name__ == "__main__":
    unittest.main()
