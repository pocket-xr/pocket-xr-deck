"""Head tracking over USB HID: the XREAL Air family and VITURE glasses, rewritten from Pocket XR's AirImuProtocol and
VitureImuProtocol (each written there from public, MIT licensed protocol write-ups; see Pocket XR docs/LICENSES.md).

SteamOS gives the signed-in user every hidraw device (70-steam-jupiter-input.rules), so no setup is needed.
Writes to hidraw go out as they are when the first byte is not 0, which holds for both protocols' frames.

Air family: 64 byte reports on HID interface 3 (2 on the Air 2 Ultra, 1 on the XBX A01 and A01+, whose MCU is on 0);
command 0x19 with 1 starts the stream. The XBX may also want its MCU woken first (see AIR_XBX).
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
AIR_MODELS = {0x0424: "XREAL Air", 0x0428: "XREAL Air 2", 0x0432: "XREAL Air 2 Pro", 0x0426: "XREAL Air 2 Ultra",
              0x0440: "XREAL XBX A01", 0x0442: "XREAL XBX A01+"}
AIR_ULTRA = 0x0426
# XBX A01 and A01+: the IMU on interface 1, the MCU on 0 (wheaney's nrealAirLinuxDriver, hid_ids.c, MIT). A tester's
# A01+ (November 2026) showed three HID interfaces, 0 to 2, each with 64 byte reports. With 0.6.0 its interface 1 sent
# nothing at all after the stream command. The same library marks these two as needing an MCU "heartbeat": on interface
# 0, commands 0x26, 0x57, 0x12 (1), 0x02 (1), 0x34, 0x35, then 0x31 with the SDK version "3.1.1", then 0x1A with the
# time every 100 ms; its comment says this gates the IMU stream (sequence found by taowen's ar-glass-lib). So the
# reader tries interface 1 alone first, then with the heartbeat, then interface 2, and logs what each gives.
# Seen with 0.6.1 on that A01+: after the heartbeat, interface 1 sent its 0xAA 0x53 start packet and then samples, and it
# kept streaming with the heartbeat stopped. The tester's buttons were off afterwards. No command to hand the buttons
# back is known (none is guessed), so the heartbeat now runs only until samples flow, then stops.
# Seen with 0.7.2 on that A01+ (22 Nov 2026): every time the glasses appeared (after boot, and after each USB drop)
# interface 1 sent nothing for the whole 6 s wait, and samples came within a second of the heartbeat. So the XBX now
# gets the heartbeat first; interface 1 alone, then 2, are still tried if the MCU doesn't answer.
# A tester's report (Pierre Zammit, after 0.7.3): with Pocket XR disabled his A01+ stopped disconnecting; with it on,
# the whole USB-C link (display too) reset about every 10 minutes, with head tracking on and with Off. His first drop
# was the day after 0.6.2 began stopping the heartbeat 3 s after samples flowed. XREAL's driver keeps it going. The
# guess (not proven): once the SDK handshake is sent, the firmware resets the link when the SDK client goes quiet. So
# from 0.7.4 the heartbeat, once started, keeps going while the glasses are attached, through Off too, and stops only
# when the glasses go, the reader stops, or a write fails. The cost: on 0.6.1 his buttons were off while it ran.
# With 0.7.4 his head tracking stopped about 3 minutes in, every time, and then every write and open on the glasses
# timed out (ETIMEDOUT): the MCU had hung. The heartbeat loop sent the next heartbeat as soon as the MCU answered,
# hundreds a second, not one every 100 ms. 0.7.5 sends exactly one every 100 ms (HEARTBEAT_S), and logs the rate.
AIR_XBX = frozenset({0x0440, 0x0442})
# Letting go of the XBX for its own buttons (Gaming Mode's "Use the glasses' buttons"): with 0.7.6 his buttons came
# back only 1 min 20 s to 3 min 25 s after the heartbeat stopped and the files closed, when the glasses reset
# themselves. The handshake above puts the MCU in a mode it keeps until then. No public driver documents a command
# that ends it, so none is sent. 0.7.7 tried a USB reset (USBDEVFS_RESET): on his A01+ it went through but the glasses
# went on as before and their buttons came back 2 min 40 s later, so the reset is gone. A reset leaves the glasses
# powered, so their controller keeps running; so does deauthorising them in sysfs.
#
# Brightness while Pocket XR has the glasses, from Monado's XREAL Air driver (xreal_air_hmd.c, Tobias Frisch,
# BSL-1.0), whose control frames are the same as MCU frames here (mcu_command): R_BRIGHTNESS (0x03) answers status 0
# and the level in its data's first two bytes, W_BRIGHTNESS (0x04) takes the level as one byte, 0 to 7. A button
# press comes as P_BUTTON_PRESSED (0x6C05): data[0] the physical button, data[4] the action, data[8] the value; for
# brightness up (6) and down (7) the value is the brightness after the press. Monado wrote it for the Air, Air 2 and
# Air 2 Pro; whether the XBX takes the same messages is not known yet, so what it answers is logged.
MCU_R_BRIGHTNESS = 0x03
MCU_W_BRIGHTNESS = 0x04
MCU_P_BUTTON = 0x6C05
BUTTON_BRIGHTNESS_UP = 0x06
BUTTON_BRIGHTNESS_DOWN = 0x07
BRIGHTNESS_MAX = 7


def mcu_parse(frame):
    """(message id, data) of an MCU frame, or None. The data is as long as the frame's length field says (17 + data),
    without the report's padding."""
    frame = bytes(frame)
    if len(frame) < 22 or frame[0] != MCU_HEAD:
        return None
    length = struct.unpack_from("<H", frame, 5)[0]
    end = 5 + length if 17 <= length <= len(frame) - 5 else len(frame)
    return struct.unpack_from("<H", frame, 15)[0], frame[22:end]


