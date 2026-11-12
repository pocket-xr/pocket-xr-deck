"""Head tracking over USB HID: the XREAL Air family and VITURE glasses, rewritten from Pocket XR's AirImuProtocol and
VitureImuProtocol (each written there from public, MIT licensed protocol write-ups; see Pocket XR docs/LICENSES.md).

SteamOS gives the signed-in user every hidraw device (70-steam-jupiter-input.rules), so no setup is needed.
Writes to hidraw go out as they are when the first byte is not 0, which holds for both protocols' frames.

Air family: 64 byte reports on HID interface 3 (2 on the Air 2 Ultra); command 0x19 with 1 starts the stream.
VITURE: frames with preamble 0x0010; 0x0301 (raw stream, rate index 2 = 120 Hz) starts it, 0x7309 carries a sample.
Pocket XR found the Beast takes no new command while an answer of its own is unread, so what is waiting is read first.
"""
import glob
import math
import os
import select
import struct
import threading
import time
import zlib

G = 9.81
DEG = math.pi / 180

# ---------------- XREAL Air family ----------------
AIR_MODELS = {0x0424: "XREAL Air", 0x0428: "XREAL Air 2", 0x0432: "XREAL Air 2 Pro", 0x0426: "XREAL Air 2 Ultra"}
AIR_ULTRA = 0x0426


def air_interface(pid):
    return 2 if pid == AIR_ULTRA else 3


def air_command(cmd_id, data=b""):
    p = bytearray(64)
    p[0] = 0xAA
    length = len(data) + 3
    p[5] = length & 0xFF
    p[6] = (length >> 8) & 0xFF
    p[7] = cmd_id
    p[8:8 + len(data)] = data
    crc = zlib.crc32(bytes(p[5:5 + length])) & 0xFFFFFFFF
    p[1:5] = struct.pack("<I", crc)
    return bytes(p)


def air_stream(on=True):
    return air_command(0x19, bytes([1 if on else 0]))


def _i24(p, i):
    v = p[i] | (p[i + 1] << 8) | (p[i + 2] << 16)
    return v - (1 << 24) if v & 0x800000 else v


def air_parse(p):
    """(timestamp, gyro rad/s, accel m/s2) in head axes (x right, y up, z back), or None."""
    if len(p) < 0x2A or p[0] != 0x01 or p[1] != 0x02:
        return None
    g_mul = struct.unpack_from("<H", p, 0x0C)[0]
    g_div = struct.unpack_from("<i", p, 0x0E)[0]
    a_mul = struct.unpack_from("<H", p, 0x1B)[0]
    a_div = struct.unpack_from("<i", p, 0x1D)[0]
    if g_div == 0 or a_div == 0:
        return None
    gs = g_mul / g_div * DEG
    as_ = a_mul / a_div * G
    g = (_i24(p, 0x12) * gs, _i24(p, 0x15) * gs, _i24(p, 0x18) * gs)
    a = (_i24(p, 0x21) * as_, _i24(p, 0x24) * as_, _i24(p, 0x27) * as_)
    ts = struct.unpack_from("<Q", p, 0x04)[0]

    # The sensor's axes are x left, y back, z up (as ar-drivers-rs maps them): head x = -x, y = z, z = y.
    def head(v):
        return (-v[0], v[2], v[1])
    return ts, head(g), head(a)


def air_report(ts, gyro_deg_s, accel_g, div=8192):
    """A report in the sensor's own axes, for the tests."""
    p = bytearray(64)
    p[0], p[1] = 0x01, 0x02
    struct.pack_into("<Q", p, 0x04, ts)
    struct.pack_into("<Hi", p, 0x0C, 1, div)
    struct.pack_into("<Hi", p, 0x1B, 1, div)
    for k, v in enumerate(gyro_deg_s):
        p[0x12 + 3 * k:0x15 + 3 * k] = (round(v * div) & 0xFFFFFF).to_bytes(3, "little")
    for k, v in enumerate(accel_g):
        p[0x21 + 3 * k:0x24 + 3 * k] = (round(v * div) & 0xFFFFFF).to_bytes(3, "little")
    return bytes(p)


