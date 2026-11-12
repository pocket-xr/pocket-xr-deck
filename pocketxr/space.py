"""The Space, as Pocket XR on Android has it: windows around the head, each facing it, with a place, a size, a depth and
a curve; what the space pointer is over; snapping; arrange layouts; presets.

Ported from Pocket XR's PanelLayout, PanelPlacement, WindowSnap, PanelCurve, WindowControls, ArrangeLayouts,
AllWindows and WindowPresets (the numbers are theirs). Angles are degrees, yaw left positive; head axes x right, y up,
z back. A window's size is angular (width and height in degrees), as in Pocket XR.
"""
import json
import math
import os

# PanelLayout / PanelLimits
DEFAULT_DISTANCE = 1.4
DEFAULT_WIDTH_DEG = 40.0
DEFAULT_HEIGHT_DEG = 22.5
MIN_DISTANCE = 0.3
MAX_DISTANCE = 15.0
MIN_SIZE_DEG = 12.0
MAX_WIDTH_DEG = 100.0
MAX_HEIGHT_DEG = 70.0
DEPTH_MIN_SIZE_DEG = 3.0
MAX_PITCH = 70.0
PIXELS_PER_DEGREE = 44
MIN_SIDE_PX, MAX_SIDE_PX = 320, 2560
MAX_TOTAL_PX = (2560, 1440)
# PanelPlacement
STEP_DEG = 2.0
PLACE_GAP_DEG = 2.0
# Frame and handle (PanelInput)
FRAME_INSET_DEG = 0.3
FRAME_DEG = 1.6
CORNER_FRACTION = 0.12
CORNER_EDGE_DEG = 0.3
RESIZE_HOLD_S = 0.150
RESIZE_MOVE_DEG = 1.0
# WindowSnap
SNAP_RANGE_DEG = 4.0
SNAP_ALIGN_RANGE_DEG = 6.0
SNAP_HOLD_DEG = 6.0
SNAP_GAP_DEG = 1.5
BETWEEN_PREFERENCE_DEG = 1.5
FIT_DEPTH_SHARE = 0.15
# PanelCurve
CURVE_MAX = 2.5
CURVE_FLAT_EPS = 0.005
CURVE_EDGE_MAX_DEG = 85.0
CURVE_COLUMNS = 64
# WindowControls
BUTTON_SHARE = 0.07
BUTTON_MIN_PER_M = 0.022
BUTTON_MAX_PER_M = 0.04
BUTTON_GAP = 0.45
BUTTON_SPACING = 0.4
BUTTON_CATCH = 0.5
CONTROLS_STAY_S = 1.8
CONTROLS_FADE_S = 0.7
# Reset: in front at the head's yaw, 0.2 m below the eyes
RESET_DROP_M = 0.2
# Depth (Further/Closer): distance x (1 + 0.03 step)
DEPTH_STEP = 0.03
# Arrange
ARRANGE_TWEEN_S = 0.5
ARRANGE_R = 3.0
ARRANGE_GAP_M = 0.3
ARRANGE_ROW_GAP_M = 0.2
# AllWindows
MAX_SPAN_DEG = 330.0
PRESETS_MAX = 8


def clamp(v, lo, hi):
    return lo if v < lo else hi if v > hi else v


def deg_to_m(deg, d):
    return 2 * d * math.tan(math.radians(deg) / 2)


def m_to_deg(m, d):
    return math.degrees(2 * math.atan(m / 2 / d))


def direction(yaw, pitch):
    y, p = math.radians(yaw), math.radians(pitch)
    return (-math.sin(y) * math.cos(p), math.sin(p), -math.cos(y) * math.cos(p))


def angles(v):
    x, y, z = v
    n = math.sqrt(x * x + y * y + z * z) or 1.0
    return math.degrees(math.atan2(-x, -z)), math.degrees(math.asin(clamp(y / n, -1.0, 1.0)))


def wrap(a):
    return (a + 180.0) % 360.0 - 180.0


