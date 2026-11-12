"""Head orientation from gyro and accelerometer: a small complementary filter.

Head axes are x right, y up, z back (OpenGL's). The Aura's sensor already uses them; the One
family is "x right, y down, z front" (Pocket XR's AxisMap), so its y and z are negated.
"""
import math
import threading

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

    def __init__(self, axes="aura"):
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
        self.last_gyro = (0.0, 0.0, 0.0)

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
                self.ref = about_y(yaw_of(self.q) - self.recentre_yaw)
                self.want_recentre = False

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

    def recentre(self, yaw_deg=0.0):
        """The head's heading becomes straight ahead, with the view turned [yaw_deg] (left positive): as on Android,
        the windows' middle comes in front of the head rather than the room's zero."""
        with self.lock:
            self.recentre_yaw = math.radians(yaw_deg)
            self.want_recentre = True

    def view(self):
        """Head orientation relative to the recentred forward."""
        with self.lock:
            return qmul(qconj(self.ref), self.q)
