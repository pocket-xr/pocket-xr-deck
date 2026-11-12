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

    BIAS_SECONDS = 1.5
    KP = 1.0  # how hard tilt follows gravity, 1/s
    STILL_RAD_S = 0.06

    def __init__(self, axes="aura"):
        self.sign = AXES[axes]
        self.lock = threading.Lock()
        self.q = (1.0, 0.0, 0.0, 0.0)  # world from head
        self.ref = (1.0, 0.0, 0.0, 0.0)  # recentre
        self.last_ts = None
        self.bias = [0.0, 0.0, 0.0]
        self.bias_sum = [0.0, 0.0, 0.0]
        self.bias_n = 0
        self.bias_start = None
        self.bias_ready = False
        self.g_mag = None
        self.count = 0
        self.want_recentre = True
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
                self._level_from(a)
                return
            dt = (ts_ns - self.last_ts) / 1e9
            self.last_ts = ts_ns
            if not (0.0 < dt < 0.05):
                return
            an = math.sqrt(a[0] ** 2 + a[1] ** 2 + a[2] ** 2)
            if not self.bias_ready:
                if self.bias_start is None:
                    self.bias_start = ts_ns
                for i in range(3):
                    self.bias_sum[i] += g[i]
                self.bias_n += 1
                self.g_mag = an if self.g_mag is None else 0.99 * self.g_mag + 0.01 * an
                if (ts_ns - self.bias_start) / 1e9 >= self.BIAS_SECONDS:
                    self.bias = [s / self.bias_n for s in self.bias_sum]
                    self.bias_ready = True
                    self._level_from(a)
                    self.want_recentre = True
                return
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
                self.ref = about_y(yaw_of(self.q))
                self.want_recentre = False

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

    def recentre(self):
        with self.lock:
            self.want_recentre = True

    def view(self):
        """Head orientation relative to the recentred forward."""
        with self.lock:
            return qmul(qconj(self.ref), self.q)
