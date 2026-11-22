"""A tester's five reports (Pierre Zammit, 22 Nov 2026, XBX A01+ on a Deck): recentre with the head tilted, the
gyro calibration, keys for the back buttons' actions, Gaming Mode's pointer, and the installer's Decky panel and
Update launcher."""
import json
import math
import os
import struct
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import fusion as F  # noqa: E402
from pocketxr import keys as K  # noqa: E402
from pocketxr import xpointer as X  # noqa: E402

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")


def head(yaw, pitch, roll=0.0):
    """A head orientation: turned yaw left, pitched up, rolled (degrees)."""
    q = F.qmul(F.about_y(math.radians(yaw)), F.about_x(math.radians(pitch)))
    return F.qnorm(F.qmul(q, (math.cos(math.radians(roll) / 2), 0.0, 0.0, math.sin(math.radians(roll) / 2))))


def recentred(q, follow=True, yaw_deg=0.0):
    h = F.HeadFusion("aura")
    h.q = q
    h.recentre(yaw_deg, follow_tilt=follow)
    with h.lock:
        h._apply_recentre()
        h.want_recentre = False
    return h


class Recentre(unittest.TestCase):
    def test_lying_back_brings_the_screen_in_front(self):
        # the log's case: recentred with the head 16.6 degrees up, and the screen stayed 16.6 degrees down
        h = recentred(head(20.0, 16.6))
        f = F.qrot(h.view(), (0.0, 0.0, -1.0))
        self.assertAlmostEqual(f[1], 0.0, places=6)
        self.assertAlmostEqual(f[2], -1.0, places=6)

    def test_the_roll_is_not_taken(self):
        h = recentred(head(-35.0, 60.0, 25.0))
        v = h.view()
        f = F.qrot(v, (0.0, 0.0, -1.0))
        self.assertAlmostEqual(f[2], -1.0, places=6)
        up = F.qrot(v, (0.0, 1.0, 0.0))
        self.assertAlmostEqual(math.degrees(math.atan2(-up[0], up[1])), 25.0, places=4)  # the head's own roll stays

    def test_a_small_nod_keeps_the_room_level(self):
        h = recentred(head(10.0, 8.0))
        f = F.qrot(h.view(), (0.0, 0.0, -1.0))
        self.assertAlmostEqual(math.degrees(math.asin(f[1])), 8.0, places=4)

    def test_without_follow_tilt_only_the_heading(self):
        h = recentred(head(10.0, 40.0), follow=False)
        f = F.qrot(h.view(), (0.0, 0.0, -1.0))
        self.assertAlmostEqual(math.degrees(math.asin(f[1])), 40.0, places=4)

    def test_looking_straight_down_still_has_a_heading(self):
        h = recentred(head(30.0, -88.0))
        f = F.qrot(h.view(), (0.0, 0.0, -1.0))
        self.assertAlmostEqual(f[2], -1.0, places=4)

    def test_the_fusions_own_recentre_keeps_the_tilt(self):
        h = recentred(head(0.0, 30.0))
        self.assertAlmostEqual(math.degrees(h.ref_pitch), 30.0, places=4)
        h.q = head(5.0, 30.0)
        with h.lock:
            h.want_recentre = True
            h._apply_recentre()
        self.assertAlmostEqual(math.degrees(h.ref_pitch), 30.0, places=4)

    def test_the_windows_middle_turn_still_applies(self):
        h = recentred(head(0.0, 30.0), yaw_deg=20.0)
        f = F.qrot(h.view(), (0.0, 0.0, -1.0))
        self.assertAlmostEqual(math.degrees(math.atan2(-f[0], -f[2])), 20.0, places=4)


def feed(h, seconds, gyro_dps, noise_dps=0.0, t0=0):
    ts = t0
    for i in range(int(seconds * 1000)):
        ts += 1_000_000
        n = noise_dps * (1 if i % 2 else -1)
        g = tuple(math.radians(x + n) for x in gyro_dps)
        h.report(ts, g, (0.0, 9.81, 0.0))
    return ts


