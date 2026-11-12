"""Text and simple shapes for things drawn in space (window titles, buttons, the launcher), with Cairo from SteamOS."""
import ctypes
import ctypes.util

cairo = ctypes.CDLL(ctypes.util.find_library("cairo") or "libcairo.so.2")


class TextExtents(ctypes.Structure):
    _fields_ = [("x_bearing", ctypes.c_double), ("y_bearing", ctypes.c_double), ("width", ctypes.c_double),
                ("height", ctypes.c_double), ("x_advance", ctypes.c_double), ("y_advance", ctypes.c_double)]


FORMAT_ARGB32 = 0
cairo.cairo_image_surface_create.restype = ctypes.c_void_p
cairo.cairo_image_surface_create.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
cairo.cairo_create.restype = ctypes.c_void_p
cairo.cairo_create.argtypes = [ctypes.c_void_p]
for _f in ("cairo_destroy", "cairo_surface_destroy", "cairo_surface_flush", "cairo_paint", "cairo_fill",
           "cairo_new_path", "cairo_close_path"):
    getattr(cairo, _f).argtypes = [ctypes.c_void_p]
cairo.cairo_image_surface_get_data.restype = ctypes.c_void_p
cairo.cairo_image_surface_get_data.argtypes = [ctypes.c_void_p]
cairo.cairo_image_surface_get_stride.argtypes = [ctypes.c_void_p]
cairo.cairo_select_font_face.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int, ctypes.c_int]
cairo.cairo_set_font_size.argtypes = [ctypes.c_void_p, ctypes.c_double]
cairo.cairo_set_source_rgba.argtypes = [ctypes.c_void_p] + [ctypes.c_double] * 4
cairo.cairo_move_to.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
cairo.cairo_show_text.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
cairo.cairo_text_extents.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.POINTER(TextExtents)]
cairo.cairo_arc.argtypes = [ctypes.c_void_p] + [ctypes.c_double] * 5
cairo.cairo_rectangle.argtypes = [ctypes.c_void_p] + [ctypes.c_double] * 4
cairo.cairo_set_line_width.argtypes = [ctypes.c_void_p, ctypes.c_double]
cairo.cairo_stroke.argtypes = [ctypes.c_void_p]

# Inter and Noto Sans have no Korean, Japanese or Chinese, and Cairo's simple text API takes no other font for a
# character its font lacks, so those languages get SteamOS's own Noto Sans CJK for their region (it has Latin too).
CJK_FONTS = {"ko": "Noto Sans CJK KR", "ja": "Noto Sans CJK JP", "zh_CN": "Noto Sans CJK SC", "zh_TW": "Noto Sans CJK TC"}


def ui_font(medium=False, lang=None):
    """The font family for the UI's text in this language: Inter (Pocket XR's look), or Noto Sans CJK."""
    from . import look, i18n
    cjk = CJK_FONTS.get(lang or i18n.lang())
    if cjk:
        return cjk + " Medium" if medium else cjk
    return look.FONT_MEDIUM if medium else look.FONT


def plain_font(lang=None):
    """The font for the simple labels: Noto Sans, or Noto Sans CJK in Korean, Japanese and Chinese."""
    from . import i18n
    return CJK_FONTS.get(lang or i18n.lang(), "Noto Sans")


FONT = plain_font().encode()


