"""Head orientation from gyro and accelerometer: a small complementary filter.

Head axes are x right, y up, z back (OpenGL's). The Aura's sensor already uses them; the One
family is "x right, y down, z front" (Pocket XR's AxisMap), so its y and z are negated.
"""
import json
import math
import os
import threading
import time

AXES = {
    "aura": (1.0, 1.0, 1.0),
    "one": (1.0, -1.0, -1.0),
}


def qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (
        aw * bw - ax * bx - ay * by - az * bz,
        aw * bx + ax * bw + ay * bz - az * by,
        aw * by - ax * bz + ay * bw + az * bx,
        aw * bz + ax * by - ay * bx + az * bw,
    )


def qconj(q):
    return (q[0], -q[1], -q[2], -q[3])


def qnorm(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def qrot(q, v):
    """v rotated by q."""
    p = qmul(qmul(q, (0.0, v[0], v[1], v[2])), qconj(q))
    return p[1:]


def yaw_of(q):
    """Turn about the world's up axis, radians."""
    fwd = qrot(q, (0.0, 0.0, -1.0))
    return math.atan2(-fwd[0], -fwd[2])


def about_y(angle):
    return (math.cos(angle / 2), 0.0, math.sin(angle / 2), 0.0)


BIAS_FILE = os.path.expanduser("~/.config/pocket-xr-deck/gyro-bias.json")


def load_bias(key, path=None):
    """The gyro bias a calibration saved for these glasses ("vendor:product"), radians a second, or None."""
    try:
        with open(path or BIAS_FILE) as f:
            b = json.load(f).get(key, {}).get("bias")
        return [float(x) for x in b] if b and len(b) == 3 else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def save_bias(key, bias, path=None):
    path = path or BIAS_FILE
    try:
        with open(path) as f:
            d = json.load(f)
        if not isinstance(d, dict):
            d = {}
    except (OSError, ValueError):
        d = {}
    d[key] = {"bias": [round(float(x), 7) for x in bias], "saved": time.strftime("%Y-%m-%d %H:%M:%S")}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(d, f, indent=1)
    os.replace(tmp, path)


def about_x(angle):
    """Positive turns the forward (0, 0, -1) up."""
    return (math.cos(angle / 2), math.sin(angle / 2), 0.0, 0.0)


def matrix(q):
    """Column-major 4x4 rotation for OpenGL."""
    w, x, y, z = q
    return [
        1 - 2 * (y * y + z * z), 2 * (x * y + w * z), 2 * (x * z - w * y), 0.0,
        2 * (x * y - w * z), 1 - 2 * (x * x + z * z), 2 * (y * z + w * x), 0.0,
        2 * (x * z + w * y), 2 * (y * z - w * x), 1 - 2 * (x * x + y * y), 0.0,
        0.0, 0.0, 0.0, 1.0,
    ]


class HeadFusion:
    """Gyro integration, tilt pulled toward gravity, gyro bias from the first still seconds."""

    KP = 1.0  # how hard tilt follows gravity, 1/s
    REST_BLOCK = 500  # reports, half a second at 1 kHz
    # Mike, 12 Nov 2026: the windows sometimes moved far to the right. A worn head turning slowly and smoothly passed
    # the old test (one quiet half second, mean under 3 deg/s) and was learnt as bias: -1.4 deg/s on the yaw axis once,
    # which turns the Space about 80 degrees a minute. The Aura's stream is already near zero at rest (under 0.5 deg/s),
    # so the bias is now learnt only from two seconds of real stillness: four quiet half seconds in a row, each axis's
    # mean under 1 deg/s and its spread under 0.6 deg/s.
    REST_SD = math.radians(0.6)
    REST_MAX = math.radians(1.0)  # the Aura; glasses whose stream is not calibrated on board keep 3 deg/s
    REST_MAX_OTHER = math.radians(3.0)
    REST_RUN = 4
    REST_GAIN = 0.5
    # The first stillness used to recentre too, whenever it came; worn, that could be minutes in, and the windows
    # jumped to wherever the head faced then. Now only in the first seconds after the stream starts.
    FIRST_RECENTRE_S = 5.0
    # A recentre you ask for takes the head's pitch as straight ahead too, whatever it is, so the screen comes to where
    # you look, lying back or at a desk below you (as Pocket XR for Mac's recentreFollowsTilt). Never the roll: the
    # picture stays level. Looking nearly straight up or down, the heading comes from the head's right side. A tester
    # (Pierre Zammit, 22 Nov 2026) could not bring the picture in front lying down: recentre zeroed only the heading
    # ("recentred", then "pitch 16.6 degrees"). 0.7.1 took the pitch only past 15 degrees, and with it he found that
    # recentre still moved the screen only sideways; most of his recentres were near level.
    NEAR_VERTICAL_DEG = 80.0
    # Hold-still calibration (Quick Access): the glasses lie still for CAL_S and the gyro's mean becomes its bias,
    # saved for those glasses (BIAS_FILE). The automatic learning above keeps refining it. Taken only if nothing moved:
    # each axis spread under CAL_SD and mean under CAL_MAX. A tester's XBX A01+ drifted about 0.1 deg/s to the right
    # while worn and still (22 Nov 2026), after the automatic learning.
    CAL_S = 4.0
    CAL_SD = math.radians(2.0)
    CAL_MAX = math.radians(5.0)
    CAL_MIN_REPORTS = 200

    def __init__(self, axes="aura", bias=None):
        self.sign = AXES[axes]
        self.rest_max = self.REST_MAX if axes == "aura" else self.REST_MAX_OTHER
        self.lock = threading.Lock()
        self.q = (1.0, 0.0, 0.0, 0.0)  # world from head
        self.ref = (1.0, 0.0, 0.0, 0.0)  # recentre
        self.last_ts = None
        self.bias = [0.0, 0.0, 0.0]
        self.bias_sum = [0.0, 0.0, 0.0]
        self.bias_sq = [0.0, 0.0, 0.0]
        self.bias_n = 0
        self.bias_ready = False  # true after the first quiet half second
        self.rest_blocks = 0
        self.rest_run = []  # the quiet half seconds in a row so far: their means
        self.first_ts = None
        self.g_mag = None
        self.count = 0
        self.want_recentre = True
        self.recentre_yaw = 0.0  # radians the view is turned at a recentre: the windows' middle in front
        self.ref_pitch = 0.0  # radians up that count as straight ahead, from the last recentre that took the tilt
        self.recentre_sets_tilt = False
        self.recentre_follows_tilt = False
        self.last_gyro = (0.0, 0.0, 0.0)
        self.cal = None  # while a hold-still calibration runs: its sums
        self.cal_result = None  # ("ok", mean deg/s, spread deg/s) or ("moved", mean, spread), once one has ended
        if bias is not None and len(bias) == 3:
            # Saved by a calibration: used from the start, and refined by the stillness learning as usual
            self.bias = [float(b) for b in bias]
            self.bias_ready = True

    def _axes(self, v):
        return (v[0] * self.sign[0], v[1] * self.sign[1], v[2] * self.sign[2])

    def report(self, ts_ns, gyro, accel):
        g = self._axes(gyro)
        a = self._axes(accel)
        with self.lock:
            self.count += 1
            if self.last_ts is None:
                self.last_ts = ts_ns
                self.first_ts = ts_ns
                self._level_from(a)
                return
            dt = (ts_ns - self.last_ts) / 1e9
            self.last_ts = ts_ns
            if not (0.0 < dt < 0.05):
                return
            an = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
            self.g_mag = an if self.g_mag is None else 0.999 * self.g_mag + 0.001 * an
            if self.cal is not None:
                self._calibrate_step(g, ts_ns)
            self._rest_block(g, ts_ns)
            w = [g[i] - self.bias[i] for i in range(3)]
            self.last_gyro = tuple(w)
            # Tilt: the accelerometer reads the reaction to gravity, "up", in head axes.
            if an > 0 and self.g_mag and abs(an / self.g_mag - 1.0) < 0.1:
                up_est = qrot(qconj(self.q), (0.0, 1.0, 0.0))
                am = (a[0] / an, a[1] / an, a[2] / an)
                e = (
                    am[1] * up_est[2] - am[2] * up_est[1],
                    am[2] * up_est[0] - am[0] * up_est[2],
                    am[0] * up_est[1] - am[1] * up_est[0],
                )
                for i in range(3):
                    w[i] += self.KP * e[i]
            half = 0.5 * dt
            dq = (1.0, w[0] * half, w[1] * half, w[2] * half)
            self.q = qnorm(qmul(self.q, dq))
            if self.want_recentre:
                self._apply_recentre()
                self.want_recentre = False

    def _apply_recentre(self):
        """The heading straight ahead (the lock is held); with a recentre that follows the tilt, the head's pitch too.
        The fusion's own recentres keep the pitch the last one took."""
        f = qrot(self.q, (0.0, 0.0, -1.0))
        head_pitch = math.asin(max(-1.0, min(1.0, f[1])))
        if self.recentre_sets_tilt:
            self.ref_pitch = head_pitch if self.recentre_follows_tilt else 0.0
            self.recentre_sets_tilt = False
        yaw = yaw_of(self.q)
        if abs(head_pitch) >= math.radians(self.NEAR_VERTICAL_DEG):
            r = qrot(self.q, (1.0, 0.0, 0.0))  # up x right: where the head faces along the floor
            if math.hypot(r[0], r[2]) >= 0.2:
                yaw = math.atan2(-r[2], r[0])
        if self.ref_pitch == 0.0:
            self.ref = about_y(yaw - self.recentre_yaw)
        else:
            # the heading, then the pitch, then the windows' middle turn about the level up axis: the view at the
            # recentre is that turn alone, level
            self.ref = qnorm(qmul(qmul(about_y(yaw), about_x(self.ref_pitch)), about_y(-self.recentre_yaw)))

    def _rest_block(self, g, ts_ns):
        """
        The bias is learnt only from half seconds where the gyro is truly quiet, at start and all
        the time after. Measured on the Aura (11 Nov 2026): at rest its stream is already close to
        zero (under 0.5 deg/s) with about 0.3 deg/s of noise; a worn, still head is under 1 deg/s.
        The first version averaged the first 1.5 s whatever the head did, learnt a few deg/s of
        head turn as bias, and the window crept sideways about 3 deg/s.
        """
        for i in range(3):
            self.bias_sum[i] += g[i]
            self.bias_sq[i] += g[i] * g[i]
        self.bias_n += 1
        if self.bias_n < self.REST_BLOCK:
            return
        n = self.bias_n
        mean = [s / n for s in self.bias_sum]
        sd = [math.sqrt(max(0.0, q / n - m * m)) for q, m in zip(self.bias_sq, mean)]
        self.bias_sum = [0.0, 0.0, 0.0]
        self.bias_sq = [0.0, 0.0, 0.0]
        self.bias_n = 0
        if not (max(sd) < self.REST_SD and all(abs(m) < self.rest_max for m in mean)):
            self.rest_run = []
            return
        self.rest_run.append(mean)
        if len(self.rest_run) < self.REST_RUN:
            return
        run_mean = [sum(m[i] for m in self.rest_run) / len(self.rest_run) for i in range(3)]
        self.rest_run = []
        gain = self.REST_GAIN if self.bias_ready else 1.0  # two still seconds: the first is taken as it is
        for i in range(3):
            self.bias[i] += gain * (run_mean[i] - self.bias[i])
        self.rest_blocks += 1
        if not self.bias_ready:
            self.bias_ready = True
            if (ts_ns - self.first_ts) / 1e9 < self.FIRST_RECENTRE_S:
                self.want_recentre = True

    def _level_from(self, a):
        """Start with tilt from gravity, yaw zero."""
        n = math.sqrt(sum(c * c for c in a))
        if n == 0:
            return
        up = (a[0] / n, a[1] / n, a[2] / n)
        # Rotation taking head "up" (a) to world up (0, 1, 0).
        c = up[1]
        axis = (-up[2], 0.0, up[0])  # up x (0,1,0)
        s = math.sqrt(axis[0] ** 2 + axis[2] ** 2)
        if s < 1e-6:
            self.q = (1.0, 0.0, 0.0, 0.0) if c > 0 else (0.0, 1.0, 0.0, 0.0)
            return
        ang = math.atan2(s, c)
        k = math.sin(ang / 2) / s
        self.q = qnorm((math.cos(ang / 2), axis[0] * k, 0.0, axis[2] * k))

    def start_calibration(self, seconds=None):
        """Starts a hold-still calibration; its result appears in cal_result."""
        with self.lock:
            self.cal = {"seconds": seconds or self.CAL_S, "end": None, "sum": [0.0] * 3, "sq": [0.0] * 3, "n": 0}
            self.cal_result = None

    def _calibrate_step(self, g, ts_ns):
        c = self.cal
        if c["end"] is None:
            c["end"] = ts_ns + int(c["seconds"] * 1e9)
        for i in range(3):
            c["sum"][i] += g[i]
            c["sq"][i] += g[i] * g[i]
        c["n"] += 1
        if ts_ns < c["end"]:
            return
        n = c["n"]
        mean = [s / n for s in c["sum"]]
        sd = [math.sqrt(max(0.0, q / n - m * m)) for q, m in zip(c["sq"], mean)]
        deg = (tuple(round(math.degrees(m), 3) for m in mean), tuple(round(math.degrees(s), 3) for s in sd))
        self.cal = None
        if n >= self.CAL_MIN_REPORTS and max(sd) < self.CAL_SD and all(abs(m) < self.CAL_MAX for m in mean):
            self.bias = mean
            self.bias_ready = True
            self.rest_run = []
            self.cal_result = ("ok",) + deg
        else:
            self.cal_result = ("moved",) + deg

    def recentre(self, yaw_deg=0.0, follow_tilt=False):
        """The head's heading becomes straight ahead, with the view turned [yaw_deg] (left positive): as on Android,
        the windows' middle comes in front of the head rather than the room's zero. With [follow_tilt], the head's
        pitch becomes straight ahead too, however small."""
        with self.lock:
            self.recentre_yaw = math.radians(yaw_deg)
            self.recentre_follows_tilt = bool(follow_tilt)
            self.recentre_sets_tilt = True
            self.want_recentre = True

    def view(self):
        """Head orientation relative to the recentred forward."""
        with self.lock:
            return qmul(qconj(self.ref), self.q)