class Pose:
    __slots__ = ("yaw", "pitch", "distance", "wdeg", "hdeg", "curve")

    def __init__(self, yaw=0.0, pitch=0.0, distance=DEFAULT_DISTANCE, wdeg=DEFAULT_WIDTH_DEG,
                 hdeg=DEFAULT_HEIGHT_DEG, curve=0.0):
        self.yaw, self.pitch, self.distance, self.wdeg, self.hdeg, self.curve = yaw, pitch, distance, wdeg, hdeg, curve

    def copy(self):
        return Pose(self.yaw, self.pitch, self.distance, self.wdeg, self.hdeg, self.curve)

    def to_json(self):
        return {k: round(getattr(self, k), 3) for k in self.__slots__}

    @staticmethod
    def from_json(d):
        p = Pose()
        for k in Pose.__slots__:
            if k in d:
                setattr(p, k, float(d[k]))
        return p

    @property
    def left(self):
        return self.yaw + self.wdeg / 2

    @property
    def right(self):
        return self.yaw - self.wdeg / 2

    @property
    def top(self):
        return self.pitch + self.hdeg / 2

    @property
    def bottom(self):
        return self.pitch - self.hdeg / 2

    def width_m(self):
        return deg_to_m(self.wdeg, self.distance)

    def height_m(self):
        return deg_to_m(self.hdeg, self.distance)

    def button_deg(self):
        """WindowControls: a button is 7% of the window's height, within 0.022 to 0.04 of the distance."""
        h_m = BUTTON_SHARE * self.height_m()
        h_m = clamp(h_m, BUTTON_MIN_PER_M * self.distance, BUTTON_MAX_PER_M * self.distance)
        return m_to_deg(h_m, self.distance)

    def pixels(self):
        """The app's own size for this window, as Pocket XR: 44 px a degree, each side 320 to 2560, at most 2560x1440."""
        w = clamp(round(self.wdeg * PIXELS_PER_DEGREE), MIN_SIDE_PX, MAX_SIDE_PX)
        h = clamp(round(self.hdeg * PIXELS_PER_DEGREE), MIN_SIDE_PX, MAX_SIDE_PX)
        cap = MAX_TOTAL_PX if w >= h else (MAX_TOTAL_PX[1], MAX_TOTAL_PX[0])
        k = min(1.0, cap[0] / w, cap[1] / h)
        return int(w * k), int(h * k)


# ---------------- curve (PanelCurve) ----------------
def max_curve(wdeg):
    a = math.radians(wdeg / 2)
    if a <= 0:
        return CURVE_MAX
    return min(CURVE_MAX, 1 + math.sin(math.radians(CURVE_EDGE_MAX_DEG) - a) / math.sin(a))


def curve_geometry(p):
    """(R, fc, phi_edge): cylinder radius, its centre's distance ahead (along the window's forward), and the
    cylinder angle of each edge so it is seen at half the width from the centre. None when flat."""
    c = min(p.curve, max_curve(p.wdeg))
    if c <= CURVE_FLAT_EPS:
        return None
    R = p.distance / c
    fc = p.distance - R
    a = math.radians(p.wdeg / 2)
    lo, hi = 0.0, math.pi - 1e-3
    for _ in range(40):
        m = (lo + hi) / 2
        seen = math.atan2(R * math.sin(m), fc + R * math.cos(m))
        if seen < a:
            lo = m
        else:
            hi = m
    return R, fc, lo


def column(p, u, geo=None):
    """Local (x, forward) of the point u (0 left .. 1 right) across the window."""
    if geo is None:
        geo = curve_geometry(p)
    if geo is None:
        w = deg_to_m(p.wdeg, p.distance)
        return (u - 0.5) * w, p.distance
    R, fc, pe = geo
    phi = (u - 0.5) * 2 * pe
    return R * math.sin(phi), fc + R * math.cos(phi)


