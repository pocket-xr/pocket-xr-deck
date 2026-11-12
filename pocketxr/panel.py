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
        root.geometry("440x790+830+5")
        root.minsize(380, 600)
        try:
            root.iconphoto(True, tk.PhotoImage(file=sys.argv[1])) if len(sys.argv) > 1 else None
        except tk.TclError:
            pass
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self.inbox = queue.Queue()
        self.state = {}
        self.view_buttons = {}
        self.source_buttons = {}

        tk.Label(root, text="Pocket XR", bg=BG, fg=TEXT, font=(FONT, 22, "bold")).pack(anchor="w", padx=18, pady=(14, 0))
        self.status = tk.Label(root, text="Starting...", bg=BG, fg=DIM, font=(FONT, 11), justify="left", anchor="w", wraplength=400)
        self.status.pack(fill="x", padx=18, pady=(2, 10))

        self.view_row = self.segment("View", [("3dof", "Window in space"), ("steady", "Steady 6DoF")], "view", self.view_buttons)
        self.segment("Show", [("deck", "Deck screen"), ("apps", "App windows")], "source", self.source_buttons)

        space = self.card("Space")
        self.button(space, "Launcher", lambda: send("launcher")).grid(row=0, column=0, sticky="ew", padx=4, pady=4)
        self.button(space, "Control Center", lambda: send("cc")).grid(row=0, column=1, sticky="ew", padx=4, pady=4)
        space.columnconfigure(0, weight=1)
        space.columnconfigure(1, weight=1)
        self.snap = tk.BooleanVar(value=True)
        self.locked = tk.BooleanVar(value=False)
        for i, (var, label, cmd) in enumerate(((self.snap, "Snap windows together", "snap"),
                                               (self.locked, "Lock screens", "locked"))):
            tk.Checkbutton(space, text=label, variable=var, command=lambda v=var, c=cmd: send(c, v.get()), bg=CARD,
                           fg=TEXT, selectcolor=CARD, activebackground=CARD, activeforeground=TEXT, font=(FONT, 11),
                           anchor="w", highlightthickness=0, bd=0).grid(row=1 + i, column=0, columnspan=2, sticky="w",
                                                                        padx=4, pady=(4, 0))

        row = self.card("Window in front")
        self.button(row, "Recentre", lambda: send("recentre"), wide=True).grid(row=0, column=0, columnspan=2, sticky="ew", padx=4, pady=4)
        self.button(row, "Smaller", lambda: send("size", -1)).grid(row=1, column=0, sticky="ew", padx=4, pady=4)
        self.button(row, "Bigger", lambda: send("size", 1)).grid(row=1, column=1, sticky="ew", padx=4, pady=4)
        self.near = self.button(row, "Nearer", lambda: send("distance", -1))
        self.near.grid(row=2, column=0, sticky="ew", padx=4, pady=4)
        self.far = self.button(row, "Further", lambda: send("distance", 1))
        self.far.grid(row=2, column=1, sticky="ew", padx=4, pady=4)
        row.columnconfigure(0, weight=1)
        row.columnconfigure(1, weight=1)
        self.look = tk.BooleanVar(value=True)
        self.viture = tk.BooleanVar(value=False)
        self.viture_box = tk.Checkbutton(row, text="VITURE head tracking", variable=self.viture,
                                         command=lambda: send("viture", self.viture.get()), bg=CARD, fg=TEXT,
                                         selectcolor=CARD, activebackground=CARD, activeforeground=TEXT,
                                         font=(FONT, 11), anchor="w", highlightthickness=0, bd=0)

        self.message = tk.Label(root, text="", bg=BG, fg=ACCENT_HI, font=(FONT, 12), justify="left", anchor="w", wraplength=400)
        self.message.pack(fill="x", padx=18, pady=(6, 4))

        legend = ("Back buttons\n"
                  "L4  recentre          hold L4  switch view\n"
                  "R4  next app           hold R4  Deck screen / apps\n"
                  "L5  launcher           hold L5  lock screens\n"
                  "R5  Control Center     hold R5  adjust all")
        tk.Label(root, text=legend, bg=BG, fg=DIM, font=(FONT, 10), justify="left", anchor="w").pack(fill="x", padx=18, pady=(4, 8))

        self.button(root, "Quit and put the glasses back", self.quit, wide=True).pack(fill="x", padx=18, pady=(0, 14), side="bottom")

        threading.Thread(target=self.reader, daemon=True).start()
        root.after(100, self.poll)

    def card(self, title):
        tk.Label(self.root, text=title, bg=BG, fg=DIM, font=(FONT, 11)).pack(anchor="w", padx=18)
        f = tk.Frame(self.root, bg=CARD, padx=8, pady=8)
        f.pack(fill="x", padx=14, pady=(2, 10))
        return f

    def button(self, parent, text, cmd, wide=False):
        return tk.Button(parent, text=text, command=cmd, bg=CARD if parent is not self.root else "#26292E", fg=TEXT,
                         activebackground=ACCENT, activeforeground="white", relief="flat", bd=0,
                         font=(FONT, 13), height=2, highlightthickness=1, highlightbackground="#33363B")

    def segment(self, title, options, cmd, store):
        f = self.card(title)
        for i, (key, label) in enumerate(options):
            b = tk.Button(f, text=label, command=lambda k=key: send(cmd, k), relief="flat", bd=0, font=(FONT, 13),
                          height=2, fg=TEXT, bg=CARD, activebackground=ACCENT, activeforeground="white",
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
        if st.get("viture"):
            self.viture_box.configure(text=st.get("viture_label", "VITURE head tracking"))
            self.viture_box.grid(row=4, column=0, columnspan=2, sticky="w", padx=4, pady=(2, 2))
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
