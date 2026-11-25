"""Up to six PC screens a phone can open from this computer (pocketxr/host/screens.py): three at first as before, the
ports 47989 + 1000 per screen, the host following the control panel's setting without a restart, the helper listing
what is served, and the virtual outputs side by side in screen order. No stream with more than three screens has been
run; these need no Deck."""
import json
import os
import sys
import tempfile
import threading
import unittest
from unittest import mock

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
sys.path.insert(0, ROOT)
from pocketxr.host import desktop, helper, identity, screens, server  # noqa: E402


class Counts(unittest.TestCase):
    def test_three_at_first_six_at_most(self):
        self.assertEqual(screens.DEFAULT, 3)
        self.assertEqual(screens.MAX, 6)
        self.assertEqual(screens.ports(), (47989, 48989, 49989))
        self.assertEqual(server.BASE_PORTS, (47989, 48989, 49989))  # what the host serves when nothing is changed
        self.assertEqual(screens.ports(6), (47989, 48989, 49989, 50989, 51989, 52989))
        self.assertEqual(screens.ports(1), (47989,))

    def test_a_count_not_offered(self):
        for value, count in ((0, 1), (-2, 1), (9, 6), (6, 6), (4, 4), ("5", 5), (5.0, 5), (4.5, 3), ("x", 3),
                             (None, 3), (True, 3), (float("nan"), 3), (float("inf"), 3), ([4], 3)):
            self.assertEqual(screens.count_of(value), count, value)

    def test_the_screens_ports_never_meet(self):
        used = []
        for p in screens.ports(screens.MAX):
            used.append(set(range(p - 5, p + 22)))  # HTTPS P-5 to RTSP P+21
        every = set()
        for u in used:
            self.assertFalse(every & u)
            every |= u
        self.assertNotIn(helper.PORT, every)
        self.assertLess(max(every), 65536)

    def test_the_setting_from_the_desktop_apps_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "settings.json")
            self.assertEqual(screens.wanted(path), 3)  # no file
            for data, count in (({"host_screens": 6}, 6), ({"host_screens": 12}, 6), ({"text_scale": 125}, 3),
                                ([1, 2], 3), ({"host_screens": "lots"}, 3)):
                with open(path, "w") as f:
                    json.dump(data, f)
                self.assertEqual(screens.wanted(path), count, data)
            with open(path, "w") as f:
                f.write("{not json")
            self.assertEqual(screens.wanted(path), 3)

    def test_the_old_app_had_three(self):
        self.assertEqual(identity.OLD_SCREENS, 3)


class StubIdentity:
    def unique_id(self, port):
        return "ID-%d" % port


class Names(unittest.TestCase):
    def test_screen_six(self):
        host = type("H", (), {"name": "steamdeck", "identity": StubIdentity(), "log": staticmethod(lambda t: None)})()
        s = server.Screen(host, 5, screens.ports(6)[5])
        self.assertEqual(s.name, "steamdeck screen 6")
        self.assertEqual((s.http_port, s.https_port, s.video_port, s.control_port, s.audio_port, s.rtsp_port),
                         (52989, 52984, 52998, 52999, 53000, 53010))


class FakeScreen:
    """server.Screen without sockets: started, stopped, streaming or not."""
    busy = set()
    made = []

    def __init__(self, host, index, port):
        self.host, self.index, self.http_port = host, index, port
        self.name = host.name if index == 0 else "%s screen %d" % (host.name, index + 1)
        self.started = self.stopped = False
        self.running = False
        FakeScreen.made.append(self)

    def start(self):
        if self.http_port in FakeScreen.busy:
            raise OSError("busy")
        self.started = True

    def stop(self):
        self.stopped = True


def fake_host(count=3):
    h = server.Host.__new__(server.Host)  # its parts set_count uses, without encoders, TLS or devices
    h.name = "steamdeck"
    h.lines = []
    h.log = h.lines.append
    h.busy = set()
    h.change = threading.Lock()
    h.screens = [FakeScreen(h, i, p) for i, p in enumerate(screens.ports(count))]
    return h


