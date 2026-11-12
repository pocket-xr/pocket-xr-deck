"""PC VR: SteamVR from the PC in the glasses, as Pocket XR's PC VR tile does on Android.

The Pocket XR PC helper on the PC is found on the network (UDP 47610), paired once (the PC asks its user) and asked to
start SteamVR for this Deck. ALVR's client library runs through Pocket XR's bridge (native/pxr_pcvr.c), which decodes
the stream on the Deck's GPU; each frame comes here as NV12 in two textures and is drawn, per eye, where the PC drew it:
a quad at the head orientation the frame was rendered for, so drawing it with the head's orientation now turns it to
the head (rotation reprojection).

While it connects, Pocket XR's loading room is shown (pcvr_scene.py); it opens as a portal over the Space, fades away
once the picture is steady, comes back as "Waiting for your PC" if the picture pauses, and holding L5 or R5 for two
seconds closes the portal back to the Space.
"""
import ctypes
import json
import math
import os
import socket
import threading
import time

from . import fusion
from . import pcvr_scene as scene
from .gl import GL_LINEAR, GL_QUADS, GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, gl

HERE = os.path.dirname(os.path.abspath(__file__))
NATIVE = os.path.join(HERE, "..", "native")
PORT = 47610
VIEW_W, VIEW_H, RATE = 1920, 1080, 60.0
IPD = 0.063
HEAD_HEIGHT = 1.6
# When the loading room gives way to the game, as Pocket XR on Android (PcVrRenderer.kt)
MIN_LOADING_S = 1.2  # the room is shown at least this long, so it never flashes
STEADY_S = 1.5  # frames have come steadily this long
STEADY_GAP_S = 0.15  # a gap longer than this is not steady
FADE_S = 0.8
STALL_S = 1.0  # no frame this long: "Waiting for your PC"
STALL_ALPHA = 0.95
STALL_EASE = 0.08
HOLD_TO_LEAVE_S = 2.0
HOLD_SHOWN_S = 0.3
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
PORTAL = b"""
uniform vec4 viewport;
uniform float portal;
void portal_clip() {
    vec2 q = ((gl_FragCoord.xy - viewport.xy) / viewport.zw - 0.5) * vec2(viewport.z / viewport.w, 1.0);
    if (length(q) > portal) discard;
}
"""
FRAG_DEBUG = b"""
#version 120
uniform sampler2D ty;
uniform sampler2D tuv;
""" + PORTAL + b"""
void main() {
    portal_clip();
    vec2 t = gl_TexCoord[0].st;
    gl_FragColor = vec4(texture2D(tuv, t).r, texture2D(tuv, t).a, texture2D(ty, t).r, 1.0);
}
"""
FRAG = FRAG_DEBUG if os.environ.get("POCKETXR_PCVR_DEBUG") == "1" else b"""
#version 120
uniform sampler2D ty;
uniform sampler2D tuv;
""" + PORTAL + b"""
void main() {
    portal_clip();
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
        # what is shown: the loading room, the portal, the stall and leaving cards
        t = time.monotonic()
        self.room = scene.Room(self.log)
        self.opened_at = t
        self.loading_since = t
        self.closing_at = None
        self.last_frame_at = None
        self.steady_since = None
        self.reveal_at = None
        self.reconnecting = False
        self.stall = 0.0
        self.leave_down_at = None
        self.loc = None
        self.size = 0.0
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
                if self.reveal_at is not None:  # back to the loading room until the game comes back
                    self.reconnecting = True
                    self.reveal_at = None
                    self.loading_since = time.monotonic()
                self.frame_ts = 0
                self.last_frame_at = self.steady_since = None
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
        self.loc = (gl.glGetUniformLocation(p, b"viewport"), gl.glGetUniformLocation(p, b"portal"))
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
        self.room.forget_gl()

    # ---- what is shown ----
    def tick(self, view_q):
        """Once a frame, before the eyes: takes the newest frame and moves the loading room, portal and cards on.
        Returns "leave" when L5 or R5 has been held long enough."""
        now = time.monotonic()
        self.size = self._portal_size(now)  # once a frame, so both eyes match
        self.room.follow(view_q)
        if self.streaming:
            if self.tex is None:
                self._gl_setup()
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
                if self.last_frame_at is None or now - self.last_frame_at > STEADY_GAP_S:
                    self.steady_since = now
                self.last_frame_at = now
        if (self.reveal_at is None and self.frame_ts and self.frame_pose is not None
                and self.steady_since is not None and now - self.steady_since >= STEADY_S
                and now - self.loading_since >= MIN_LOADING_S):
            self.reveal_at = now
            self.reconnecting = False
            self.log(f"pcvr: the picture is steady, the loading room fades ({self.frames} frames)")
        stalled = (self.reveal_at is not None and now - self.reveal_at > FADE_S
                   and (self.last_frame_at is None or now - self.last_frame_at > STALL_S))
        self.stall += ((STALL_ALPHA if stalled else 0.0) - self.stall) * STALL_EASE
        if self.leave_down_at is not None and self.closing_at is None and now - self.leave_down_at >= HOLD_TO_LEAVE_S:
            self.leave_down_at = None
            return "leave"
        return None

    def _portal_size(self, now):
        """How open the portal is, 0 to 1 (1: PC VR fills the view)."""
        if self.closing_at is not None:
            return 1.0 - scene.ease_out3((now - self.closing_at) / scene.PORTAL_CLOSE_S)
        return scene.ease_out3((now - self.opened_at) / scene.PORTAL_OPEN_S)

    def closed(self):
        return self.closing_at is not None and time.monotonic() - self.closing_at >= scene.PORTAL_CLOSE_S

    def covers(self):
        """True when PC VR fills the view, so the Space behind need not be drawn."""
        return self.closing_at is None and self.size >= 1.0

    def _room_alpha(self, now):
        if self.reveal_at is None:
            return 1.0
        t = max(0.0, min(1.0, (now - self.reveal_at) / FADE_S))
        return 1.0 - t * t * (3 - 2 * t)

    def _words(self, now):
        """The card's (title, line, hint), its ring (-1 turning, -2 none, 0..1 filling) and how strongly it shows
        over the game."""
        hint = "Hold L5 or R5 to leave PC VR"
        if self.leave_down_at is not None and now - self.leave_down_at >= HOLD_SHOWN_S:
            p = min(1.0, (now - self.leave_down_at) / HOLD_TO_LEAVE_S)
            return scene.TITLES["leaving"] + ("",), p, min(p * 2.5, 0.92)
        if self.closing_at is not None:
            return scene.TITLES["leaving"] + ("",), 1.0, 0.0
        if self.state == "failed":
            return ("PC VR did not start", self.message, hint), -2.0, 0.0
        if self.reveal_at is not None:
            return scene.TITLES["stalled"] + (hint,), -1.0, self.stall
        if self.reconnecting:
            return scene.TITLES["reconnecting"] + (hint,), -1.0, 0.0
        if self.state == "finding":
            slow = now - self.opened_at > scene.SLOW_FIND_S
            return scene.TITLES["finding_slow" if slow else "finding"] + (hint,), -1.0, 0.0
        if self.state == "pairing":
            return ("Allow this Steam Deck on your PC", "A question is on your PC's screen.", hint), -1.0, 0.0
        return scene.TITLES["starting"] + (hint,), -1.0, 0.0

    def draw_eye(self, eye, view_q, tans, viewport):
        """This eye's PC VR: the game's frame where the PC drew it, then the loading room or a card over it, all
        inside the portal. Call with the eye's view and projection set and its viewport (x, y, w, h) in place."""
        now = time.monotonic()
        size = self.size
        aspect = viewport[2] / max(1.0, viewport[3])
        opening = size < 1.0 or self.closing_at is not None
        portal = scene.portal_radius(size, aspect) if opening else 10.0
        room_alpha = self._room_alpha(now)
        if room_alpha < 1.0 and self.frame_ts and self.frame_pose is not None:
            self._draw_frame(eye, viewport, portal)
        words, progress, over = self._words(now)
        self.room.draw(now, view_q, tans, viewport, max(room_alpha, over), None, words, progress, portal)
        if opening:
            self.room.draw_rim(size, viewport)

    def _draw_frame(self, eye, viewport, portal):
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
        gl.glUniform4f(self.loc[0], *[float(v) for v in viewport])
        gl.glUniform1f(self.loc[1], float(portal))
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
