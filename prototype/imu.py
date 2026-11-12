"""The XREAL One family and Aura sensor stream: TCP 169.254.2.1:52998, read only.

Written from Pocket XR's notes on the public protocol (Pocket XR docs/SPATIAL.md 1.1 and
docs/LICENSES.md credit the MIT projects that describe it). Nothing is ever sent to the glasses.

Frame: magic 0x28 0x36 (some firmware 0x27 0x36), u32 big endian body length, body.
Sensor reports have a 128 byte little endian body:
  0x00 device id u64, 0x08 timestamp ns u64, 0x18 type u32 (0x0B IMU, 0x04 magnetometer),
  0x1C gyro xyz f32 rad/s, 0x28 accel xyz f32, 0x34 mag xyz f32, 0x40 temperature f32.
"""
import socket
import struct
import threading
import time

HOST = "169.254.2.1"
ECM_HOST = "169.254.1.1"
PORT = 52998
HEADER = 6
BODY = 128
TYPE_IMU = 0x0B
TYPE_MAG = 0x04
_MAGIC0 = (0x28, 0x27)


class Framer:
    """Splits the byte stream into reports, skipping bytes until a magic, as Pocket XR does."""

    def __init__(self):
        self.buf = bytearray()
        self.reports = 0
        self.imu = 0
        self.dropped = 0
        self.bad_length = 0

    def feed(self, chunk):
        self.buf += chunk
        out = []
        b = self.buf
        pos = 0
        n = len(b)
        while n - pos >= HEADER:
            if not (b[pos] in _MAGIC0 and b[pos + 1] == 0x36):
                pos += 1
                self.dropped += 1
                continue
            length = struct.unpack_from(">I", b, pos + 2)[0]
            if length != BODY:
                pos += 1
                self.bad_length += 1
                continue
            if n - pos < HEADER + BODY:
                break
            at = pos + HEADER
            rtype = struct.unpack_from("<I", b, at + 0x18)[0]
            if rtype == TYPE_IMU:
                ts = struct.unpack_from("<Q", b, at + 0x08)[0]
                g = struct.unpack_from("<3f", b, at + 0x1C)
                a = struct.unpack_from("<3f", b, at + 0x28)
                temp = struct.unpack_from("<f", b, at + 0x40)[0]
                out.append((ts, g, a, temp))
                self.imu += 1
            self.reports += 1
            pos += HEADER + BODY
        del self.buf[:pos]
        if len(self.buf) > 65536:
            self.dropped += len(self.buf) - 65536
            del self.buf[:-65536]
        return out


def encode_report(ts_ns, gyro, accel, rtype=TYPE_IMU, magic0=0x28):
    """One frame, for tests and the fake source."""
    body = bytearray(BODY)
    struct.pack_into("<QQ", body, 0, 1, ts_ns)
    struct.pack_into("<I", body, 0x18, rtype)
    struct.pack_into("<3f", body, 0x1C, *gyro)
    struct.pack_into("<3f", body, 0x28, *accel)
    struct.pack_into("<f", body, 0x40, 30.0)
    return bytes([magic0, 0x36]) + struct.pack(">I", BODY) + bytes(body)


class ImuReader(threading.Thread):
    """Connects, reads, and hands each IMU report to on_report(ts_ns, gyro, accel). Reconnects on loss."""

    def __init__(self, on_report, hosts=(HOST, ECM_HOST), log=print):
        super().__init__(daemon=True)
        self.on_report = on_report
        self.hosts = hosts
        self.log = log
        self.connected_to = None
        self.stop = False
        self.framer = Framer()

    def run(self):
        delay = 1.0
        while not self.stop:
            for host in self.hosts:
                if self.stop:
                    return
                try:
                    s = socket.create_connection((host, PORT), timeout=3)
                except OSError as e:
                    self.log(f"imu: {host}:{PORT} not reachable ({e})")
                    continue
                self.connected_to = host
                self.log(f"imu: reading {host}:{PORT}")
                delay = 1.0
                try:
                    s.settimeout(3)
                    s.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    while not self.stop:
                        chunk = s.recv(65536)
                        if not chunk:
                            raise OSError("closed by the glasses")
                        for ts, g, a, _t in self.framer.feed(chunk):
                            self.on_report(ts, g, a)
                except OSError as e:
                    self.log(f"imu: link lost ({e})")
                finally:
                    self.connected_to = None
                    s.close()
            time.sleep(delay)
            delay = min(delay * 2, 8.0)


class FakeImu(threading.Thread):
    """A slow head turn left and right, for a run without glasses."""

    def __init__(self, on_report):
        super().__init__(daemon=True)
        self.on_report = on_report
        self.connected_to = "fake"
        self.stop = False
        self.framer = Framer()

    def run(self):
        import math
        t0 = time.monotonic_ns()
        while not self.stop:
            t = (time.monotonic_ns() - t0) / 1e9
            yaw_rate = 0.6 * math.cos(t * 0.8) if t > 2 else 0.0
            data = encode_report(time.monotonic_ns(), (0.0, yaw_rate, 0.0), (0.0, 9.8, 0.0))
            for ts, g, a, _ in self.framer.feed(data):
                self.on_report(ts, g, a)
            time.sleep(0.001)
