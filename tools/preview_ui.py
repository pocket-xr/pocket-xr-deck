"""Paints the in-space UI to PNGs (on a dark backdrop, as the glasses show it) for design review."""
import ctypes
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import space as S, ui  # noqa: E402
from pocketxr.text import cairo, FORMAT_ARGB32  # noqa: E402

cairo.cairo_image_surface_create_for_data.restype = ctypes.c_void_p
cairo.cairo_image_surface_create_for_data.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int]
cairo.cairo_surface_write_to_png.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
out = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ui"
os.makedirs(out, exist_ok=True)


def save(name, data, w, h, bg=(0.02, 0.025, 0.03)):
    cv = ui.Canvas(w + 80, h + 80)
    cv.fill_round(0, 0, w + 80, h + 80, 0, bg + (1.0,))
    src = cairo.cairo_image_surface_create_for_data(data, FORMAT_ARGB32, w, h, w * 4)
    cairo.cairo_set_source_surface(cv.c, src, 40, 40)
    cairo.cairo_paint(cv.c)
    d, W, H = cv.done()
    s = cairo.cairo_image_surface_create_for_data(d, FORMAT_ARGB32, W, H, W * 4)
    cairo.cairo_surface_write_to_png(s, f"{out}/{name}.png".encode())


class A:
    def __init__(self, n):
        self.name, self.id, self.icon = n, n, None


apps = [A(n) for n in ["Firefox", "Google Chrome", "Konsole", "Dolphin", "Steam", "Discord", "Spotify", "VLC media player",
                       "Kate", "System Settings", "Heroic Games Launcher", "Bottles", "Flatseal", "Moonlight", "Proton VPN",
                       "EmuDeck"]]
from pocketxr import apps as appsmod  # noqa: E402
real = appsmod.list_apps()
c = ui.launcher_card(real or apps, 0, lambda a: a.icon)
save("launcher", c.data, c.w, c.h)
poses = [S.Pose(30, 0), S.Pose(0, 0), S.Pose(-30, 0)]
layouts = [(n, S.arrange(n, poses, 1, 0.0), 1) for n in S.layout_choices(3)]
c = ui.cc_card({"layouts": layouts, "snap": False, "locked": False, "cursor_follows_head": True, "speed": 5,
                "curve": 30, "focus": True, "presets": ["Workspace 2", "Workspace 1"]})
save("cc", c.data, c.w, c.h)
for name, kw in (("capsule_right", dict(names=["reset", "close"], hover="close")), ("capsule_move", dict(names=["move"], pill_w=260)),
                 ("capsule_back", dict(names=["back"]))):
    d, w, h = ui.capsule(**kw)
    save(name, d, w, h)
d, w, h = ui.toast("Saved this layout as Workspace 3.")
save("toast", d, w, h)
d, w, h = ui.cursor(160)
save("cursor", d, w, h)
d, w, h = ui.handle(80)
save("handle", d, w, h)
print("ok", out)