# ---------------- hit testing ----------------
def to_local(p, ray):
    """The ray in the window's own frame: x right, y up, f forward (towards the window)."""
    x, y, z = ray
    yr = math.radians(p.yaw)
    # undo yaw (about y)
    x1 = x * math.cos(yr) - z * math.sin(yr)
    z1 = x * math.sin(yr) + z * math.cos(yr)
    pr = math.radians(p.pitch)
    # undo pitch (about x)
    y2 = y * math.cos(pr) + z1 * math.sin(pr)
    z2 = -y * math.sin(pr) + z1 * math.cos(pr)
    return x1, y2, -z2


def surface_uv(p, ray):
    """(u, v, depth m) where the ray meets the window's surface (extended past its edges), or None."""
    x, y, f = to_local(p, ray)
    if f <= 1e-6:
        return None
    geo = curve_geometry(p)
    h = deg_to_m(p.hdeg, p.distance)
    if geo is None:
        t = p.distance / f
        u = x * t / deg_to_m(p.wdeg, p.distance) + 0.5
    else:
        R, fc, pe = geo
        # |t (x, f) - (0, fc)| = R, larger root
        a = x * x + f * f
        b = -2 * f * fc
        cc = fc * fc - R * R
        disc = b * b - 4 * a * cc
        if disc < 0:
            return None
        t = (-b + math.sqrt(disc)) / (2 * a)
        phi = math.atan2(x * t, f * t - fc)
        u = phi / (2 * pe) + 0.5
    yy = y * t
    v = 0.5 - yy / h
    depth = t * math.sqrt(x * x + y * y + f * f)
    return u, v, depth


# Zones, as PanelZone
BODY, FRAME, HANDLE, BUTTON = "body", "frame", "handle", "button"
BUTTONS_ABOVE = ("back", "move", "reset", "close")


def buttons(p, app=True):
    """The button row above the window: [(name, u0, u1)] in u, with the row's v range, from WindowControls."""
    hb = p.button_deg()
    row_v1 = -(BUTTON_GAP * hb) / p.hdeg
    row_v0 = row_v1 - hb / p.hdeg
    du = hb / p.wdeg
    out = [("back", 0.0, du)] if app else []
    pill = max(0.3 * p.wdeg, 3 * hb) / p.wdeg
    out.append(("move", 0.5 - pill / 2, 0.5 + pill / 2))
    x = 1.0
    for name in ("close", "reset"):
        out.append((name, x - du, x))
        x -= du + BUTTON_SPACING * du
    return out, row_v0, row_v1


def zone(p, u, v, locked=False, app=True):
    """What part of the window (u, v) is: (zone, name or None)."""
    hb = p.button_deg()
    catch_u, catch_v = BUTTON_CATCH * hb / p.wdeg, BUTTON_CATCH * hb / p.hdeg
    btns, v0, v1 = buttons(p, app)
    if v0 - catch_v <= v <= v1 + catch_v:
        for name, u0, u1 in btns:
            if u0 - catch_u <= u <= u1 + catch_u:
                if locked and name in ("move", "reset"):
                    return None, None
                return BUTTON, name
    # resize handle: near the bottom right corner, outside the window plus 0.3 deg inside its edge
    c = CORNER_FRACTION * min(p.wdeg, p.hdeg)
    du_in, dv_in = CORNER_EDGE_DEG / p.wdeg, CORNER_EDGE_DEG / p.hdeg
    if not locked and 1 - c / p.wdeg <= u <= 1 + (FRAME_INSET_DEG + FRAME_DEG) / p.wdeg and \
            1 - c / p.hdeg <= v <= 1 + (FRAME_INSET_DEG + FRAME_DEG) / p.hdeg and (u >= 1 - du_in or v >= 1 - dv_in):
        return HANDLE, None
    if 0 <= u <= 1 and 0 <= v <= 1:
        return BODY, None
    # clicks still land within 0.3 deg outside the body
    iu, iv = FRAME_INSET_DEG / p.wdeg, FRAME_INSET_DEG / p.hdeg
    if -iu <= u <= 1 + iu and -iv <= v <= 1 + iv:
        return BODY, None
    ou, ov = (FRAME_INSET_DEG + FRAME_DEG) / p.wdeg, (FRAME_INSET_DEG + FRAME_DEG) / p.hdeg
    if -ou <= u <= 1 + ou and -ov <= v <= 1 + ov and v >= v1 + catch_v:
        return (None, None) if locked else (FRAME, None)
    return None, None