def _rounded(cr, x, y, w, h, r):
    import math
    cairo.cairo_new_path(cr)
    cairo.cairo_arc(cr, x + w - r, y + r, r, -math.pi / 2, 0)
    cairo.cairo_arc(cr, x + w - r, y + h - r, r, 0, math.pi / 2)
    cairo.cairo_arc(cr, x + r, y + h - r, r, math.pi / 2, math.pi)
    cairo.cairo_arc(cr, x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cairo.cairo_close_path(cr)


def label(text, size_px=28, fg=(0.89, 0.886, 0.902, 1.0), bg=(0.114, 0.125, 0.141, 0.92), pad=12, radius=10,
          min_w=0, bold=False):
    """A rounded label: (BGRA bytes premultiplied, width, height)."""
    raw = text.encode("utf-8")
    probe = cairo.cairo_image_surface_create(FORMAT_ARGB32, 4, 4)
    pc = cairo.cairo_create(probe)
    cairo.cairo_select_font_face(pc, FONT, 0, 1 if bold else 0)
    cairo.cairo_set_font_size(pc, size_px)
    ext = TextExtents()
    cairo.cairo_text_extents(pc, raw, ctypes.byref(ext))
    cairo.cairo_destroy(pc)
    cairo.cairo_surface_destroy(probe)
    w = max(min_w, int(ext.x_advance + 2 * pad + 0.5))
    h = int(size_px * 1.45 + 2 * pad * 0.5)
    surf = cairo.cairo_image_surface_create(FORMAT_ARGB32, w, h)
    cr = cairo.cairo_create(surf)
    if bg[3] > 0:
        cairo.cairo_set_source_rgba(cr, *bg)
        _rounded(cr, 0, 0, w, h, radius)
        cairo.cairo_fill(cr)
    cairo.cairo_select_font_face(cr, FONT, 0, 1 if bold else 0)
    cairo.cairo_set_font_size(cr, size_px)
    cairo.cairo_set_source_rgba(cr, *fg)
    cairo.cairo_move_to(cr, (w - ext.x_advance) / 2, h / 2 - (ext.y_bearing + ext.height / 2))
    cairo.cairo_show_text(cr, raw)
    cairo.cairo_surface_flush(surf)
    stride = cairo.cairo_image_surface_get_stride(surf)
    data = cairo.cairo_image_surface_get_data(surf)
    out = b"".join(ctypes.string_at(data + y * stride, w * 4) for y in range(h)) if stride != w * 4 \
        else ctypes.string_at(data, w * 4 * h)
    cairo.cairo_destroy(cr)
    cairo.cairo_surface_destroy(surf)
    return out, w, h


cairo.cairo_image_surface_create_from_png.restype = ctypes.c_void_p
cairo.cairo_image_surface_create_from_png.argtypes = [ctypes.c_char_p]
cairo.cairo_image_surface_get_width.argtypes = [ctypes.c_void_p]
cairo.cairo_image_surface_get_height.argtypes = [ctypes.c_void_p]
cairo.cairo_surface_status.argtypes = [ctypes.c_void_p]
cairo.cairo_scale.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
cairo.cairo_set_source_surface.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
cairo.cairo_line_to.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double]
cairo.cairo_set_line_cap.argtypes = [ctypes.c_void_p, ctypes.c_int]


def _take(surf, w, h):
    cairo.cairo_surface_flush(surf)
    stride = cairo.cairo_image_surface_get_stride(surf)
    data = cairo.cairo_image_surface_get_data(surf)
    if stride == w * 4:
        return ctypes.string_at(data, w * 4 * h)
    return b"".join(ctypes.string_at(data + y * stride, w * 4) for y in range(h))


def png(path, size):
    """A PNG scaled into size x size, BGRA premultiplied; None when it cannot be read."""
    src = cairo.cairo_image_surface_create_from_png(path.encode())
    if not src or cairo.cairo_surface_status(src) != 0:
        if src:
            cairo.cairo_surface_destroy(src)
        return None
    sw, sh = cairo.cairo_image_surface_get_width(src), cairo.cairo_image_surface_get_height(src)
    surf = cairo.cairo_image_surface_create(FORMAT_ARGB32, size, size)
    cr = cairo.cairo_create(surf)
    k = size / max(sw, sh)
    cairo.cairo_scale(cr, k, k)
    cairo.cairo_set_source_surface(cr, src, (size / k - sw) / 2, (size / k - sh) / 2)
    cairo.cairo_paint(cr)
    out = _take(surf, size, size)
    cairo.cairo_destroy(cr)
    cairo.cairo_surface_destroy(surf)
    cairo.cairo_surface_destroy(src)
    return out


def letter_tile(text, size, hue=(0.23, 0.48, 1.0)):
    """A round tile with the app's first letter, for apps whose icon is not a PNG."""
    surf = cairo.cairo_image_surface_create(FORMAT_ARGB32, size, size)
    cr = cairo.cairo_create(surf)
    import math
    cairo.cairo_set_source_rgba(cr, hue[0] * 0.55, hue[1] * 0.55, hue[2] * 0.55, 1.0)
    cairo.cairo_arc(cr, size / 2, size / 2, size / 2 - 1, 0, 2 * math.pi)
    cairo.cairo_fill(cr)
    raw = (text[:1] or "?").upper().encode()
    cairo.cairo_select_font_face(cr, FONT, 0, 1)
    cairo.cairo_set_font_size(cr, size * 0.5)
    ext = TextExtents()
    cairo.cairo_text_extents(cr, raw, ctypes.byref(ext))
    cairo.cairo_set_source_rgba(cr, 1, 1, 1, 1)
    cairo.cairo_move_to(cr, (size - ext.x_advance) / 2, size / 2 - (ext.y_bearing + ext.height / 2))
    cairo.cairo_show_text(cr, raw)
    out = _take(surf, size, size)
    cairo.cairo_destroy(cr)
    cairo.cairo_surface_destroy(surf)
    return out


