"""The XREAL control link, 169.254.2.1:52999, rewritten from Pocket XR's GlassesWire.

Frame: u16 type, u32 body length (both big endian), body. An RPC body is a u32 big endian id
(top bit set on requests) and a protobuf with the request in field 3 and the answer in field 4
(answer field 1 = result, 0 for done; field 2 = the value; field 3 = a second value).

Only commands Pocket XR has proven on the Aura are here, and SENDABLE refuses anything else.
Never 10079 (EDID), never 10325 to 10328 (firmware update), never a guessed id.
"""
import socket
import struct
import threading
import time

HOST = "169.254.2.1"
PORT = 52999

HEARTBEAT = 10000
STEREO_GET, STEREO_SET = 10273, 10274  # 2D (0) / 3D side by side (1)
ULTRAWIDE_GET, ULTRAWIDE_SET = 10277, 10278
SIZE_RANGE, SIZE_GET, SIZE_SET = 10396, 10397, 10398
ANCHOR_GET, ANCHOR_SET = 10404, 10405  # Spatial Anchor
SERIAL_GET = 10025

SENDABLE = {HEARTBEAT, STEREO_GET, STEREO_SET, ULTRAWIDE_GET, ULTRAWIDE_SET, SIZE_RANGE, SIZE_GET, SIZE_SET,
            ANCHOR_GET, ANCHOR_SET, SERIAL_GET}
FORBIDDEN = {10079, 10325, 10326, 10327, 10328}
assert not (SENDABLE & FORBIDDEN)


# ---------- protobuf, just enough ----------
def _varint(v):
    out = bytearray()
    while True:
        b = v & 0x7F
        v >>= 7
        if v:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def pb_varint(field, v):
    """Zero is left out, as proto3 and Pocket XR's ProtoWriter do: "off" is an empty request."""
    return b"" if v == 0 else _varint(field << 3) + _varint(v)


def pb_float(field, f):
    raw = struct.pack("<f", f)
    return b"" if raw == bytes(4) else _varint((field << 3) | 5) + raw


def pb_message(field, body):
    return _varint((field << 3) | 2) + _varint(len(body)) + body


def pb_parse(b):
    """{field: [values]}: varints as int, fixed32 as ('f32', float), length-delimited as bytes. None if malformed."""
    out = {}
    i = 0

    def varint():
        nonlocal i
        v = 0
        shift = 0
        while i < len(b):
            c = b[i]
            i += 1
            v |= (c & 0x7F) << shift
            if not c & 0x80:
                return v
            shift += 7
        raise ValueError

    try:
        while i < len(b):
            key = varint()
            field, wire = key >> 3, key & 7
            if wire == 0:
                val = varint()
            elif wire == 5:
                val = ("f32", struct.unpack_from("<f", b, i)[0])
                i += 4
            elif wire == 1:
                val = ("f64", struct.unpack_from("<d", b, i)[0])
                i += 8
            elif wire == 2:
                n = varint()
                val = bytes(b[i:i + n])
                i += n
            else:
                return None
            out.setdefault(field, []).append(val)
    except (ValueError, struct.error):
        return None
    return out


# ---------- frames ----------
def header(mtype, length):
    return struct.pack(">HI", mtype, length)


def heartbeat(t1_ns):
    body = bytearray(33)
    body[0] = 1  # request
    struct.pack_into("<Q", body, 1, t1_ns & 0xFFFFFFFFFFFFFFFF)
    return header(HEARTBEAT, len(body)) + bytes(body)


def rpc_id(counter):
    return ((counter + 1) & 0x7FFFFFFF) | 0x80000000


def rpc(mtype, rid, request=b""):
    if mtype not in SENDABLE or mtype in FORBIDDEN:
        raise ValueError(f"{mtype} is not a command this app may send")
    pb = pb_message(3, request)
    return header(mtype, 4 + len(pb)) + struct.pack(">I", rid) + pb


def stereo_set(rid, sbs):
    return rpc(STEREO_SET, rid, pb_varint(1, 1 if sbs else 0))


def ultrawide_set(rid, on):
    return rpc(ULTRAWIDE_SET, rid, pb_varint(1, 1 if on else 0))


def anchor_set(rid, on):
    return rpc(ANCHOR_SET, rid, pb_varint(1, 1 if on else 0))


def size_set(rid, size):
    return rpc(SIZE_SET, rid, pb_float(1, size))


class Answer:
    def __init__(self, mtype, rid, fields):
        self.type = mtype
        self.id = rid
        resp = pb_parse((fields.get(4) or [b""])[-1]) if fields else None
        resp = resp or {}
        self.result = resp.get(1, [0])[-1]
        self.value = self._num(resp.get(2))
        self.value3 = self._num(resp.get(3))
        self.raw = resp

    @staticmethod
    def _num(vals):
        if not vals:
            return None
        v = vals[-1]
        if isinstance(v, tuple):
            return v[1]
        if isinstance(v, int):
            return v
        return None

    def __repr__(self):
        return f"{self.type} result {self.result} value {self.value} value3 {self.value3}"


class Framer:
    def __init__(self):
        self.buf = bytearray()

    def feed(self, chunk):
        self.buf += chunk
        out = []
        pos = 0
        b = self.buf
        while len(b) - pos >= 6:
            mtype, n = struct.unpack_from(">HI", b, pos)
            if n > 1 << 20:
                pos += 1
                continue
            if len(b) - pos < 6 + n:
                break
            body = bytes(b[pos + 6:pos + 6 + n])
            pos += 6 + n
            if mtype != HEARTBEAT and n >= 4:
                rid = struct.unpack_from(">I", body, 0)[0]
                if not rid & 0x80000000:  # answers have the top bit clear
                    out.append(Answer(mtype, rid, pb_parse(body[4:]) or {}))
        del self.buf[:pos]
        return out


class Link:
    """One open control link: a heartbeat every 50 ms (as Pocket XR does), and request() waits for its answer."""

    def __init__(self, host=HOST, log=print):
        self.log = log
        self.sock = socket.create_connection((host, PORT), timeout=3)
        self.sock.settimeout(0.2)
        self.counter = 0
        self.lock = threading.Lock()
        self.answers = {}
        self.closed = False
        self.framer = Framer()
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._beat, daemon=True).start()

    def _send(self, data):
        with self.lock:
            self.sock.sendall(data)

    def _beat(self):
        while not self.closed:
            try:
                self._send(heartbeat(time.monotonic_ns()))
            except OSError:
                break
            time.sleep(0.05)

    def _reader(self):
        while not self.closed:
            try:
                chunk = self.sock.recv(65536)
            except socket.timeout:
                continue
            except OSError:
                break
            if not chunk:
                break
            for a in self.framer.feed(chunk):
                self.answers[a.id & 0x7FFFFFFF] = a
        self.closed = True

    def request(self, build, *args, wait=3.0):
        rid = rpc_id(self.counter)
        self.counter += 1
        data = build(rid, *args)
        mtype = struct.unpack_from(">H", data, 0)[0]
        self._send(data)
        end = time.monotonic() + wait
        while time.monotonic() < end and not self.closed:
            a = self.answers.pop(rid & 0x7FFFFFFF, None)
            if a is not None:
                self.log(f"  {mtype} -> {a}")
                return a
            time.sleep(0.01)
        self.log(f"  {mtype} -> no answer")
        return None

    def get(self, mtype, wait=3.0):
        return self.request(lambda rid: rpc(mtype, rid), wait=wait)

    def close(self):
        self.closed = True
        try:
            self.sock.close()
        except OSError:
            pass
