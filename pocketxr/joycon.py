"""Joy-Cons as PC VR's hands, as Pocket XR on Android uses them: each Joy-Con's motion turns that hand, its buttons
and stick are the controller's.

On the Deck the Joy-Cons are read from their raw HID devices (/dev/hidrawN), which Desktop Mode lets the signed-in
user open. Linux's hid-nintendo driver also makes input devices for them, but the ones for motion are open to root
only, and the raw reports carry everything at once: buttons, both sticks and three motion samples each 15 ms.

Steam holds the Joy-Cons too and turns their motion sensors off, as it does the Deck's own. While PC VR runs, Pocket XR
turns them on with the Joy-Con's "enable IMU" subcommand (0x40, argument 1), the same command the Linux driver sends
when a Joy-Con connects, and sends it again if Steam turns them off. When PC VR ends they are turned off again
(argument 0), as Steam had them.

The raw report (input report 0x30, from the public Joy-Con protocol notes the driver is built on):
    byte 3     right buttons: Y 0x01, X 0x02, B 0x04, A 0x08, SR 0x10, SL 0x20, R 0x40, ZR 0x80
    byte 4     shared: minus 0x01, plus 0x02, right stick 0x04, left stick 0x08, home 0x10, capture 0x20
    byte 5     left buttons: down 0x01, up 0x02, right 0x04, left 0x08, SR 0x10, SL 0x20, L 0x40, ZL 0x80
    bytes 6-8  left stick, bytes 9-11 right stick: two 12 bit values (x, then y with up positive)
    bytes 13-48  three motion samples of six int16: accelerometer x y z (4096 per g), gyro x y z (0.07 degrees per
               second each)
The right Joy-Con's sensor sits turned over, so its y and z read the other way; turned back, both Joy-Cons read x
toward the shoulder buttons, y to the left and z out of the face, as Linux reports them and as Android's pose expects.

Buttons, as on Android: the face button under your thumb's rest (A on the right, the right arrow on the left) is the
controller's A or X, the one above it B or Y; ZL and ZR are the triggers, L and R the grips, minus and plus the menu,
the stick and its click the thumbstick. Capture on the left and Home on the right line that Joy-Con up with the way
you face; each is lined up by itself shortly after it first reports.
"""
import math
import os
import select
import struct
import threading
import time

REPORT_FULL = 0x30
RUMBLE_OFF = bytes([0x00, 0x01, 0x40, 0x40, 0x00, 0x01, 0x40, 0x40])
SUBCMD_IMU = 0x40
GYRO_RAD = math.radians(0.07)  # per raw unit
ACCEL_PER_G = 4096.0
SAMPLE_S = 0.005  # three samples a report, a report each 15 ms
STICK_RANGE = 1400.0  # raw units from centre to the edge, about, on the Joy-Cons measured
STICK_DEAD = 0.15
SCAN_S = 2.0
STALE_S = 0.5  # no report this long: the Joy-Con is gone, the Deck's controls take that hand back
IMU_RETRY_S = 2.0
AUTO_RECENTRE_S = 0.7

# The pose, from Android's JoyConPose.kt
MAX_DT_S = 0.1
ACCEL_WINDOW_G = 0.15
GAIN = 2.0
BIAS_GAIN = 0.05
SETTLE_S = 0.5
SETTLE_GAIN = 20.0
SHOULDER_SIDE_M = 0.2
SHOULDER_DROP_M = -0.3
ARM_M = 0.4
# A Joy-Con lying still: its gyro's resting offset is taken from it (the factory offset is not read)
REST_RAD = math.radians(2.0)
REST_S = 0.8
REST_EASE = 0.02


def _qmul(a, b):
    aw, ax, ay, az = a
    bw, bx, by, bz = b
    return (aw * bw - ax * bx - ay * by - az * bz,
            aw * bx + ax * bw + ay * bz - az * by,
            aw * by - ax * bz + ay * bw + az * bx,
            aw * bz + ax * by - ay * bx + az * bw)


def _qnorm(q):
    n = math.sqrt(sum(c * c for c in q)) or 1.0
    return tuple(c / n for c in q)


