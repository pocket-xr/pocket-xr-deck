"""0.7.16: Pierre Zammit's 0.7.15 log (25 Nov 2026). 0.7.15 opened a silent X screen on a thread of its own, and the
reader still stuck: in the main thread's X calls on the screen that answered, libX11's process-wide lock held by the
open that never ended. Now a screen is asked over its socket first, without Xlib. No X server here: X is stood in."""
import os
import socket
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import xpointer as X  # noqa: E402


class FakeProbe:
    answers = {}

    def __init__(self, name, now):
        self.name, self.started = name, now

    def poll(self, now, wait):
        a = FakeProbe.answers.get(self.name)
        if a == "yes":
            return True
        if now - self.started >= wait:
            return False
        return None


class AskedFirst(unittest.TestCase):
    def setUp(self):
        FakeProbe.answers = {":0": "yes", ":1": "yes", ":2": "never"}
        self.made = []

    def make(self, name):
        self.made.append(name)
        return "screen " + name

    def round(self, screens, probes, now):
        return X.open_screens([":0", ":1", ":2"], screens, probes, self.make, now, wait=2.0, again=15.0, probe=FakeProbe)

    def test_a_silent_screen_is_never_opened_and_nothing_waits(self):
        screens, probes = {}, {}
        self.assertEqual(self.round(screens, probes, 0.0), [])
        self.assertEqual(sorted(screens), [":0", ":1"])
        self.assertTrue(X.pending(probes))
        said = self.round(screens, probes, 2.5)
        self.assertEqual([n for n, _ in said], [":2"])
        self.assertIn("not answering", said[0][1])
        self.assertFalse(X.pending(probes))
        # Quiet until asked again, and not said again
        self.assertEqual(self.round(screens, probes, 10.0), [])
        self.assertEqual(self.round(screens, probes, 18.0), [])
        self.assertTrue(X.pending(probes))
        self.assertNotIn(":2", self.made)
        # Once it answers, it is opened
        FakeProbe.answers[":2"] = "yes"
        self.round(screens, probes, 18.5)
        self.assertIn(":2", screens)

    def test_a_screen_that_refuses_says_why(self):
        def make(name):
            raise OSError("Authorization required")
        FakeProbe.answers = {":2": "yes"}
        said = X.open_screens([":2"], {}, {}, make, 0.0, probe=FakeProbe)
        self.assertEqual(said, [(":2", "Authorization required")])


@unittest.skipUnless(hasattr(socket, "AF_UNIX") and sys.platform != "win32", "Unix sockets: Linux")
class RealSocket(unittest.TestCase):
    """The probe against a listening socket that answers, and one that only listens."""

    def server(self, answer):
        root = tempfile.mkdtemp()
        path = os.path.join(root, "X7")
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(path)
        srv.listen(1)
        self.addCleanup(srv.close)

        def run():
            c, _ = srv.accept()
            setup = c.recv(12)
            if answer and setup[:1] == b"l":
                c.send(b"\x00")  # Failed: as an X server refusing a client without authorisation
            threading.Event().wait(1.0)
            c.close()
        threading.Thread(target=run, daemon=True).start()
        return root

    def test_an_answer_and_a_silence(self):
        p = X.Probe(":7", 0.0, root=self.server(True))
        got = None
        for _ in range(100):
            got = p.poll(0.0, 2.0)
            if got is not None:
                break
            threading.Event().wait(0.01)
        self.assertTrue(got)
        q = X.Probe(":7", 0.0, root=self.server(False))
        threading.Event().wait(0.2)
        self.assertIsNone(q.poll(0.5, 2.0))
        self.assertFalse(q.poll(2.5, 2.0))

    def test_no_socket_cannot_answer(self):
        self.assertFalse(X.Probe(":9", 0.0, root=tempfile.mkdtemp()).poll(0.0, 2.0))


class CursorChanges(unittest.TestCase):
    def test_events_are_drained_and_reported(self):
        s = X.Screen.__new__(X.Screen)
        s.fd, s.dpy, s.events = 5, 1, None
        left = [3]

        class X11:
            def XPending(self, dpy):
                return left[0]

            def XNextEvent(self, dpy, buf):
                left[0] -= 1
        s.x11 = X11()
        self.assertTrue(s.changed())
        self.assertEqual(left[0], 0)
        self.assertFalse(s.changed())
        s.fd = None
        self.assertFalse(s.changed())


if __name__ == "__main__":
    unittest.main()
