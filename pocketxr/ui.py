"""Pocket XR's "Light on glass" drawn with Cairo: cards, capsules, switches, steppers, icons and layout thumbnails,
for the launcher, the Control Center, the window controls, toasts and the cursor in the glasses.

Every builder returns premultiplied BGRA bytes with its size, plus the clickable rects (in pixels) where it has any.
Hover and press are drawn as overlays on top, so a card is only painted again when what it shows changes.
"""
import ctypes
import ctypes.util
import math
import time

from . import look as L
from .text import FORMAT_ARGB32, TextExtents, _take, cairo

cairo.cairo_set_font_size.argtypes = [ctypes.c_void_p, ctypes.c_double]
cairo.cairo_curve_to.argtypes = [ctypes.c_void_p] + [ctypes.c_double] * 6
cairo.cairo_fill_preserve.argtypes = [ctypes.c_void_p]
cairo.cairo_save.argtypes = [ctypes.c_void_p]
cairo.cairo_restore.argtypes = [ctypes.c_void_p]
cairo.cairo_translate.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
cairo.cairo_clip.argtypes = [ctypes.c_void_p]
cairo.cairo_pattern_create_radial.restype = ctypes.c_void_p
cairo.cairo_pattern_create_radial.argtypes = [ctypes.c_double] * 6
cairo.cairo_pattern_add_color_stop_rgba.argtypes = [ctypes.c_void_p] + [ctypes.c_double] * 5
cairo.cairo_set_source.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
cairo.cairo_pattern_destroy.argtypes = [ctypes.c_void_p]
cairo.cairo_set_operator.argtypes = [ctypes.c_void_p, ctypes.c_int]


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = int(w), int(h)
        self.s = cairo.cairo_image_surface_create(FORMAT_ARGB32, self.w, self.h)
        self.c = cairo.cairo_create(self.s)

    def done(self):
        out = _take(self.s, self.w, self.h)
        cairo.cairo_destroy(self.c)
        cairo.cairo_surface_destroy(self.s)
        return out, self.w, self.h

    def rgba(self, col, alpha=1.0):
        cairo.cairo_set_source_rgba(self.c, col[0], col[1], col[2], col[3] * alpha)

    def rpath(self, x, y, w, h, r):
        c = self.c
        r = max(0.0, min(r, w / 2, h / 2))
        cairo.cairo_new_path(c)
        cairo.cairo_arc(c, x + w - r, y + r, r, -math.pi / 2, 0)
        cairo.cairo_arc(c, x + w - r, y + h - r, r, 0, math.pi / 2)
        cairo.cairo_arc(c, x + r, y + h - r, r, math.pi / 2, math.pi)
        cairo.cairo_arc(c, x + r, y + r, r, math.pi, 3 * math.pi / 2)
        cairo.cairo_close_path(c)

    def glass(self, x, y, w, h, r, fill=L.GLASS, rim=L.RIM, rim_w=1.5):
        """Smoked glass with a hairline light rim."""
        self.rpath(x + rim_w / 2, y + rim_w / 2, w - rim_w, h - rim_w, r)
        self.rgba(fill)
        cairo.cairo_fill_preserve(self.c)
        if rim:
            self.rgba(rim)
            cairo.cairo_set_line_width(self.c, rim_w)
            cairo.cairo_stroke(self.c)
        else:
            cairo.cairo_new_path(self.c)

    def fill_round(self, x, y, w, h, r, col, alpha=1.0):
        self.rpath(x, y, w, h, r)
        self.rgba(col, alpha)
        cairo.cairo_fill(self.c)

    def stroke_round(self, x, y, w, h, r, col, width):
        self.rpath(x + width / 2, y + width / 2, w - width, h - width, r)
        self.rgba(col)
        cairo.cairo_set_line_width(self.c, width)
        cairo.cairo_stroke(self.c)

    def text(self, x, y, s, size, col=L.INK, medium=False, align="left", max_w=None):
        """Text with its vertical middle at y; cut with an ellipsis to max_w."""
        c = self.c
        cairo.cairo_select_font_face(c, (L.FONT_MEDIUM if medium else L.FONT).encode(), 0, 0)
        cairo.cairo_set_font_size(c, size)
        raw = s.encode("utf-8")
        ext = TextExtents()
        cairo.cairo_text_extents(c, raw, ctypes.byref(ext))
        if max_w and ext.x_advance > max_w:
            while s and ext.x_advance > max_w:
                s = s[:-1]
                raw = (s.rstrip() + "…").encode("utf-8")
                cairo.cairo_text_extents(c, raw, ctypes.byref(ext))
        if align == "center":
            x -= ext.x_advance / 2
        elif align == "right":
            x -= ext.x_advance
        self.rgba(col)
        cairo.cairo_move_to(c, x, y + size * 0.36)
        cairo.cairo_show_text(c, raw)
        return ext.x_advance

    def line(self, pts, col, width, close=False):
        c = self.c
        cairo.cairo_new_path(c)
        cairo.cairo_move_to(c, *pts[0])
        for p in pts[1:]:
            cairo.cairo_line_to(c, *p)
        if close:
            cairo.cairo_close_path(c)
        self.rgba(col)
        cairo.cairo_set_line_width(c, width)
        cairo.cairo_set_line_cap(c, 1)
        cairo.cairo_stroke(c)

    def circle(self, x, y, r, col, fill=True, width=2.0):
        c = self.c
        cairo.cairo_new_path(c)
        cairo.cairo_arc(c, x, y, r, 0, 2 * math.pi)
        self.rgba(col)
        if fill:
            cairo.cairo_fill(c)
        else:
            cairo.cairo_set_line_width(c, width)
            cairo.cairo_stroke(c)

    def icon(self, name, cx, cy, size, col=L.INK):
        """Line icons on a size x size box centred at (cx, cy), stroke about 1/11 of the size."""
        s = size / 2
        w = max(1.5, size / 11)
        if name == "back":
            self.line([(cx + s * 0.25, cy - s * 0.5), (cx - s * 0.25, cy), (cx + s * 0.25, cy + s * 0.5)], col, w)
        elif name == "next":
            self.line([(cx - s * 0.25, cy - s * 0.5), (cx + s * 0.25, cy), (cx - s * 0.25, cy + s * 0.5)], col, w)
        elif name == "close":
            k = s * 0.42
            self.line([(cx - k, cy - k), (cx + k, cy + k)], col, w)
            self.line([(cx + k, cy - k), (cx - k, cy + k)], col, w)
        elif name == "reset":
            # a circular arrow: most of a circle, its arrowhead at the top end pointing round
            c = self.c
            r = s * 0.46
            a0, a1 = math.radians(-60), math.radians(220)
            cairo.cairo_new_path(c)
            cairo.cairo_arc(c, cx, cy, r, a0, a1)
            self.rgba(col)
            cairo.cairo_set_line_width(c, w)
            cairo.cairo_stroke(c)
            tx, ty = cx + r * math.cos(a0), cy + r * math.sin(a0)
            # tangent going backwards round the circle (anticlockwise on screen)
            dx, dy = math.sin(a0), -math.cos(a0)
            nx, ny = math.cos(a0), math.sin(a0)
            k = s * 0.3
            self.line([(tx - dx * k + nx * k * 0.6, ty - dy * k + ny * k * 0.6), (tx, ty),
                       (tx - dx * k - nx * k * 0.6, ty - dy * k - ny * k * 0.6)], col, w)
        elif name == "grip":
            for i in (-1, 0, 1):
                for j in (-0.5, 0.5):
                    self.circle(cx + i * s * 0.5, cy + j * s * 0.5, s * 0.13, col)
        elif name == "lock":
            self.fill_round(cx - s * 0.42, cy - s * 0.05, s * 0.84, s * 0.62, s * 0.12, col)
            c = self.c
            cairo.cairo_new_path(c)
            cairo.cairo_arc(c, cx, cy - s * 0.08, s * 0.28, math.pi, 2 * math.pi)
            cairo.cairo_line_to(c, cx + s * 0.28, cy)
            cairo.cairo_move_to(c, cx - s * 0.28, cy)
            cairo.cairo_line_to(c, cx - s * 0.28, cy - s * 0.08)
            self.rgba(col)
            cairo.cairo_set_line_width(c, w)
            cairo.cairo_stroke(c)
        elif name == "recenter":
            self.circle(cx, cy, s * 0.42, col, fill=False, width=w)
            self.circle(cx, cy, s * 0.12, col)
            for a in range(4):
                ang = a * math.pi / 2
                self.line([(cx + math.cos(ang) * s * 0.55, cy + math.sin(ang) * s * 0.55),
                           (cx + math.cos(ang) * s * 0.8, cy + math.sin(ang) * s * 0.8)], col, w)
        elif name == "minus":
            self.line([(cx - s * 0.4, cy), (cx + s * 0.4, cy)], col, w)
        elif name == "plus":
            self.line([(cx - s * 0.4, cy), (cx + s * 0.4, cy)], col, w)
            self.line([(cx, cy - s * 0.4), (cx, cy + s * 0.4)], col, w)
        elif name == "save":
            self.line([(cx, cy - s * 0.5), (cx, cy + s * 0.2)], col, w)
            self.line([(cx - s * 0.3, cy - s * 0.1), (cx, cy + s * 0.2), (cx + s * 0.3, cy - s * 0.1)], col, w)
            self.line([(cx - s * 0.5, cy + s * 0.5), (cx + s * 0.5, cy + s * 0.5)], col, w)
        elif name == "all":
            for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                self.stroke_round(cx + dx * s * 0.27 - s * 0.22, cy + dy * s * 0.22 - s * 0.16, s * 0.44, s * 0.32,
                                  s * 0.06, col, w * 0.8)

    def switch(self, x, y, on, scale=1.0):
        """A switch 52 x 32 (x scale), track accent when on, knob white."""
        w, h = 52 * scale, 32 * scale
        self.fill_round(x, y, w, h, h / 2, L.ACCENT if on else (1, 1, 1, 0.16))
        kx = x + w - h / 2 if on else x + h / 2
        self.circle(kx, y + h / 2, h / 2 - 4 * scale, (1, 1, 1, 0.96))
        return w, h


