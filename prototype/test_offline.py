"""Checks that need no glasses and no screen: the framer and the fusion's directions."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fusion  # noqa: E402
import imu  # noqa: E402
import control  # noqa: E402


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


def test_control_bytes_match_pocket_xr():
    # Pocket XR ControlWire: header (type u16 BE, length u32 BE), RPC id u32 BE, then field 3 = request.
    rid = control.rpc_id(0)
    assert rid == 0x80000001
    assert control.ultrawide_set(rid, True).hex() == "282600000008" + "80000001" + "1a020801"
    assert control.anchor_set(rid, True).hex() == "28a5" + "00000008" + "80000001" + "1a020801"
    # Off: proto3 leaves the zero out, so the request is empty (Pocket XR ProtoWriter.varint).
    assert control.anchor_set(rid, False).hex() == "28a5" + "00000006" + "80000001" + "1a00"
    # Screen size: field 1 as a float, "1a 05 0d <f32 LE>" as recorded for the Aura.
    assert control.size_set(rid, 1.2).hex() == "289e" + "0000000b" + "80000001" + "1a050d" + "9a99993f"
    assert control.rpc(control.ANCHOR_GET, rid).hex() == "28a4" + "00000006" + "80000001" + "1a00"
    hb = control.heartbeat(5)
    assert hb[:6].hex() == "271000000021" and hb[6] == 1 and hb[7] == 5 and len(hb) == 39


def test_control_refuses_other_ids():
    for bad in (10079, 10325, 10326, 10327, 10328, 10281, 12345):
        try:
            control.rpc(bad, 0x80000001)
        except ValueError:
            continue
        raise AssertionError(bad)


def test_control_reads_answers():
    f = control.Framer()
    # Answer to 10397: id with top bit clear, field 4 = { 1: 0, 2: f32 1.2 }
    resp = control.pb_float(2, 1.2)
    body = bytes.fromhex("00000001") + control.pb_message(4, resp)
    rng = control.pb_float(2, 0.85) + control.pb_float(3, 1.2)
    body2 = bytes.fromhex("00000002") + control.pb_message(4, rng)
    # an empty answer: Ultrawide off is left out
    body3 = bytes.fromhex("00000003") + control.pb_message(4, b"")
    data = control.heartbeat(1) + control.header(10397, len(body)) + body + control.header(10396, len(body2)) + body2         + control.header(10277, len(body3)) + body3
    out = f.feed(data[:20]) + f.feed(data[20:])
    assert [a.type for a in out] == [10397, 10396, 10277]
    assert abs(out[0].value - 1.2) < 1e-6 and out[0].result == 0
    assert abs(out[1].value - 0.85) < 1e-6 and abs(out[1].value3 - 1.2) < 1e-6
    assert out[2].value is None


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
