"""gamescope's reshade interface, spoken over its Wayland socket in Gaming Mode.

gamescope (Steam's compositor in Gaming Mode) offers a small Wayland interface, gamescope_reshade (version 1, MIT
licensed protocol by Wayne Heaney): load a ReShade effect, enable and disable it, and set the effect's runtime values.
SteamOS has no Python Wayland library, so the few messages needed are written here by hand.

The Wayland wire format: each message is the object's id (u32), then the message size in bytes (high 16 bits,
header included) and its opcode (low 16 bits), then the arguments, each padded to 4 bytes: u32 as is, a string as its
length with the trailing NUL then the bytes, an array as its length then the bytes.

    wl_display (object 1)  requests: 0 sync(new_id callback), 1 get_registry(new_id registry)
                           events:   0 error(object, code, message), 1 delete_id(id)
    wl_registry            requests: 0 bind(name, interface, version, new_id)
                           events:   0 global(name, interface, version), 1 global_remove(name)
    wl_callback            events:   0 done(serial)
    gamescope_reshade      requests: 0 destroy, 1 set_effect(path), 2 enable_effect,
                                     3 set_uniform_variable(key, array value), 4 disable_effect
                           events:   0 effect_ready(path)
"""
import os
import select
import socket
import struct


def _string(s):
    b = s.encode() + b"\0"
    return struct.pack("<I", len(b)) + b + b"\0" * (-len(b) % 4)


def _array(b):
    return struct.pack("<I", len(b)) + b + b"\0" * (-len(b) % 4)


def _read_string(data, at):
    n = struct.unpack_from("<I", data, at)[0]
    s = data[at + 4:at + 4 + n - 1].decode(errors="replace")
    return s, at + 4 + n + (-n % 4)


def socket_path():
    """gamescope's Wayland socket, when Gaming Mode is running; None otherwise. The socket file can outlive its
    gamescope, so one counts only when it answers a connection."""
    run = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    for name in ("gamescope-0", "gamescope-1"):
        p = os.path.join(run, name)
        if not os.path.exists(p):
            continue
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            s.settimeout(0.5)
            s.connect(p)
            return p
        except OSError:
            continue
        finally:
            s.close()
    return None


class Reshade:
    """One connection to gamescope with its reshade interface bound."""

    def __init__(self, path, log=print):
        self.log = log
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.connect(path)
        self.next_id = 2
        self.buf = b""
        self.globals = {}
        self.ready = None
        self.error = None
        registry = self._new_id()
        self._send(1, 1, struct.pack("<I", registry))
        done = self._roundtrip()
        if not done:
            raise OSError("gamescope did not answer")
        found = self.globals.get("gamescope_reshade")
        if found is None:
            raise OSError("this gamescope has no reshade interface")
        name, version = found
        self.obj = self._new_id()
        self._send(registry, 0, struct.pack("<I", name) + _string("gamescope_reshade") + struct.pack("<II", 1, self.obj))
        self._registry = registry
        self._roundtrip()
        if self.error:
            raise OSError(self.error)

    def _new_id(self):
        i = self.next_id
        self.next_id += 1
        return i

    def _send(self, obj, opcode, args=b""):
        size = 8 + len(args)
        self.sock.sendall(struct.pack("<II", obj, (size << 16) | opcode) + args)

    def _roundtrip(self, timeout=3.0):
        cb = self._new_id()
        self._send(1, 0, struct.pack("<I", cb))
        self._cb = cb
        self._cb_done = False
        self.sock.settimeout(timeout)
        try:
            while not self._cb_done:
                data = self.sock.recv(65536)
                if not data:
                    raise OSError("gamescope closed the connection")
                self._feed(data)
        except socket.timeout:
            return False
        finally:
            self.sock.settimeout(None)
        return True

    def _feed(self, data):
        self.buf += data
        while len(self.buf) >= 8:
            obj, word = struct.unpack_from("<II", self.buf, 0)
            size, opcode = word >> 16, word & 0xFFFF
            if size < 8 or len(self.buf) < size:
                return
            body = self.buf[8:size]
            self.buf = self.buf[size:]
            self._event(obj, opcode, body)

    def _event(self, obj, opcode, body):
        if obj == 1 and opcode == 0:  # wl_display.error
            o, code = struct.unpack_from("<II", body, 0)
            msg, _ = _read_string(body, 8)
            self.error = f"Wayland error on object {o}, code {code}: {msg}"
            self.log("gaming: " + self.error)
        elif obj == getattr(self, "_registry", 2) and opcode == 0:  # wl_registry.global
            name = struct.unpack_from("<I", body, 0)[0]
            iface, at = _read_string(body, 4)
            version = struct.unpack_from("<I", body, at)[0]
            self.globals[iface] = (name, version)
        elif obj == getattr(self, "_cb", None) and opcode == 0:  # wl_callback.done
            self._cb_done = True
        elif obj == getattr(self, "obj", None) and opcode == 0:  # effect_ready
            self.ready, _ = _read_string(body, 0)

    def pump(self):
        """Reads whatever gamescope has sent, without waiting (so its messages never pile up)."""
        while True:
            r, _, _ = select.select([self.sock], [], [], 0)
            if not r:
                return
            data = self.sock.recv(65536)
            if not data:
                raise OSError("gamescope closed the connection")
            self._feed(data)

    # ---- the interface ----
    def set_effect(self, path):
        """Loads the effect (a path under ~/.local/share/gamescope/reshade/Shaders), disabled until enable()."""
        self.ready = None
        self._send(self.obj, 1, _string(path))

    def enable(self):
        self._send(self.obj, 2)

    def disable(self):
        self._send(self.obj, 4)

    def set_floats(self, key, values):
        """Sets a float uniform (by its "source" name) to these values."""
        self._send(self.obj, 3, _string(key) + _array(struct.pack(f"<{len(values)}f", *values)))

    def close(self):
        try:
            self._send(self.obj, 4)
            self._send(self.obj, 0)
            self.sock.close()
        except OSError:
            pass