class Calibration(unittest.TestCase):
    def test_still_glasses_give_their_bias(self):
        h = F.HeadFusion("aura")
        t = feed(h, 0.2, (0, 0, 0))
        h.start_calibration(1.0)
        feed(h, 1.2, (0.1, -0.12, 0.05), noise_dps=0.3, t0=t)
        res, mean, sd = h.cal_result
        self.assertEqual(res, "ok")
        self.assertAlmostEqual(mean[1], -0.12, places=2)
        self.assertAlmostEqual(math.degrees(h.bias[1]), -0.12, places=2)
        self.assertTrue(h.bias_ready)
        self.assertIsNone(h.cal)

    def test_moving_glasses_are_not_taken(self):
        h = F.HeadFusion("aura")
        t = feed(h, 0.2, (0, 0, 0))
        h.start_calibration(1.0)
        feed(h, 1.2, (0, 0, 0), noise_dps=8.0, t0=t)
        self.assertEqual(h.cal_result[0], "moved")
        self.assertEqual(h.bias, [0.0, 0.0, 0.0])

    def test_saved_per_glasses_and_loaded_at_start(self):
        path = os.path.join(tempfile.mkdtemp(), "gyro-bias.json")
        F.save_bias("3318:0442", [0.001, -0.002, 0.0005], path)
        F.save_bias("3318:0439", [0.0, 0.0, 0.0], path)
        self.assertEqual(F.load_bias("3318:0442", path), [0.001, -0.002, 0.0005])
        self.assertIsNone(F.load_bias("35ca:1211", path))
        self.assertIsNone(F.load_bias("3318:0442", path + ".missing"))
        h = F.HeadFusion("aura", bias=F.load_bias("3318:0442", path))
        self.assertTrue(h.bias_ready)
        self.assertEqual(h.bias, [0.001, -0.002, 0.0005])
        with open(path) as f:
            self.assertIn("saved", json.load(f)["3318:0442"])


class Keys(unittest.TestCase):
    def test_defaults_and_settings(self):
        self.assertEqual(K.key_map(), {119: "recentre", 70: "switch_view"})
        m = K.key_map({"recentre": "", "next_app": "KEY_F13", "nonsense": "KEY_F1", "launcher": "KEY_NOPE"})
        self.assertEqual(m, {70: "switch_view", 183: "next_app"})
        for action, (button, kind) in K.ACTIONS.items():
            self.assertIn(button, ("L4", "L5", "R4", "R5"))
            self.assertIn(kind, ("tap", "hold"))

    def test_finds_keyboards_with_the_keys(self):
        root = tempfile.mkdtemp()

        def dev(n, codes):
            bits = 0
            for c in codes:
                bits |= 1 << c
            words = []
            while bits:
                words.append("%x" % (bits & (2 ** 64 - 1)))
                bits >>= 64
            d = os.path.join(root, "event%d" % n, "device", "capabilities")
            os.makedirs(d)
            with open(os.path.join(d, "key"), "w") as f:
                f.write(" ".join(reversed(words)) or "0")
        dev(0, [30, 31, 119])     # a keyboard with Pause
        dev(1, [304, 305])        # a gamepad's buttons only
        dev(2, [183])             # F13 alone
        self.assertEqual(K.keyboards([119, 70], root), ["/dev/input/event0"])
        self.assertEqual(K.keyboards([183], root), ["/dev/input/event2"])

    def test_a_key_press_does_its_action_once(self):
        got = []
        ka = K.KeyActions(got.append, {}, log=lambda m: None)
        r, w = os.pipe()
        ka._rescan = lambda: ka.devices.setdefault("/dev/input/event9", r)
        ka.start()
        ev = lambda code, value: struct.pack("llHHi", 0, 0, K.EV_KEY, code, value)
        os.write(w, ev(119, 1) + ev(119, 2) + ev(119, 0) + ev(70, 1) + ev(30, 1) + struct.pack("llHHi", 0, 0, 0, 0, 0))
        end = time.monotonic() + 3
        while len(got) < 2 and time.monotonic() < end:
            time.sleep(0.02)
        ka.stop = True
        self.assertEqual(got, ["recentre", "switch_view"])  # key repeat (2), let go (0) and other keys left out


