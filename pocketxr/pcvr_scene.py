"""PC VR's loading room and portal, as Pocket XR on Android draws them (pcvr/PcVrLoading.kt, PcVrRenderer.kt).

The loading room: a calm, dark room with a soft blue horizon that breathes (close to SteamVR's own, so the hand-over
feels like the lights coming up, not a cut), and one card in front of you saying what is happening, with a turning arc,
or a ring filling while the leave button is held. It is fixed in the world; turned well away, the card drifts back.

The portal: PC VR opens as a circle growing from the middle of each eye's view over the live Space, with a soft blue rim,
and closes the same way.
"""
import ctypes
import math

from . import look as L
from . import ui
from .i18n import tr
from .gl import GL_LINEAR, GL_QUADS, GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, gl

CARD_W, CARD_H = 1200, 640
CARD_HALF_TAN = 0.36  # about 40 degrees across
CARD_Y_TAN = -0.03  # a little below eye level
SPIN_Y = 205.0  # the spinner's centre, pixels from the card's top
SLOW_FIND_S = 20.0
FOLLOW_AFTER_RAD = math.radians(35.0)
FOLLOW_RATE = 0.04  # share of the excess turn taken back each frame

PORTAL_OPEN_S = 0.75
PORTAL_CLOSE_S = 0.55

GL_BLEND = 0x0BE2
GL_SRC_ALPHA = 0x0302
GL_ONE_MINUS_SRC_ALPHA = 0x0303
GL_ONE = 1
GL_ZERO = 0

VERT = b"""
#version 120
varying vec2 vUv;
void main() { vUv = gl_MultiTexCoord0.st; gl_Position = gl_Vertex; }
"""

ROOM = b"""
#version 120
varying vec2 vUv;
uniform sampler2D card;
uniform mat3 view;
uniform vec4 tans;
uniform vec2 cardHalf;
uniform float cardY;
uniform vec2 spinAt;
uniform float time;
uniform float alpha;
uniform float progress;
uniform vec4 viewport;
uniform float portal;
uniform float aspect;
void main() {
    vec2 q = ((gl_FragCoord.xy - viewport.xy) / viewport.zw - 0.5) * vec2(aspect, 1.0);
    if (length(q) > portal) discard;
    vec3 d = normalize(view * vec3(mix(tans.x, tans.y, vUv.x), mix(tans.w, tans.z, vUv.y), -1.0));
    float e = d.y;
    // Night sky above, a soft blue horizon that breathes, a dark floor with a faint grid fading away.
    vec3 col = mix(vec3(0.030, 0.050, 0.110), vec3(0.010, 0.014, 0.032), smoothstep(0.0, 0.7, e));
    float breathe = 0.85 + 0.15 * sin(time * 1.2);
    col += vec3(0.08, 0.26, 0.78) * exp(-abs(e) * 9.0) * 0.55 * breathe;
    if (e < -0.002) {
        vec2 p = d.xz * (1.6 / -e) * 0.5;
        vec2 g = abs(fract(p) - 0.5) / max(fwidth(p), vec2(1e-4));
        float line = 1.0 - min(min(g.x, g.y), 1.0);
        col += vec3(0.15, 0.35, 0.80) * line * 0.16 * exp(-length(p) * 0.25);
    }
    if (d.z < -1e-3) {
        vec2 t = d.xy / -d.z;
        vec2 c = vec2((t.x + cardHalf.x) / (2.0 * cardHalf.x), (t.y - cardY + cardHalf.y) / (2.0 * cardHalf.y));
        if (all(greaterThanEqual(c, vec2(0.0))) && all(lessThanEqual(c, vec2(1.0)))) {
            vec4 k = texture2D(card, vec2(c.x, 1.0 - c.y));
            col = mix(col, k.rgb / max(k.a, 1e-4), k.a);
            vec2 s = (c - spinAt) * vec2(cardHalf.x / cardHalf.y, 1.0);
            float r = length(s);
            float band = 1.0 - smoothstep(0.004, 0.010, abs(r - 0.075));
            if (progress < -1.5) {
                // no ring
            } else if (progress < 0.0) {
                // A turning arc: something is happening.
                float a = fract(atan(s.y, s.x) / 6.2831853 + time * 0.7);
                col += vec3(0.45, 0.70, 1.0) * band * smoothstep(0.0, 0.8, a) * k.a;
            } else {
                // A ring filling clockwise from the top: how long is left to hold.
                float a = fract(0.25 - atan(s.y, s.x) / 6.2831853);
                col += mix(vec3(0.16, 0.22, 0.32), vec3(0.45, 0.70, 1.0), step(a, progress)) * band * k.a;
            }
        }
    }
    gl_FragColor = vec4(col, alpha);
}
"""