def brightness_answer(data):
    """The level in an R_BRIGHTNESS answer's data, or None. Monado's Air answers a status (0) and the level; a tester's
    XBX A01+ (23 Nov 2026) answered the level alone: its frame's length field said 18, so one byte of data, 04."""
    if len(data) == 1 and data[0] <= BRIGHTNESS_MAX:
        return data[0]
    if len(data) >= 2 and data[0] == 0 and data[1] <= BRIGHTNESS_MAX:
        return data[1]
    return None


XBX_MCU = 0
MCU_HEAD = 0xFD
MCU_HEARTBEAT = 0x1A
MCU_SDK_VERSION = b"3.1.1"
MCU_BOOTSTRAP = ((0x26, b""), (0x57, b""), (0x12, b"\x01\x00\x00\x00"), (0x02, b"\x01\x00\x00\x00"),
                 (0x34, b""), (0x35, b""), (0x31, MCU_SDK_VERSION))


def air_interface(pid):
    """The HID interface that carries the IMU."""
    if pid == AIR_ULTRA:
        return 2
    if pid in AIR_XBX:
        return 1
    return 3


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


def mcu_command(msg_id, data=b"", timestamp=0):
    """An XREAL MCU frame: 0xFD, CRC-32 of what follows it from the length on, the length (17 + data), a timestamp,
    the message id, 5 reserved bytes, the data. Sent as it is, not padded (as hidapi's hid_write does there)."""
    length = 17 + len(data)
    body = struct.pack("<HQH", length, timestamp, msg_id) + bytes(5) + bytes(data)
    return bytes([MCU_HEAD]) + struct.pack("<I", zlib.crc32(body) & 0xFFFFFFFF) + body


def mcu_heartbeat():
    return mcu_command(MCU_HEARTBEAT, struct.pack("<Q", time.monotonic_ns()))