def _qconj(q):
    return (q[0], -q[1], -q[2], -q[3])


def _rotate(q, v):
    w, x, y, z = _qmul(_qmul(q, (0.0, v[0], v[1], v[2])), _qconj(q))
    return (x, y, z)


def _yaw_of(q):
    f = _rotate(q, (0.0, 0.0, -1.0))
    return math.atan2(-f[0], -f[2])


def _yaw_quat(yaw):
    return (math.cos(yaw / 2), 0.0, math.sin(yaw / 2), 0.0)


class Pose:
    """One Joy-Con's orientation from its gyro and accelerometer, and where its grip sits (JoyConPose.kt)."""

    def __init__(self, right):
        self.right = right
        self.attitude = (1.0, 0.0, 0.0, 0.0)
        self.yaw_fix = (1.0, 0.0, 0.0, 0.0)
        self.bias = [0.0, 0.0, 0.0]
        self.settle = SETTLE_S
        self.angular_velocity = (0.0, 0.0, 0.0)
        self.rest_mean = None
        self.rest_since = None
        self.rest_bias = (0.0, 0.0, 0.0)

    @property
    def orientation(self):
        return _qnorm(_qmul(self.yaw_fix, self.attitude))

    def _rest(self, g, now):
        """Learns the gyro's resting offset while the Joy-Con lies still."""
        if self.rest_mean is None:
            self.rest_mean = g
        m = self.rest_mean
        if max(abs(g[i] - m[i]) for i in range(3)) > REST_RAD:
            self.rest_mean = g
            self.rest_since = now
            return
        self.rest_mean = tuple(m[i] + (g[i] - m[i]) * REST_EASE for i in range(3))
        if self.rest_since is None:
            self.rest_since = now
        elif now - self.rest_since >= REST_S:
            self.rest_bias = self.rest_mean

    def update(self, gx, gy, gz, ax, ay, az, dt, now):
        """One sample in the sensors' own axes (radians per second, g); [dt] seconds since the last."""
        if dt <= 0 or dt > MAX_DT_S:
            return
        self._rest((gx, gy, gz), now)
        gx, gy, gz = gx - self.rest_bias[0], gy - self.rest_bias[1], gz - self.rest_bias[2]
        gyro = (-gy, gz, -gx)
        accel = (-ay, az, -ax)
        length = math.sqrt(sum(c * c for c in accel))
        corr = (0.0, 0.0, 0.0)
        settling = self.settle > 0
        if abs(length - 1.0) < ACCEL_WINDOW_G:
            meas = tuple(c / length for c in accel)
            exp = _rotate(_qconj(self.attitude), (0.0, 1.0, 0.0))
            err = (meas[1] * exp[2] - meas[2] * exp[1], meas[2] * exp[0] - meas[0] * exp[2],
                   meas[0] * exp[1] - meas[1] * exp[0])
            gain = SETTLE_GAIN if settling else GAIN
            corr = tuple(e * gain for e in err)
            if not settling:
                self.bias = [self.bias[i] - err[i] * BIAS_GAIN * dt for i in range(3)]
        if settling:
            self.settle -= dt
        w = [gyro[i] - self.bias[i] + corr[i] for i in range(3)]
        self.attitude = _qnorm(_qmul(self.attitude, (1.0, w[0] * dt / 2, w[1] * dt / 2, w[2] * dt / 2)))
        self.angular_velocity = _rotate(self.orientation, tuple(gyro[i] - self.bias[i] for i in range(3)))

    def recentre(self, head):
        """Points the Joy-Con's forward at the head's forward, leaving its pitch and roll alone."""
        self.yaw_fix = _yaw_quat(_yaw_of(head) - _yaw_of(self.attitude))

    def position(self, head):
        """The grip's place relative to the head, metres, for a head turned to [head]."""
        body = _yaw_quat(_yaw_of(head))
        side = SHOULDER_SIDE_M if self.right else -SHOULDER_SIDE_M
        shoulder = _rotate(body, (side, SHOULDER_DROP_M, 0.0))
        reach = _rotate(self.orientation, (0.0, 0.0, -ARM_M))
        return tuple(shoulder[i] + reach[i] for i in range(3))