# ---------------- window controls ----------------
def capsule(names, hover=None, h=72, pill_w=None, held=False):
    """One glass capsule holding buttons in a row (the window's controls), hover tinted. Returns bytes, w, h."""
    pad = round(h * 0.16)
    bw = h - 2 * pad
    widths = [(pill_w or bw * 3) if n == "move" else bw for n in names]
    w = sum(widths) + pad * (len(names) + 1)
    cv = Canvas(w, h)
    cv.glass(0, 0, w, h, h / 2, fill=L.HELD_GLASS if held else L.GLASS)
    x = pad
    for n, bwid in zip(names, widths):
        if n == hover:
            col = L.DANGER if n == "close" else L.ACCENT
            cv.fill_round(x, pad, bwid, bw, bw / 2, col, 0.9)
        ink = (1, 1, 1, 1) if n == hover else L.INK
        cv.icon("grip" if n == "move" else n, x + bwid / 2, h / 2, bw * 0.62, ink)
        x += bwid + pad
    return cv.done()


def handle(h=60, active=False, locked=False):
    """The resize handle: an L just outside the bottom right corner, or a lock while screens are locked."""
    cv = Canvas(h, h)
    if locked:
        cv.glass(0, 0, h, h, h / 2)
        cv.icon("lock", h / 2, h / 2, h * 0.56, L.INK)
    else:
        col = L.ACCENT if active else L.INK_2
        t = h * 0.16
        cv.line([(t, h - t), (h - t, h - t), (h - t, t)], col, t)
    return cv.done()


