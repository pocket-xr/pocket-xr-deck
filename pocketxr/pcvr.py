"""PC VR: SteamVR from the PC in the glasses, as Pocket XR's PC VR tile does on Android.

The Pocket XR PC helper on the PC is found on the network (UDP 47610), paired once (the PC asks its user) and asked to
start SteamVR for this Deck. ALVR's client library runs through Pocket XR's bridge (native/pxr_pcvr.c), which decodes
the stream on the Deck's GPU; each frame comes here as NV12 in two textures and is drawn, per eye, where the PC drew it:
a quad at the head orientation the frame was rendered for, so drawing it with the head's orientation now turns it to
the head (rotation reprojection).
"""
import ctypes
import json
import math
import os
import socket
import threading
import time

from . import fusion
from .gl import GL_LINEAR, GL_QUADS, GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, gl

HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE = os.path.join(HERE, "..", "native")
PORT = 47610
VIEW_W, VIEW_H, RATE = 1920, 1080, 60.0
IPD = 0.063
HEAD_HEIGHT = 1.6
GL_TEXTURE0 = 0x84C0
GL_TEXTURE1 = 0x84C1
GL_FRAGMENT_SHADER = 0x8B30
GL_VERTEX_SHADER = 0x8B31
GL_COMPILE_STATUS = 0x8B81
GL_CLAMP_TO_EDGE = 0x812F
GL_TEXTURE_WRAP_S = 0x2802
GL_TEXTURE_WRAP_T = 0x2803

VERT = b"""
#version 120
void main() { gl_TexCoord[0] = gl_MultiTexCoord0; gl_Position = ftransform(); }
"""
# NV12 to RGB, BT.709 limited range (what ALVR's encoders send).
FRAG_DEBUG = b"""
#version 120
uniform sampler2D ty;
uniform sampler2D tuv;
void main() {
    vec2 t = gl_TexCoord[0].st;
    gl_FragColor = vec4(texture2D(tuv, t).r, texture2D(tuv, t).a, texture2D(ty, t).r, 1.0);
}
"""
FRAG = FRAG_DEBUG if os.environ.get("POCKETXR_PCVR_DEBUG") == "1" else b"""
#version 120
uniform sampler2D ty;
uniform sampler2D tuv;
void main() {
    vec2 t = gl_TexCoord[0].st;
    float y = 1.1644 * (texture2D(ty, t).r - 0.0625);
    vec2 c = texture2D(tuv, t).ra - 0.5;
    gl_FragColor = vec4(y + 1.7927 * c.y, y - 0.2132 * c.x - 0.5329 * c.y, y + 2.1124 * c.x, 1.0);
}
"""


def _load():
    lib = None
    for base in (os.path.join(NATIVE, "out"), NATIVE):
        p = os.path.join(base, "libpxr_pcvr.so")
        if os.path.exists(p):
            lib = ctypes.CDLL(p)
            break
    if lib is None:
        return None
    lib.pxr_init.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_float]
    lib.pxr_poll_event.argtypes = [ctypes.POINTER(ctypes.c_float)]
    lib.pxr_hud_message.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.pxr_hostname.argtypes = [ctypes.c_char_p, ctypes.c_int]
    lib.pxr_now_ns.restype = ctypes.c_uint64
    lib.pxr_prediction_offset_ns.restype = ctypes.c_uint64
    lib.pxr_send_view_params.argtypes = [ctypes.c_float, ctypes.POINTER(ctypes.c_float)]
    lib.pxr_send_head.argtypes = [ctypes.c_uint64, ctypes.POINTER(ctypes.c_float)]
    lib.pxr_acquire.restype = ctypes.c_uint64
    lib.pxr_acquire.argtypes = [ctypes.c_uint, ctypes.c_uint, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_float)]
    lib.pxr_submit.argtypes = [ctypes.c_uint64, ctypes.c_uint64]
    lib.pxr_stats.argtypes = [ctypes.POINTER(ctypes.c_uint64)]
    return lib


