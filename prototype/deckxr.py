#!/usr/bin/env python3
"""Pocket XR Deck prototype: one window that stays still in space while the head turns (3DoF).

Desktop Mode only. Reads the glasses' sensor stream (read only, nothing is sent to the glasses),
opens a fullscreen window on the glasses' display, and draws one screen fixed in the room.
The screen shows a test card, or with --capture the Deck's own desktop.

Needs nothing installed: SDL2, OpenGL and X11 come with SteamOS and are used through ctypes.

Keys: Enter, Space, R or a click = recentre. Up / Down = nearer / further. Left / Right = smaller / bigger.
Escape or Q = quit.
"""
import argparse
import ctypes
import ctypes.util
import math
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fusion  # noqa: E402
import imu  # noqa: E402

# ---------- SDL2 ----------
sdl = ctypes.CDLL(ctypes.util.find_library("SDL2-2.0") or "libSDL2-2.0.so.0")


class Rect(ctypes.Structure):
    _fields_ = [("x", ctypes.c_int), ("y", ctypes.c_int), ("w", ctypes.c_int), ("h", ctypes.c_int)]


SDL_INIT_VIDEO = 0x20
SDL_WINDOW_OPENGL = 0x2
SDL_WINDOW_BORDERLESS = 0x10
SDL_WINDOW_FULLSCREEN_DESKTOP = 0x1001
SDL_QUIT = 0x100
SDL_KEYDOWN = 0x300
SDL_MOUSEBUTTONDOWN = 0x401
SDL_GL_DOUBLEBUFFER = 5

sdl.SDL_GetDisplayName.restype = ctypes.c_char_p
sdl.SDL_GetError.restype = ctypes.c_char_p
sdl.SDL_CreateWindow.restype = ctypes.c_void_p
sdl.SDL_CreateWindow.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint32]
sdl.SDL_GL_CreateContext.restype = ctypes.c_void_p
sdl.SDL_GL_CreateContext.argtypes = [ctypes.c_void_p]
sdl.SDL_GL_SwapWindow.argtypes = [ctypes.c_void_p]
sdl.SDL_GL_GetDrawableSize.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int)]
sdl.SDL_DestroyWindow.argtypes = [ctypes.c_void_p]
sdl.SDL_ShowCursor.argtypes = [ctypes.c_int]

# ---------- OpenGL (fixed function, enough for a prototype) ----------
gl = ctypes.CDLL(ctypes.util.find_library("GL") or "libGL.so.1")
GL_COLOR_BUFFER_BIT = 0x4000
GL_PROJECTION = 0x1701
GL_MODELVIEW = 0x1700
GL_TEXTURE_2D = 0x0DE1
GL_RGBA = 0x1908
GL_BGRA = 0x80E1
GL_UNSIGNED_BYTE = 0x1401
GL_LINEAR = 0x2601
GL_TEXTURE_MIN_FILTER = 0x2801
GL_TEXTURE_MAG_FILTER = 0x2800
GL_QUADS = 0x0007
GL_LINE_LOOP = 0x0002
GL_SCISSOR_TEST = 0x0C11
for name in ("glClearColor", "glTexCoord2f", "glVertex3f", "glColor3f", "glTranslatef"):
    getattr(gl, name).argtypes = [ctypes.c_float] * {"glClearColor": 4, "glTexCoord2f": 2, "glVertex3f": 3, "glColor3f": 3, "glTranslatef": 3}[name]