# ---------------- cursor ----------------
def cursor(size=96, pressed=False):
    """A crisp light ring with a small glow (Light on glass: drawn with light, no shadow)."""
    cv = Canvas(size, size)
    c = size / 2
    pat = cairo.cairo_pattern_create_radial(c, c, size * 0.2, c, c, size * 0.42)
    cairo.cairo_pattern_add_color_stop_rgba(pat, 0.0, 1, 1, 1, 0.0)
    cairo.cairo_pattern_add_color_stop_rgba(pat, 0.3, 1, 1, 1, 0.16)
    cairo.cairo_pattern_add_color_stop_rgba(pat, 1.0, 1, 1, 1, 0.0)
    cairo.cairo_set_source(cv.c, pat)
    cairo.cairo_paint(cv.c)
    cairo.cairo_pattern_destroy(pat)
    cv.circle(c, c, size * 0.24, (1, 1, 1, 0.96) if not pressed else L.ACCENT, fill=False, width=size * 0.055)
    cv.circle(c, c, size * 0.04, (1, 1, 1, 0.9))
    return cv.done()


def ripple(size=128):
    cv = Canvas(size, size)
    cv.circle(size / 2, size / 2, size * 0.44, (1, 1, 1, 0.85), fill=False, width=size * 0.035)
    return cv.done()


