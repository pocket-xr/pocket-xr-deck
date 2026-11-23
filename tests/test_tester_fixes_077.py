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


class UsbReset(unittest.TestCase):
    def test_usb_node_from_the_interface(self):
        d = tempfile.mkdtemp()
        dev = os.path.join(d, "usb1", "1-1")
        os.makedirs(os.path.join(dev, "1-1:1.0"))
        with open(os.path.join(dev, "busnum"), "w") as f:
            f.write("1\n")
        with open(os.path.join(dev, "devnum"), "w") as f:
            f.write("7\n")
        self.assertEqual(hidimu.usb_node(os.path.join(dev, "1-1:1.0")), "/dev/bus/usb/001/007")
        self.assertIsNone(hidimu.usb_node(os.path.join(d, "nothing", "1-1:1.0")))

    def test_reset_said_or_refused(self):
        calls = []

        def opener(path, flags):
            calls.append((path, flags))
            return os.open(os.devnull, os.O_WRONLY)
        self.assertIsNone(hidimu.usb_reset("/dev/bus/usb/001/007", opener, lambda fd, req, arg: calls.append(req)))
        self.assertEqual(calls, [("/dev/bus/usb/001/007", os.O_WRONLY), hidimu.USBDEVFS_RESET])

        def refused(path, flags):
            raise PermissionError(13, "Permission denied")
        why = hidimu.usb_reset("/dev/bus/usb/001/007", refused, None)
        self.assertEqual(why, "/dev/bus/usb/001/007 not writable (Permission denied)")
        self.assertEqual(hidimu.USBDEVFS_RESET, (ord("U") << 8) | 20)  # _IO('U', 20)

    def reader(self, result):
        lines = []
        r = hidimu.AirReader(lambda *a: None, 0x0442, log=lines.append, nodes=lambda: [])
        r.last_nodes = [(0, "/dev/hidraw4", 0x0442, "/sys/x/usb1/1-1/1-1:1.0")]
        done = []
        r._usb_reset = lambda node: done.append(node) or result
        hidimu_node, hidimu.usb_node = hidimu.usb_node, (lambda iface: "/dev/bus/usb/001/007")
        self.addCleanup(setattr, hidimu, "usb_node", hidimu_node)
        return r, lines, done

    def test_only_after_the_handshake(self):
        r, lines, done = self.reader(None)
        r._reset_for_buttons()
        self.assertEqual(done, [])  # nothing was sent to the glasses, nothing to undo
        r.handshake = True
        r._reset_for_buttons()
        self.assertEqual(done, ["/dev/bus/usb/001/007"])
        self.assertIn("imu: glasses reset over USB (/dev/bus/usb/001/007), so their own buttons work again", lines)
        self.assertFalse(r.handshake)

    def test_refused_is_logged(self):
        r, lines, done = self.reader("/dev/bus/usb/001/007 not writable (Permission denied)")
        r.handshake = True
        r._reset_for_buttons()
        self.assertTrue(any(x.startswith("imu: no USB reset of the glasses: /dev/bus/usb/001/007 not writable")
                            and "up to a few minutes" in x for x in lines), lines)

    def test_new_nodes_mean_no_handshake_yet(self):
        r = hidimu.AirReader(lambda *a: None, 0x0442, log=lambda x: None, nodes=lambda: [])
        r.handshake = True
        r.last_nodes = [(0, "/dev/hidraw4", 0x0442, "/sys/a")]
        r.stop = True  # _find stops at once
        r._find([(0, "/dev/hidraw9", 0x0442, "/sys/a")])
        self.assertFalse(r.handshake)


class UsbRule(unittest.TestCase):
    """The installer's udev rule that lets the seated user reset XREAL and VITURE glasses (Mike, 23 Nov 2026)."""

    def read(self, name):
        with open(os.path.join(ROOT, name), encoding="utf-8") as f:
            return f.read()

    def test_installer_offers_it_for_these_glasses_only(self):
        sh = self.read("install.sh")
        self.assertIn('/etc/udev/rules.d/71-pocket-xr-usb.rules', sh)
        self.assertIn('SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="3318", TAG+="uaccess"', sh)
        self.assertIn('SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device", ATTR{idVendor}=="35ca", TAG+="uaccess"', sh)
        self.assertEqual(sh.count('SUBSYSTEM=="usb"'), 2)  # no other USB devices in that rule
        self.assertIn("sudo udevadm trigger --subsystem-match=usb --action=change", sh)
        self.assertIn("unplug them and plug them back in", sh)
        self.assertIn("Skipped the USB permission", sh)
        self.assertIn(hidimu.USB_RULE, sh)

    def test_uninstall_removes_it(self):
        sh = self.read("uninstall.sh")
        self.assertIn("/etc/udev/rules.d/71-pocket-xr-usb.rules", sh)
        self.assertIn("sudo rm -f $RULES", sh)

    def test_the_log_says_the_reset_needs_the_rule(self):
        lines = []
        r = hidimu.AirReader(lambda *a: None, 0x0442, log=lines.append, nodes=lambda: [])
        r.last_nodes = [(0, "/dev/hidraw4", 0x0442, "/sys/x/usb1/1-1/1-1:1.0")]
        r.handshake = True
        r._usb_reset = lambda node: f"{node} not writable (Permission denied)"
        saved = hidimu.usb_node, hidimu.USB_RULE
        hidimu.usb_node, hidimu.USB_RULE = (lambda iface: "/dev/bus/usb/001/007"), "/nonexistent/71-pocket-xr-usb.rules"
        try:
            r._reset_for_buttons()
        finally:
            hidimu.usb_node, hidimu.USB_RULE = saved
        self.assertTrue(any("the reset needs the USB permission the installer offers" in x for x in lines), lines)


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
