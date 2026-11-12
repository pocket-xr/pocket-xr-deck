"""Checks that need no glasses and no screen: the framer and the fusion's directions."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fusion  # noqa: E402
import imu  # noqa: E402


def test_framer_splits_and_skips_junk():
    f = imu.Framer()
    a = imu.encode_report(1000, (0.1, 0.2, 0.3), (0, 9.8, 0))
    b = imu.encode_report(2000, (0, 0, 0), (0, 9.8, 0), magic0=0x27)
    mag = imu.encode_report(3000, (0, 0, 0), (0, 0, 0), rtype=imu.TYPE_MAG)
    data = b"\x00\x28junk" + a + mag + b
    out = f.feed(data[:50]) + f.feed(data[50:])
    assert [r[0] for r in out] == [1000, 2000], out
    assert abs(out[0][1][1] - 0.2) < 1e-6
    assert f.reports == 3


def run(head, seconds, gyro, accel=(0.0, 9.8, 0.0), t0=0):
    ts = t0
    for _ in range(int(seconds * 1000)):
        ts += 1_000_000
        head.report(ts, gyro, accel)
    return ts


def yaw_pitch(head):
    fwd = fusion.qrot(head.view(), (0.0, 0.0, -1.0))
    return math.degrees(math.atan2(-fwd[0], -fwd[2])), math.degrees(math.asin(fwd[1]))


def test_turn_left_is_positive_yaw():
    h = fusion.HeadFusion("aura")
    t = run(h, 2.0, (0.0, 0.0, 0.0))
    assert h.bias_ready
    run(h, 1.0, (0.0, math.radians(30), 0.0), t0=t)  # turn about +y = to the left
    yaw, pitch = yaw_pitch(h)
    assert 28 < yaw < 31, yaw
    assert abs(pitch) < 1, pitch


def test_bias_removed():
    h = fusion.HeadFusion("aura")
    bias = (0.01, -0.02, 0.005)
    t = run(h, 3.0, bias)  # learnt from quiet half seconds; a fraction of a degree goes by first
    y0, _ = yaw_pitch(h)
    run(h, 10.0, bias, t0=t)
    yaw, pitch = yaw_pitch(h)
    assert abs(yaw - y0) < 0.2 and abs(pitch) < 0.5, (y0, yaw, pitch)


def test_moving_at_start_then_still_does_not_creep():
    # 11 Nov 2026 on the Deck: a head turning during the first seconds was learnt as bias.
    import random
    random.seed(1)
    h = fusion.HeadFusion("aura")
    ts = 0
    for k in range(3000):  # 3 s of a wobbling head turn
        ts += 1_000_000
        h.report(ts, (0.0, 0.3 * math.sin(k / 300) + random.gauss(0, 0.05), 0.0), (0.0, 9.8, 0.0))
    bias = (0.004, 0.006, -0.003)
    for _ in range(4000):  # then still, with noise and a small real bias
        ts += 1_000_000
        h.report(ts, tuple(b + random.gauss(0, 0.004) for b in bias), (0.0, 9.8, 0.0))
    y0, _ = yaw_pitch(h)
    for _ in range(20000):
        ts += 1_000_000
        h.report(ts, tuple(b + random.gauss(0, 0.004) for b in bias), (0.0, 9.8, 0.0))
    y1, _ = yaw_pitch(h)
    assert abs(y1 - y0) < 1.0, (y0, y1)


def test_tilt_follows_gravity():
    # Glasses pitched 20 degrees down: world up, seen from the head, leans toward the head's back (+z).
    a = 20 * math.pi / 180
    accel = (0.0, 9.8 * math.cos(a), 9.8 * math.sin(a))
    h = fusion.HeadFusion("aura")
    run(h, 8.0, (0.0, 0.0, 0.0), accel=accel)
    _, pitch = yaw_pitch(h)
    assert abs(pitch + 20) < 1.0, pitch


def test_one_axes_flip():
    h = fusion.HeadFusion("one")
    t = run(h, 2.0, (0, 0, 0), accel=(0.0, -9.8, 0.0))
    run(h, 1.0, (0.0, -math.radians(30), 0.0), accel=(0.0, -9.8, 0.0), t0=t)
    yaw, _ = yaw_pitch(h)
    assert 28 < yaw < 31, yaw


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