# The portal's rim: a blue glow at the circle's edge, added on top.
RIM = b"""
#version 120
varying vec2 vUv;
uniform float size;
uniform float radius;
uniform float aspect;
void main() {
    vec2 p = (vUv - 0.5) * vec2(aspect, 1.0);
    float r = length(p);
    float glow = exp(-abs(r - radius) * 38.0) * (1.0 - size * size) * 0.9;
    gl_FragColor = vec4(vec3(0.30, 0.55, 1.0) * glow, 1.0);
}
"""

gl.glGetUniformLocation.restype = ctypes.c_int
gl.glGetUniformLocation.argtypes = [ctypes.c_uint, ctypes.c_char_p]
gl.glUniform1f.argtypes = [ctypes.c_int, ctypes.c_float]
gl.glUniform2f.argtypes = [ctypes.c_int, ctypes.c_float, ctypes.c_float]
gl.glUniform4f.argtypes = [ctypes.c_int] + [ctypes.c_float] * 4
gl.glUniformMatrix3fv.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_ubyte, ctypes.POINTER(ctypes.c_float)]

TITLES = {
    "finding": (tr("Connecting to your PC"), tr("This takes a few seconds.")),
    "finding_slow": (tr("Still looking for your PC"),
                     tr("Check the Pocket XR PC helper is running and both are on the same Wi-Fi.")),
    "starting": (tr("Starting SteamVR"), tr("Almost there.")),
    "reconnecting": (tr("Reconnecting to your PC"), tr("Your game keeps running.")),
    "leaving": (tr("Going back to your Space"), tr("Keep holding, or let go to stay.")),
    "stalled": (tr("Waiting for your PC"), tr("The picture paused. It comes back by itself.")),
}


def ease_out3(t):
    t = max(0.0, min(1.0, t))
    return 1 - (1 - t) ** 3


def portal_radius(size, aspect):
    """The circle's radius in the eye's units (height 1): from nothing to past the view's corners."""
    return size * (0.5 * math.sqrt(aspect * aspect + 1.0) + 0.08)


def _compile(vs, fs, log):
    gl.glCreateShader.restype = ctypes.c_uint
    gl.glCreateProgram.restype = ctypes.c_uint

    def sh(kind, src):
        s = gl.glCreateShader(kind)
        arr = (ctypes.c_char_p * 1)(src)
        gl.glShaderSource(s, 1, arr, None)
        gl.glCompileShader(s)
        ok = ctypes.c_int()
        gl.glGetShaderiv(s, 0x8B81, ctypes.byref(ok))
        if not ok.value:
            buf = ctypes.create_string_buffer(4096)
            gl.glGetShaderInfoLog(s, 4096, None, buf)
            log("pcvr: scene shader: " + buf.value.decode(errors="replace"))
        return s

    p = gl.glCreateProgram()
    gl.glAttachShader(p, sh(0x8B31, vs))
    gl.glAttachShader(p, sh(0x8B30, fs))
    gl.glLinkProgram(p)
    return p