# ---------------- toast ----------------
def toast(msg, max_w=1100):
    probe = Canvas(4, 4)
    tw = probe.text(0, 0, msg, 30, max_w=max_w)
    probe.done()
    w, h = int(tw + 64), 72
    cv = Canvas(w, h)
    cv.glass(0, 0, w, h, h / 2, fill=L.GLASS_RAISED, rim=L.RIM_FOCUS)
    cv.text(w / 2, h / 2, msg, 30, L.INK, align="center", max_w=max_w)
    return cv.done()


# ---------------- layout thumbnails ----------------
def thumb(cv, x, y, w, h, poses, main_i, col_main=L.ACCENT, col=L.INK_2):
    """The windows of a layout seen from above the head: yaw across, pitch up, scaled into the box."""
    if not poses:
        return
    xs = [(-p.left, -p.right) for p in poses]
    ys = [(-p.top, -p.bottom) for p in poses]
    x0, x1 = min(a for a, _ in xs), max(b for _, b in xs)
    y0, y1 = min(a for a, _ in ys), max(b for _, b in ys)
    sx = (w - 8) / max(1e-3, x1 - x0)
    sy = (h - 8) / max(1e-3, y1 - y0)
    k = min(sx, sy)
    ox = x + (w - (x1 - x0) * k) / 2
    oy = y + (h - (y1 - y0) * k) / 2
    for i, ((a, b), (c, d)) in enumerate(zip(xs, ys)):
        rx, ry = ox + (a - x0) * k, oy + (c - y0) * k
        cv.fill_round(rx, ry, max(2, (b - a) * k - 2), max(2, (d - c) * k - 2), 3,
                      col_main if i == main_i else col, 0.95 if i == main_i else 0.55)


# ---------------- cards ----------------
cairo.cairo_image_surface_create_from_png.restype = ctypes.c_void_p
cairo.cairo_image_surface_create_from_png.argtypes = [ctypes.c_char_p]
cairo.cairo_image_surface_get_width.argtypes = [ctypes.c_void_p]
cairo.cairo_image_surface_get_height.argtypes = [ctypes.c_void_p]
cairo.cairo_surface_status.argtypes = [ctypes.c_void_p]
cairo.cairo_scale.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
cairo.cairo_set_source_surface.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
_ICON_CACHE = {}
try:
    rsvg = ctypes.CDLL(ctypes.util.find_library("rsvg-2") or "librsvg-2.so.2")

    class RsvgRectangle(ctypes.Structure):
        _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("width", ctypes.c_double),
                    ("height", ctypes.c_double)]

    rsvg.rsvg_handle_new_from_file.restype = ctypes.c_void_p
    rsvg.rsvg_handle_new_from_file.argtypes = [ctypes.c_char_p, ctypes.c_void_p]
    rsvg.rsvg_handle_render_document.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(RsvgRectangle),
                                                 ctypes.c_void_p]