gl.glFrustum.argtypes = [ctypes.c_double] * 6
gl.glTexImage2D.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
gl.glTexSubImage2D.argtypes = [ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
gl.glLoadMatrixf.argtypes = [ctypes.POINTER(ctypes.c_float)]
gl.glMultMatrixf.argtypes = [ctypes.POINTER(ctypes.c_float)]


def log(msg):
    print(time.strftime("%H:%M:%S ") + msg, flush=True)


def test_card(w=1280, h=720):
    """A grid with a bright border and a cross in the middle, RGBA."""
    row_bg = bytearray()
    row_line = bytes([90, 140, 220, 255]) * w
    for x in range(w):
        row_bg += bytes([90, 140, 220, 255]) if x % 80 == 0 else bytes([18, 24, 44, 255])
    white = bytes([255, 255, 255, 255])
    out = bytearray()
    for y in range(h):
        row = bytearray(row_line if y % 80 == 0 else row_bg)
        if y < 8 or y >= h - 8:
            row = bytearray(white * w)
        else:
            row[0:32] = white * 8
            row[(w - 8) * 4:] = white * 8
        if abs(y - h // 2) < 3:
            row[(w // 2 - 60) * 4:(w // 2 + 60) * 4] = bytes([255, 80, 80, 255]) * 120
        if abs(y - h // 2) < 60:
            row[(w // 2 - 3) * 4:(w // 2 + 3) * 4] = bytes([255, 80, 80, 255]) * 6
        # Coloured corners so up, down, left and right are easy to tell.
        if 8 <= y < 100:
            row[8 * 4:100 * 4] = bytes([80, 220, 120, 255]) * 92  # top left green
            row[(w - 100) * 4:(w - 8) * 4] = bytes([240, 200, 60, 255]) * 92  # top right yellow
        out += row
    return w, h, bytes(out)


class X11Capture:
    """The Deck's own screen through XGetSubImage, BGRA."""

    def __init__(self, x, y, w, h):
        self.x11 = ctypes.CDLL(ctypes.util.find_library("X11") or "libX11.so.6")
        self.x11.XOpenDisplay.restype = ctypes.c_void_p
        self.x11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.x11.XDefaultRootWindow.restype = ctypes.c_ulong
        self.x11.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
        self.x11.XGetImage.restype = ctypes.c_void_p
        self.x11.XGetImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int]
        self.x11.XGetSubImage.restype = ctypes.c_void_p
        self.x11.XGetSubImage.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint, ctypes.c_ulong, ctypes.c_int, ctypes.c_void_p, ctypes.c_int, ctypes.c_int]
        self.dpy = self.x11.XOpenDisplay(None)
        if not self.dpy:
            raise RuntimeError("no X display")
        self.root = self.x11.XDefaultRootWindow(self.dpy)
        self.x, self.y, self.w, self.h = x, y, w, h
        self.img = self.x11.XGetImage(self.dpy, self.root, x, y, w, h, 0xFFFFFFFF, 2)
        if not self.img:
            raise RuntimeError("XGetImage failed")
        # struct XImage: int width, height, xoffset, format; char *data (offset 16 on x86_64).
        self.data = ctypes.c_void_p.from_address(self.img + 16).value

    def grab(self):
        self.x11.XGetSubImage(self.dpy, self.root, self.x, self.y, self.w, self.h, 0xFFFFFFFF, 2, self.img, 0, 0)
        return self.data


def pick_display(want):
    n = sdl.SDL_GetNumVideoDisplays()
    found = []
    for i in range(n):
        r = Rect()
        sdl.SDL_GetDisplayBounds(i, ctypes.byref(r))
        name = (sdl.SDL_GetDisplayName(i) or b"?").decode(errors="replace")
        found.append((i, name, r.x, r.y, r.w, r.h))
        log(f"display {i}: '{name}' {r.w}x{r.h} at {r.x},{r.y}")
    if want is not None:
        return found[want], found
    for d in found:
        if "xreal" in d[1].lower() or "ultra" in d[1].lower() or "viture" in d[1].lower():
            return d, found
    for d in found:
        if d[4] >= 1920 and d[5] == 1080:
            return d, found
    return found[-1], found


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--display", type=int, help="SDL display index of the glasses")
    ap.add_argument("--axes", default="aura", choices=sorted(fusion.AXES))
    ap.add_argument("--fov", type=float, default=38.0, help="vertical field of view per eye, degrees")
    ap.add_argument("--capture", action="store_true", help="show the Deck's own screen instead of the test card")
    ap.add_argument("--fake", action="store_true", help="no glasses: a made-up slow head turn")
    ap.add_argument("--seconds", type=float, default=0, help="quit after this long (0 = never)")
    args = ap.parse_args()

    head = fusion.HeadFusion(args.axes)
    reader = imu.FakeImu(head.report) if args.fake else imu.ImuReader(head.report, log=log)
    reader.start()

    if sdl.SDL_Init(SDL_INIT_VIDEO) != 0:
        log("SDL_Init failed: " + sdl.SDL_GetError().decode())
        return 1
    (di, dname, dx, dy, dw, dh), displays = pick_display(args.display)
    log(f"using display {di} '{dname}' {dw}x{dh}")
    sdl.SDL_GL_SetAttribute(SDL_GL_DOUBLEBUFFER, 1)
    pos = 0x2FFF0000 | di
    win = sdl.SDL_CreateWindow(b"Pocket XR Deck", pos, pos, dw, dh,
                               SDL_WINDOW_OPENGL | SDL_WINDOW_BORDERLESS | SDL_WINDOW_FULLSCREEN_DESKTOP)
    if not win:
        log("SDL_CreateWindow failed: " + sdl.SDL_GetError().decode())
        return 1
    ctx = sdl.SDL_GL_CreateContext(win)
    if not ctx:
        log("GL context failed: " + sdl.SDL_GetError().decode())
        return 1
    if sdl.SDL_GL_SetSwapInterval(1) != 0:
        log("vsync not available")
    sdl.SDL_ShowCursor(0)

    tex = ctypes.c_uint(0)
    gl.glGenTextures(1, ctypes.byref(tex))
    gl.glBindTexture(GL_TEXTURE_2D, tex)
    gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)

    cap = None
    if args.capture:
        others = [d for d in displays if d[0] != di]
        src = others[0] if others else displays[0]
        try:
            cap = X11Capture(src[2], src[3], src[4], src[5])
            tw, th = src[4], src[5]
            gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, tw, th, 0, GL_BGRA, GL_UNSIGNED_BYTE, cap.grab())
            log(f"capturing display {src[0]} '{src[1]}' {tw}x{th}")
        except Exception as e:  # noqa: BLE001
            log(f"capture failed ({e}); showing the test card")
            cap = None
    if cap is None:
        tw, th, pixels = test_card()
        gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, tw, th, 0, GL_RGBA, GL_UNSIGNED_BYTE, pixels)

    distance = 2.0
    width = 1.6
    fov = args.fov
    event = (ctypes.c_ubyte * 64)()
    frames = 0
    t_start = time.monotonic()
    t_log = t_start
    last_count = 0
    last_cap = 0.0
    running = True
    log("hold the glasses still for 2 s while the gyro settles")
    while running:
        while sdl.SDL_PollEvent(ctypes.byref(event)):
            etype = int.from_bytes(bytes(event[0:4]), "little")
            if etype == SDL_QUIT:
                running = False
            elif etype == SDL_KEYDOWN:
                sym = int.from_bytes(bytes(event[20:24]), "little")
                if sym in (27, ord("q")):
                    running = False
                elif sym in (13, 32, ord("r")):
                    head.recentre()
                    log("recentred")
                elif sym == 0x40000052:
                    distance = max(0.6, distance - 0.2)
                elif sym == 0x40000051:
                    distance = min(6.0, distance + 0.2)
                elif sym == 0x40000050:
                    width = max(0.4, width - 0.1)
                elif sym == 0x4000004F:
                    width = min(6.0, width + 0.1)
            elif etype == SDL_MOUSEBUTTONDOWN:
                head.recentre()
                log("recentred (click)")

        now = time.monotonic()
        if cap is not None and now - last_cap > 1 / 30:
            gl.glBindTexture(GL_TEXTURE_2D, tex)
            gl.glTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, tw, th, GL_BGRA, GL_UNSIGNED_BYTE, cap.grab())
            last_cap = now

        w = ctypes.c_int()
        h = ctypes.c_int()
        sdl.SDL_GL_GetDrawableSize(win, ctypes.byref(w), ctypes.byref(h))
        w, h = w.value, h.value
        sbs = w >= 3 * h
        eyes = [(-0.032, 0, w // 2), (0.032, w // 2, w // 2)] if sbs else [(0.0, 0, w)]

        gl.glClearColor(0.0, 0.0, 0.0, 1.0)
        gl.glClear(GL_COLOR_BUFFER_BIT)
        view = head.view()
        m = (ctypes.c_float * 16)(*fusion.matrix(fusion.qconj(view)))
        qh = th / tw * width
        for eye_x, vx, vw in eyes:
            gl.glViewport(vx, 0, vw, h)
            gl.glMatrixMode(GL_PROJECTION)
            gl.glLoadIdentity()
            near = 0.05
            top = near * math.tan(math.radians(fov) / 2)
            right = top * vw / h
            gl.glFrustum(-right, right, -top, top, near, 100.0)
            gl.glMatrixMode(GL_MODELVIEW)
            gl.glLoadIdentity()
            gl.glTranslatef(-eye_x, 0.0, 0.0)
            gl.glMultMatrixf(m)
            gl.glEnable(GL_TEXTURE_2D)
            gl.glBindTexture(GL_TEXTURE_2D, tex)
            gl.glColor3f(1.0, 1.0, 1.0)
            gl.glBegin(GL_QUADS)
            gl.glTexCoord2f(0, 1); gl.glVertex3f(-width / 2, -qh / 2, -distance)  # noqa: E702
            gl.glTexCoord2f(1, 1); gl.glVertex3f(width / 2, -qh / 2, -distance)  # noqa: E702
            gl.glTexCoord2f(1, 0); gl.glVertex3f(width / 2, qh / 2, -distance)  # noqa: E702
            gl.glTexCoord2f(0, 0); gl.glVertex3f(-width / 2, qh / 2, -distance)  # noqa: E702
            gl.glEnd()
            gl.glDisable(GL_TEXTURE_2D)
        sdl.SDL_GL_SwapWindow(win)
        frames += 1

        if now - t_log >= 2.0:
            dt = now - t_log
            count = head.count
            fwd = fusion.qrot(view, (0.0, 0.0, -1.0))
            yaw = math.degrees(math.atan2(-fwd[0], -fwd[2]))
            pitch = math.degrees(math.asin(max(-1.0, min(1.0, fwd[1]))))
            gyro = math.degrees(math.sqrt(sum(c * c for c in head.last_gyro)))
            fr = reader.framer
            log(f"fps {frames / dt:5.1f}  imu {(count - last_count) / dt:6.0f}/s  link {reader.connected_to}  "
                f"yaw {yaw:6.1f}  pitch {pitch:5.1f}  turn {gyro:5.1f} deg/s  bias_ready {head.bias_ready}  "
                f"dropped {fr.dropped} badlen {fr.bad_length}  {w}x{h}{' SBS' if sbs else ''}")
            frames = 0
            t_log = now
            last_count = count
        if args.seconds and now - t_start > args.seconds:
            running = False

    reader.stop = True
    sdl.SDL_DestroyWindow(win)
    sdl.SDL_Quit()
    log("bye")
    return 0


if __name__ == "__main__":
    sys.exit(main())