def _wrap(text, size, max_w, medium=False):
    """Splits text into lines no wider than max_w at this size (at most two; the second is cut if need be)."""
    cv = ui.Canvas(8, 8)
    c = cv.c
    ui.cairo.cairo_select_font_face(c, ui.ui_font(medium).encode(), 0, 0)
    ui.cairo.cairo_set_font_size(c, size)
    ext = ui.TextExtents()

    def width(s):
        ui.cairo.cairo_text_extents(c, s.encode("utf-8"), ctypes.byref(ext))
        return ext.x_advance

    if width(text) <= max_w or len(text) < 2:
        cv.done()
        return [text]

    def split(words, sep):
        # two lines of about the same width, so no word is left alone on the second
        best = min(range(1, len(words)), key=lambda i: max(width(sep.join(words[:i])), width(sep.join(words[i:]))))
        return [sep.join(words[:best]).strip(), sep.join(words[best:]).strip()]

    words = text.split()
    lines = split(words, " ") if len(words) >= 2 else None
    cjk = any(ord(ch) >= 0x2E80 for ch in text)
    if cjk and (lines is None or max(width(ln) for ln in lines) > max_w):
        lines = split(list(text), "")  # Japanese and Chinese have no spaces: between any two characters
    cv.done()
    return lines or [text]


def paint_card(title, line, hint=""):
    """Pocket XR's loading card: smoked navy, a light rim, "PC VR" above, the title, a line (two if it is long)
    and, at the foot, how to leave with the Deck's buttons."""
    cv = ui.Canvas(CARD_W, CARD_H)
    cv.rpath(4, 4, CARD_W - 8, CARD_H - 8, 48)
    cv.rgba((12 / 255, 18 / 255, 34 / 255, 225 / 255))
    ui.cairo.cairo_fill_preserve(cv.c)
    cv.rgba((150 / 255, 190 / 255, 255 / 255, 70 / 255))
    ui.cairo.cairo_set_line_width(cv.c, 2.5)
    ui.cairo.cairo_stroke(cv.c)
    cx = CARD_W / 2
    cv.text(cx, 82, "P C   V R", 30, (127 / 255, 168 / 255, 1.0, 1.0), medium=True, align="center")
    cv.text(cx, 352, title, 64, (1, 1, 1, 1), medium=True, align="center", max_w=CARD_W - 80)
    for i, ln in enumerate(_wrap(line, 32, CARD_W - 120)):
        cv.text(cx, 416 + 44 * i, ln, 32, (170 / 255, 180 / 255, 200 / 255, 1.0), align="center", max_w=CARD_W - 80)
    if hint:
        cv.line([(cx - 260, 532), (cx + 260, 532)], (150 / 255, 190 / 255, 1.0, 40 / 255), 1.5)
        cv.text(cx, 578, hint, 26, (127 / 255, 168 / 255, 1.0, 0.85), align="center")
    return cv.done()