class Pointer(unittest.TestCase):
    def test_cursor_shown_only_with_a_visible_pixel(self):
        import ctypes
        px = (ctypes.c_ulong * 4)(0, 0, 0, 0)
        img = X._CursorImage(width=2, height=2, pixels=ctypes.cast(px, ctypes.POINTER(ctypes.c_ulong)))
        self.assertFalse(X.cursor_shown(img))
        px[3] = 0xFF000000
        self.assertTrue(X.cursor_shown(img))
        self.assertFalse(X.cursor_shown(X._CursorImage(width=0, height=0)))

    def test_displays_and_xauthority(self):
        d = tempfile.mkdtemp()
        for n in ("X0", "X1", "notx"):
            open(os.path.join(d, n), "w").close()
        self.assertEqual(X.display_names(d), [":0", ":1"])
        proc = tempfile.mkdtemp()
        for pid, comm, env in ((10, "gamescope", b"A=1\0XAUTHORITY=/run/user/1000/xauth_abc\0"),
                               (11, "bash", b"XAUTHORITY=/nope\0")):
            os.makedirs(os.path.join(proc, str(pid)))
            with open(os.path.join(proc, str(pid), "comm"), "w") as f:
                f.write(comm + "\n")
            with open(os.path.join(proc, str(pid), "environ"), "wb") as f:
                f.write(env)
        self.assertEqual(X.xauthority_candidates(proc), ["/run/user/1000/xauth_abc"])

    def test_effect_draws_the_pointer_in_the_pictures_coordinates(self):
        with open(os.path.join(ROOT, "pocketxr", "reshade", "PocketXR.fx"), encoding="utf-8") as f:
            fx = f.read()
        self.assertIn('uniform float4 pxr_cursor < source = "pxr_cursor"; >;', fx)
        self.assertIn("(uv - pxr_cursor.xy) * float2(BUFFER_WIDTH, BUFFER_HEIGHT)", fx)

        # the arrow test, as the effect does it: tip at the pointer, inside positive
        def edge(p, p0, p1, o):
            n = (p1[1] - p0[1], p0[0] - p1[0])
            ln = math.hypot(*n)
            n = (n[0] / ln, n[1] / ln)
            d = (p[0] - p0[0]) * n[0] + (p[1] - p0[1]) * n[1]
            s = (o[0] - p0[0]) * n[0] + (o[1] - p0[1]) * n[1]
            return d * (1 if s > 0 else -1)
        a, b, c = (0, 0), (0, 17), (12, 12)
        arrow = lambda p: min(edge(p, a, b, c), edge(p, b, c, a), edge(p, c, a, b))
        self.assertGreater(arrow((3, 10)), 1.2)
        self.assertGreater(arrow((0.3, 0.8)), -0.6)  # the tip itself is drawn
        for p in ((-2, 5), (10, 4), (3, 20)):
            self.assertLess(arrow(p), -0.6)


