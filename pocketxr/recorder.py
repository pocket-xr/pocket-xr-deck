"""Recording, as Pocket XR on Android records (SpaceRecorder.kt): a clean 1080p MP4 of exactly what you see.

While recording, 30 times a second the finished picture's left eye (the whole picture when it is not side by side) is
read back from the GPU and handed to ffmpeg, which comes with SteamOS, to encode as H.264 at 12 Mbit/s on the Deck's
own video encoder (VA-API), with no sound. Videos are saved in ~/Videos/Pocket XR.

The view must never wait for a recording, above all in PC VR, where the GPU is busy with the game's picture: the first
version read through two buffers in turn and took the PC VR view from 60 frames a second to 18. Now each read goes into
one of three pixel buffers with a fence after it, and a buffer is collected only once its fence says the GPU is done;
if all three are still busy, that frame is left out of the video, never waited for. The pixels are read as BGRA, which
the video hardware takes as it is, so the colour conversion to the encoder's format is done there too (a third of the
CPU time ffmpeg needs to convert them itself).

The red dot that says it is recording is drawn after the read, so it is on the glasses only, never in the video.

If the hardware encoder cannot start, ffmpeg's software one (libx264, its fastest setting) is used instead.
"""
import ctypes
import math
import os
import queue
import subprocess
import threading
import time

from .gl import GL_BLEND, GL_MODELVIEW, GL_ONE_MINUS_SRC_ALPHA, GL_PROJECTION, GL_SRC_ALPHA, GL_TRIANGLE_FAN, gl

GL_BGRA = 0x80E1
GL_UNSIGNED_BYTE = 0x1401
GL_BACK = 0x0405
GL_PIXEL_PACK_BUFFER = 0x88EB
GL_STREAM_READ = 0x88E1
GL_READ_ONLY = 0x88B8
GL_PACK_ALIGNMENT = 0x0D05
GL_SYNC_GPU_COMMANDS_COMPLETE = 0x9117
GL_ALREADY_SIGNALED = 0x911A
GL_CONDITION_SATISFIED = 0x911B

FPS = 30
BITRATE = "12M"
FOLDER = os.path.expanduser("~/Videos/Pocket XR")
BUFFERS = 3
QUEUE_FRAMES = 4  # frames waiting for ffmpeg; past this one is dropped rather than the view slowing

gl.glMapBuffer.restype = ctypes.c_void_p
gl.glMapBuffer.argtypes = [ctypes.c_uint, ctypes.c_uint]
gl.glBufferData.argtypes = [ctypes.c_uint, ctypes.c_ssize_t, ctypes.c_void_p, ctypes.c_uint]
gl.glReadPixels.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_uint, ctypes.c_uint,
                            ctypes.c_void_p]
gl.glFenceSync.restype = ctypes.c_void_p
gl.glFenceSync.argtypes = [ctypes.c_uint, ctypes.c_uint]
gl.glClientWaitSync.restype = ctypes.c_uint
gl.glClientWaitSync.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_uint64]
gl.glDeleteSync.argtypes = [ctypes.c_void_p]
gl.glVertex2f.argtypes = [ctypes.c_float] * 2


def _ffmpeg(path, w, h, hardware):
    src = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "bgr0", "-s", f"{w}x{h}", "-use_wallclock_as_timestamps", "1", "-i", "-"]
    if hardware:
        enc = ["-vaapi_device", "/dev/dri/renderD128",
               "-vf", "vflip,hwupload,scale_vaapi=w=1920:h=1080:format=nv12",
               "-c:v", "h264_vaapi", "-b:v", BITRATE]
    else:
        enc = ["-vf", "vflip,scale=1920:1080,format=yuv420p", "-c:v", "libx264", "-preset", "ultrafast", "-b:v", BITRATE]
    out = ["-fps_mode", "cfr", "-r", str(FPS), "-movflags", "+faststart", path]
    return subprocess.Popen(src + enc + out, stdin=subprocess.PIPE, stderr=subprocess.PIPE)