# ---------------- placing a new window (PanelPlacement) ----------------
def overlaps(a, b, gap=PLACE_GAP_DEG):
    return abs(wrap(a.yaw - b.yaw)) < (a.wdeg + b.wdeg) / 2 + gap and abs(a.pitch - b.pitch) < (a.hdeg + b.hdeg) / 2 + gap


def place_new(others, wdeg, hdeg, yaw, pitch=0.0, distance=DEFAULT_DISTANCE, curve=0.0):
    """At yaw (pitch 0) if clear; else step sideways 2 deg at a time, right first, out to 180; else other rows."""
    rows = [0, 1, -1, 2, -2]
    row_h = hdeg + 2 * (BUTTON_GAP + 1) * Pose(0, 0, distance, wdeg, hdeg).button_deg() + 2.0
    for r in rows:
        pt = clamp(pitch + r * row_h, -MAX_PITCH, MAX_PITCH)
        k = 0
        while k * STEP_DEG <= 180:
            for s in ((0,) if k == 0 else (-1, 1)):  # right (negative yaw) first
                cand = Pose(wrap(yaw + s * k * STEP_DEG), pt, distance, wdeg, hdeg, curve)
                if not any(overlaps(cand, o) for o in others):
                    return cand
            k += 1
    return Pose(yaw, pitch, distance, wdeg, hdeg, curve)


# ---------------- snap (WindowSnap) ----------------
def _cands_h(p, q, slack):
    out = [("left", q.left - p.wdeg / 2), ("right", q.right + p.wdeg / 2), ("centre", q.yaw)]
    if abs(p.pitch - q.pitch) < (p.hdeg + q.hdeg) / 2 + slack:  # side by side
        out += [("dock-left", q.left + SNAP_GAP_DEG + p.wdeg / 2), ("dock-right", q.right - SNAP_GAP_DEG - p.wdeg / 2)]
    return out


def _cands_v(p, q, slack):
    out = [("top", q.top - p.hdeg / 2), ("bottom", q.bottom + p.hdeg / 2), ("middle", q.pitch)]
    if abs(wrap(p.yaw - q.yaw)) < (p.wdeg + q.wdeg) / 2 + slack:  # same column
        out += [("above", q.top + SNAP_GAP_DEG + p.hdeg / 2), ("below", q.bottom - SNAP_GAP_DEG - p.hdeg / 2)]
    return out