class Room:
    """The loading room and the portal's rim. All on the GL thread."""

    def __init__(self, log):
        self.log = log
        self.room = None
        self.rim = None
        self.tex = None
        self.card_key = None
        self.anchor_yaw = None
        self.t0 = None

    def _setup(self):
        self.room = _compile(VERT, ROOM, self.log)
        self.rim = _compile(VERT, RIM, self.log)
        t = ctypes.c_uint()
        gl.glGenTextures(1, ctypes.byref(t))
        gl.glBindTexture(GL_TEXTURE_2D, t)
        gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        self.tex = t.value

    def forget_gl(self):
        self.room = self.rim = self.tex = None
        self.card_key = None

    def _card(self, key):
        if key == self.card_key:
            return
        self.card_key = key
        data, w, h = paint_card(*key)
        title = key[0]
        gl.glBindTexture(GL_TEXTURE_2D, self.tex)
        gl.glTexImage2D(GL_TEXTURE_2D, 0, 0x1908, w, h, 0, 0x80E1, 0x1401, data)  # RGBA from BGRA bytes
        self.log(f"pcvr: loading card: {title}" + (f" ({key[1]})" if key[1] else ""))

    def follow(self, head_q):
        """The card sits where you were looking; turned well away, it eases back in front of you. Yaw only."""
        w, x, y, z = head_q
        fx = -(2 * (x * z + y * w))
        fz = -(1 - 2 * (x * x + y * y))
        yaw = math.atan2(-fx, -fz)
        if self.anchor_yaw is None:
            self.anchor_yaw = yaw
        d = (yaw - self.anchor_yaw + math.pi) % (2 * math.pi) - math.pi
        if abs(d) > FOLLOW_AFTER_RAD:
            self.anchor_yaw += (abs(d) - FOLLOW_AFTER_RAD) * (1 if d > 0 else -1) * FOLLOW_RATE

    def _view(self, head_q):
        """inverse(anchor) * head as a 3x3 matrix, column major: view directions into the card's frame."""
        a = (math.cos(self.anchor_yaw / 2), 0.0, math.sin(self.anchor_yaw / 2), 0.0)
        aw, ax, ay, az = a[0], -a[1], -a[2], -a[3]
        bw, bx, by, bz = head_q
        x = aw * bx + ax * bw + ay * bz - az * by
        y = aw * by - ax * bz + ay * bw + az * bx
        z = aw * bz + ax * by - ay * bx + az * bw
        w = aw * bw - ax * bx - ay * by - az * bz
        return [1 - 2 * (y * y + z * z), 2 * (x * y + z * w), 2 * (x * z - y * w),
                2 * (x * y - z * w), 1 - 2 * (x * x + z * z), 2 * (y * z + x * w),
                2 * (x * z + y * w), 2 * (y * z - x * w), 1 - 2 * (x * x + y * y)]

    @staticmethod
    def _full_quad():
        gl.glMatrixMode(0x1701)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        gl.glMatrixMode(0x1700)
        gl.glPushMatrix()
        gl.glLoadIdentity()
        gl.glBegin(GL_QUADS)
        for (s, t) in ((0, 0), (1, 0), (1, 1), (0, 1)):
            gl.glTexCoord2f(s, t)
            gl.glVertex3f(s * 2 - 1, t * 2 - 1, 0.0)
        gl.glEnd()
        gl.glPopMatrix()
        gl.glMatrixMode(0x1701)
        gl.glPopMatrix()
        gl.glMatrixMode(0x1700)

    def draw(self, now, head_q, tans, viewport, alpha, phase, words=None, progress=-1.0, portal=10.0):
        """The room into the current eye viewport (x, y, w, h), at alpha over what is there, inside the portal."""
        if alpha <= 0.0:
            return
        if self.room is None:
            self._setup()
        if self.t0 is None:
            self.t0 = now
        self._card(tuple(words) if words else TITLES.get(phase, TITLES["finding"]) + ("",))
        p = self.room
        gl.glUseProgram(p)
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        gl.glActiveTexture(0x84C0)
        gl.glBindTexture(GL_TEXTURE_2D, self.tex)
        u = lambda n: gl.glGetUniformLocation(p, n)  # noqa: E731
        gl.glUniform1i(u(b"card"), 0)
        m = (ctypes.c_float * 9)(*self._view(head_q))
        gl.glUniformMatrix3fv(u(b"view"), 1, 0, m)
        gl.glUniform1f(u(b"time"), float(now - self.t0))
        gl.glUniform1f(u(b"alpha"), float(alpha))
        gl.glUniform1f(u(b"progress"), float(progress))
        gl.glUniform2f(u(b"cardHalf"), CARD_HALF_TAN, CARD_HALF_TAN * CARD_H / CARD_W)
        gl.glUniform1f(u(b"cardY"), CARD_Y_TAN)
        gl.glUniform2f(u(b"spinAt"), 0.5, 1.0 - SPIN_Y / CARD_H)
        gl.glUniform4f(u(b"tans"), *tans)
        gl.glUniform4f(u(b"viewport"), *[float(v) for v in viewport])
        gl.glUniform1f(u(b"portal"), float(portal))
        gl.glUniform1f(u(b"aspect"), float(viewport[2]) / max(1.0, float(viewport[3])))
        self._full_quad()
        gl.glUseProgram(0)
        gl.glDisable(GL_BLEND)

    def draw_rim(self, size, viewport):
        """The portal's rim glow over the current eye viewport."""
        if self.rim is None:
            self._setup()
        aspect = float(viewport[2]) / max(1.0, float(viewport[3]))
        p = self.rim
        gl.glUseProgram(p)
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(GL_ONE, GL_ONE)
        gl.glUniform1f(gl.glGetUniformLocation(p, b"size"), float(size))
        gl.glUniform1f(gl.glGetUniformLocation(p, b"radius"), float(portal_radius(size, aspect)))
        gl.glUniform1f(gl.glGetUniformLocation(p, b"aspect"), aspect)
        self._full_quad()
        gl.glUseProgram(0)
        gl.glDisable(GL_BLEND)