class GamingService(unittest.TestCase):
    def setUp(self):
        try:
            from pocketxr import gaming
        except (ImportError, OSError, AttributeError) as e:
            self.skipTest(f"gaming.py loads on Linux only ({e})")
        self.gaming = gaming

    def fake(self):
        class G:
            pass
        g = G()
        g.lines = []
        g.log = g.lines.append
        g.lock = threading.Lock()
        return g

    def test_keys_act_only_in_gaming_mode_with_glasses(self):
        g = self.fake()
        done = []
        g.recentre = lambda: done.append("recentre")
        g.next_mode = lambda: done.append("next_mode")
        g.reshade, g.glasses = None, object()
        self.gaming.Gaming._key(g, "recentre")
        self.assertEqual(done, [])
        g.reshade = object()
        self.gaming.Gaming._key(g, "recentre")
        self.gaming.Gaming._key(g, "switch_view")
        self.gaming.Gaming._key(g, "launcher")  # no Gaming Mode action
        self.assertEqual(done, ["recentre", "next_mode"])

    def test_pointer_sent_only_when_it_changes(self):
        g = self.fake()
        sent = []

        class R:
            def set_floats(self, k, v):
                sent.append((k, v))
        g.reshade = R()
        g.pointer_sent = None
        g.pointer_moved_at = time.monotonic()
        g.pointer = (0.25, 0.5, True)
        self.gaming.Gaming._send_pointer(g)
        self.gaming.Gaming._send_pointer(g)
        g.pointer = (0.25, 0.5, False)  # the app hid its cursor
        self.gaming.Gaming._send_pointer(g)
        g.pointer = (0.3, 0.5, True)
        g.pointer_moved_at = time.monotonic() - 3.5  # still for longer than gamescope's hide delay
        self.gaming.Gaming._send_pointer(g)
        g.pointer = None
        self.gaming.Gaming._send_pointer(g)
        self.assertEqual(sent, [("pxr_cursor", (0.25, 0.5, 1.0, 0.0)), ("pxr_cursor", (0.25, 0.5, 0.0, 0.0)),
                                ("pxr_cursor", (0.3, 0.5, 0.0, 0.0)), ("pxr_cursor", (0.0, 0.0, 0.0, 0.0))])

    def test_keys_from_the_x_helper_do_their_action(self):
        g = self.fake()
        done = []
        g._key = done.append
        g.key_actions = {119: "recentre", 70: "switch_view"}
        g.pointer = None

        class P:
            stdout = iter(["display :0 1280x800\n", "key 119\n", "key 30\n", "pointer 0.5 0.5 1\n", "key 70\n"])

            def wait(self):
                return 0
        self.gaming.Gaming._read_pointer(g, P())
        self.assertEqual(done, ["recentre", "switch_view"])
        self.assertIn("gaming: pointer: display :0 1280x800", g.lines)

    def test_helper_watches_the_keys_it_is_given(self):
        self.assertEqual(X.watched_keys(["--keys", "119,70,x,999"]), [70, 119])
        self.assertEqual(X.watched_keys([]), [])

    def test_calibration_result_is_saved_and_said(self):
        g = self.fake()
        h = F.HeadFusion("aura")
        h.bias = [0.001, 0.0, 0.0]
        h.cal_result = ("ok", (0.057, 0.0, 0.0), (0.3, 0.3, 0.3))
        g.head = h

        class Gl:
            vendor, product = 0x3318, 0x0442
        g.glasses = Gl()
        g._glasses_key = self.gaming.Gaming._glasses_key
        saved = []
        real = F.save_bias
        F.save_bias = lambda key, bias, path=None: saved.append((key, list(bias)))
        try:
            self.gaming.Gaming._check_calibration(g)
        finally:
            F.save_bias = real
        self.assertEqual(saved, [("3318:0442", [0.001, 0.0, 0.0])])
        self.assertEqual(g.cal_text, "Calibrated. Saved for these glasses.")
        self.assertIn("calibrated: gyro bias (0.057, 0.0, 0.0) deg/s", g.lines[-1])
        self.assertIsNone(h.cal_result)


class Installer(unittest.TestCase):
    def test_update_launcher_and_panel_replacement_are_there(self):
        with open(os.path.join(ROOT, "install.sh"), encoding="utf-8") as f:
            sh = f.read()
        self.assertIn('Exec=$DEST/update.sh', sh)
        self.assertIn("Terminal=true", sh)
        self.assertIn('sudo rm -rf "$PLUGINS/PocketXR" && panel_files sudo', sh)
        self.assertIn("sudo systemctl restart plugin_loader", sh)
        with open(os.path.join(ROOT, "update.sh"), encoding="utf-8") as f:
            up = f.read()
        self.assertIn("releases/latest/download/pocket-xr-deck.tar.gz", up)
        with open(os.path.join(ROOT, "make-release.sh"), encoding="utf-8") as f:
            self.assertIn("update.sh", f.read())
        with open(os.path.join(ROOT, "uninstall.sh"), encoding="utf-8") as f:
            self.assertIn("pocket-xr-update.desktop", f.read())


if __name__ == "__main__":
    unittest.main()
