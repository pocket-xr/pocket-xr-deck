"""The glasses' own settings, kept right for the view the user picked, as Pocket XR does on the phone.

Runs in its own thread. Only commands Pocket XR has proven are sent (see control.py), one at a time,
at least 3 s apart, each read back (on the Deck, 11 Nov 2026, a Spatial Anchor set sent within a
second of Ultrawide was refused with 5001).

  3DoF on the Aura:  Spatial Anchor off, Ultrawide off (the app does the head tracking).
  Steady in 6DoF:    2D, Ultrawide on, largest size, then Spatial Anchor on, last.
                     On the One series with the XREAL Eye, the user turns 6DoF on in the glasses' menu.
  Quit:              Steady's Spatial Anchor off first, then Ultrawide off.
"""
import queue
import threading
import time

from . import control as c

SET_GAP_S = 3.0
TRIES = 2
SIZE_SAME = 0.005

TURN_ON_6DOF = "Turn on 6DoF in your glasses' menu (Spatial Display) so the screen stays put as you move."
TURN_OFF_6DOF = "Turn 6DoF off again in your glasses' menu."


def flag(a):
    return 0 if a is None or a.value is None else int(a.value)


class SettingsControl(threading.Thread):
    """Holds the control link and works toward the wanted view. Calls on_state(dict) and on_message(text)."""

    def __init__(self, glasses, log, on_state, on_message):
        super().__init__(daemon=True)
        self.glasses = glasses
        self.log = log
        self.on_state = on_state
        self.on_message = on_message
        self.jobs = queue.Queue()
        self.link = None
        self.stop = False
        self.state = {}
        self.wanted = None
        self.busy = False
        # What this app turned on, so quitting puts back only that.
        self.we_set_ultrawide = False
        self.we_set_anchor = False

    # ---- requests from the app ----
    def want(self, view):
        self.jobs.put(("view", view))

    def recentre(self):
        self.jobs.put(("recentre", None))

    def restore(self, done):
        """Put the glasses back for normal use, then call done()."""
        self.jobs.put(("restore", done))

    # ---- the thread ----
    def run(self):
        while not self.stop:
            if self.link is None or self.link.closed:
                if not self._open():
                    time.sleep(2.0)
                    continue
            try:
                job, arg = self.jobs.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self.busy = True
                if job == "view":
                    self.wanted = arg
                    self._apply(arg)
                elif job == "recentre":
                    if self.state.get("ultrawide") == 1:
                        self.link.request(c.recenter)
                elif job == "restore":
                    self._restore()
                    arg()
            except OSError as e:
                self.log(f"settings: link lost ({e})")
                self.link = None
            finally:
                self.busy = False
                self._publish()

    def _open(self):
        try:
            self.link = c.Link(log=self.log)
        except OSError as e:
            self.log(f"settings: control link not open yet ({e})")
            return False
        self.log("settings: control link open")
        self._read()
        if self.wanted:
            self.jobs.put(("view", self.wanted))
        return True

    def _read(self):
        g = self.link
        st = {
            "stereo": flag(g.get(c.STEREO_GET)),
            "anchor": flag(g.get(c.ANCHOR_GET)),
        }
        rng = g.get(c.SIZE_RANGE)
        size = g.get(c.SIZE_GET)
        st["size"] = size.value if size else None
        st["size_max"] = rng.value3 if rng else None
        # Ultrawide last: when it says on, the range read beside it is already Ultrawide's own (Pocket XR).
        st["ultrawide"] = flag(g.get(c.ULTRAWIDE_GET))
        self.state = st
        self._publish()
        return st

    def _publish(self):
        st = dict(self.state)
        st["link"] = self.link is not None and not self.link.closed
        st["busy"] = self.busy
        self.on_state(st)

    def _set_and_check(self, build, value, get, want, what):
        for attempt in range(1, TRIES + 1):
            self.log(f"settings: {what} (try {attempt})")
            self.link.request(build, value)
            end = time.monotonic() + SET_GAP_S
            while time.monotonic() < end:
                if flag(self.link.get(get)) == want:
                    time.sleep(max(0.0, end - time.monotonic()))  # the display may still be re-plugging
                    return True
                time.sleep(0.5)
        self.log(f"settings: {what} did not read back")
        return False

    def _apply(self, view):
        st = self._read()
        if view == "steady" and self.glasses.steady_6dof:
            self._steady_on(st)
        elif self.glasses.managed:
            # 3DoF: the app tracks the head, so the glasses' own hold must be off (Pocket XR's once-per-link auto-off).
            if st["anchor"] == 1:
                self._set_and_check(c.anchor_set, False, c.ANCHOR_GET, 0, "Spatial Anchor off for 3DoF")
            if st["ultrawide"] == 1:
                self._set_and_check(c.ultrawide_set, False, c.ULTRAWIDE_GET, 0, "Ultrawide off for 3DoF")
        elif view != "steady" and st.get("ultrawide") == 1 and self.we_set_ultrawide:
            if self._set_and_check(c.ultrawide_set, False, c.ULTRAWIDE_GET, 0, "Ultrawide off"):
                self.we_set_ultrawide = False
            if not self.glasses.app_anchor:
                self.on_message(TURN_OFF_6DOF)
        self._read()

    def _steady_on(self, st):
        self.on_message("Setting up Steady mode in 6DoF...")
        if st["stereo"] == 1 and not self._set_and_check(c.stereo_set, False, c.STEREO_GET, 0, "2D, on the way to Ultrawide"):
            self.on_message("The glasses stayed in 3D, so Steady mode could not start.")
            return
        if st["ultrawide"] != 1:
            if not self._set_and_check(c.ultrawide_set, True, c.ULTRAWIDE_GET, 1, "Ultrawide on"):
                self.on_message("Ultrawide did not come on, so Steady mode could not start.")
                return
            self.we_set_ultrawide = True
        st = self._read()
        top, size = st.get("size_max"), st.get("size")
        if top is not None and size is not None and size < top - SIZE_SAME:
            self.log(f"settings: screen size {size:.2f} -> {top:.2f}")
            self.link.request(c.size_set, float(top))
            time.sleep(SET_GAP_S)
        if self.glasses.app_anchor:
            if self._read()["anchor"] != 1:
                if not self._set_and_check(c.anchor_set, True, c.ANCHOR_GET, 1, "Spatial Anchor on"):
                    self.on_message("Spatial Anchor did not come on. Try again, or turn it on in the glasses' menu.")
                    return
                self.we_set_anchor = True
            self.on_message("Steady mode in 6DoF is on. The glasses hold the screen in place as you move.")
        else:
            self.on_message(TURN_ON_6DOF)

    def _restore(self):
        if self.link is None or self.link.closed:
            return
        st = self._read()
        changed = False
        if st["anchor"] == 1 and (self.we_set_anchor or (self.glasses.managed and self.wanted == "steady")):
            self._set_and_check(c.anchor_set, False, c.ANCHOR_GET, 0, "Spatial Anchor off")
            changed = True
        if st["ultrawide"] == 1 and (self.we_set_ultrawide or (self.glasses.managed and self.wanted == "steady")):
            self._set_and_check(c.ultrawide_set, False, c.ULTRAWIDE_GET, 0, "Ultrawide off")
            changed = True
            if not self.glasses.app_anchor and self.glasses.steady_6dof:
                self.on_message(TURN_OFF_6DOF)
        self.we_set_anchor = self.we_set_ultrawide = False
        self._read()
        if not changed:
            return
        # Held a moment after a change, as Pocket XR does, so the glasses keep it (the One dropped app-set modes).
        time.sleep(2.0)

    def close(self):
        self.stop = True
        if self.link:
            self.link.close()
