"""Pocket XR's control panel on the Deck's own screen, made for touch, in Pocket XR's "Light on glass" tokens
(look.py): smoked cards with a hairline rim, one accent, Inter, red only for Quit. A child of the app.

It reads the app's state as JSON lines on stdin and writes what the user taps as JSON lines on stdout.
"""
import json
import os
import queue
import sys
import threading
import tkinter as tk

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr.look import TK as C  # noqa: E402

FONT, MEDIUM = "Inter", "Inter Medium"
W = 440


def send(cmd, value=None):
    sys.stdout.write(json.dumps({"cmd": cmd, "value": value}) + "\n")
    sys.stdout.flush()


def rounded(cv, x0, y0, x1, y1, r, **kw):
    """A rounded rectangle on a canvas, as one smooth polygon."""
    r = max(0, min(r, (x1 - x0) / 2, (y1 - y0) / 2))
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1,
           x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, splinesteps=12, **kw)


class Button(tk.Canvas):
    """A rounded button: glass at rest, lighter on hover, accent when pressed or selected."""

    def __init__(self, parent, text, command, height=44, width=None, bg=C["card"], font=(MEDIUM, 12), kind="normal",
                 radius=12):
        super().__init__(parent, height=height, width=width or 10, bg=bg, highlightthickness=0, bd=0)
        self.text, self.command, self.kind, self.radius, self.font = text, command, kind, radius, font
        self.selected = False
        self.enabled = True
        self.hover = False
        self.pressed = False
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<Enter>", lambda e: self._set(hover=True))
        self.bind("<Leave>", lambda e: self._set(hover=False, pressed=False))
        self.bind("<ButtonPress-1>", lambda e: self._set(pressed=True))
        self.bind("<ButtonRelease-1>", self._release)

    def _set(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)
        self.draw()

    def _release(self, e):
        fire = self.pressed and self.enabled
        self._set(pressed=False)
        if fire and 0 <= e.x <= self.winfo_width() and 0 <= e.y <= self.winfo_height():
            self.command()

    def set(self, selected=None, enabled=None):
        changed = False
        if selected is not None and selected != self.selected:
            self.selected, changed = selected, True
        if enabled is not None and enabled != self.enabled:
            self.enabled, changed = enabled, True
        if changed:
            self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        if self.kind == "danger":
            fill = "#3A1A1C" if (self.pressed or self.hover) else C["card"]
            rim, ink = C["danger"], C["danger"]
        elif self.selected:
            fill, rim, ink = C["accent"], C["accent"], "#FFFFFF"
        elif self.pressed and self.enabled:
            fill, rim, ink = C["accent_deep"], C["accent"], "#FFFFFF"
        elif self.hover and self.enabled:
            fill, rim, ink = C["hover"], C["rim_focus"], C["ink"]
        else:
            fill, rim, ink = C["raised"], C["rim"], C["ink"] if self.enabled else C["ink3"]
        rounded(self, 1, 1, w - 1, h - 1, self.radius, fill=fill, outline=rim, width=1)
        self.create_text(w / 2, h / 2, text=self.text, fill=ink, font=self.font)


class Switch(tk.Canvas):
    """A row with a title, a line under it, and a switch; the whole row toggles."""

    def __init__(self, parent, title, sub, command, bg=C["card"]):
        super().__init__(parent, height=44, bg=bg, highlightthickness=0, bd=0)
        self.title, self.sub, self.command = title, sub, command
        self.on = False
        self.bind("<Configure>", lambda e: self.draw())
        self.bind("<ButtonRelease-1>", lambda e: self.command(not self.on))

    def set(self, on):
        if on != self.on:
            self.on = on
            self.draw()

    def draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        self.create_text(14, 14, text=self.title, anchor="w", fill=C["ink"], font=(FONT, 11))
        self.create_text(14, 31, text=self.sub, anchor="w", fill=C["ink2"], font=(FONT, 8))
        tw, th = 46, 26
        x0, y0 = w - 14 - tw, (h - th) / 2
        rounded(self, x0, y0, x0 + tw, y0 + th, th / 2, fill=C["accent"] if self.on else "#33363D", outline="")
        k = x0 + tw - th / 2 if self.on else x0 + th / 2
        self.create_oval(k - th / 2 + 3, y0 + 3, k + th / 2 - 3, y0 + th - 3, fill="#F5F5F6", outline="")