class Following(unittest.TestCase):
    def setUp(self):
        FakeScreen.busy, FakeScreen.made = set(), []
        patch = mock.patch.object(server, "Screen", FakeScreen)
        patch.start()
        self.addCleanup(patch.stop)

    def test_unchanged_stays_as_it_is(self):
        h = fake_host()
        self.assertFalse(server.Host.set_count(h, 3))
        self.assertEqual(h.ports, [47989, 48989, 49989])
        self.assertEqual(h.lines, [])

    def test_up_to_six_and_the_helper_lists_them(self):
        h = fake_host()
        self.assertTrue(server.Host.set_count(h, 6))
        self.assertEqual(h.ports, [47989, 48989, 49989, 50989, 51989, 52989])
        self.assertEqual([s.name for s in h.screens][3:], ["steamdeck screen 4", "steamdeck screen 5",
                                                            "steamdeck screen 6"])
        self.assertTrue(all(s.started for s in h.screens[3:]))
        with tempfile.TemporaryDirectory() as tmp:
            hp = helper.Helper(h, tokens=os.path.join(tmp, "t.json"), log=lambda t: None, ask=lambda q: True)
            self.assertEqual(hp.here(), "POCKETXR-HERE 1 47610 steamdeck 47989,48989,49989,50989,51989,52989")
            token = hp.answer({"op": "pair", "phone": "Flip 7"})["token"]
            self.assertEqual(hp.answer({"op": "screens-setup", "token": token})["ports"],
                             [47989, 48989, 49989, 50989, 51989, 52989])
        self.assertIn("steamdeck now on 47989, 48989, 49989, 50989, 51989, 52989 (6 PC screens asked for)", h.lines[-1])

    def test_down_again_never_cuts_a_stream(self):
        h = fake_host(6)
        streaming = h.screens[5]
        streaming.running = True
        self.assertTrue(server.Host.set_count(h, 3))
        self.assertEqual(h.ports, [47989, 48989, 49989, 52989])  # screen 6 stays while its phone streams
        self.assertTrue(h.screens[3].stopped is False and streaming is h.screens[3])
        self.assertTrue(all(s.stopped for s in FakeScreen.made[3:5]))
        streaming.running = False
        self.assertTrue(server.Host.set_count(h, 3))  # the next look, after the stream ended
        self.assertEqual(h.ports, [47989, 48989, 49989])
        self.assertTrue(streaming.stopped)

    def test_a_busy_port_is_left_out_and_not_tried_again(self):
        h = fake_host()
        FakeScreen.busy = {50989}
        self.assertTrue(server.Host.set_count(h, 5))
        self.assertEqual(h.ports, [47989, 48989, 49989, 51989])
        self.assertEqual(h.busy, {50989})
        made = len(FakeScreen.made)
        self.assertFalse(server.Host.set_count(h, 5))
        self.assertEqual(len(FakeScreen.made), made)


class Outputs(unittest.TestCase):
    def test_six_virtual_outputs_side_by_side_in_screen_order(self):
        outs = [{"name": "eDP-1", "x": 0, "y": 0, "w": 949, "h": 593}]
        for p in (52989, 47989, 50989, 49989, 51989, 48989):
            outs.append({"name": "Virtual-pxr-%d" % p, "x": 949, "y": 0, "w": 1000, "h": 600})
        moves = desktop.arrange(outs)
        self.assertEqual(moves, ["output.Virtual-pxr-%d.position.%d,0" % (p, 949 + 1000 * k)
                                 for k, p in enumerate(screens.ports(6)) if k > 0])


class Panel(unittest.TestCase):
    def read(self, *p):
        with open(os.path.join(ROOT, *p), encoding="utf-8") as f:
            return f.read()

    def test_setting_panel_and_log(self):
        app = self.read("pocketxr", "app.py")
        self.assertIn("host_screens.SETTING: host_screens.DEFAULT,", app)
        self.assertIn('elif cmd == "host_screens":', app)
        self.assertIn("PC screens for a phone: {old} -> {new}, on ports ", app)
        panel = self.read("pocketxr", "panel.py")
        self.assertIn('send("host_screens", step)', panel)
        self.assertIn('st.get("host_screens", 3)', panel)


if __name__ == "__main__":
    unittest.main()