def icon(name, size, fg=(0.89, 0.886, 0.902, 1.0), bg=(0.114, 0.125, 0.141, 0.85), pill_w=None):
    """A window button on a glass capsule: back, move (a grip pill), reset, close, lock. BGRA, (w, h)."""
    import math
    w = pill_w or size
    h = size
    surf = cairo.cairo_image_surface_create(FORMAT_ARGB32, w, h)
    cr = cairo.cairo_create(surf)
    cairo.cairo_set_source_rgba(cr, *bg)
    _rounded(cr, 0, 0, w, h, h / 2)
    cairo.cairo_fill(cr)
    cairo.cairo_set_source_rgba(cr, *fg)
    cairo.cairo_set_line_width(cr, max(2.0, h * 0.09))
    cairo.cairo_set_line_cap(cr, 1)
    c = h / 2
    s = h * 0.22
    if name == "back":
        cairo.cairo_move_to(cr, c + s * 0.5, c - s)
        cairo.cairo_line_to(cr, c - s * 0.5, c)
        cairo.cairo_line_to(cr, c + s * 0.5, c + s)
        cairo.cairo_stroke(cr)
    elif name == "close":
        cairo.cairo_move_to(cr, c - s, c - s)
        cairo.cairo_line_to(cr, c + s, c + s)
        cairo.cairo_move_to(cr, c + s, c - s)
        cairo.cairo_line_to(cr, c - s, c + s)
        cairo.cairo_stroke(cr)
    elif name == "reset":
        cairo.cairo_new_path(cr)
        cairo.cairo_arc(cr, c, c, s, -math.pi * 0.35, math.pi * 1.45)
        cairo.cairo_stroke(cr)
        ax, ay = c + s * math.cos(-math.pi * 0.35), c + s * math.sin(-math.pi * 0.35)
        cairo.cairo_move_to(cr, ax - s * 0.55, ay - s * 0.15)
        cairo.cairo_line_to(cr, ax, ay)
        cairo.cairo_line_to(cr, ax + s * 0.05, ay - s * 0.6)
        cairo.cairo_stroke(cr)
    elif name == "move":
        for i in range(3):
            for j in range(2):
                cairo.cairo_new_path(cr)
                cairo.cairo_arc(cr, w / 2 + (i - 1) * h * 0.2, c + (j - 0.5) * h * 0.2, h * 0.05, 0, 2 * math.pi)
                cairo.cairo_fill(cr)
    elif name == "lock":
        cairo.cairo_rectangle(cr, c - s, c - s * 0.1, 2 * s, s * 1.2)
        cairo.cairo_fill(cr)
        cairo.cairo_new_path(cr)
        cairo.cairo_arc(cr, c, c - s * 0.1, s * 0.6, math.pi, 2 * math.pi)
        cairo.cairo_stroke(cr)
    out = _take(surf, w, h)
    cairo.cairo_destroy(cr)
    cairo.cairo_surface_destroy(surf)
    return out, w, h


def ring(size, fg=(1, 1, 1, 0.95), edge=(0, 0, 0, 0.6)):
    """The space pointer: a ring with a dark edge, BGRA."""
    import math
    surf = cairo.cairo_image_surface_create(FORMAT_ARGB32, size, size)
    cr = cairo.cairo_create(surf)
    c = size / 2
    cairo.cairo_set_source_rgba(cr, *edge)
    cairo.cairo_set_line_width(cr, size * 0.22)
    cairo.cairo_new_path(cr)
    cairo.cairo_arc(cr, c, c, size * 0.32, 0, 2 * math.pi)
    cairo.cairo_stroke(cr)
    cairo.cairo_set_source_rgba(cr, *fg)
    cairo.cairo_set_line_width(cr, size * 0.12)
    cairo.cairo_new_path(cr)
    cairo.cairo_arc(cr, c, c, size * 0.32, 0, 2 * math.pi)
    cairo.cairo_stroke(cr)
    out = _take(surf, size, size)
    cairo.cairo_destroy(cr)
    cairo.cairo_surface_destroy(surf)
    return out
