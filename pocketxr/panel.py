"""Pocket XR's control panel on the Deck's own screen, made for touch. A child of the app.

It reads the app's state as JSON lines on stdin and writes what the user taps as JSON lines on stdout.
"""
import json
import queue
import sys
import threading
import tkinter as tk

BG = "#161616"
CARD = "#1D2024"
TEXT = "#E3E2E6"
DIM = "#9A9AA0"
ACCENT = "#3A7BFF"
ACCENT_HI = "#5A93FF"
FONT = "Noto Sans"


def send(cmd, value=None):
    sys.stdout.write(json.dumps({"cmd": cmd, "value": value}) + "\n")
    sys.stdout.flush()


class Panel:
    def __init__(self, root):
        self.root = root
        root.title("Pocket XR")
        root.configure(bg=BG)
        # Fits the Deck's screen above the taskbar (800 px, less about 50 for the taskbar and 30 for the title bar).
        sh = root.winfo_screenheight()
        h = max(560, min(720, sh - 80))
        root.geometry(f"440x{h}+834+0")
        root.minsize(380, 520)
        try:
            root.iconphoto(True, tk.PhotoImage(file=sys.argv[1])) if len(sys.argv) > 1 else None
        except tk.TclError:
            pass
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.inbox = queue.Queue()
        self.state = {}
        self.view_buttons = {}
        self.source_buttons = {}

        # Quit first, at the bottom, so it is always on screen whatever the panel's height.
        self.button(root, "Quit and put the glasses back", self.quit).pack(fill="x", padx=14, pady=(0, 10), side="bottom")
        tk.Label(root, text="Pocket XR", bg=BG, fg=TEXT, font=(FONT, 17, "bold")).pack(anchor="w", padx=16, pady=(8, 0))
        self.status = tk.Label(root, text="Starting...", bg=BG, fg=DIM, font=(FONT, 10), justify="left", anchor="w", wraplength=400)
        self.status.pack(fill="x", padx=16, pady=(0, 4))

        self.view_row = self.segment("View", [("3dof", "Window in space"), ("steady", "Steady 6DoF")], "view", self.view_buttons)
        self.segment("Show", [("deck", "Deck screen"), ("apps", "App windows")], "source", self.source_buttons)

        space = self.card("Space")
        self.button(space, "Launcher", lambda: send("launcher")).grid(row=0, column=0, sticky="ew", padx=3, pady=3)
        self.button(space, "Control Center", lambda: send("cc")).grid(row=0, column=1, sticky="ew", padx=3, pady=3)
        space.columnconfigure(0, weight=1)
        space.columnconfigure(1, weight=1)
        self.snap = tk.BooleanVar(value=True)
        self.locked = tk.BooleanVar(value=False)
        self.follows = tk.BooleanVar(value=True)
        for i, (var, label, cmd) in enumerate(((self.snap, "Snap windows together", "snap"),
                                               (self.locked, "Lock screens", "locked"),
                                               (self.follows, "Cursor follows head", "cursor_follows_head"))):
            tk.Checkbutton(space, text=label, variable=var, command=lambda v=var, c=cmd: send(c, v.get()), bg=CARD,
                           fg=TEXT, selectcolor=CARD, activebackground=CARD, activeforeground=TEXT, font=(FONT, 11),
                           anchor="w", highlightthickness=0, bd=0).grid(row=1 + i // 2, column=i % 2, sticky="w",
                                                                        padx=3, pady=(3, 0))

        row = self.card("Window in front")
        for c, (label, cmd, val) in enumerate((("Recentre", "recentre", None), ("Smaller", "size", -1), ("Bigger", "size", 1),
                                               ("Nearer", "distance", -1), ("Further", "distance", 1))):
            b = self.button(row, label, lambda c_=cmd, v_=val: send(c_, v_), small=True)
            b.grid(row=0, column=c, sticky="ew", padx=2, pady=2)
            row.columnconfigure(c, weight=1)
            if label == "Nearer":
                self.near = b
            elif label == "Further":
                self.far = b
        self.look = tk.BooleanVar(value=True)
        self.viture = tk.BooleanVar(value=False)
        self.viture_box = tk.Checkbutton(row, text="VITURE head tracking", variable=self.viture,
                                         command=lambda: send("viture", self.viture.get()), bg=CARD, fg=TEXT,
                                         selectcolor=CARD, activebackground=CARD, activeforeground=TEXT,
                                         font=(FONT, 11), anchor="w", highlightthickness=0, bd=0)

        self.message = tk.Label(root, text="", bg=BG, fg=ACCENT_HI, font=(FONT, 11), justify="left", anchor="w", wraplength=400)
        self.message.pack(fill="x", padx=16, pady=(2, 2))

        legend = ("Back buttons\n"
                  "L4  recentre          hold L4  switch view\n"
                  "R4  next app           hold R4  Deck screen / apps\n"
                  "L5  launcher           hold L5  lock screens\n"
                  "R5  Control Center     hold R5  adjust all")
        tk.Label(root, text=legend, bg=BG, fg=DIM, font=(FONT, 9), justify="left", anchor="w").pack(fill="x", padx=16, pady=(2, 4))

        threading.Thread(target=self.reader, daemon=True).start()
        root.after(100, self.poll)

    def card(self, title):
        tk.Label(self.root, text=title, bg=BG, fg=DIM, font=(FONT, 10)).pack(anchor="w", padx=16)
        f = tk.Frame(self.root, bg=CARD, padx=5, pady=5)
        f.pack(fill="x", padx=12, pady=(0, 5))
        return f

    def button(self, parent, text, cmd, wide=False, small=False):
        return tk.Button(parent, text=text, command=cmd, bg=CARD if parent is not self.root else "#26292E", fg=TEXT,
                         activebackground=ACCENT, activeforeground="white", relief="flat", bd=0,
                         font=(FONT, 10 if small else 12), height=1, pady=7, padx=2, highlightthickness=1,
                         highlightbackground="#33363B")

    def segment(self, title, options, cmd, store):
        f = self.card(title)
        for i, (key, label) in enumerate(options):
            b = tk.Button(f, text=label, command=lambda k=key: send(cmd, k), relief="flat", bd=0, font=(FONT, 12),
                          height=1, pady=7, fg=TEXT, bg=CARD, activebackground=ACCENT, activeforeground="white",
                          highlightthickness=1, highlightbackground="#33363B")
            b.grid(row=0, column=i, sticky="ew", padx=4)
            f.columnconfigure(i, weight=1)
            store[key] = b
        return f

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
        self.state = st
        for k, b in self.view_buttons.items():
            on = st.get("view") == k
            b.configure(bg=ACCENT if on else CARD, fg="white" if on else TEXT)
        steady_ok = st.get("steady_ok", False)
        self.view_buttons["steady"].configure(state="normal" if steady_ok else "disabled",
                                              disabledforeground="#55585E")
        for k, b in self.source_buttons.items():
            on = st.get("source") == k
            b.configure(bg=ACCENT if on else CARD, fg="white" if on else TEXT)
        flat = st.get("flat", False)
        for b in (self.near, self.far):
            b.configure(state="disabled" if flat else "normal", disabledforeground="#55585E")
        if self.snap.get() != st.get("snap", True):
            self.snap.set(st.get("snap", True))
        if self.locked.get() != st.get("locked", False):
            self.locked.set(st.get("locked", False))
        if self.follows.get() != st.get("cursor_follows_head", True):
            self.follows.set(st.get("cursor_follows_head", True))
        if st.get("viture"):
            self.viture_box.configure(text=st.get("viture_label", "VITURE head tracking"))
            self.viture_box.grid(row=1, column=0, columnspan=5, sticky="w", padx=3, pady=(2, 0))
            if self.viture.get() != st.get("viture_on", False):
                self.viture.set(st.get("viture_on", False))
        else:
            self.viture_box.grid_remove()
        self.status.configure(text=st.get("status", ""))
        self.message.configure(text=st.get("message", ""))

    def quit(self):
        send("quit")
        self.message.configure(text="Putting your glasses back...")


def main():
    root = tk.Tk()
    Panel(root)
    root.mainloop()


if __name__ == "__main__":
    main()
