"""The control panel at a Deck's height: taller than its window, so everything between the title and Send logs scrolls,
and every row, PC screens for a phone and Text size too, can be brought into view clear of Send logs. A drag scrolls
and taps nothing; a tap still taps. Needs an X display (skipped without one)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

try:
    import tkinter as tk
    from pocketxr import panel
    ROOT = tk.Tk() if os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY") else None
except Exception:  # no Tk, or no display
    ROOT = None
if ROOT is not None:
    ROOT.withdraw()

STATE = {"view": "3dof", "source": "deck", "text_scale": 100, "host_screens": 3, "flat": True, "message": "",
         "status": "s"}


@unittest.skipIf(ROOT is None, "no display")
class PanelScroll(unittest.TestCase):
    def setUp(self):
        self.sent = []
        self.send = panel.send
        panel.send = lambda c, v=None: self.sent.append((c, v))
        self.top = tk.Toplevel(ROOT)
        with mock.patch.object(panel.Panel, "reader", lambda self: None):  # no app on stdin to say goodbye
            self.p = panel.Panel(self.top)
        self.top.geometry("%dx%d" % (panel.W, 560))  # the Deck: 593 logical pixels high, less 80
        self.p.show(STATE)
        self.top.update()

    def tearDown(self):
        panel.send = self.send
        self.top.destroy()

    def y(self, w):
        return w.winfo_rooty() - self.top.winfo_rooty()

    def rows(self):
        p = self.p
        keys = [w for w in p.content.winfo_children() if isinstance(w, tk.Frame)][-1]
        return ([p.view["3dof"], p.source["deck"], p.space_buttons["pcvr"], p.space_buttons["record"]]
                + list(p.switches.values()) + [p.text_size, p.host_screens, p.adjust["Recentre"], p.gap, keys])

    def test_more_than_fits(self):
        self.assertGreater(self.p.content.winfo_reqheight(), self.p.canvas.winfo_height())

    def test_every_row_can_be_reached(self):
        top = self.y(self.p.canvas)
        bottom = top + self.p.canvas.winfo_height()
        for w in self.rows():
            self.p.scroll_to(w)
            self.top.update()
            self.assertTrue(w.winfo_ismapped())
            self.assertGreaterEqual(self.y(w), top)
            self.assertLessEqual(self.y(w) + w.winfo_height(), min(bottom, self.y(self.p.logs_button)))

    def test_send_logs_and_quit_stay(self):
        before = self.y(self.p.logs_button), self.y(self.p.quit_row)
        self.p.scroll_to(self.rows()[-1])
        self.top.update()
        self.assertEqual((self.y(self.p.logs_button), self.y(self.p.quit_row)), before)
        self.assertLessEqual(self.y(self.p.quit_row) + self.p.quit_row.winfo_height(), self.top.winfo_height())

    def press(self, w, dy=0, kind="<ButtonPress-1>", **kw):
        x, y = w.winfo_rootx() + 20, w.winfo_rooty() + 10
        w.event_generate(kind, x=20, y=10 + dy, rootx=x, rooty=y + dy, **kw)
        self.top.update()

    def test_a_tap_taps_and_a_drag_scrolls(self):
        b = self.p.space_buttons["pcvr"]
        self.press(b, button=1)
        self.press(b, kind="<ButtonRelease-1>", button=1)
        self.assertEqual(self.sent, [("pcvr", None)])
        self.sent.clear()
        start = self.p.canvas.canvasy(0)
        self.press(b, button=1)
        for d in (5, 30, 90):
            self.press(b, -d, "<B1-Motion>", state=0x100)
        self.press(b, -90, "<ButtonRelease-1>", button=1)
        self.assertEqual(self.sent, [])
        self.assertGreater(self.p.canvas.canvasy(0), start)

    def test_the_wheel_scrolls(self):
        start = self.p.canvas.canvasy(0)
        self.p.space_buttons["pcvr"].event_generate("<Button-5>", x=5, y=5)
        self.top.update()
        self.assertGreater(self.p.canvas.canvasy(0), start)


if __name__ == "__main__":
    unittest.main()