except OSError:
    rsvg = None


def _svg(cv, path, cx, cy, size):
    if rsvg is None:
        return False
    h = _ICON_CACHE.get(path)
    if h is None:
        h = rsvg.rsvg_handle_new_from_file(path.encode(), None) or 0
        _ICON_CACHE[path] = h
    if not h:
        return False
    vp = RsvgRectangle(cx - size / 2, cy - size / 2, size, size)
    return bool(rsvg.rsvg_handle_render_document(h, cv.c, ctypes.byref(vp), None))


def icon_png(cv, path, name, cx, cy, size):
    """An app's icon centred at (cx, cy), or a round tile with its first letter when it has no PNG icon."""
    src = None
    if path and path.endswith(".svg"):
        if _svg(cv, path, cx, cy, size):
            return
        path = None
    if path:
        src = _ICON_CACHE.get(path)
        if src is None:
            src = cairo.cairo_image_surface_create_from_png(path.encode())
            if not src or cairo.cairo_surface_status(src) != 0:
                src = 0
            _ICON_CACHE[path] = src
    if src:
        sw, sh = cairo.cairo_image_surface_get_width(src), cairo.cairo_image_surface_get_height(src)
        k = size / max(sw, sh)
        cairo.cairo_save(cv.c)
        cairo.cairo_translate(cv.c, cx - sw * k / 2, cy - sh * k / 2)
        cairo.cairo_scale(cv.c, k, k)
        cairo.cairo_set_source_surface(cv.c, src, 0, 0)
        cairo.cairo_paint(cv.c)
        cairo.cairo_restore(cv.c)
        return
    hue = (sum(map(ord, name)) % 360) / 360.0
    import colorsys
    r, g, b = colorsys.hsv_to_rgb(hue, 0.45, 0.62)
    cv.circle(cx, cy, size * 0.46, (r, g, b, 1.0))
    cv.text(cx, cy, (name[:1] or "?").upper(), size * 0.42, (1, 1, 1, 0.95), medium=True, align="center")
# A card's glass a little more solid than a window control's, so a window behind does not show through its text.
CARD_GLASS = L.GLASS[:3] + (0.97,)


def clock12():
    """The time in 12-hour form, "7:23 PM"."""
    t = time.localtime()
    return f"{(t.tm_hour % 12) or 12}:{t.tm_min:02d} {'AM' if t.tm_hour < 12 else 'PM'}"


class CardSpec:
    """A painted card and its clickable rects: [(x, y, w, h, action, arg, radius)]."""

    def __init__(self, data, w, h, items):
        self.data, self.w, self.h, self.items = data, w, h, items