class Card(tk.Canvas):
    """A section: a small caps title above a rounded card that holds a frame."""

    def __init__(self, parent, title):
        self.title = title
        self.wrap = tk.Frame(parent, bg=C["page"])
        self.wrap.pack(fill="x", padx=12, pady=(0, 2))
        tk.Label(self.wrap, text=title.upper(), bg=C["page"], fg=C["ink3"], font=(MEDIUM, 8)).pack(anchor="w", padx=4,
                                                                                                    pady=(2, 2))
        super().__init__(self.wrap, bg=C["page"], highlightthickness=0, bd=0, height=10)
        self.pack(fill="x")
        self.body = tk.Frame(self, bg=C["card"])
        self.win = self.create_window(6, 6, window=self.body, anchor="nw")
        self.bind("<Configure>", self._fit)
        self.body.bind("<Configure>", self._fit)

    def _fit(self, _e=None):
        w = self.winfo_width()
        h = self.body.winfo_reqheight() + 12
        self.itemconfigure(self.win, width=max(10, w - 12))
        if int(self.cget("height")) != h:
            self.configure(height=h)
        self.delete("bg")
        rounded(self, 1, 1, w - 1, h - 1, 14, fill=C["card"], outline=C["rim"], width=1, tags="bg")
        self.tag_lower("bg")