def hexstart(data, n=16):
    """The first bytes of a report in hex, for the log."""
    data = bytes(data)
    return data[:n].hex(" ") + (" ..." if len(data) > n else "") + f" ({len(data)} bytes)"


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
# A second Beast USB id, reported by a tester (November 2026) with the same layout: HID on interface 5.
VITURE_BEAST_1201 = 0x1201
BEAST_PRODUCTS = frozenset({VITURE_BEAST, VITURE_BEAST_1201})
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
    return [n[:3] for n in hidraw_map(vendor, product)]


def hidraw_map(vendor, product=None):
    """[(interface number, /dev/hidrawN, product id, sysfs path of the interface)]."""
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
            out.append((num, "/dev/" + os.path.basename(h), pid, iface_dir))
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
    """Reads the Air family's IMU. Each time the glasses appear it logs which hidraw node is which interface, and the
    first bytes of whatever the glasses' nodes send. On the XBX it first wakes the MCU on interface 0 (the heartbeat
    above), then asks interface 1, then interface 2, and logs which one streamed."""
    WAIT_S = 6.0         # how long an interface may stay silent before the next one is tried
    HEARTBEAT_S = 0.1    # the XBX MCU heartbeat's period, as XREAL's driver
    BEAT_LOG_S = 60.0    # how often the heartbeat's rate goes in the log
    RETRY_S = 10.0       # after every interface was silent
    LOGGED_PER_NODE = 12  # raw reports logged per node per try
    RECORD_S = 5.0          # every report in full, this long after the samples start (record_path)

    def __init__(self, on_report, pid, log=print, nodes=None, opener=None, record_path=None):
        super().__init__(on_report, log)
        self.pid = pid
        self.record_path = record_path  # a file for RECORD_S of raw reports, made once per reader
        self.recorded = False
        self.paused = False  # Gaming Mode's "off": no motion stream (the XBX heartbeat keeps going, see AIR_XBX)
        # "Use the glasses' buttons" (Gaming Mode's Quick Access): no stream, no heartbeat, every file on the glasses
        # closed, until it is set back. A tester (Pierre Zammit, 23 Nov 2026) asked for this: his XBX's buttons
        # (brightness) don't work while Pocket XR reads the glasses.
        self.released = False
        self.brightness = None  # 0 to BRIGHTNESS_MAX, from the glasses' MCU while the heartbeat runs
        self.brightness_answered = False  # the glasses answered R_BRIGHTNESS at all
        self._mcu_out = []  # MCU frames for the heartbeat's thread to write
        self.last_beat = None  # time.monotonic() of the last heartbeat written
        self.beats = 0  # heartbeats written
        self._nodes = nodes or (lambda: hidraw_map(0x3318, self.pid))
        self._open = opener or (lambda path: os.open(path, os.O_RDWR))
        self._logged = {}
        self._mcu = None  # (fd, thread, state) while the heartbeat runs
        self.decision = None

    @property
    def held(self):
        """Not reading the glasses for now: Off (paused) or let go (released)."""
        return self.paused or self.released

    # ---- raw bytes in the log ----
    def _note(self, dev, data, what="read"):
        n = self._logged.get(dev, 0)
        if n < self.LOGGED_PER_NODE:
            self._logged[dev] = n + 1
            self.log(f"imu: {dev} {what} {hexstart(data)}")

    def _read(self, fd, dev):
        data = os.read(fd, 64)
        self._note(dev, data)
        return data

    def _drain(self, fd, seconds=0.3, dev="?"):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            r, _, _ = select.select([fd], [], [], max(0.0, end - time.monotonic()))
            if not r:
                return
            self._read(fd, dev)

    def _wait_ok(self, seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end and not self.stop and not self.held:
            time.sleep(min(0.2, max(0.0, end - time.monotonic())))

    # ---- the XBX's MCU ----
    def _mcu_ask(self, fd, dev, msg_id, data=b""):
        """Sends one MCU command and waits up to 2 s for any 0xFD frame back (the library takes any as the answer)."""
        os.write(fd, mcu_command(msg_id, data))
        end = time.monotonic() + 2.0
        while time.monotonic() < end:
            r, _, _ = select.select([fd], [], [], max(0.0, end - time.monotonic()))
            if r and self._read(fd, dev)[:1] == bytes([MCU_HEAD]):
                return True
        return False

    def _mcu_running(self):
        return bool(self._mcu and self._mcu[1].is_alive())

    def _start_mcu(self, node):
        num, dev = node[0], node[1]
        if self._mcu_running():
            return True
        self._stop_mcu()  # one that ended on a failed write
        try:
            fd = self._open(dev)
        except OSError as e:
            self.log(f"imu: MCU {dev} not open ({e})")
            return False
        try:
            self._drain(fd, 0.2, dev)
            for msg_id, data in MCU_BOOTSTRAP:
                ok = self._mcu_ask(fd, dev, msg_id, data)
                self.log(f"imu: MCU command 0x{msg_id:02x} on interface {num}: {'answered' if ok else 'no answer'}")
                if not ok:
                    os.close(fd)
                    return False
            for _ in range(2):
                self._mcu_ask(fd, dev, MCU_HEARTBEAT, struct.pack("<Q", time.monotonic_ns()))
        except OSError as e:
            self.log(f"imu: MCU on {dev} failed ({e})")
            os.close(fd)
            return False
        state = {"run": True}
        self.brightness = None
        self.brightness_answered = False
        self._mcu_out.append(mcu_command(MCU_R_BRIGHTNESS))

        def beat():
            # One heartbeat every HEARTBEAT_S, as XREAL's driver sends it; answers and button reports are read in
            # between so they don't pile up (the first few logged). Up to 0.7.4 the next one went out as soon as an
            # answer came, which is within milliseconds: a flood (see AIR_XBX).
            next_at = time.monotonic()
            counted, since = 0, next_at
            while state["run"] and not self.stop:
                try:
                    now = time.monotonic()
                    if now >= next_at:
                        os.write(fd, mcu_heartbeat())
                        self.last_beat = now
                        self.beats += 1
                        counted += 1
                        next_at += self.HEARTBEAT_S
                        if next_at <= now:  # late (a slow write): no burst to catch up
                            next_at = now + self.HEARTBEAT_S
                    if now - since >= self.BEAT_LOG_S:
                        self.log(f"imu: MCU heartbeat: {counted / (now - since):.1f} a second")
                        counted, since = 0, now
                    while self._mcu_out:
                        os.write(fd, self._mcu_out.pop(0))
                    r, _, _ = select.select([fd], [], [], max(0.0, next_at - time.monotonic()))
                    if r:
                        self._mcu_frame(self._read(fd, dev))
                except OSError as e:
                    if state["run"]:
                        state["failed"] = True
                        self.log(f"imu: MCU heartbeat stopped ({e}); {self._beat_age()}")
                    return
        t = threading.Thread(target=beat, daemon=True, name="xbx-heartbeat")
        self._mcu = (fd, t, state)
        t.start()
        self.log(f"imu: MCU heartbeat running on interface {num} ({dev})")
        return True

    def set_brightness(self, level):
        """Sets the glasses' brightness (0 to BRIGHTNESS_MAX) through their MCU; False when the heartbeat isn't running
        (the MCU is only open then)."""
        if not self._mcu_running():
            return False
        level = max(0, min(BRIGHTNESS_MAX, int(level)))
        self._mcu_out.append(mcu_command(MCU_W_BRIGHTNESS, bytes([level])))
        self.brightness = level
        self.log(f"imu: brightness {level} of {BRIGHTNESS_MAX} sent")
        return True

    def _mcu_frame(self, frame):
        """What the MCU says while the heartbeat runs: the brightness, and the glasses' own buttons."""
        got = mcu_parse(frame)
        if not got:
            return
        msg, data = got
        if msg == MCU_R_BRIGHTNESS:
            self.brightness_answered = True
            level = brightness_answer(data)
            if level is not None:
                self.brightness = level
                self.log(f"imu: the glasses' brightness is {level} of {BRIGHTNESS_MAX} (answer {data.hex(' ')})")
            else:
                self.log(f"imu: brightness answer not understood ({data.hex(' ') or 'no data'})")
        elif msg == MCU_W_BRIGHTNESS:
            # What a set answers is not documented: logged whole, so a log shows whether the glasses took it
            self.log(f"imu: brightness set answered {data.hex(' ') or 'with no data'}")
        elif msg == MCU_P_BUTTON and len(data) >= 9:
            phys, action, value = data[0], data[4], data[8]
            self.log(f"imu: glasses button {phys}, action {action}, value {value}")
            if action in (BUTTON_BRIGHTNESS_UP, BUTTON_BRIGHTNESS_DOWN) and value <= BRIGHTNESS_MAX:
                # The value is the brightness after the press (Monado). Setting it again does nothing if the glasses
                # already took it, and sets it if they only reported the press.
                self.set_brightness(value)

    def _stop_mcu(self, why=""):
        if not self._mcu:
            return
        fd, t, state = self._mcu
        state["run"] = False
        t.join(1.0)
        try:
            os.close(fd)
        except OSError:
            pass
        self._mcu = None
        if not state.get("failed"):  # one that ended on a failed write said so then
            self.log("imu: MCU heartbeat stopped" + (f" ({why})" if why else ""))

    # ---- the IMU ----
    def _try_imu(self, node, seconds):
        """Opens an interface, asks for the stream and waits for 0x01 0x02 samples. Returns the open fd once they
        come, else None."""
        num, dev = node[0], node[1]
        try:
            fd = self._open(dev)
        except OSError as e:
            self.log(f"imu: {dev} not open ({e})")
            return None
        try:
            self._drain(fd, 0.3, dev)
            os.write(fd, air_stream(True))
            self.log(f"imu: Air stream asked for on {dev} (interface {num})")
            end = time.monotonic() + seconds
            while time.monotonic() < end and not self.stop and not self.held:
                r, _, _ = select.select([fd], [], [], max(0.0, min(0.5, end - time.monotonic())))
                if r and air_parse(self._read(fd, dev)):
                    return fd
            if not self.stop and not self.held:
                self.log(f"imu: no samples on interface {num} in {seconds:g} s")
        except OSError as e:
            self.log(f"imu: {dev} failed ({e})")
        try:
            os.write(fd, air_stream(False))
        except OSError:
            pass
        os.close(fd)
        return None

    def _find(self, nodes):
        """(fd, node) of the interface that streams, tried in the order the class docstring gives, else (None, None)."""
        for n in nodes:
            self.log(f"imu: {os.path.basename(n[1])} is interface {n[0]}" + (f" ({n[3]})" if len(n) > 3 else ""))
        self._logged = {}
        by_num = {n[0]: n for n in nodes}
        first = by_num.get(air_interface(self.pid))
        if self.pid in AIR_XBX and XBX_MCU in by_num and not self.stop and not self.held:
            self._start_mcu(by_num[XBX_MCU])
        if first:
            fd = self._try_imu(first, self.WAIT_S)
            if fd is not None:
                return fd, first
        if self.pid not in AIR_XBX or self.stop or self.held:
            return None, None
        for num in sorted(by_num):
            if num in (XBX_MCU, air_interface(self.pid)) or self.stop or self.held:
                continue
            fd = self._try_imu(by_num[num], self.WAIT_S)
            if fd is not None:
                return fd, by_num[num]
        return None, None

    def _start_recording(self):
        if not self.record_path or self.recorded:
            return None
        self.recorded = True
        try:
            os.makedirs(os.path.dirname(self.record_path), exist_ok=True)
            f = open(self.record_path, "w")
        except OSError as e:
            self.log(f"imu: no raw recording ({e})")
            return None
        f.write(f"# {AIR_MODELS.get(self.pid, hex(self.pid))}: every report for {self.RECORD_S:g} s, "
                "ms since the first, then the 64 bytes in hex\n")
        self.log(f"imu: recording {self.RECORD_S:g} s of raw reports in {os.path.basename(self.record_path)}")
        return f

    def _stream(self, fd, dev, first_report=None):
        clock = AirTimestamp()
        quiet = 0
        started = time.monotonic()
        rec = self._start_recording()
        rec_end = started + self.RECORD_S
        while not self.stop and not self.held:
            now = time.monotonic()
            if rec and now >= rec_end:
                rec.close()
                rec = None
                self.log("imu: raw recording done")
            r, _, _ = select.select([fd], [], [], 2.0)
            if not r:
                quiet += 1
                if quiet >= 3:
                    self.log("imu: samples stopped for 6 s; looking again")
                    if rec:
                        rec.close()
                    return
                self.log("imu: no Air reports for 2 s; asking again")
                os.write(fd, air_stream(True))
                continue
            data = self._read(fd, dev)
            if rec:
                rec.write(f"{(time.monotonic() - started) * 1000:.1f} {bytes(data).hex(' ')}\n")
            rep = air_parse(data)
            if rep:
                quiet = 0
                ts, g, a = rep
                self.reports += 1
                self.on_report(clock.to_ns(ts), g, a)

    def run(self):
        while not self.stop:
            if self.released:
                self._stop_mcu("let go for the glasses' own buttons")
            if self.held:
                time.sleep(0.5)
                continue
            nodes = self._nodes()
            if not nodes:
                time.sleep(2.0)
                continue
            fd, node = self._find(nodes)
            if fd is None:
                if not self.stop and not self.held:
                    self.log(f"imu: no interface sent samples; trying again in {self.RETRY_S:g} s")
                self._wait_ok(self.RETRY_S)
                continue
            dev = node[1]
            self.decision = f"interface {node[0]} ({dev})" + (", with the MCU heartbeat" if self._mcu else "")
            self.log(f"imu: Air samples on {self.decision}")
            self.connected_to = dev
            lost = False
            try:
                self._stream(fd, dev)
            except OSError as e:
                lost = True
                self.log(f"imu: Air link lost ({e}); {self._beat_age()}")
            finally:
                try:
                    os.write(fd, air_stream(False))
                except OSError:
                    pass
                os.close(fd)
                self.connected_to = None
                if lost:
                    self._stop_mcu("the glasses went")
            self._wait_ok(1.0)
        self._stop_mcu("Pocket XR stopped reading the glasses")

    def _beat_age(self):
        """For the log of a USB drop: how long since the last MCU heartbeat went out."""
        if self.last_beat is None:
            return "no MCU heartbeat sent"
        return (f"last MCU heartbeat {time.monotonic() - self.last_beat:.1f} s before"
                + ("" if self._mcu_running() else ", and it was not running"))


def beast_first(nodes):
    """(interface, path, product) nodes in the order tried: the Beast's motion sensor is HID interface 5, so a Beast's
    interface 5 comes first; on other models every interface is tried, lowest first."""
    return sorted(nodes, key=lambda n: (not (n[2] in BEAST_PRODUCTS and n[0] == 5), n[0]))


class VitureReader(_HidReader):
    """axes: "beast" for the Beast (the sensor sends x right, y down, z front: as the One), else as the sensor sends."""

    def __init__(self, on_report, pid, log=print):
        super().__init__(on_report, log)
        self.pid = pid

    def _candidates(self):
        nodes = [n for n in hidraw_nodes(VITURE) if n[2] != VITURE_MICROPHONE]
        return beast_first(nodes)

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
