"""Pocket XR's design tokens ("Light on glass"), the same as core's Look.kt on Android.

The XREAL glasses are see-through: black is the room and only light shows. So surfaces are smoked glass with a
hairline light rim, focus is shown with light (a brighter rim and a faint halo), there is one accent, and a lighter
one for "you are holding this". Red is for Close and Quit only.
"""


def argb(v):
    """0xAARRGGBB to (r, g, b, a) floats."""
    return ((v >> 16) & 255) / 255, ((v >> 8) & 255) / 255, (v & 255) / 255, ((v >> 24) & 255) / 255


def hexrgb(v):
    return "#%06X" % (v & 0xFFFFFF)


GLASS = argb(0xE6141820)
GLASS_RAISED = argb(0xEB1E2330)
GLASS_HOVER = argb(0xF02A3142)
RIM = argb(0x24FFFFFF)
RIM_FOCUS = argb(0x52FFFFFF)
ACCENT = argb(0xFF5A93FF)
ACCENT_DEEP = argb(0xFF3A6FD8)
HELD = argb(0xFF8FB6FF)
HELD_GLASS = argb(0xFF16233D)
DANGER = argb(0xFFE5484D)
INK = argb(0xEBFFFFFF)
INK_2 = argb(0xA3FFFFFF)
INK_3 = argb(0x66FFFFFF)
PAGE = argb(0xFF0C0D10)
PAD = argb(0xFF15171C)
CARD = argb(0xFF1A1D24)

RADIUS_S, RADIUS_M, RADIUS_L = 8.0, 14.0, 20.0
RIM_DP = 1.5
TYPE_CAPTION, TYPE_BODY, TYPE_LABEL, TYPE_TITLE, TYPE_HEADLINE, TYPE_DISPLAY = 12, 14, 16, 20, 28, 40

HOVER_S = 0.120
ENTER_S = 0.280
EXIT_S = 0.160
ENTER_SCALE = 0.98

FONT = "Inter"
FONT_MEDIUM = "Inter Medium"

# The Deck panel (Tk) in the same tokens, as hex strings over the page colour.
TK = {
    "page": "#0C0D10", "pad": "#15171C", "card": "#1A1D24", "raised": "#1E2330", "hover": "#2A3142",
    "rim": "#2A2D33", "rim_focus": "#55585F", "ink": "#EDEDEE", "ink2": "#A5A6A8", "ink3": "#6A6B6E",
    "accent": "#5A93FF", "accent_deep": "#3A6FD8", "held": "#8FB6FF", "danger": "#E5484D",
}


def ease_enter(t):
    """Pocket XR's emphasised ease, cubic-bezier(0.2, 0, 0, 1)."""
    return _bezier(t, 0.2, 0.0, 0.0, 1.0)


def ease_exit(t):
    return _bezier(t, 0.3, 0.0, 1.0, 1.0)


def _bezier(t, x1, y1, x2, y2):
    t = 0.0 if t < 0 else 1.0 if t > 1 else t
    lo, hi = 0.0, 1.0
    for _ in range(24):
        m = (lo + hi) / 2
        x = 3 * (1 - m) ** 2 * m * x1 + 3 * (1 - m) * m * m * x2 + m ** 3
        if x < t:
            lo = m
        else:
            hi = m
    m = (lo + hi) / 2
    return 3 * (1 - m) ** 2 * m * y1 + 3 * (1 - m) * m * m * y2 + m ** 3