class AirTimestamp:
    """Ns per unit, decided from the first step: at about 1 kHz a step under 50 000 can only be microseconds."""

    def __init__(self):
        self.last = None
        self.scale = 1
        self.decided = False

    def to_ns(self, raw):
        if not self.decided and self.last is not None and raw > self.last:
            self.scale = 1000 if raw - self.last < 50_000 else 1
            self.decided = True
        self.last = raw
        return raw * self.scale


# ---------------- VITURE ----------------
VITURE = 0x35CA
VITURE_BEAST = 0x1211
VITURE_MICROPHONE = 0x1102
V_PREAMBLE = 0x0010
V_HEADER = 8
V_IMU_CONTROL = 0x0301
V_RAW = 0x7309
V_RATE_120 = 2


def v_frame(msg_id, payload):
    p = struct.pack("<HHHH", V_PREAMBLE, msg_id, len(payload), sum(payload) & 0xFFFF) + bytes(payload)
    return p + bytes(64 - len(p))


def v_start():
    return v_frame(V_IMU_CONTROL, bytes([0x02, V_RATE_120]))


def v_stop():
    return v_frame(V_IMU_CONTROL, bytes([0x00, 0]))


def v_read(p):
    """(message id, payload) or None when the preamble, length or checksum is wrong."""
    if len(p) < V_HEADER:
        return None
    pre, mid, n, ck = struct.unpack_from("<HHHH", p, 0)
    if pre != V_PREAMBLE or V_HEADER + n > len(p):
        return None
    payload = bytes(p[V_HEADER:V_HEADER + n])
    if sum(payload) & 0xFFFF != ck:
        return None
    return mid, payload


def v_parse_raw(payload):
    """(counter, gyro rad/s, accel g) in the sensor's axes, or None."""
    if len(payload) < 34:
        return None
    counter = struct.unpack_from("<I", payload, 4)[0]
    v = struct.unpack_from("<6f", payload, 10)
    if not all(math.isfinite(x) for x in v):
        return None
    return counter, v[0:3], v[3:6]


def v_raw(counter, gyro, accel_g):
    p = bytearray(46)
    struct.pack_into("<I", p, 4, counter)
    struct.pack_into("<6f", p, 10, *gyro, *accel_g)
    return v_frame(V_RAW, bytes(p))


class VitureClock:
    """A sample carries only a counter: the step is measured against the Deck's clock over the first 120 samples."""

    def __init__(self, hz=120.0):
        self.nominal = 1e9 / hz
        self.first = None
        self.first_ns = 0
        self.last = -1
        self.period = self.nominal
        self.learned = False

    def to_ns(self, counter, host_ns):
        if self.first is None or counter < self.last:
            self.first, self.first_ns, self.learned, self.period = counter, host_ns, False, self.nominal
        self.last = counter
        steps = counter - self.first
        if not self.learned and steps >= 120:
            m = (host_ns - self.first_ns) / steps
            if self.period / 20 < m < self.period * 20:
                self.period = m
            self.learned = True
        return self.first_ns + round(steps * self.period)


# ---------------- finding the device ----------------
def hidraw_nodes(vendor, product=None):
    """[(interface number, /dev/hidrawN, product id)] for a vendor's USB HID devices."""
    out = []
    for h in sorted(glob.glob("/sys/class/hidraw/hidraw*")):
        dev = os.path.realpath(os.path.join(h, "device"))
        iface_dir = os.path.dirname(dev)  # .../1-1:1.3
        usb_dir = os.path.dirname(iface_dir)
        try:
            vid = int(open(os.path.join(usb_dir, "idVendor")).read(), 16)
            pid = int(open(os.path.join(usb_dir, "idProduct")).read(), 16)
            num = int(open(os.path.join(iface_dir, "bInterfaceNumber")).read(), 16)
        except (OSError, ValueError):
            continue
        if vid == vendor and (product is None or pid == product):
            out.append((num, "/dev/" + os.path.basename(h), pid))
    return out