class Recorder:
    def __init__(self, log, on_saved=None):
        self.log = log
        self.on_saved = on_saved  # called with the file's path once a video is finished
        self.wanted = False
        self.proc = None
        self.path = None
        self.size = None
        self.pbo = None
        self.fences = [None] * BUFFERS  # a buffer's fence while its read is under way
        self.order = []  # buffers with a read under way, oldest first
        self.last_at = 0.0
        self.started_at = 0.0
        self.frames = 0
        self.dropped = 0
        self.cost = [0.0, 0.0, 0]  # time spent on the GL thread: total, longest, frames
        self.queue = None
        self.writer = None
        self.finishing = []

    @property
    def recording(self):
        return self.proc is not None

    def toggle(self):
        self.wanted = not self.wanted
        return self.wanted

    # ---- on the GL thread, with the finished picture in the back buffer, before the swap ----
    def frame(self, w, h, sbs):
        rw = w // 2 if sbs else w
        if self.wanted and self.proc is None:
            self._start(rw, h)
        elif self.proc is not None and (not self.wanted or self.size != (rw, h)):
            if self.size != (rw, h):
                self.log("record: the view changed size, so this video ends here")
                self.wanted = False
            self._stop()
        if self.proc is None:
            return
        t0 = time.perf_counter()
        self._collect()
        now = time.monotonic()
        if now - self.last_at >= 1.0 / FPS - 0.004:
            self.last_at = now
            self._read(rw, h)
        spent = time.perf_counter() - t0
        self.cost[0] += spent
        self.cost[1] = max(self.cost[1], spent)
        self.cost[2] += 1
        self._dot(w, h, sbs)

    def forget_gl(self):
        """The GL context is going away (the view closes): the video ends here."""
        if self.proc is not None:
            self.wanted = False
            self._stop()

    def _start(self, w, h):
        os.makedirs(FOLDER, exist_ok=True)
        path = os.path.join(FOLDER, time.strftime("Pocket XR %Y-%m-%d %H-%M-%S.mp4"))
        proc = None
        for hardware in (True, False):
            proc = _ffmpeg(path, w, h, hardware)
            time.sleep(0.15)
            if proc.poll() is None:
                break
            err = proc.stderr.read().decode(errors="replace").strip().splitlines()
            self.log(f"record: {'hardware' if hardware else 'software'} encoder did not start: {err[-1] if err else ''}")
            proc = None
        if proc is None:
            self.wanted = False
            return
        ids = (ctypes.c_uint * BUFFERS)()
        gl.glGenBuffers(BUFFERS, ids)
        for i in range(BUFFERS):
            gl.glBindBuffer(GL_PIXEL_PACK_BUFFER, ids[i])
            gl.glBufferData(GL_PIXEL_PACK_BUFFER, w * h * 4, None, GL_STREAM_READ)
        gl.glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)
        self.pbo = tuple(ids)
        self.fences = [None] * BUFFERS
        self.order = []
        self.proc, self.path, self.size = proc, path, (w, h)
        self.started_at = time.monotonic()
        self.last_at = 0.0
        self.frames = self.dropped = 0
        self.cost = [0.0, 0.0, 0]
        self.queue = queue.Queue(maxsize=QUEUE_FRAMES)
        self.writer = threading.Thread(target=self._write, args=(proc, self.queue), name="record", daemon=True)
        self.writer.start()
        self.log(f"record: recording {w}x{h} to {path}")

    def _read(self, w, h):
        free = [i for i in range(BUFFERS) if self.fences[i] is None]
        if not free:  # the GPU has not finished the last reads: leave this frame out rather than wait
            self.dropped += 1
            return
        i = free[0]
        gl.glReadBuffer(GL_BACK)
        gl.glPixelStorei(GL_PACK_ALIGNMENT, 1)
        gl.glBindBuffer(GL_PIXEL_PACK_BUFFER, self.pbo[i])
        gl.glReadPixels(0, 0, w, h, GL_BGRA, GL_UNSIGNED_BYTE, None)
        gl.glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)
        gl.glPixelStorei(GL_PACK_ALIGNMENT, 4)
        self.fences[i] = gl.glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0)
        self.order.append(i)

    def _collect(self):
        """Hands every finished read to ffmpeg, oldest first, without waiting for one that is not."""
        w, h = self.size
        while self.order:
            i = self.order[0]
            if gl.glClientWaitSync(self.fences[i], 0, 0) not in (GL_ALREADY_SIGNALED, GL_CONDITION_SATISFIED):
                return
            self.order.pop(0)
            gl.glDeleteSync(self.fences[i])
            self.fences[i] = None
            gl.glBindBuffer(GL_PIXEL_PACK_BUFFER, self.pbo[i])
            ptr = gl.glMapBuffer(GL_PIXEL_PACK_BUFFER, GL_READ_ONLY)
            if ptr:
                data = ctypes.string_at(ptr, w * h * 4)
                gl.glUnmapBuffer(GL_PIXEL_PACK_BUFFER)
                try:
                    self.queue.put_nowait(data)
                    self.frames += 1
                except queue.Full:
                    self.dropped += 1
            gl.glBindBuffer(GL_PIXEL_PACK_BUFFER, 0)

    def _write(self, proc, q):
        while True:
            data = q.get()
            if data is None:
                break
            try:
                proc.stdin.write(data)
            except (BrokenPipeError, OSError):
                break

    def _stop(self):
        proc, path, q, writer = self.proc, self.path, self.queue, self.writer
        secs = time.monotonic() - self.started_at
        frames, dropped = self.frames, self.dropped
        total, longest, n = self.cost
        self.proc = None
        for i, f in enumerate(self.fences):
            if f is not None:
                gl.glDeleteSync(f)
                self.fences[i] = None
        self.order = []
        if self.pbo is not None:
            ids = (ctypes.c_uint * BUFFERS)(*self.pbo)
            gl.glDeleteBuffers(BUFFERS, ids)
            self.pbo = None
        cost = f"{1000 * total / max(1, n):.1f} ms a frame, longest {1000 * longest:.1f} ms"

        def finish():
            q.put(None)
            writer.join(timeout=5.0)
            try:
                proc.stdin.close()
            except OSError:
                pass
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
            err = proc.stderr.read().decode(errors="replace").strip()
            if proc.returncode == 0 and os.path.exists(path):
                self.log(f"record: saved {path} ({secs:.0f} s, {frames} frames, {dropped} left out; {cost})")
                if self.on_saved:
                    self.on_saved(path)
            else:
                self.log(f"record: the video could not be saved ({err.splitlines()[-1] if err else proc.returncode})")

        t = threading.Thread(target=finish, name="record-finish", daemon=True)
        t.start()
        self.finishing = [x for x in self.finishing if x.is_alive()] + [t]

    def wait(self):
        """Before the app exits: a video being finished is written out in full."""
        for t in self.finishing:
            t.join(timeout=25.0)

    def _dot(self, w, h, sbs):
        """The red dot, top left of each eye, on the glasses only."""
        if time.monotonic() % 1.2 > 0.9:  # it blinks, as a recording light does
            return
        gl.glViewport(0, 0, w, h)
        gl.glMatrixMode(GL_PROJECTION)
        gl.glLoadIdentity()
        gl.glMatrixMode(GL_MODELVIEW)
        gl.glLoadIdentity()
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        r_px = 14
        for ex in ((0, w // 2) if sbs else (0,)):
            cx = ex + 150
            cy = h - 110
            gl.glColor4f(0.9, 0.28, 0.3, 0.95)
            gl.glBegin(GL_TRIANGLE_FAN)
            gl.glVertex2f(cx * 2.0 / w - 1, cy * 2.0 / h - 1)
            for k in range(25):
                a = k * 2 * math.pi / 24
                gl.glVertex2f((cx + r_px * math.cos(a)) * 2.0 / w - 1, (cy + r_px * math.sin(a)) * 2.0 / h - 1)
            gl.glEnd()
        gl.glColor4f(1.0, 1.0, 1.0, 1.0)
        gl.glDisable(GL_BLEND)