def snap(p, others, partner=None):
    """The snapped (yaw, pitch, partner index, fit size or None) for p among others (a list of Poses)."""
    best = None
    for i, q in enumerate(others):
        held = i == partner
        rh = SNAP_HOLD_DEG if held else SNAP_RANGE_DEG
        rv = SNAP_HOLD_DEG if held else SNAP_ALIGN_RANGE_DEG
        h = min(((abs(wrap(p.yaw - t)), t) for _, t in _cands_h(p, q, rv)), default=None)
        v = min(((abs(p.pitch - t), t) for _, t in _cands_v(p, q, rv)), default=None)
        hs = h if h and h[0] < rh else None
        vs = v if v and v[0] < rv else None
        if not hs and not vs:
            continue
        score = (hs[0] if hs else rh) + (vs[0] if vs else rv) - (0.5 if held else 0.0)
        if best is None or score < best[0]:
            best = (score, i, hs, vs)
    yaw, pitch, part = p.yaw, p.pitch, None
    h_snapped = False
    if best:
        _, part, hs, vs = best
        if hs:
            yaw = hs[1]
            h_snapped = True
        if vs:
            pitch = vs[1]
        # an axis the partner did not settle may snap to any other window within range
        if not hs or not vs:
            for i, q in enumerate(others):
                if i == part:
                    continue
                if not hs:
                    h = min(((abs(wrap(p.yaw - t)), t) for _, t in _cands_h(p, q, SNAP_RANGE_DEG)))
                    if h[0] < SNAP_RANGE_DEG:
                        yaw, hs = h[1], h
                        h_snapped = True
                if not vs:
                    v = min(((abs(p.pitch - t), t) for _, t in _cands_v(p, q, SNAP_RANGE_DEG)))
                    if v[0] < SNAP_RANGE_DEG:
                        pitch, vs = v[1], v
    fit = None
    # between two windows level with p, its centre in the gap
    level = [q for q in others if abs(q.pitch - p.pitch) < (q.hdeg + p.hdeg) / 2]
    for a in level:
        for b in level:
            if a is b or a.right <= b.left:
                continue
            gap_l, gap_r = a.right, b.left  # a on the left (higher yaw), b on the right
            if not (gap_r < p.yaw < gap_l):
                continue
            centre = (gap_l + gap_r) / 2
            d_between = abs(p.yaw - centre)
            d_dock = abs(p.yaw - yaw) if h_snapped else 1e9
            if d_between < SNAP_RANGE_DEG * 2 and (not best or d_dock + BETWEEN_PREFERENCE_DEG >= d_between):
                yaw = centre
                ds = [a.distance, b.distance, p.distance]
                if max(ds) <= min(ds) * (1 + FIT_DEPTH_SHARE):
                    fw = (gap_l - gap_r) - 2 * SNAP_GAP_DEG
                    fh = a.hdeg if abs(a.hdeg - b.hdeg) <= 1.0 else None
                    if fw >= MIN_SIZE_DEG:
                        fit = (fw, fh)
                        pitch = (a.pitch + b.pitch) / 2 if fh else pitch
    return yaw, clamp(pitch, -MAX_PITCH, MAX_PITCH), part, fit


# ---------------- arrange layouts (ArrangeLayouts) ----------------
def layout_choices(n):
    if n <= 1:
        return ["Center", "Theater"]
    if n == 2:
        return ["Side by side", "Main + side", "Stacked", "Circle"]
    if n == 3:
        return ["Three across", "Main + two stacked", "Focus center", "Circle"]
    if n == 4:
        return ["2x2 grid", "Main + three stacked", "Main + strip below", "Four across", "Circle"]
    return ["Grid", "Main + strip below", "Focus center", "Main + column", "All around you", "Circle"]


def _shape(p):
    return p.hdeg and deg_to_m(p.hdeg, p.distance) / max(1e-3, deg_to_m(p.wdeg, p.distance)) or 0.5625


def _put(p, yaw, pitch, dist, width_m, shape):
    q = p.copy()
    q.distance = dist
    q.wdeg = clamp(m_to_deg(width_m, dist), DEPTH_MIN_SIZE_DEG, MAX_WIDTH_DEG)
    q.hdeg = clamp(m_to_deg(width_m * shape, dist), DEPTH_MIN_SIZE_DEG, MAX_HEIGHT_DEG)
    q.yaw, q.pitch = wrap(yaw), clamp(pitch, -MAX_PITCH, MAX_PITCH)
    return q


def _row(items, yaw0, pitch, R, widths, shapes):
    """Windows in a row on a cylinder of radius R, centred at yaw0, gaps ARRANGE_GAP_M."""
    total = sum(widths) + ARRANGE_GAP_M * (len(widths) - 1)
    x = total / 2
    out = []
    for p, w, s in zip(items, widths, shapes):
        c = x - w / 2
        out.append(_put(p, yaw0 + math.degrees(c / R), pitch, R, w, s))
        x -= w + ARRANGE_GAP_M
    return out


