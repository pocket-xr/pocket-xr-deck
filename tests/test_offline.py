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
    # The Beast also comes as 0x1201 (a tester's, November 2026), with the same layout.
    b1201 = glasses.detect([(0x35CA, 0x1102, [0x01, 0x03], "VITURE Microphone"), (0x35CA, 0x1301, [0x03], "VITURE Pro 2"),
                            (0x35CA, 0x1201, [0x03] * 6, "VITURE Beast XR Glasses")])
    assert b1201.product == 0x1201 and b1201.beast and b1201.axes == "one" and b1201.viture_tracking_default()
    assert b1201.why_no_tracking() is None
    assert glasses.is_beast(0x1211) and glasses.is_beast(0x1201) and not glasses.is_beast(0x1301)
    nodes = [(0, "/dev/hidraw0", 0x1201), (5, "/dev/hidraw5", 0x1201), (3, "/dev/hidraw3", 0x1201)]
    assert [n[0] for n in hidimu.beast_first(nodes)] == [5, 0, 3]
    assert [n[0] for n in hidimu.beast_first([(n[0], n[1], 0x1211) for n in nodes])] == [5, 0, 3]
    assert [n[0] for n in hidimu.beast_first([(n[0], n[1], 0x1301) for n in nodes])] == [0, 3, 5]
    air2 = glasses.detect([(0x3318, 0x0428, [0x03] * 4, "XREAL Air 2")])
    assert air2.family == "air" and air2.imu == "air" and air2.axes == "aura" and not air2.control_link
    helen = glasses.detect([(0x3318, 0x043F, [0x03] * 4, "")])
    assert helen.family == "air" and helen.imu is None
    assert hidimu.air_interface(0x0426) == 2 and hidimu.air_interface(0x0428) == 3


def test_xbx_a01_reads_the_air_imu_on_interface_1():
    # A tester's A01+ (November 2026): three HID interfaces, product string "xbx a01+"
    for pid, name in ((0x0440, "XREAL XBX A01"), (0x0442, "XREAL XBX A01+")):
        g = glasses.detect([(0x3318, pid, [0x03] * 3, "xbx a01+")])
        assert g.family == "air" and g.imu == "air" and g.name == name and g.why_no_tracking() is None
        assert hidimu.air_interface(pid) == 1 and hidimu.AIR_MODELS[pid] == name
    # Interface 1 first (wheaney's library); the MCU on 0 and interface 2 only if it stays silent (see below)
    nodes = [(0, "/dev/hidraw3", 0x0442), (1, "/dev/hidraw4", 0x0442), (2, "/dev/hidraw5", 0x0442)]
    assert [n for n in nodes if n[0] == hidimu.air_interface(0x0442)] == [(1, "/dev/hidraw4", 0x0442)]


def test_mcu_frame_matches_the_library_layout():
    import struct
    import zlib
    f = hidimu.mcu_command(0x31, b"3.1.1")
    assert f[0] == 0xFD and len(f) == 5 + 17 + 5
    length, ts, msg_id = struct.unpack_from("<HQH", f, 5)
    assert (length, ts, msg_id) == (22, 0, 0x31) and f[17:22] == bytes(5) and f[22:] == b"3.1.1"
    assert struct.unpack_from("<I", f, 1)[0] == zlib.crc32(f[5:]) & 0xFFFFFFFF
    assert hidimu.mcu_heartbeat()[15:17] == b"\x1a\x00" and len(hidimu.mcu_heartbeat()) == 30
    assert [m for m, _ in hidimu.MCU_BOOTSTRAP] == [0x26, 0x57, 0x12, 0x02, 0x34, 0x35, 0x31]
    assert hidimu.hexstart(bytes(range(20)), 4) == "00 01 02 03 ... (20 bytes)"