def launcher_card(apps, page, icon_for, cols=5, rows=3):
    W, H = 1450, 950
    cv = Canvas(W, H)
    items = []
    cv.glass(0, 0, W, H, 44, fill=CARD_GLASS, rim=L.RIM)
    cv.text(56, 70, "Apps", 44, L.INK, medium=True)
    cv.text(W - 140, 58, clock12(), 32, L.INK, medium=True, align="right")
    cv.text(W - 140, 92, time.strftime("%A %d %B"), 20, L.INK_2, align="right")
    # close
    cx, cy, r = W - 74, 72, 30
    cv.glass(cx - r, cy - r, 2 * r, 2 * r, r, fill=L.GLASS_RAISED)
    cv.icon("close", cx, cy, 26, L.INK)
    items.append((cx - r, cy - r, 2 * r, 2 * r, "launcher_close", None, r))
    per = cols * rows
    pages = max(1, math.ceil(len(apps) / per))
    shown = apps[page * per:(page + 1) * per]
    gx, gy, tw, th = 56, 140, (W - 112) / cols, 220
    for i, a in enumerate(shown):
        r_, c_ = divmod(i, cols)
        x = gx + c_ * tw
        y = gy + r_ * (th + 14)
        icon_png(cv, icon_for(a), a.name, x + tw / 2, y + 74, 112)
        cv.text(x + tw / 2, y + 170, a.name, 22, L.INK, align="center", max_w=tw - 24)
        items.append((x + 6, y, tw - 12, th, "launch", a, 24))
    if not apps:
        cv.text(W / 2, H / 2, "No apps found", 24, L.INK_2, align="center")
    if pages > 1:
        dy = H - 64
        total = pages * 22
        for p in range(pages):
            cv.circle(W / 2 - total / 2 + p * 22 + 11, dy, 6 if p == page else 4, L.INK if p == page else L.INK_3)
        for arg, x, ic in ((-1, W / 2 - total / 2 - 70, "back"), (1, W / 2 + total / 2 + 70, "next")):
            cv.glass(x - 28, dy - 28, 56, 56, 28, fill=L.GLASS_RAISED)
            cv.icon(ic, x, dy, 26, L.INK)
            items.append((x - 28, dy - 28, 56, 56, "page", arg, 28))
    data, w, h = cv.done()
    return CardSpec(data, w, h, items)