def arrange(name, poses, main_index, head_yaw):
    """New poses for the windows (in the given left-to-right order), the main window first decided by main_index."""
    n = len(poses)
    if n == 0:
        return []
    shapes = [_shape(p) for p in poses]
    order = list(range(n))
    main = order.pop(main_index)
    R = ARRANGE_R
    res = [None] * n

    def pitch_of(y_m, r=R):
        return math.degrees(math.atan2(y_m, r))

    if name in ("Center", "Theater"):
        d, w = (2.6, 2.0) if name == "Center" else (5.0, 4.2)
        res[main] = _put(poses[main], head_yaw, 0, d, w, shapes[main])
        for k, i in enumerate(order):
            res[i] = _put(poses[i], head_yaw + (k + 1) * 40, 0, d, w * 0.5, shapes[i])
        return res
    if name in ("Side by side", "Three across", "Four across"):
        widths_by_n = {1: 1.6, 2: 1.4, 3: 1.1, 4: 0.95}
        w = widths_by_n.get(n, 0.8)
        seq = order[:len(order) // 2] + [main] + order[len(order) // 2:]
        row = _row([poses[i] for i in seq], head_yaw, 0, R, [w] * n, [shapes[i] for i in seq])
        for i, q in zip(seq, row):
            res[i] = q
        return res
    if name == "Stacked":
        w = 1.3
        heights = [w * s for s in shapes]
        seq = [main] + order
        total = sum(heights[i] for i in seq) + ARRANGE_ROW_GAP_M * (n - 1)
        y = total / 2
        for i in seq:
            hh = heights[i]
            res[i] = _put(poses[i], head_yaw, pitch_of(y - hh / 2), R, w, shapes[i])
            y -= hh + ARRANGE_ROW_GAP_M
        return res
    if name in ("Main + side", "Main + two stacked", "Main + three stacked", "Main + column"):
        mw = 1.8
        side_w = {1: 1.0, 2: 0.9, 3: 0.75}.get(len(order), 0.6)
        total = mw + ARRANGE_GAP_M + side_w
        mc = total / 2 - mw / 2
        sc = total / 2 - mw - ARRANGE_GAP_M - side_w / 2
        res[main] = _put(poses[main], head_yaw + math.degrees(mc / R), 0, R, mw, shapes[main])
        heights = [side_w * shapes[i] for i in order]
        tot_h = sum(heights) + ARRANGE_ROW_GAP_M * (len(order) - 1)
        y = tot_h / 2
        for i, hh in zip(order, heights):
            res[i] = _put(poses[i], head_yaw + math.degrees(sc / R), pitch_of(y - hh / 2), R, side_w, shapes[i])
            y -= hh + ARRANGE_ROW_GAP_M
        return res
    if name in ("Grid", "2x2 grid"):
        cols = math.ceil(math.sqrt(n))
        w = 1.0 if cols > 2 else 1.25
        seq = [main] + order
        rows = math.ceil(n / cols)
        row_h = max(w * s for s in shapes)
        y = (rows * row_h + (rows - 1) * ARRANGE_ROW_GAP_M) / 2 - row_h / 2
        for r in range(rows):
            items = seq[r * cols:(r + 1) * cols]
            row = _row([poses[i] for i in items], head_yaw, pitch_of(y), R, [w] * len(items), [shapes[i] for i in items])
            for i, q in zip(items, row):
                res[i] = q
            y -= row_h + ARRANGE_ROW_GAP_M
        return res
    if name == "Main + strip below":
        mw = 1.8
        sw = 0.8 if len(order) <= 3 else 0.65
        mh = mw * shapes[main]
        sh = max(sw * shapes[i] for i in order) if order else 0
        total = mh + ARRANGE_ROW_GAP_M + sh
        res[main] = _put(poses[main], head_yaw, pitch_of(total / 2 - mh / 2), R, mw, shapes[main])
        row = _row([poses[i] for i in order], head_yaw, pitch_of(total / 2 - mh - ARRANGE_ROW_GAP_M - sh / 2), R,
                   [sw] * len(order), [shapes[i] for i in order])
        for i, q in zip(order, row):
            res[i] = q
        return res
    if name == "All around you":
        r = 2.5
        step = 360.0 / n
        seq = [main] + order
        w = min(1.6, deg_to_m(step - 8, r))
        for k, i in enumerate(seq):
            s = 0 if k == 0 else ((k + 1) // 2) * (-1 if k % 2 else 1)  # right, then left
            res[i] = _put(poses[i], head_yaw + s * step, 0, r, w, shapes[i])
        return res
    if name in ("Circle", "Focus center"):
        base = 1.43 / 1.4
        mw = 1.4 * base
        res[main] = _put(poses[main], head_yaw, 0, R, mw, shapes[main])
        right_x, left_x = mw / 2, mw / 2
        for k, i in enumerate(order):
            w = base
            if k % 2 == 0:
                c = right_x + ARRANGE_GAP_M + w / 2
                right_x = c + w / 2
                res[i] = _put(poses[i], head_yaw - math.degrees(c / R), 0, R, w, shapes[i])
            else:
                c = left_x + ARRANGE_GAP_M + w / 2
                left_x = c + w / 2
                res[i] = _put(poses[i], head_yaw + math.degrees(c / R), 0, R, w, shapes[i])
        return res
    return [p.copy() for p in poses]


def ease(t):
    t = clamp(t, 0.0, 1.0)
    return 1 - (1 - t) * (1 - t)


def blend(a, b, t):
    q = a.copy()
    for k in Pose.__slots__:
        va, vb = getattr(a, k), getattr(b, k)
        if k == "yaw":
            setattr(q, k, va + wrap(vb - va) * t)
        else:
            setattr(q, k, va + (vb - va) * t)
    return q


# ---------------- Adjust all (AllWindows) ----------------
def adjust_all(poses, dyaw=0.0, dpitch=0.0, dist_factor=1.0, size_factor=1.0):
    """Every window as one group: turn, push or pull, resize; stops as a whole at the first limit."""
    if not poses:
        return poses
    cy = sum(p.yaw for p in poses) / len(poses)
    cp = sum(p.pitch for p in poses) / len(poses)
    dists = [p.distance * dist_factor for p in poses]
    if min(dists) < MIN_DISTANCE or max(dists) > MAX_DISTANCE:
        dist_factor = 1.0
    k = size_factor / dist_factor
    out = []
    for p in poses:
        q = p.copy()
        q.distance = p.distance * dist_factor
        q.wdeg = p.wdeg * k
        q.hdeg = p.hdeg * k
        q.yaw = wrap(cy + wrap(p.yaw - cy) * k + dyaw)
        q.pitch = cp + (p.pitch - cp) * k + dpitch
        out.append(q)
    ok = all(DEPTH_MIN_SIZE_DEG <= q.wdeg <= MAX_WIDTH_DEG and DEPTH_MIN_SIZE_DEG <= q.hdeg <= MAX_HEIGHT_DEG and
             q.top <= MAX_PITCH and q.bottom >= -MAX_PITCH for q in out)
    span = max(q.left for q in out) - min(q.right for q in out)
    if not ok or span > MAX_SPAN_DEG:
        return poses
    return out


# ---------------- presets and saved places ----------------
class Store:
    """Saved places per app (so an app comes back where it was) and up to 8 named presets, as WindowPresets."""

    def __init__(self, path):
        self.path = path
        self.apps = {}
        self.presets = []  # [{"name": str, "windows": [{"app": cls, "pose": {...}}]}], newest first
        try:
            with open(path) as f:
                d = json.load(f)
            self.apps = d.get("apps", {})
            self.presets = d.get("presets", [])[:PRESETS_MAX]
        except (OSError, ValueError):
            pass

    def save(self):
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"apps": self.apps, "presets": self.presets}, f, indent=1)
        os.replace(tmp, self.path)

    def remember(self, cls, pose):
        if cls:
            self.apps[cls] = pose.to_json()

    def add_preset(self, windows):
        n = 1
        names = {p["name"] for p in self.presets}
        while f"Workspace {n}" in names:
            n += 1
        self.presets.insert(0, {"name": f"Workspace {n}", "windows": windows})
        del self.presets[PRESETS_MAX:]
        self.save()
        return f"Workspace {n}"