class Panel:
    def __init__(self, root):
        self.root = root
        root.title("Pocket XR")
        root.configure(bg=C["page"])
        sh = root.winfo_screenheight()
        h = max(560, min(720, sh - 80))
        root.geometry(f"{W}x{h}+834+0")
        root.minsize(380, 520)
        try:
            if len(sys.argv) > 1:
                self.icon = tk.PhotoImage(file=sys.argv[1])
                root.iconphoto(True, self.icon)
            else:
                self.icon = None
        except tk.TclError:
            self.icon = None
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.inbox = queue.Queue()

        # Quit first, at the bottom, so it is always on screen whatever the panel's height.
        quit_row = tk.Frame(root, bg=C["page"])
        quit_row.pack(side="bottom", fill="x", padx=12, pady=(2, 8))
        Button(quit_row, "Quit and put the glasses back", self.quit, height=40, bg=C["page"], kind="danger",
               radius=20).pack(fill="x")

        head = tk.Frame(root, bg=C["page"])
        head.pack(fill="x", padx=16, pady=(8, 2))
        if self.icon is not None:
            self.small_icon = self.icon.subsample(max(1, self.icon.width() // 32))
            tk.Label(head, image=self.small_icon, bg=C["page"]).pack(side="left", padx=(0, 10))
        titles = tk.Frame(head, bg=C["page"])
        titles.pack(side="left", fill="x", expand=True)
        tk.Label(titles, text="Pocket XR", bg=C["page"], fg=C["ink"], font=(MEDIUM, 17)).pack(anchor="w")
        self.status = tk.Label(titles, text="Starting...", bg=C["page"], fg=C["ink2"], font=(FONT, 10), anchor="w",
                               justify="left", wraplength=W - 90)
        self.status.pack(anchor="w", fill="x")

        self.view = self.segment("View", [("3dof", "Window in space"), ("steady", "Steady 6DoF")], "view")
        self.source = self.segment("Show", [("deck", "Deck screen"), ("apps", "App windows")], "source")

        sp = Card(root, "Space")
        row = tk.Frame(sp.body, bg=C["card"])
        row.pack(fill="x", padx=4, pady=(4, 2))
        self.space_buttons = {}
        for i, (label, cmd) in enumerate((("Launcher", "launcher"), ("Control Center", "cc"), ("PC VR", "pcvr"), ("Record", "record"))):
            b = Button(row, label, lambda c=cmd: send(c), height=38)
            b.grid(row=0, column=i, sticky="ew", padx=4)
            row.columnconfigure(i, weight=1)
            self.space_buttons[cmd] = b
        self.switches = {}
        for key, title, sub in (("sbs_3d", "3D side by side", "Each eye its own view: windows at a real depth"),
                                ("snap", "Snap windows together", "Line up and dock as you move them"),
                                ("locked", "Lock screens", "Nothing moves or resizes; clicks still work"),
                                ("cursor_follows_head", "Cursor follows head", "Off: the cursor stays in the room")):
            s = Switch(sp.body, title, sub, lambda on, k=key: send(k, on))
            s.pack(fill="x", padx=2)
            self.switches[key] = s
        self.viture = Switch(sp.body, "VITURE head tracking", "Experimental on models other than the Beast",
                             lambda on: send("viture", on))

        win = Card(root, "Window in front")
        wr = tk.Frame(win.body, bg=C["card"])
        wr.pack(fill="x", padx=4, pady=4)
        self.adjust = {}
        for c_, (label, cmd, val) in enumerate((("Recentre", "recentre", None), ("Smaller", "size", -1),
                                                 ("Bigger", "size", 1), ("Nearer", "distance", -1),
                                                 ("Further", "distance", 1))):
            b = Button(wr, label, lambda c=cmd, v=val: send(c, v), height=36, font=(FONT, 10), radius=10)
            b.grid(row=0, column=c_, sticky="ew", padx=2)
            wr.columnconfigure(c_, weight=1)
            self.adjust[label] = b

        self.message = tk.Label(root, text="", bg=C["page"], fg=C["accent"], font=(FONT, 10), justify="left",
                                anchor="w", wraplength=W - 36)

        keys = tk.Frame(root, bg=C["page"])
        keys.pack(fill="x", padx=16, pady=(2, 2))
        tk.Label(keys, text="BACK BUTTONS", bg=C["page"], fg=C["ink3"], font=(MEDIUM, 9)).grid(
            row=0, column=0, columnspan=4, sticky="w", pady=(0, 3))
        rows = (("L4", "Recentre", "hold: switch view"), ("R4", "Next app", "hold: Deck / apps"),
                ("L5", "Launcher", "hold: lock screens"), ("R5", "Control Center", "hold: adjust all"))
        for i, (k, tap, hold) in enumerate(rows):
            r, c_ = divmod(i, 2)
            cell = tk.Frame(keys, bg=C["page"])
            cell.grid(row=1 + r, column=c_, sticky="w", padx=(0, 14), pady=2)
            chip = tk.Canvas(cell, width=30, height=22, bg=C["page"], highlightthickness=0)
            rounded(chip, 1, 1, 29, 21, 7, fill=C["raised"], outline=C["rim_focus"])
            chip.create_text(15, 11, text=k, fill=C["ink"], font=(MEDIUM, 9))
            chip.pack(side="left", padx=(0, 6))
            t = tk.Frame(cell, bg=C["page"])
            t.pack(side="left")
            tk.Label(t, text=tap, bg=C["page"], fg=C["ink"], font=(FONT, 10)).pack(anchor="w")
            tk.Label(t, text=hold, bg=C["page"], fg=C["ink3"], font=(FONT, 8)).pack(anchor="w")
        keys.columnconfigure(0, weight=1)
        keys.columnconfigure(1, weight=1)
        # The message line sits between the guide and Quit, and only takes room when there is something to say.
        self.message.pack(side="bottom", fill="x", padx=18, pady=(0, 2), before=quit_row) if False else None
        self.quit_row = quit_row

        threading.Thread(target=self.reader, daemon=True).start()
        root.after(100, self.poll)

    def segment(self, title, options, cmd):
        card = Card(self.root, title)
        row = tk.Frame(card.body, bg=C["card"])
        row.pack(fill="x", padx=4, pady=4)
        out = {}
        for i, (key, label) in enumerate(options):
            b = Button(row, label, lambda k=key: send(cmd, k), height=38)
            b.grid(row=0, column=i, sticky="ew", padx=4)
            row.columnconfigure(i, weight=1)
            out[key] = b
        return out

    def reader(self):
        for line in sys.stdin:
            try:
                self.inbox.put(json.loads(line))
            except ValueError:
                pass
        self.inbox.put({"exit": True})

    def poll(self):
        try:
            while True:
                msg = self.inbox.get_nowait()
                if msg.get("exit"):
                    self.root.destroy()
                    return
                self.show(msg)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def show(self, st):
        for k, b in self.view.items():
            b.set(selected=st.get("view") == k)
        self.view["steady"].set(enabled=st.get("steady_ok", False) or st.get("view") == "steady")
        for k, b in self.source.items():
            b.set(selected=st.get("source") == k)
        on = bool(st.get("pcvr"))
        b = self.space_buttons["pcvr"]
        label = "Leave PC VR" if on else "PC VR"
        if b.text != label:
            b.text = label
            b.draw()
        b.set(selected=on)
        rec = bool(st.get("recording"))
        b = self.space_buttons["record"]
        label = "Stop recording" if rec else "Record"
        if b.text != label:
            b.text = label
            b.draw()
        b.set(selected=rec)
        for k, s in self.switches.items():
            s.set(bool(st.get(k, k in ("cursor_follows_head", "sbs_3d"))))
        flat = st.get("flat", False)
        for k in ("Nearer", "Further"):
            self.adjust[k].set(enabled=not flat)
        if st.get("viture"):
            if not self.viture.winfo_ismapped():
                self.viture.pack(fill="x", padx=2)
            self.viture.title = st.get("viture_label", "VITURE head tracking")
            self.viture.set(st.get("viture_on", False))
        elif self.viture.winfo_ismapped():
            self.viture.pack_forget()
        status = st.get("status", "")
        if self.status.cget("text") != status:
            self.status.configure(text=status)
        msg = st.get("message", "")
        if self.message.cget("text") != msg:
            self.message.configure(text=msg)
            if msg and not self.message.winfo_ismapped():
                self.message.pack(side="bottom", fill="x", padx=18, pady=(0, 2))
            elif not msg and self.message.winfo_ismapped():
                self.message.pack_forget()

    def quit(self):
        send("quit")
        self.message.configure(text="Putting your glasses back...")


def main():
    root = tk.Tk()
    Panel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
