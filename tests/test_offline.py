"""Checks that need no glasses and no screen: the framer and the fusion's directions."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import control, fusion, glasses, hidimu, imu  # noqa: E402


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
    t = run(h, 2.5, (0.0, 0.0, 0.0))
    assert h.bias_ready
    run(h, 1.0, (0.0, math.radians(30), 0.0), t0=t)  # turn about +y = to the left
    yaw, pitch = yaw_pitch(h)
    assert 28 < yaw < 31, yaw
    assert abs(pitch) < 1, pitch


def test_bias_removed():
    h = fusion.HeadFusion("aura")
    bias = (0.01, -0.015, 0.005)  # the Aura's at rest is under 0.5 deg/s; these are up to 0.9
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
    t = run(h, 2.5, (0, 0, 0), accel=(0.0, -9.8, 0.0))
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


def test_glasses_detect():
    aura = [(0x3318, 0x043A, [0x03, 0x0E, 0x0E, 0x02, 0x0A], "XREAL Aura")]
    g = glasses.detect(aura)
    assert g.family == "aura" and g.steady_6dof and g.app_anchor and g.network_imu and not g.eye
    one = [(0x3318, 0x0438, [0x02, 0x0A, 0x03], "XREAL One")]
    g = glasses.detect(one)
    assert g.family == "one" and not g.steady_6dof and g.axes == "one"
    assert "XREAL Eye" in g.why_no_6dof()
    one_eye = one + [(0x3318, 0x0450, [0x0E, 0x0E], "XREAL Eye")]
    g = glasses.detect(one_eye)
    assert g.steady_6dof and not g.app_anchor
    vit = [(0x35CA, 0x101D, [0x03], "VITURE Luma")]
    g = glasses.detect(vit)
    assert g.family == "viture" and not g.network_imu and "SDK" in g.why_no_6dof()
    assert glasses.detect([(0x28DE, 0x1205, [0x03], "Steam Deck Controller")]) is None


def test_follow_bytes():
    # Pocket XR ControlWire.spaceMode(id, SPACE_FOLLOW): 10284 with { 1: 1 }; 10421 reads it back.
    assert control.follow(0x80000001).hex() == "282c" + "00000008" + "80000001" + "1a020801"
    assert control.rpc(control.SPACE_MODE_GET, 0x80000001).hex() == "28b5" + "00000006" + "80000001" + "1a00"


def test_recenter_bytes():
    assert control.recenter(0x80000001).hex() == "2827" + "00000006" + "80000001" + "1a00"


def test_air_command_and_report():
    c = hidimu.air_stream(True)
    assert len(c) == 64 and c[0] == 0xAA and c[5:9] == bytes([4, 0, 0x19, 1])
    import zlib, struct
    assert struct.unpack_from("<I", c, 1)[0] == zlib.crc32(c[5:9])
    # Sensor axes x left, y back, z up: a turn about the sensor's z is a turn about the head's y (up).
    rep = hidimu.air_parse(hidimu.air_report(1000, (0.0, 0.0, 30.0), (0.0, 0.0, 1.0)))
    ts, g, a = rep
    assert ts == 1000 and abs(g[1] - math.radians(30)) < 1e-3 and abs(g[0]) < 1e-6 and abs(g[2]) < 1e-6
    assert abs(a[1] - 9.81) < 1e-2  # gravity's reaction along head up, in m/s2
    assert hidimu.air_parse(c) is None  # a command answer is not a report
    t = hidimu.AirTimestamp()
    t.to_ns(1000)
    assert t.to_ns(2000) == 2000 * 1000  # 1 kHz in microseconds


def test_viture_frames():
    st = hidimu.v_start()
    assert len(st) == 64 and st[:10].hex() == "1000" + "0103" + "0200" + "0400" + "0202"
    raw = hidimu.v_raw(7, (0.1, 0.2, 0.3), (0.0, -1.0, 0.0))
    mid, payload = hidimu.v_read(raw)
    assert mid == 0x7309
    counter, g, a = hidimu.v_parse_raw(payload)
    assert counter == 7 and abs(g[1] - 0.2) < 1e-6 and abs(a[1] + 1.0) < 1e-6
    bad = bytearray(raw)
    bad[12] ^= 0xFF
    assert hidimu.v_read(bytes(bad)) is None  # checksum
    c = hidimu.VitureClock()
    t0 = c.to_ns(0, 10_000_000)
    for k in range(1, 121):
        c.to_ns(k, 10_000_000 + k * 10_000_000)  # 100 Hz really
    assert c.learned and abs(c.period - 10_000_000) < 1


def test_glasses_families():
    beast = [(0x35CA, 0x1102, [0x01, 0x03], "VITURE Microphone"), (0x35CA, 0x1211, [0x03] * 6, "VITURE Beast XR Glasses")]
    g = glasses.detect(beast)
    assert g.beast and g.imu == "viture" and g.axes == "one" and g.viture_tracking_default()
    assert g.why_no_tracking() is None
    pro2 = glasses.detect([(0x35CA, 0x1301, [0x03], "VITURE Pro 2")])
    assert not pro2.beast and not pro2.viture_tracking_default() and "off" in pro2.why_no_tracking()
    air2 = glasses.detect([(0x3318, 0x0428, [0x03] * 4, "XREAL Air 2")])
    assert air2.family == "air" and air2.imu == "air" and air2.axes == "aura" and not air2.control_link
    helen = glasses.detect([(0x3318, 0x043F, [0x03] * 4, "")])
    assert helen.family == "air" and helen.imu is None
    assert hidimu.air_interface(0x0426) == 2 and hidimu.air_interface(0x0428) == 3


def test_joycon_pose_and_buttons():
    import math
    from pocketxr import joycon
    # lying flat, face up: points forward once lined up with a head facing forward
    pose = joycon.Pose(False)
    t = 0.0
    for _ in range(300):
        t += 0.005
        pose.update(0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.005, t)
    pose.recentre((1.0, 0.0, 0.0, 0.0))
    f = joycon._rotate(pose.orientation, (0.0, 0.0, -1.0))
    assert f[2] < -0.99, f
    # held level, the hand is at a held hand's height, well below the eyes (12 Nov 2026: it was a foot too high)
    p = pose.position((1.0, 0.0, 0.0, 0.0))
    assert -0.62 < p[1] < -0.5 and p[2] < -0.2, p
    # turning about the face's axis (z, out of the face) by 90 degrees turns the hand to the left
    for _ in range(200):
        t += 0.005
        pose.update(0.0, 0.0, math.radians(90.0), 0.0, 0.0, 1.0, 0.005, t)
    f = joycon._rotate(pose.orientation, (0.0, 0.0, -1.0))
    assert f[0] < -0.9, f
    # buttons: A is the right hand's primary, ZL the left trigger, capture the left recentre
    report = bytearray(49)
    report[0] = 0x30
    report[3] = 0x08
    report[5] = 0x80
    report[4] = 0x20
    b, trig, sq, rec = joycon.buttons_of(report, 1)
    assert b & 1 and trig == 0.0 and not rec
    b, trig, sq, rec = joycon.buttons_of(report, 0)
    assert b & 0x40 and trig == 1.0 and rec and not b & 1
    # sticks: 12 bit pairs
    report[6:9] = bytes([0x00, 0x08, 0x80])  # x 0x800, y 0x800
    assert joycon.stick_raw(report, 0) == (0x800, 0x800)


def test_slow_turn_is_not_bias_and_no_late_recentre():
    # 12 Nov 2026: a slow smooth turn (1.4 deg/s) was learnt as bias, and the first stillness minutes in recentred.
    h = fusion.HeadFusion("aura")
    t = run(h, 6.0, (0.0, math.radians(1.4), 0.0))  # a slow steady turn, no stillness: not bias
    assert not h.bias_ready and abs(h.bias[1]) < 1e-9, h.bias
    y0, _ = yaw_pitch(h)
    run(h, 3.0, (0.0, 0.0, 0.0), t0=t)  # still at last, 6 s in: the bias is learnt, the view is not recentred
    y1, _ = yaw_pitch(h)
    assert h.bias_ready and abs(y1 - y0) < 0.5 and abs(y0) > 5, (y0, y1)


def test_recentre_brings_the_windows_middle_in_front():
    # As Android's RecentreContent: windows from 0 to 60 degrees left; after a recentre facing anywhere, the head's
    # forward is at their middle.
    from pocketxr import space as S
    from pocketxr.spaceview import SpaceView

    class Fake:
        pass
    sv = Fake()
    sv.poses = {1: S.Pose(10.0, 0.0, 2.0, 20.0, 12.0), 2: S.Pose(50.0, 0.0, 2.0, 20.0, 12.0)}
    sv.focus = 1
    yaw = SpaceView.content_yaw(sv)
    assert abs(yaw - 30.0) < 0.01, yaw
    h = fusion.HeadFusion("aura")
    t = run(h, 2.5, (0.0, 0.0, 0.0))
    t = run(h, 1.0, (0.0, math.radians(-40), 0.0), t0=t)  # turned 40 degrees right
    h.recentre(yaw)
    run(h, 0.01, (0.0, 0.0, 0.0), t0=t)
    fwd = fusion.qrot(h.view(), (0.0, 0.0, -1.0))
    assert abs(S.angles(fwd)[0] - 30.0) < 0.5, S.angles(fwd)


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
