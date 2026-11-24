"""A tester's report on 0.7.6 (Pierre Zammit, 23 Nov 2026, XBX A01+ on a Deck): taps on the top of the frame mostly
missed, and the glasses' own buttons came back only minutes after "Use the glasses' buttons". Soft taps and the jolt
log are tested in test_tester_fixes_075.py."""
import json
import os
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import hidimu  # noqa: E402
from pocketxr import taps as T  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


class TapValues(unittest.TestCase):
    def test_his_taps_and_cadence_are_inside(self):
        self.assertLessEqual(T.TAP_G, 0.33)  # his softest tap
        self.assertLessEqual(T.JERK_G, 0.23)  # his gentlest 3 ms jump
        self.assertGreater(T.JERK_G, 0.10)  # the largest in his plain head movement
        self.assertLessEqual(T.TAP_GAP_MIN_S, 0.32)
        self.assertGreaterEqual(T.TAP_GAP_MAX_S, 0.5)  # 2 taps a second
        self.assertGreater(T.TAP_GAP_MIN_S, 0.134)  # putting the glasses on: two jolts 134 ms apart


class NoUsbReset(unittest.TestCase):
    """0.7.7's USB reset went through on his XBX but the glasses kept their mode (Pierre Zammit, 23 Nov 2026): gone."""

    def test_reset_and_rule_are_gone(self):
        src = open(os.path.join(ROOT, "pocketxr", "hidimu.py"), encoding="utf-8").read()
        self.assertNotIn("USBDEVFS_RESET =", src)
        self.assertNotIn("_reset_for_buttons", src)
        with open(os.path.join(ROOT, "install.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertNotIn('ENV{DEVTYPE}=="usb_device"', sh)
        self.assertNotIn("sudo udevadm trigger --subsystem-match=usb", sh)
        self.assertIn("no longer uses the USB permission", sh)
        with open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8") as f:
            self.assertIn("71-pocket-xr-usb.rules", f.read())  # still removed on uninstall


class Brightness(unittest.TestCase):
    """Brightness through the MCU, as Monado's XREAL Air driver does (BSL-1.0)."""

    def frame(self, msg, data):
        return hidimu.mcu_command(msg, bytes(data))

    def reader(self):
        lines = []
        r = hidimu.AirReader(lambda *a: None, 0x0442, log=lines.append, nodes=lambda: [])
        r._mcu_running = lambda: True
        return r, lines

    def test_frames_match_monados(self):
        f = hidimu.mcu_command(hidimu.MCU_W_BRIGHTNESS, bytes([5]))
        self.assertEqual(f[0], 0xFD)
        self.assertEqual(f[5:7], (17 + 1).to_bytes(2, "little"))  # length
        self.assertEqual(f[15:17], (0x04).to_bytes(2, "little"))  # message id
        self.assertEqual(f[17:22], bytes(5))  # reserved
        self.assertEqual(f[22:], bytes([5]))
        self.assertEqual(hidimu.mcu_parse(f), (hidimu.MCU_W_BRIGHTNESS, bytes([5])))
        self.assertIsNone(hidimu.mcu_parse(bytes([1, 2]) + bytes(40)))
        self.assertEqual((hidimu.MCU_R_BRIGHTNESS, hidimu.MCU_W_BRIGHTNESS, hidimu.MCU_P_BUTTON),
                         (0x03, 0x04, 0x6C05))

    def test_read_set_and_answers(self):
        r, lines = self.reader()
        r._mcu_frame(self.frame(hidimu.MCU_R_BRIGHTNESS, [0, 4]))
        self.assertEqual(r.brightness, 4)
        self.assertTrue(r.set_brightness(9))  # clamped
        self.assertEqual(hidimu.mcu_parse(r._mcu_out[-2]), (hidimu.MCU_W_BRIGHTNESS, bytes([7])))
        self.assertEqual(hidimu.mcu_parse(r._mcu_out[-1])[0], hidimu.MCU_R_BRIGHTNESS)  # then read back
        r._mcu_frame(self.frame(hidimu.MCU_W_BRIGHTNESS, [0]))
        r._mcu_frame(self.frame(hidimu.MCU_R_BRIGHTNESS, [0, 7]))  # it took
        self.assertEqual(r.brightness, 7)
        self.assertIsNone(r.brightness_unsupported)
        self.assertIn("imu: the glasses' brightness is 4 of 7 (answer 00 04)", lines)
        self.assertIn("imu: brightness set answered 00", lines)
        r._mcu_frame(self.frame(hidimu.MCU_W_BRIGHTNESS, [1]))  # a refusing status
        self.assertTrue(r.brightness_unsupported)
        self.assertFalse(r.set_brightness(3))

    def test_not_while_the_mcu_is_closed(self):
        r = hidimu.AirReader(lambda *a: None, 0x0442, log=lambda x: None, nodes=lambda: [])
        self.assertFalse(r.set_brightness(3))
        self.assertEqual(r._mcu_out, [])

    def test_the_glasses_buttons_are_logged_and_their_brightness_applied(self):
        r, lines = self.reader()
        data = [2, 0, 0, 0, hidimu.BUTTON_BRIGHTNESS_UP, 0, 0, 0, 5]
        r._mcu_frame(self.frame(hidimu.MCU_P_BUTTON, data))
        self.assertIn("imu: glasses button 2, action 6, value 5", lines)
        self.assertEqual(hidimu.mcu_parse(r._mcu_out[-2]), (hidimu.MCU_W_BRIGHTNESS, bytes([5])))
        r._mcu_out.clear()
        r._mcu_frame(self.frame(hidimu.MCU_P_BUTTON, [1, 0, 0, 0, 1, 0, 0, 0, 1]))  # display toggle: logged only
        self.assertEqual(r._mcu_out, [])

    def test_asked_for_when_the_heartbeat_starts(self):
        src = open(os.path.join(ROOT, "pocketxr", "hidimu.py"), encoding="utf-8").read()
        self.assertIn("self._mcu_out.append(mcu_command(MCU_R_BRIGHTNESS))", src)

    def test_quick_access(self):
        with open(os.path.join(ROOT, "decky", "src", "index.tsx"), encoding="utf-8") as f:
            self.assertIn('op: "set_brightness"', f.read())
        for lang in ("ko", "ja", "zh_CN", "zh_TW", "es", "pt_BR", "fr", "de", "it", "ru"):
            with open(os.path.join(ROOT, "pocketxr", "locale", lang + ".json"), encoding="utf-8") as f:
                self.assertIn("Glasses brightness", json.load(f), lang)


class FirmTaps(unittest.TestCase):
    def test_his_firm_taps_fit(self):
        self.assertGreaterEqual(T.SPIKE_MAX_S, 0.101)  # his longest firm tap with 0.7.7
        self.assertLess(T.SPIKE_MAX_S, 0.25)


class GamingSwitch(unittest.TestCase):
    def setUp(self):
        try:
            from pocketxr import gaming
        except (ImportError, OSError, AttributeError) as e:
            self.skipTest(f"gaming.py loads on Linux only ({e})")
        self.gaming = gaming

    def test_kept_when_the_glasses_come_back(self):
        class G:
            pass
        g = G()
        g.lines = []
        g.log = g.lines.append
        g.buttons_released = False
        g.reader = hidimu.AirReader(lambda *a: None, 0x0442, nodes=lambda: [])
        self.gaming.Gaming._glasses_buttons(g, True)
        self.assertTrue(g.buttons_released and g.reader.released)
        with open(os.path.join(ROOT, "pocketxr", "gaming.py"), encoding="utf-8") as f:
            src = f.read()
        self.assertIn("self.reader.released = self.buttons_released", src)

    def test_texts_in_every_language(self):
        for lang in ("ko", "ja", "zh_CN", "zh_TW", "es", "pt_BR", "fr", "de", "it", "ru"):
            with open(os.path.join(ROOT, "pocketxr", "locale", lang + ".json"), encoding="utf-8") as f:
                t = json.load(f)
            self.assertTrue(any(k.startswith("Lets go of the glasses") and "blink off and on" in k for k in t), lang)
            self.assertTrue(any(k.startswith("Tap the glasses' frame") and "2 taps a second" in k for k in t), lang)
            self.assertFalse(any(k.endswith("Head tracking pauses until you turn this off.") for k in t), lang)


if __name__ == "__main__":
    unittest.main()