def _stick(raw, centre):
    x = (raw[0] - centre[0]) / STICK_RANGE
    y = (raw[1] - centre[1]) / STICK_RANGE
    r = math.hypot(x, y)
    if r < STICK_DEAD:
        return 0.0, 0.0
    k = min(1.0, (r - STICK_DEAD) / (1.0 - STICK_DEAD)) / r
    return x * k, y * k


def buttons_of(report, side):
    """(bridge button bits, trigger, squeeze, recentre pressed) for the Joy-Con on [side] (0 left, 1 right). Bits: 1
    primary, 2 secondary, 4 menu, 8 stick click; touches 0x10, 0x20, 0x40 trigger, 0x80 stick."""
    r, s, l = report[3], report[4], report[5]
    if side == 0:
        prim, sec, menu, click, trig, grip, recentre = l & 0x04, l & 0x02, s & 0x01, s & 0x08, l & 0x80, l & 0x40, s & 0x20
    else:
        prim, sec, menu, click, trig, grip, recentre = r & 0x08, r & 0x04, s & 0x02, s & 0x04, r & 0x80, r & 0x40, s & 0x10
    b = 0
    if prim:
        b |= 1 | 0x10
    if sec:
        b |= 2 | 0x20
    if menu:
        b |= 4
    if click:
        b |= 8 | 0x80
    if trig:
        b |= 0x40
    return b, 1.0 if trig else 0.0, 1.0 if grip else 0.0, bool(recentre)


def stick_raw(report, side):
    d = report[6:9] if side == 0 else report[9:12]
    return d[0] | ((d[1] & 0x0F) << 8), (d[1] >> 4) | (d[2] << 4)


class JoyCon:
    def __init__(self, side, node, fd):
        self.side = side
        self.node = node
        self.fd = fd
        self.pose = Pose(side == 1)
        self.lock = threading.Lock()
        self.first_at = None
        self.last_at = None
        self.last_sample_at = None
        self.report = None
        self.stick_centre = None
        self.centred = False
        self.recentre_held = False
        self.recentre_asked = False
        self.imu_zero_since = None
        self.imu_asked_at = 0.0
        self.counter = 0