def cc_card(state):
    """The Control Center: header, Arrange (with a thumbnail of each layout), Windows switches, Pointer and Curve
    steppers, and saved layouts. state: dict of what it shows."""
    W = 1600
    n_layouts = len(state["layouts"]) + 1
    left_end = 140 + 30 + math.ceil(n_layouts / 3) * (190 + 16)
    right_end = 140 + 26 + 3 * 92 + 34 + 26 + 96 + 84 + 34 + 26 + min(3, len(state["presets"])) * 74 + 64
    H = int(max(left_end, right_end) + 56)
    cv = Canvas(W, H)
    items = []
    cv.glass(0, 0, W, H, 44, fill=CARD_GLASS, rim=L.RIM)
    cv.text(56, 72, "Control Center", 40, L.INK, medium=True)
    # Recenter view pill and close
    px, py, pw, ph = W - 380, 44, 230, 56
    cv.glass(px, py, pw, ph, ph / 2, fill=L.GLASS_RAISED)
    cv.icon("recenter", px + 36, py + ph / 2, 30, L.INK)
    cv.text(px + 62, py + ph / 2, "Recenter view", 20, L.INK)
    items.append((px, py, pw, ph, "recenter", None, ph / 2))
    cx, cy, r = W - 82, 72, 30
    cv.glass(cx - r, cy - r, 2 * r, 2 * r, r, fill=L.GLASS_RAISED)
    cv.icon("close", cx, cy, 26, L.INK)
    items.append((cx - r, cy - r, 2 * r, 2 * r, "cc_close", None, r))

    # ---- Arrange (left) ----
    lx, ly, lw = 56, 140, 820
    cv.text(lx, ly, "ARRANGE", 16, L.INK_3, medium=True)
    if state.get("locked"):
        cv.text(lx + 120, ly, "Screens are locked", 16, L.INK_3)
    layouts = state["layouts"]  # [(name, poses, main_i)]
    tile_w, tile_h, gap = (lw - 20) / 3, 190, 16
    for i, (name, poses, mi) in enumerate(layouts + [("Adjust all", None, 0)]):
        r_, c_ = divmod(i, 3)
        x = lx + c_ * (tile_w + 10)
        y = ly + 30 + r_ * (tile_h + gap)
        cv.glass(x, y, tile_w, tile_h, L.RADIUS_M * 1.6, fill=L.GLASS_RAISED)
        if poses:
            thumb(cv, x + 22, y + 18, tile_w - 44, tile_h - 78, poses, mi)
        else:
            cv.icon("all", x + tile_w / 2, y + 66, 64, L.INK_2)
        cv.text(x + tile_w / 2, y + tile_h - 32, name, 20, L.INK, align="center", max_w=tile_w - 20)
        items.append((x, y, tile_w, tile_h, "adjust_all" if poses is None else "arrange", name, L.RADIUS_M * 1.6))

    # ---- right column ----
    rx, rw = 920, W - 920 - 56
    y = 140
    cv.text(rx, y, "WINDOWS", 16, L.INK_3, medium=True)
    y += 26
    rows = [("snap", "Snap windows together", "Line up and dock as you move them"),
            ("locked", "Lock screens", "Nothing moves or resizes; clicks still work"),
            ("cursor_follows_head", "Cursor follows head", "Off: the cursor stays in the room")]
    cv.glass(rx, y, rw, 3 * 92, L.RADIUS_M * 1.6, fill=L.GLASS_RAISED)
    for i, (key, title, sub) in enumerate(rows):
        ry = y + i * 92
        if i:
            cv.fill_round(rx + 24, ry, rw - 48, 1, 0, L.RIM)
        cv.text(rx + 28, ry + 34, title, 22, L.INK)
        cv.text(rx + 28, ry + 64, sub, 16, L.INK_2, max_w=rw - 140)
        cv.switch(rx + rw - 28 - 64, ry + 26, state.get(key), scale=64 / 52)
        items.append((rx, ry, rw, 92, "toggle", key, 0))
    y += 3 * 92 + 34

    def stepper(y, label, value, action):
        cv.glass(rx, y, rw, 84, L.RADIUS_M * 1.6, fill=L.GLASS_RAISED)
        cv.text(rx + 28, y + 42, label, 22, L.INK)
        bx = rx + rw - 28 - 220
        for k, (ic, arg) in enumerate((("minus", -1), ("plus", 1))):
            x = bx if k == 0 else bx + 220 - 52
            cv.glass(x, y + 16, 52, 52, 26, fill=L.GLASS_HOVER)
            cv.icon(ic, x + 26, y + 42, 26, L.INK)
            items.append((x, y + 16, 52, 52, action, arg, 26))
        cv.text(bx + 110, y + 42, value, 22, L.INK, medium=True, align="center")

    cv.text(rx, y, "POINTER AND WINDOW", 16, L.INK_3, medium=True)
    y += 26
    stepper(y, "Cursor speed", f"{state['speed'] * 10}%", "speed")
    y += 96
    stepper(y, "Curve" + ("" if state.get("focus") else " (no window)"), f"{state['curve']}%", "curve")
    y += 84 + 34
    cv.text(rx, y, "SAVED LAYOUTS", 16, L.INK_3, medium=True)
    y += 26
    presets = state["presets"][:3]
    for i, name in enumerate(presets):
        cv.glass(rx, y, rw, 64, L.RADIUS_M * 1.4, fill=L.GLASS_RAISED)
        cv.text(rx + 28, y + 32, name, 20, L.INK)
        cv.icon("next", rx + rw - 36, y + 32, 22, L.INK_2)
        items.append((rx, y, rw, 64, "preset", i, L.RADIUS_M * 1.4))
        y += 74
    cv.stroke_round(rx, y, rw, 64, 32, L.ACCENT, 2.0)
    cv.icon("save", rx + 40, y + 32, 26, L.ACCENT)
    cv.text(rx + 68, y + 32, "Save this layout", 20, L.ACCENT, medium=True)
    items.append((rx, y, rw, 64, "save_preset", None, 32))
    data, w, h = cv.done()
    return CardSpec(data, w, h, items)


def overlay(w, h, r, col, alpha):
    """A rounded hover or press tint for a card item."""
    cv = Canvas(max(2, int(w)), max(2, int(h)))
    cv.fill_round(0, 0, w, h, r, col, alpha)
    return cv.done()