class _HidReader(threading.Thread):
    def __init__(self, on_report, log):
        super().__init__(daemon=True)
        self.on_report = on_report
        self.log = log
        self.stop = False
        self.connected_to = None
        self.reports = 0

    def _drain(self, fd, seconds=0.3):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            r, _, _ = select.select([fd], [], [], max(0.0, end - time.monotonic()))
            if not r:
                return
            os.read(fd, 64)


class AirReader(_HidReader):
    def __init__(self, on_report, pid, log=print):
        super().__init__(on_report, log)
        self.pid = pid

    def run(self):
        while not self.stop:
            nodes = [n for n in hidraw_nodes(0x3318, self.pid) if n[0] == air_interface(self.pid)]
            if not nodes:
                time.sleep(2.0)
                continue
            dev = nodes[0][1]
            try:
                fd = os.open(dev, os.O_RDWR)
            except OSError as e:
                self.log(f"imu: {dev} not open ({e})")
                time.sleep(3.0)
                continue
            clock = AirTimestamp()
            try:
                self._drain(fd)
                os.write(fd, air_stream(True))
                self.connected_to = dev
                self.log(f"imu: Air stream asked for on {dev}")
                while not self.stop:
                    r, _, _ = select.select([fd], [], [], 2.0)
                    if not r:
                        self.log("imu: no Air reports for 2 s; asking again")
                        os.write(fd, air_stream(True))
                        continue
                    rep = air_parse(os.read(fd, 64))
                    if rep:
                        ts, g, a = rep
                        self.reports += 1
                        self.on_report(clock.to_ns(ts), g, a)
            except OSError as e:
                self.log(f"imu: Air link lost ({e})")
            finally:
                try:
                    os.write(fd, air_stream(False))
                except OSError:
                    pass
                os.close(fd)
                self.connected_to = None
            time.sleep(1.0)


class VitureReader(_HidReader):
    """axes: "beast" for the Beast (the sensor sends x right, y down, z front: as the One), else as the sensor sends."""

    def __init__(self, on_report, pid, log=print):
        super().__init__(on_report, log)
        self.pid = pid

    def _candidates(self):
        nodes = [n for n in hidraw_nodes(VITURE) if n[2] != VITURE_MICROPHONE]
        # The Beast's motion sensor is HID interface 5; on other models every interface is tried.
        nodes.sort(key=lambda n: (not (n[2] == VITURE_BEAST and n[0] == 5), n[0]))
        return nodes

    def run(self):
        while not self.stop:
            found = False
            for num, dev, pid in self._candidates():
                if self.stop:
                    return
                if self._try(dev):
                    found = True
                    break
            if not found:
                time.sleep(3.0)

    def _try(self, dev):
        try:
            fd = os.open(dev, os.O_RDWR)
        except OSError as e:
            self.log(f"imu: {dev} not open ({e})")
            return False
        clock = VitureClock()
        streaming = False
        try:
            self._drain(fd)  # an answer of the glasses' own still waiting blocks a new command
            os.write(fd, v_start())
            deadline = time.monotonic() + 2.0
            while not self.stop:
                r, _, _ = select.select([fd], [], [], 2.0)
                if not r:
                    if streaming:
                        self.log("imu: VITURE samples stopped")
                    return streaming
                f = v_read(os.read(fd, 64))
                if f is None or f[0] != V_RAW:
                    if not streaming and time.monotonic() > deadline:
                        return False
                    continue
                s = v_parse_raw(f[1])
                if s is None:
                    continue
                if not streaming:
                    streaming = True
                    self.connected_to = dev
                    self.log(f"imu: VITURE samples on {dev}")
                counter, g, a = s
                self.reports += 1
                self.on_report(clock.to_ns(counter, time.monotonic_ns()), g, (a[0] * G, a[1] * G, a[2] * G))
            return streaming
        except OSError as e:
            self.log(f"imu: VITURE link lost ({e})")
            return streaming
        finally:
            try:
                os.write(fd, v_stop())
                self._drain(fd, 0.2)
            except OSError:
                pass
            os.close(fd)
            self.connected_to = None