def available():
    return any(os.path.exists(os.path.join(b, "libpxr_pcvr.so")) for b in (os.path.join(NATIVE, "out"), NATIVE))


class PcVr:
    """One PC VR session: status for the panel and toasts, frames for the view."""

    def __init__(self, app):
        self.app = app
        self.log = app.log
        self.lib = _load()
        self.state = "finding"  # finding, pairing, starting, waiting, streaming, failed
        self.message = "Looking for your PC..."
        self.stop = False
        self.started = False
        self.streaming = False
        self.tex = None
        self.prog = None
        self.frame_ts = 0
        self.frame_pose = None  # (quat w x y z, fovs[8])
        self.frame_size = (0, 0)
        self.frames = 0
        self.token_path = os.path.join(os.path.expanduser("~/.config/pocket-xr-deck"), "pc-helper.json")
        h, v = math.atan(math.tan(math.radians(19)) * 16 / 9), math.radians(19)
        self.fovs = (ctypes.c_float * 8)(-h, h, v, -v, -h, h, v, -v)
        threading.Thread(target=self._connect, daemon=True).start()

    # ---- the PC helper (UDP find, pair once, start) ----
    def _find(self, timeout=6.0):
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.settimeout(0.5)
        end = time.time() + timeout
        while time.time() < end and not self.stop:
            s.sendto(b"POCKETXR-FIND 1", ("255.255.255.255", PORT))
            try:
                data, addr = s.recvfrom(256)
            except socket.timeout:
                continue
            parts = data.decode(errors="replace").split()
            if parts[:2] == ["POCKETXR-HERE", "1"]:
                return addr[0], int(parts[2]), " ".join(parts[3:])
        return None

    @staticmethod
    def _ask(host, port, req, timeout=60.0):
        with socket.create_connection((host, port), timeout=timeout) as c:
            c.sendall((json.dumps(req) + "\n").encode())
            return json.loads(c.makefile().readline())

    def _connect(self):
        if self.lib is None:
            self.state, self.message = "failed", "PC VR's parts are missing from this install."
            return
        found = self._find()
        if not found:
            self.state = "failed"
            self.message = "No PC found. Start the Pocket XR PC helper on your PC, on the same network."
            return
        host, port, pc = found
        self.log(f"pcvr: PC helper on {pc} ({host})")
        try:
            token = json.load(open(self.token_path)).get("token")
        except (OSError, ValueError):
            token = None
        try:
            if not token:
                self.state, self.message = "pairing", f"Allow this Steam Deck on {pc}: a question is on its screen."
                r = self._ask(host, port, {"op": "pair", "phone": "Steam Deck"}, timeout=120)
                if not r.get("ok"):
                    self.state, self.message = "failed", f"{pc} did not allow this Deck."
                    return
                token = r["token"]
                os.makedirs(os.path.dirname(self.token_path), exist_ok=True)
                with open(self.token_path, "w") as f:
                    json.dump({"token": token, "pc": r.get("pc")}, f)
            self.lib.pxr_init(VIEW_W, VIEW_H, RATE)
            self.started = True
            name = ctypes.create_string_buffer(128)
            self.lib.pxr_hostname(name, 128)
            self.state, self.message = "starting", f"Starting SteamVR on {pc}..."
            r = self._ask(host, port, {"op": "start", "token": token, "alvr": name.value.decode()})
            if not r.get("ok"):
                self.state, self.message = "failed", f"{pc}: {r.get('why', 'could not start SteamVR')}"
                return
            if not r.get("steam") or not r.get("alvr"):
                self.state, self.message = "failed", f"{pc} needs Steam and SteamVR installed."
                return
            self.state, self.message = "waiting", f"Waiting for SteamVR on {pc}..."
        except OSError as e:
            self.state, self.message = "failed", f"Lost the PC ({e})."

    # ---- every frame, on the GL thread ----
    def frame(self, view_q, gyro_head):
        if not self.started:
            return
        lib = self.lib
        ev = (ctypes.c_float * 4)()
        while True:
            t = lib.pxr_poll_event(ev)
            if t < 0:
                break
            if t == 0:  # ALVR's status text changed
                buf = ctypes.create_string_buffer(4096)
                if lib.pxr_hud_message(buf, 4096) >= 0:
                    hud = buf.value.decode(errors="replace")
                    lines = [x for x in hud.splitlines() if x.strip()]
                    self.log("pcvr: ALVR says: " + " | ".join(lines[-2:]))
            elif t == 1:  # streaming started
                self.streaming = True
                self.state, self.message = "streaming", ""
                lib.pxr_send_view_params(IPD, self.fovs)
                self.log(f"pcvr: streaming {int(ev[0])}x{int(ev[1])} per eye at {ev[2]:.0f} Hz")
            elif t == 2:  # stopped
                self.streaming = False
                lib.pxr_destroy_decoder()
                self.state, self.message = "waiting", "The PC stopped the stream. Waiting..."
            elif t == 4:
                lib.pxr_create_decoder(int(ev[0]))
        # the head now, a little ahead (ALVR's own delay), in ALVR's axes (x right, y up, z back, as ours)
        now = lib.pxr_now_ns()
        ahead = lib.pxr_prediction_offset_ns()
        w = fusion.qrot(view_q, gyro_head)
        dt = ahead / 1e9
        ang = math.sqrt(w[0] ** 2 + w[1] ** 2 + w[2] ** 2) * dt
        q = view_q
        if ang > 1e-6:
            k = math.sin(ang / 2) / (ang / dt)
            q = fusion.qnorm(fusion.qmul((math.cos(ang / 2), w[0] * k, w[1] * k, w[2] * k), view_q))
        head = (ctypes.c_float * 10)(q[1], q[2], q[3], q[0], 0.0, HEAD_HEIGHT, 0.0, w[0], w[1], w[2])
        lib.pxr_send_head(now + ahead, head)

    def _gl_setup(self):
        ids = (ctypes.c_uint * 2)()
        gl.glGenTextures(2, ids)
        for t in ids:
            gl.glBindTexture(GL_TEXTURE_2D, t)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        self.tex = (ids[0], ids[1])
        gl.glCreateShader.restype = ctypes.c_uint
        gl.glCreateProgram.restype = ctypes.c_uint
        gl.glGetUniformLocation.restype = ctypes.c_int
        gl.glGetUniformLocation.argtypes = [ctypes.c_uint, ctypes.c_char_p]

        def shader(kind, src):
            sh = gl.glCreateShader(kind)
            arr = (ctypes.c_char_p * 1)(src)
            gl.glShaderSource(sh, 1, arr, None)
            gl.glCompileShader(sh)
            ok = ctypes.c_int()
            gl.glGetShaderiv(sh, GL_COMPILE_STATUS, ctypes.byref(ok))
            if not ok.value:
                buf = ctypes.create_string_buffer(2048)
                gl.glGetShaderInfoLog(sh, 2048, None, buf)
                self.log("pcvr: shader: " + buf.value.decode(errors="replace"))
            return sh

        p = gl.glCreateProgram()
        gl.glAttachShader(p, shader(GL_VERTEX_SHADER, VERT))
        gl.glAttachShader(p, shader(GL_FRAGMENT_SHADER, FRAG))
        gl.glLinkProgram(p)
        ok = ctypes.c_int()
        gl.glGetProgramiv(p, 0x8B82, ctypes.byref(ok))  # GL_LINK_STATUS
        gl.glUseProgram(p)
        ly, luv = gl.glGetUniformLocation(p, b"ty"), gl.glGetUniformLocation(p, b"tuv")
        gl.glUniform1i(ly, 0)
        gl.glUniform1i(luv, 1)
        gl.glUseProgram(0)
        self.log(f"pcvr: shader program {p} linked {ok.value}, samplers at {ly} and {luv}")
        self.prog = p

    def _debug_textures(self):
        """Reads the frame's textures back once, to see what the decoder gave (a check while bringing PC VR up)."""
        w, h = self.frame_size
        for name, tex, cw, ch, comps, fmt in (("Y", self.tex[0], w, h, 1, 0x1909), ("UV", self.tex[1], w // 2, h // 2, 2, 0x190A)):
            buf = (ctypes.c_ubyte * (cw * ch * comps))()
            gl.glBindTexture(GL_TEXTURE_2D, tex)
            gl.glPixelStorei(0x0D05, 1)  # GL_PACK_ALIGNMENT
            gl.glGetTexImage(GL_TEXTURE_2D, 0, fmt, 0x1401, buf)
            gl.glPixelStorei(0x0D05, 4)
            step = max(1, len(buf) // 4096)
            sample = buf[::step]
            self.log(f"pcvr: {name} texture {cw}x{ch}: min {min(sample)} max {max(sample)} mean {sum(sample) / len(sample):.0f}")
        self.log(f"pcvr: frame pose {self.frame_pose}")

    def forget_gl(self):
        self.tex = None
        self.prog = None

    def draw_eye(self, eye):
        """Draws this eye's half of the newest frame where the PC drew it (call with the eye's view and projection set)."""
        if not self.streaming:
            return False
        if self.tex is None:
            self._gl_setup()
        if eye == 0:
            size = (ctypes.c_int * 2)()
            pose = (ctypes.c_float * 12)()
            ts = self.lib.pxr_acquire(self.tex[0], self.tex[1], size, pose)
            if ts:
                self.frame_ts = ts
                self.frame_size = (size[0], size[1])
                if pose[3] != 0 or pose[0] != 0 or pose[1] != 0 or pose[2] != 0:
                    self.frame_pose = ((pose[3], pose[0], pose[1], pose[2]), list(pose[4:12]))
                self.frames += 1
                if self.frames == 30 and os.environ.get("POCKETXR_PCVR_DEBUG") == "1":
                    self._debug_textures()
        if not self.frame_ts or self.frame_pose is None:
            return False
        q, f = self.frame_pose
        l, r, u, d = f[4 * eye:4 * eye + 4]
        D = 10.0
        corners = [(math.tan(l) * D, math.tan(d) * D), (math.tan(r) * D, math.tan(d) * D),
                   (math.tan(r) * D, math.tan(u) * D), (math.tan(l) * D, math.tan(u) * D)]
        u0, u1 = (0.0, 0.5) if eye == 0 else (0.5, 1.0)
        tcs = [(u0, 1.0), (u1, 1.0), (u1, 0.0), (u0, 0.0)]
        gl.glPushMatrix()
        m = (ctypes.c_float * 16)(*fusion.matrix(q))
        gl.glMultMatrixf(m)  # into the head orientation the PC drew this frame for
        gl.glUseProgram(self.prog)
        gl.glActiveTexture(GL_TEXTURE1)
        gl.glBindTexture(GL_TEXTURE_2D, self.tex[1])
        gl.glActiveTexture(GL_TEXTURE0)
        gl.glBindTexture(GL_TEXTURE_2D, self.tex[0])
        gl.glBegin(GL_QUADS)
        for (x, y), (s, t) in zip(corners, tcs):
            gl.glTexCoord2f(s, t)
            gl.glVertex3f(x, y, -D)
        gl.glEnd()
        gl.glUseProgram(0)
        gl.glPopMatrix()
        return True

    def submitted(self):
        if self.frame_ts:
            self.lib.pxr_submit(self.frame_ts, int(1e9 / RATE))

    def close(self):
        self.stop = True
        if self.started:
            try:
                self.lib.pxr_destroy()
            except Exception:  # noqa: BLE001
                pass
            self.started = False
        self.streaming = False