class FakeXbx:
    """An XBX A01+ on socket pairs: interface 0 answers MCU frames; an IMU interface streams Air samples after the
    stream command, if streams(interface, mcu_awake) says so."""

    def __init__(self, streams):
        import threading
        self.streams = streams
        self.awake = False
        self.opened = []
        self.lock = threading.Lock()

    def nodes(self):
        return [(n, "/dev/fake%d" % n, 0x0442, "/sys/fake/1-1:1.%d" % n) for n in (0, 1, 2)]

    def open(self, path):
        import socket
        import threading
        num = int(path[-1])
        self.opened.append(num)
        a, b = socket.socketpair(socket.AF_UNIX, socket.SOCK_SEQPACKET)
        threading.Thread(target=self._serve, args=(num, b), daemon=True).start()
        return a.detach()

    def _serve(self, num, sock):
        import threading
        import time
        streaming = {"on": False}

        def samples():
            ts = 0
            while streaming["on"]:
                ts += 1000
                try:
                    sock.send(hidimu.air_report(ts, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
                except OSError:
                    return
                time.sleep(0.004)
        while True:
            try:
                data = sock.recv(64)
            except OSError:
                break
            if not data:
                break
            if num == 0 and data[0] == 0xFD:
                if data[15] == 0x31:
                    self.awake = True
                sock.send(hidimu.mcu_command(data[15], b"\x00"))
            elif data[0] == 0xAA and data[7] == 0x19:
                if data[8] == 1 and not streaming["on"] and self.streams(num, self.awake):
                    streaming["on"] = True
                    threading.Thread(target=samples, daemon=True).start()
                elif data[8] == 0:
                    streaming["on"] = False
        streaming["on"] = False
        sock.close()


def _run_reader(fake):
    import time
    lines = []
    got = []
    r = hidimu.AirReader(lambda *a: got.append(a), 0x0442, log=lines.append, nodes=fake.nodes, opener=fake.open)
    r.WAIT_S = 0.4
    r.start()
    end = time.monotonic() + 10
    while time.monotonic() < end and len(got) < 20:
        time.sleep(0.05)
    r.stop = True
    r.join(3)
    return r, lines, got


def test_xbx_wakes_the_mcu_first():
    if not hasattr(__import__("socket"), "AF_UNIX"):
        return
    fake = FakeXbx(lambda num, awake: num == 1 and awake)
    r, lines, got = _run_reader(fake)
    assert len(got) >= 20, lines
    assert r.decision == "interface 1 (/dev/fake1), with the MCU heartbeat", lines
    text = "\n".join(lines)
    assert "imu: fake1 is interface 1 (/sys/fake/1-1:1.1)" in text
    assert "no samples on interface" not in text and "MCU heartbeat running on interface 0" in text
    assert "imu: /dev/fake0 read fd " in text  # the MCU's answers, in hex
    assert fake.opened[:2] == [0, 1], fake.opened  # the heartbeat first, so no 6 s wait (0.7.2's tester logs)
    assert r._mcu is None and "imu: MCU heartbeat stopped" in text  # stopped with the reader


def test_xbx_tries_interface_2_last():
    if not hasattr(__import__("socket"), "AF_UNIX"):
        return
    fake = FakeXbx(lambda num, awake: num == 2)
    r, lines, got = _run_reader(fake)
    assert len(got) >= 20, lines
    assert r.decision == "interface 2 (/dev/fake2), with the MCU heartbeat", lines
    assert fake.opened[:3] == [0, 1, 2], fake.opened


def test_xbx_still_asks_interface_1_when_the_mcu_is_silent():
    if not hasattr(__import__("socket"), "AF_UNIX"):
        return

    class SilentMcu(FakeXbx):
        def _serve(self, num, sock):
            if num == 0:
                while sock.recv(64):
                    pass  # takes the commands, never answers
                return
            return FakeXbx._serve(self, num, sock)

    fake = SilentMcu(lambda num, awake: num == 1)
    r, lines, got = _run_reader(fake)
    assert len(got) >= 20, lines
    assert r.decision == "interface 1 (/dev/fake1)", lines
    assert "imu: MCU command 0x26 on interface 0: no answer" in lines
    assert fake.opened[:2] == [0, 1], fake.opened


def test_air_2_never_opens_another_interface():
    if not hasattr(__import__("socket"), "AF_UNIX"):
        return
    import time
    fake = FakeXbx(lambda num, awake: False)
    lines = []
    r = hidimu.AirReader(lambda *a: None, 0x0428, log=lines.append,
                         nodes=lambda: [(3, "/dev/fake3", 0x0428), (4, "/dev/fake4", 0x0428)], opener=fake.open)
    r.WAIT_S, r.RETRY_S = 0.3, 0.2
    r.start()
    time.sleep(1.2)
    r.stop = True
    r.join(3)
    assert fake.opened and set(fake.opened) == {3}, fake.opened
    assert r._mcu is None


def test_xbx_heartbeat_stops_once_samples_flow_and_raw_reports_are_recorded():
    if not hasattr(__import__("socket"), "AF_UNIX"):
        return
    import tempfile
    import time
    fake = FakeXbx(lambda num, awake: num == 1 and awake)  # once woken, it keeps streaming (as the tester's A01+)
    rec = os.path.join(tempfile.mkdtemp(), "imu-raw.log")
    lines = []
    got = []
    r = hidimu.AirReader(lambda *a: got.append(a), 0x0442, log=lines.append, nodes=fake.nodes, opener=fake.open,
                         record_path=rec)
    r.WAIT_S, r.HEARTBEAT_HOLD_S, r.RECORD_S = 0.4, 0.4, 0.3
    r.start()
    end = time.monotonic() + 10
    while time.monotonic() < end and not any("no longer needed" in x for x in lines):
        time.sleep(0.05)
    n = len(got)
    time.sleep(0.6)
    r.stop = True
    r.join(3)
    text = "\n".join(lines)
    assert "the MCU heartbeat is no longer needed, so it stopped" in text, text
    assert len(got) > n, "samples kept coming without the heartbeat"
    assert not r.keep_heartbeat and r._mcu is None
    body = open(rec).read().splitlines()
    assert body[0].startswith("# XREAL XBX A01+") and len(body) > 10, body[:3]
    ms, first = body[1].split(" ", 1)
    assert float(ms) >= 0 and len(bytes.fromhex(first.replace(" ", ""))) == 64
    assert "raw recording done" in text


def test_xbx_keeps_the_heartbeat_when_samples_need_it():
    if not hasattr(__import__("socket"), "AF_UNIX"):
        return
    import time

    class NeedsBeat(FakeXbx):
        def _serve(self, num, sock):
            if num == 0:
                return FakeXbx._serve(self, num, sock)
            import threading

            def samples():
                ts = 0
                while True:
                    ts += 1000
                    if fake.beat_alive():
                        try:
                            sock.send(hidimu.air_report(ts, (0.0, 0.0, 0.0), (0.0, 0.0, 1.0)))
                        except OSError:
                            return
                    time.sleep(0.004)
            while True:
                try:
                    data = sock.recv(64)
                except OSError:
                    return
                if not data:
                    return
                if data[0] == 0xAA and data[7] == 0x19 and data[8] == 1 and num == 1 and self.awake:
                    threading.Thread(target=samples, daemon=True).start()

    fake = NeedsBeat(None)
    lines = []
    r = hidimu.AirReader(lambda *a: None, 0x0442, log=lines.append, nodes=fake.nodes, opener=fake.open)
    fake.beat_alive = lambda: r._mcu is not None
    r.WAIT_S, r.HEARTBEAT_HOLD_S = 0.4, 0.3
    r.start()
    end = time.monotonic() + 20
    while time.monotonic() < end and not r.keep_heartbeat:
        time.sleep(0.1)
    r.stop = True
    r.join(3)
    assert r.keep_heartbeat, "\n".join(lines)
    assert "it stays on from now on" in "\n".join(lines)


def test_gaming_logs_where_the_head_points():
    import time
    from pocketxr import gaming
    lines = []

    class G:
        pass
    g = G()
    g.log = lines.append
    g.head = fusion.HeadFusion("aura")
    run(g.head, 1.0, (0.0, 0.0, 0.0))
    g.head_log_until = time.monotonic() + 5
    g.head_logged = 0.0
    gaming.Gaming._log_head(g, time.monotonic())
    gaming.Gaming._log_head(g, time.monotonic())  # once a second at most
    assert len(lines) == 1 and lines[0].startswith("gaming: head yaw 0.0, pitch 0.0 degrees"), lines
    assert "gravity 9.80 m/s2" in lines[0] and "1000 reports" in lines[0], lines


def test_panel_offers_the_fixes_only_when_they_apply():
    from pocketxr import gaming
    calls = []

    def run(args, timeout=20):
        calls.append(args)
        return 0, ""
    assert glasses.stop_xr_gaming(run) == (True, "")
    assert calls[-1] == ["systemctl", "--user", "disable", "--now", "xr-driver"]
    assert glasses.wayland_back(run)[0]
    assert calls[-1] == ["steamosctl", "set-default-desktop-session", "plasma.desktop"]
    assert glasses.desktop_session(lambda a, t=20: (0, "plasmax11.desktop\n")) == "plasmax11.desktop"
    assert glasses.desktop_session(lambda a, t=20: (1, "no")) is None
    assert glasses.xr_gaming_enabled(lambda a, t=20: (0, "enabled\n"))
    assert not glasses.xr_gaming_enabled(lambda a, t=20: (1, "disabled\n"))

    class G:
        pass
    g = G()
    g.other_driver, g.xr_gaming_enabled, g.session = [], False, "plasma.desktop"
    assert gaming.Gaming._actions(g) == []
    g.other_driver = [(345, "xrDriver")]
    g.session = "plasmax11.desktop"
    assert [a["op"] for a in gaming.Gaming._actions(g)] == ["stop_xr_gaming", "wayland_back"]
    g.other_driver, g.xr_gaming_enabled = [], True  # stopped but would start again at the next login
    assert [a["op"] for a in gaming.Gaming._actions(g)] == ["stop_xr_gaming", "wayland_back"]

    # the button's command, its log line and the panel's text, done and failed
    lines = []
    g.log = lines.append
    g._check_other_driver = lambda now: None
    real = glasses._run
    try:
        glasses.stop_xr_gaming.__defaults__ = (lambda a, t=20: (0, ""),)
        assert gaming.Gaming._do_action(g, "stop_xr_gaming").startswith("Done. XR Gaming's driver is stopped")
        assert "systemctl --user disable --now xr-driver): done" in lines[-1]
        glasses.wayland_back.__defaults__ = (lambda a, t=20: (1, "Failed to connect\nno daemon"),)
        assert gaming.Gaming._do_action(g, "wayland_back") == "That didn't work: no daemon"
        assert "plasma.desktop: failed" in lines[-1]
    finally:
        glasses.stop_xr_gaming.__defaults__ = (real,)
        glasses.wayland_back.__defaults__ = (real,)


def test_xr_gaming_is_found():
    import tempfile
    root = tempfile.mkdtemp()
    for pid, name in ((12, "bash"), (345, "xrDriver"), (7, "steam")):
        os.makedirs(os.path.join(root, str(pid)))
        with open(os.path.join(root, str(pid), "comm"), "w") as f:
            f.write(name + "\n")
    assert glasses.xr_gaming_running(root) == [(345, "xrDriver")]
    os.remove(os.path.join(root, "345", "comm"))
    assert glasses.xr_gaming_running(root) == []
    assert "XR Gaming" in glasses.xr_gaming_text()


def test_deck_buttons_never_open_the_glasses():
    import tempfile
    from pocketxr import deckpad
    root = tempfile.mkdtemp()
    for n, ev in ((2, "HID_ID=0003:00003318:00000442\n"), (4, "HID_ID=0003:00003318:00000442\n"),
                  (6, "HID_ID=0003:000028DE:00001205\n")):
        d = os.path.join(root, "hidraw%d" % n, "device")
        os.makedirs(d)
        with open(os.path.join(d, "uevent"), "w") as f:
            f.write(ev)
    real = deckpad.glob.glob
    deckpad.glob.glob = lambda pattern: sorted(real(os.path.join(root, "hidraw*")))
    try:
        assert deckpad.find_device() == ["/dev/hidraw6"]
    finally:
        deckpad.glob.glob = real


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