class JoyCons:
    """Finds Joy-Cons, keeps their motion sensors on and their poses current, on a thread of its own."""

    def __init__(self, log):
        self.log = log
        self.pads = {}  # node -> JoyCon
        self.running = False
        self.thread = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._run, name="joycons", daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
            self.thread = None
        for jc in list(self.pads.values()):
            self._imu(jc, False)
            self._close(jc)

    # ---- for the frame ----
    def hand(self, side, head):
        """(14 pose floats, (buttons, trigger, squeeze, stick x, stick y)) for this hand's Joy-Con, or None when there
        is none reporting. [head] is the head's orientation (w, x, y, z); the pose is relative to the head's place."""
        now = time.monotonic()
        for jc in list(self.pads.values()):
            if jc.side != side or jc.last_at is None or now - jc.last_at > STALE_S:
                continue
            with jc.lock:
                if jc.recentre_asked or (not jc.centred and now - jc.first_at > AUTO_RECENTRE_S):
                    jc.pose.recentre(head)
                    jc.centred = True
                    jc.recentre_asked = False
                q = jc.pose.orientation
                p = jc.pose.position(head)
                w = jc.pose.angular_velocity
                report = jc.report
                centre = jc.stick_centre
            b, trig, sq, _ = buttons_of(report, side)
            sx, sy = _stick(stick_raw(report, side), centre)
            if sx or sy:
                b |= 0x80
            pose = [1.0, q[1], q[2], q[3], q[0], p[0], p[1], p[2], w[0], w[1], w[2], 0.0, 0.0, 0.0]
            return pose, (b, trig, sq, sx, sy)
        return None

    # ---- the thread ----
    def _run(self):
        next_scan = 0.0
        while self.running:
            now = time.monotonic()
            if now >= next_scan:
                self._scan()
                next_scan = now + SCAN_S
            fds = {jc.fd: jc for jc in self.pads.values()}
            if not fds:
                time.sleep(0.2)
                continue
            try:
                ready, _, _ = select.select(list(fds), [], [], 0.2)
            except (OSError, ValueError):
                ready = []
            for fd in ready:
                jc = fds[fd]
                try:
                    data = os.read(fd, 64)
                except OSError as e:
                    self.log(f"joycon: {jc.node} stopped ({e.strerror})")
                    self._close(jc)
                    continue
                self._report(jc, data)

    def _scan(self):
        try:
            names = os.listdir("/sys/class/hidraw")
        except OSError:
            return
        for name in names:
            node = "/dev/" + name
            if node in self.pads:
                continue
            try:
                with open(f"/sys/class/hidraw/{name}/device/uevent") as f:
                    ue = f.read()
            except OSError:
                continue
            if "HID_NAME=Joy-Con (L)" in ue:
                side = 0
            elif "HID_NAME=Joy-Con (R)" in ue:
                side = 1
            else:
                continue
            try:
                fd = os.open(node, os.O_RDWR | os.O_NONBLOCK)
            except OSError as e:
                self.log(f"joycon: cannot open {node} ({e.strerror})")
                continue
            jc = JoyCon(side, node, fd)
            self.pads[node] = jc
            self.log(f"joycon: {'left' if side == 0 else 'right'} Joy-Con on {node}")
            self._imu(jc, True)

    def _close(self, jc):
        self.pads.pop(jc.node, None)
        try:
            os.close(jc.fd)
        except OSError:
            pass

    def _imu(self, jc, on):
        """The Joy-Con's documented "enable IMU" subcommand: output report 1, a packet number, neutral rumble, 0x40."""
        jc.counter = (jc.counter + 1) & 0x0F
        try:
            os.write(jc.fd, bytes([0x01, jc.counter]) + RUMBLE_OFF + bytes([SUBCMD_IMU, 1 if on else 0]))
            jc.imu_asked_at = time.monotonic()
        except OSError as e:
            self.log(f"joycon: could not turn motion {'on' if on else 'off'} on {jc.node} ({e.strerror})")

    def _report(self, jc, d):
        if len(d) < 49 or d[0] != REPORT_FULL:
            return
        now = time.monotonic()
        samples = [struct.unpack_from("<6h", d, 13 + 12 * k) for k in range(3)]
        if all(not any(s) for s in samples):  # motion is off (Steam turned it off): ask again now and then
            if jc.imu_zero_since is None:
                jc.imu_zero_since = now
            if now - jc.imu_zero_since > 0.3 and now - jc.imu_asked_at > IMU_RETRY_S:
                self.log(f"joycon: motion is off on {jc.node}, turning it on")
                self._imu(jc, True)
            return
        jc.imu_zero_since = None
        with jc.lock:
            if jc.first_at is None:
                jc.first_at = now
                jc.stick_centre = stick_raw(d, jc.side)
                self.log(f"joycon: {'left' if jc.side == 0 else 'right'} Joy-Con is reporting")
            dt0 = 0.0 if jc.last_sample_at is None else now - jc.last_sample_at - 2 * SAMPLE_S
            for k, s in enumerate(samples):
                ax, ay, az, gx, gy, gz = s
                if jc.side == 1:  # the right Joy-Con's sensor is turned over
                    ay, az, gy, gz = -ay, -az, -gy, -gz
                dt = dt0 if k == 0 else SAMPLE_S
                jc.pose.update(gx * GYRO_RAD, gy * GYRO_RAD, gz * GYRO_RAD,
                               ax / ACCEL_PER_G, ay / ACCEL_PER_G, az / ACCEL_PER_G, dt, now)
            jc.last_sample_at = now
            jc.last_at = now
            jc.report = bytes(d)
            recentre = buttons_of(d, jc.side)[3]
            if recentre and not jc.recentre_held:
                jc.recentre_asked = True
            jc.recentre_held = recentre
