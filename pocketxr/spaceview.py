"""The Space on the Deck, as Pocket XR has it on Android: the space pointer, window controls, moving with snap,
resizing from the handle, push and pull, curve, lock, the launcher, the Control Center, arrange layouts, presets
and Adjust all. Geometry and numbers are in space.py; this file is the behaviour and the drawing.

The space pointer is a ray from the head, moved by the Deck's trackpad (the real pointer while it is on the glasses'
output). Over an app window the real pointer is put on the same spot of that app's own screen, so clicks, scrolls,
hovers and typing reach the app; over anything of Pocket XR's (buttons, the frame, the handle, the launcher) it is
parked on the view's one clickable spot, so those clicks come here.
"""
import ctypes
import math
import time

from . import apps as appsmod
from . import fusion
from . import space as S
from . import look as L
from . import text
from . import ui
from .gl import (GL_BLEND, GL_LINEAR, GL_LINE_LOOP, GL_ONE_MINUS_SRC_ALPHA, GL_QUADS, GL_RGBA, GL_BGRA,
                 GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_UNSIGNED_BYTE, gl)

GL_ONE = 1
GL_SRC_ALPHA = 0x0302
GL_QUAD_STRIP = 0x0008
DIM_BEHIND = 0.9  # windows not in focus dim slightly (Light on glass)
TOAST_S = 2.6
TOAST_D = 1.2
TOAST_DROP_DEG = 13.0
RIPPLE_S = 0.38  # Android: RIPPLE_MS 380
ACCENT = (0x5A / 255, 0x93 / 255, 1.0)
HELD = (0x8F / 255, 0xB6 / 255, 1.0)
INK2 = (0.62, 0.62, 0.66)
HALO_PER_M = 0.012
HALO_ALPHA = 0.32
RIM_PER_M = 0.0007
CURSOR_DEG = 1.1
# The cursor's marks, as Pocket XR on Android (SpaceRenderer): sizes in units of 0.8 degrees across
CURSOR_UNIT = 0.014  # metres across per metre away
CURSOR_DOT = 0.62
CURSOR_DOT_CORE = 0.74  # the dot's white share of its radius; a dark hairline outside it
CURSOR_RING = 1.45
CURSOR_RING_INNER = 0.84
CURSOR_GLOW = 2.6
CURSOR_GLOW_ALPHA = 0.16
RIPPLE_TO = 3.2
RIPPLE_INNER = 0.9
RETICLE_HOVER_S = 0.150
RETICLE_HOVER_MIN = 0.6
RETICLE_PRESS_SCALE = 0.7
CURSOR_IDLE_M = 2.5
CURSOR_LIMIT = (28.0, 17.0)  # the space pointer stays inside the glasses' view (degrees from the centre)
DIM_UNDER_CC = 0.3
WHEEL_DEPTH_STEPS = 2  # one wheel notch = Further/Closer x2 (distance x (1 + 0.03 x 2))
# Pocket XR's launcher is 1450 x 950 dp at 1440 dp a metre, 1.0 m away, 5 degrees down. On the Aura that card is as tall
# as the whole view (about 36 degrees) and its bottom row was cut off, so on the Deck it sits a little further, level.
LAUNCHER_D, LAUNCHER_W, LAUNCHER_H, LAUNCHER_DROP = 1.15, 1.007, 0.66, 1.0
CC_D, CC_WDEG = 1.8, 38.0
CC_OPEN_S = 0.22
COLS, ROWS = 5, 3
LEAVE_PUSH_DEG = 8.0
WHEEL_HOLD_S = 0.8  # a pause this long in scrolling lets go of the window being pushed or pulled
# "Cursor follows head" off: the cursor stays in the room; once out of view, a 3 degree net swipe brings it back
# to the edge of the view, 1.5 degrees in (Pocket XR SpatialPointer).
BRING_BACK_DEG = 3.0
BRING_BACK_IN_DEG = 1.5  # pushing this far past the left edge of the view goes back to the Deck's screen


def deg_per_px(speed):
    """Cursor speed 1..10 (Control Center steps of 10 %); 5 is Pocket XR's trackpad 0.04 deg a pixel."""
    return 0.008 * speed


class Item:
    """A clickable thing on the launcher or Control Center: a rect in its card's (u, v), and what it does."""
    __slots__ = ("u0", "v0", "u1", "v1", "action", "arg", "label", "on", "kind")

    def __init__(self, u0, v0, u1, v1, action, arg=None, label="", on=False, kind="button"):
        self.u0, self.v0, self.u1, self.v1 = u0, v0, u1, v1
        self.action, self.arg, self.label, self.on, self.kind = action, arg, label, on, kind


class SpaceView:
    def __init__(self, app):
        gl.glScalef.argtypes = [ctypes.c_float] * 3
        self.app = app
        self.log = app.log
        self.store = S.Store(app.space_path)
        self.poses = {}
        self.tweens = {}  # key -> (from, to, start)
        self.cursor = [0.0, 0.0]  # yaw, pitch offset from the head's forward
        self.ray = (0.0, 0.0, -1.0)
        self.hover = None  # (kind, key, zone, name, u, v, depth)
        self.ctl_seen = {}  # key -> last time its controls were pointed at
        self.drag = None
        self.resize = None
        self.snap_partner = None
        self.fit = None
        self.last_raised = None
        self.launcher = None  # (Pose, page) when open
        self.cc = None  # (Pose, opened at) when open
        self.adjust_all = None  # {"start": {...}}
        self.pending_spot = None  # (yaw, pitch, until): where the next new window opens (from the launcher)
        self.tex = {}  # cache key -> (texture id, w, h)
        self.app_list = None
        self.focus = None
        self.push_left = 0.0
        self.card_specs = {}
        self.closing = []
        self.appeared = {}
        self.toasts = []
        self.ripple = None
        self.pressing = False
        self.ring_k = 0.0  # the hover ring's tween, 0 to 1 (ReticleAnim)
        self.cursor_deg = CURSOR_DEG
        self.cursor_t = None
        self.wheel_hold = None  # (key, until)
        self.cursor_world = None  # (yaw, pitch) in the room, with "Cursor follows head" off
        self.bring_back = 0.0
        self.room_motion = (0.0, 0.0)

    # ---------- textures ----------
    def _tex(self, key, make):
        t = self.tex.get(key)
        if t is None:
            made = make()
            if made is None:
                return None
            data, w, h = made
            tid = ctypes.c_uint(0)
            gl.glGenTextures(1, ctypes.byref(tid))
            gl.glBindTexture(GL_TEXTURE_2D, tid)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            gl.glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            gl.glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_BGRA, GL_UNSIGNED_BYTE, data)
            t = (tid.value, w, h)
            self.tex[key] = t
        return t

    def forget_textures(self):
        """The GL context went (the view was opened again): textures are made again on use."""
        self.tex = {}

    # ---------- the windows' places ----------
    def _sync(self, panels, head_yaw, out_size, now):
        keys = {p.key for p in panels}
        for p in panels:
            if p.key in self.poses or p.frame is None:
                continue
            cls = getattr(p, "cls", "") or ""
            aspect = p.frame.h / max(1, p.frame.w)
            saved = self.store.apps.get(cls)
            others = [q for k, q in self.poses.items() if k in keys]
            if saved and not any(S.overlaps(S.Pose.from_json(saved), o, gap=0) for o in others):
                pose = S.Pose.from_json(saved)
            else:
                wdeg = S.DEFAULT_WIDTH_DEG if p.key != "deck" else S.DEFAULT_WIDTH_DEG
                hdeg = S.clamp(S.m_to_deg(S.deg_to_m(wdeg, S.DEFAULT_DISTANCE) * aspect, S.DEFAULT_DISTANCE),
                               S.MIN_SIZE_DEG, S.MAX_HEIGHT_DEG)
                yaw, pitch = head_yaw, 0.0
                if self.pending_spot and now < self.pending_spot[2]:
                    yaw, pitch = self.pending_spot[0], self.pending_spot[1]
                    self.pending_spot = None
                pose = S.place_new(others, wdeg, hdeg, yaw, pitch, S.DEFAULT_DISTANCE,
                                   self.app.settings.get("curve_default", 0.0))
            self.poses[p.key] = pose
            if p.key != "deck":
                self._fit_app_pixels(p.key, pose, out_size)
                self.focus = p.key  # a new window takes focus
        for k in list(self.poses):
            if k not in keys:
                self._remember(k, panels_by_key=None)
                del self.poses[k]

    def _fit_app_pixels(self, key, pose, out_size):
        """The app's own size follows its window, as in Pocket XR, within the glasses' output (where it can be used)."""
        w, h = pose.pixels()
        if out_size:
            k = min(1.0, out_size[0] / w, out_size[1] / h)
            w, h = int(w * k), int(h * k)
        self.app.capture.resize_app(key, w, h)

    def _remember(self, key, panels_by_key=None):
        p = next((q for q in self.app.capture.snapshot() if q.key == key), None)
        cls = getattr(p, "cls", "") if p else ""
        if cls and key in self.poses:
            self.store.remember(cls, self.poses[key])

    def save_places(self):
        for p in self.app.capture.snapshot():
            if p.key in self.poses and getattr(p, "cls", ""):
                self.store.remember(p.cls, self.poses[p.key])
        try:
            self.store.save()
        except OSError as e:
            self.log(f"space: could not save places ({e})")

    def _pose(self, key, now):
        tw = self.tweens.get(key)
        if tw:
            a, b, t0 = tw
            t = (now - t0) / S.ARRANGE_TWEEN_S
            if t >= 1:
                del self.tweens[key]
                self.poses[key] = b
                return b
            return S.blend(a, b, S.ease(t))
        return self.poses[key]

    # ---------- every frame ----------
    def frame(self, now, view_q, panels, out_size, pointer_live):
        head_fwd = fusion.qrot(view_q, (0.0, 0.0, -1.0))
        head_yaw, head_pitch = S.angles(head_fwd)
        self._sync(panels, head_yaw, out_size, now)
        for p in panels:
            if p.active and p.key != "deck":
                self.focus = p.key
        if pointer_live:
            dx, dy = self.app.capture.take_motion()
            k = deg_per_px(self.app.settings.get("cursor_speed", 5))
            if self.adjust_all is not None and (dx or dy):
                self._adjust_all_turn(-dx * k, -dy * k)
            elif not self.app.settings.get("cursor_follows_head", True):
                self.room_motion = (self.room_motion[0] - dx * k, self.room_motion[1] - dy * k)
            else:
                want = self.cursor[0] - dx * k
                if want > CURSOR_LIMIT[0] and not self.drag and not self.resize:
                    self.push_left += want - CURSOR_LIMIT[0]
                    if self.push_left > LEAVE_PUSH_DEG:
                        self.push_left = 0.0
                        self.app.capture.leave_space()
                elif dx > 0:
                    self.push_left = 0.0  # a move to the right starts the push again; a still frame does not
                self.cursor[0] = S.clamp(want, -CURSOR_LIMIT[0], CURSOR_LIMIT[0])
                self.cursor[1] = S.clamp(self.cursor[1] - dy * k, -CURSOR_LIMIT[1], CURSOR_LIMIT[1])
        if self.app.settings.get("cursor_follows_head", True):
            self.cursor_world = None
            local = S.direction(self.cursor[0], self.cursor[1])
            self.ray = fusion.qrot(view_q, local)
        else:
            self._room_cursor(view_q, head_yaw, head_pitch)
        self.hover = self._hit(panels, now)
        if self.drag:
            self._drag_update()
        if self.resize:
            self._resize_update(now)
        self._warp(panels, out_size)
        if self.hover and self.hover[0] == "window":
            self.ctl_seen[self.hover[1]] = now
        if self.wheel_hold and now < self.wheel_hold[1]:
            self.ctl_seen[self.wheel_hold[0]] = now

    def _room_cursor(self, view_q, head_yaw, head_pitch):
        """The cursor stays where it is in the room as the head turns; the trackpad moves it there."""
        if self.cursor_world is None:
            self.cursor_world = [S.wrap(head_yaw + self.cursor[0]), head_pitch + self.cursor[1]]
        dyaw, dpitch = self.room_motion
        self.room_motion = (0.0, 0.0)
        oy = S.wrap(self.cursor_world[0] - head_yaw)
        op = self.cursor_world[1] - head_pitch
        out = abs(oy) > CURSOR_LIMIT[0] or abs(op) > CURSOR_LIMIT[1]
        if out:
            self.bring_back += math.hypot(dyaw, dpitch)
            if self.bring_back >= BRING_BACK_DEG:
                self.bring_back = 0.0
                oy = S.clamp(oy, -CURSOR_LIMIT[0] + BRING_BACK_IN_DEG, CURSOR_LIMIT[0] - BRING_BACK_IN_DEG)
                op = S.clamp(op, -CURSOR_LIMIT[1] + BRING_BACK_IN_DEG, CURSOR_LIMIT[1] - BRING_BACK_IN_DEG)
                self.cursor_world = [S.wrap(head_yaw + oy), head_pitch + op]
        else:
            self.bring_back = 0.0
            self.cursor_world[0] = S.wrap(self.cursor_world[0] + dyaw)
            self.cursor_world[1] = S.clamp(self.cursor_world[1] + dpitch, -89.0, 89.0)
        # keep the head-relative offset current, for switching back
        self.cursor = [S.clamp(S.wrap(self.cursor_world[0] - head_yaw), -CURSOR_LIMIT[0], CURSOR_LIMIT[0]),
                       S.clamp(self.cursor_world[1] - head_pitch, -CURSOR_LIMIT[1], CURSOR_LIMIT[1])]
        self.ray = S.direction(self.cursor_world[0], self.cursor_world[1])

    def _hit(self, panels, now):
        best = None
        if self.cc is not None:
            if self.cc[0] is None:
                self._spec("cc")
            h = self._card_hit(self.cc[0], "cc")
            if h:
                return h
        if self.launcher is not None:
            h = self._card_hit(self.launcher[0], "launcher")
            if h:
                return h
        locked = self.app.settings.get("locked", False)
        for p in panels:
            if p.key not in self.poses:
                continue
            pose = self._pose(p.key, now)
            r = S.surface_uv(pose, self.ray)
            if r is None:
                continue
            u, v, depth = r
            zn, name = S.zone(pose, u, v, locked, app=p.key != "deck")
            if zn is None:
                continue
            if best is None or depth < best[6] - 0.01:
                best = ("window", p.key, zn, name, u, v, depth)
        return best

    def _warp(self, panels, out_size):
        cap = self.app.capture
        h = self.hover
        if self.drag or self.resize or self.adjust_all is not None or h is None or h[0] != "window" or h[2] != S.BODY \
                or h[1] == "deck":
            cap.warp_target = None  # the view's clickable spot
            cap.warp_key = None
            return
        p = next((q for q in panels if q.key == h[1]), None)
        if p is None or p.w <= 0:
            cap.warp_target = None
            cap.warp_key = None
            return
        u, v = S.clamp(h[4], 0.0, 0.999), S.clamp(h[5], 0.0, 0.999)
        cap.warp_key = p.key  # kept on top under the pointer by the capture thread (_keep_on_top)
        cap.warp_target = (p.root_x + u * p.w, p.root_y + v * p.h)
        if self.last_raised != p.key:
            cap.raise_window(p.key)
            self.last_raised = p.key

    # ---------- input ----------
    def mouse(self, button, down, now):
        h = self.hover
        if down:
            self.log(f"space: button {button} down over {h[0] + ' ' + str(h[1]) + ' ' + str(h[2]) + ' ' + str(h[3]) if h else 'nothing'}")
        if button == 1:
            self.pressing = down
        if not down:
            if self.drag:
                self._drag_end()
            if self.resize:
                self._resize_end()
            return
        if button != 1:
            return
        self.ripple = (self.ray, now)
        if self.adjust_all is not None:
            self.adjust_all = None  # a click lets go
            self.save_places()
            return
        if h is None:
            return
        kind = h[0]
        if kind in ("launcher", "cc"):
            if h[1] is not None:
                self._item(h[1])
            return
        key, zn, name = h[1], h[2], h[3]
        pose = self.poses.get(key)
        if pose is None:
            return
        locked = self.app.settings.get("locked", False)
        if zn == S.BUTTON:
            if name == "move" and not locked:
                self._drag_start(key, pose)
            elif name == "close" and key != "deck":
                self.app.capture.close_window(key)
            elif name == "back" and key != "deck":
                self.app.capture.key_to(key, "alt+Left")
            elif name == "reset" and not locked:
                q = pose.copy()
                yaw, _ = S.angles(fusion.qrot(self.app.head.view(), (0.0, 0.0, -1.0))) if self.app.head else (0, 0)
                q.yaw, q.pitch = yaw, -math.degrees(math.asin(min(0.9, S.RESET_DROP_M / q.distance)))
                self.tweens[key] = (pose.copy(), q, now)
                self.poses[key] = q
        elif zn == S.FRAME and not locked:
            self._drag_start(key, pose)
        elif zn == S.HANDLE and not locked:
            self.resize = {"key": key, "t0": now, "ray0": S.angles(self.ray), "active": False,
                           "left": pose.left, "top": pose.top}
        if key != "deck" and self.focus and self.focus != key:
            self.focus = key
        # Keys go to the window last clicked, as in Pocket XR: give the app back the keyboard after a button.
        if key != "deck":
            self.app.capture.activate(key)

    def wheel(self, dy):
        """Over a window's frame or Move pill, or while moving it: push it further or pull it closer."""
        if self.adjust_all is not None:
            self._adjust_all_depth(dy)
            return
        if self.launcher is not None and self.hover and self.hover[0] == "launcher":
            self._page(-1 if dy > 0 else 1)
            return
        now = time.monotonic()
        key = self.drag["key"] if self.drag else (self.hover[1] if self.hover and self.hover[0] == "window" and
                                                   self.hover[2] in (S.FRAME, S.BUTTON) else None)
        # A window being pushed or pulled stays the one until the scrolling pauses: as it changes size the Move pill
        # slides out from under the pointer, and the scroll must not stop there.
        if self.wheel_hold and now < self.wheel_hold[1] and self.wheel_hold[0] in self.poses:
            key = self.wheel_hold[0]
        if key is None or key not in self.poses or self.app.settings.get("locked", False):
            return
        self.wheel_hold = (key, now + WHEEL_HOLD_S)
        self.depth(key, WHEEL_DEPTH_STEPS if dy > 0 else -WHEEL_DEPTH_STEPS)

    def depth(self, key, step):
        """Further (step > 0) or closer, keeping the window's size in metres (it looks smaller further away)."""
        p = self.poses[key]
        wm, hm = p.width_m(), p.height_m()
        d = S.clamp(p.distance * (1 + S.DEPTH_STEP * step) if step > 0 else p.distance / (1 + S.DEPTH_STEP * -step),
                    S.MIN_DISTANCE, S.MAX_DISTANCE)
        q = p.copy()
        q.distance = d
        q.wdeg = S.clamp(S.m_to_deg(wm, d), S.DEPTH_MIN_SIZE_DEG, S.MAX_WIDTH_DEG)
        q.hdeg = S.clamp(S.m_to_deg(hm, d), S.DEPTH_MIN_SIZE_DEG, S.MAX_HEIGHT_DEG)
        self.poses[key] = q

    # ---------- move ----------
    def _drag_start(self, key, pose):
        ry, rp = S.angles(self.ray)
        self.drag = {"key": key, "off": (S.wrap(pose.yaw - ry), pose.pitch - rp)}
        self.snap_partner = None
        self.fit = None

    def _drag_update(self):
        key = self.drag["key"]
        p = self.poses.get(key)
        if p is None:
            self.drag = None
            return
        ry, rp = S.angles(self.ray)
        q = p.copy()
        q.yaw = S.wrap(ry + self.drag["off"][0])
        q.pitch = S.clamp(rp + self.drag["off"][1], -S.MAX_PITCH, S.MAX_PITCH)
        self.fit = None
        if self.app.settings.get("snap", False):
            others = [o for k, o in self.poses.items() if k != key]
            yaw, pitch, part, fit = S.snap(q, others, self.snap_partner)
            q.yaw, q.pitch = yaw, pitch
            self.snap_partner = part
            self.fit = fit
        self.poses[key] = q

    def _drag_end(self):
        key = self.drag["key"]
        p = self.poses.get(key)
        if p is not None and self.fit:
            q = p.copy()
            q.wdeg = self.fit[0]
            if self.fit[1]:
                q.hdeg = self.fit[1]
            self.poses[key] = q
            self._fit_app_pixels(key, q, self.app.capture.glasses_rect[2:] if self.app.capture.glasses_rect else None)
        self.drag = None
        self.fit = None
        self.save_places()

    # ---------- resize ----------
    def _resize_update(self, now):
        r = self.resize
        p = self.poses.get(r["key"])
        if p is None:
            self.resize = None
            return
        ry, rp = S.angles(self.ray)
        if not r["active"]:
            moved = math.hypot(S.wrap(ry - r["ray0"][0]), rp - r["ray0"][1])
            if now - r["t0"] >= S.RESIZE_HOLD_S and moved >= S.RESIZE_MOVE_DEG:
                r["active"] = True
            else:
                return
        q = p.copy()
        q.wdeg = S.clamp(S.wrap(r["left"] - ry), S.MIN_SIZE_DEG, S.MAX_WIDTH_DEG)
        q.hdeg = S.clamp(r["top"] - rp, S.MIN_SIZE_DEG, S.MAX_HEIGHT_DEG)
        q.yaw = S.wrap(r["left"] - q.wdeg / 2)
        q.pitch = r["top"] - q.hdeg / 2
        self.poses[r["key"]] = q

    def _resize_end(self):
        r = self.resize
        self.resize = None
        if r["active"] and r["key"] in self.poses and r["key"] != "deck":
            g = self.app.capture.glasses_rect
            self._fit_app_pixels(r["key"], self.poses[r["key"]], g[2:] if g else None)
        self.save_places()

    # ---------- curve ----------
    def curve(self, key, step):
        p = self.poses.get(key)
        if p is None or self.app.settings.get("locked", False):
            return
        q = p.copy()
        c = round((p.curve / S.CURVE_MAX) * 10 + step) / 10 * S.CURVE_MAX
        q.curve = 0.0 if c < 0.04 * S.CURVE_MAX else min(c, S.max_curve(p.wdeg))
        self.poses[key] = q
        self.save_places()

    # ---------- arrange, presets, adjust all ----------
    def _ordered(self):
        keys = [k for k in self.poses if k != "deck"] or list(self.poses)
        return sorted(keys, key=lambda k: -self.poses[k].yaw)  # left to right

    def arrange(self, name, now):
        if self.app.settings.get("locked", False):
            return
        keys = self._ordered()
        if not keys:
            return
        main = keys.index(self.focus) if self.focus in keys else len(keys) - 1
        yaw = S.angles(fusion.qrot(self.app.head.view(), (0.0, 0.0, -1.0)))[0] if self.app.head else 0.0
        new = S.arrange(name, [self.poses[k] for k in keys], main, yaw)
        for k, q in zip(keys, new):
            self.tweens[k] = (self.poses[k].copy(), q, now)
            self.poses[k] = q
        g = self.app.capture.glasses_rect
        self.log(f"space: arranged {len(keys)} windows: {name}")
        self.save_places()
        # Arrange keeps the apps' own pixels, as in Pocket XR: only the pictures are scaled.
        del g

    def save_preset(self):
        wins = []
        for p in self.app.capture.snapshot():
            if p.key in self.poses and getattr(p, "cls", ""):
                wins.append({"app": p.cls, "pose": self.poses[p.key].to_json()})
        if wins:
            name = self.store.add_preset(wins)
            self.app.message = f"Saved this layout as {name}."
            self.toast(f"Saved as {name}")

    def recall_preset(self, i, now):
        if i >= len(self.store.presets) or self.app.settings.get("locked", False):
            return
        pr = self.store.presets[i]
        by_cls = {}
        for p in self.app.capture.snapshot():
            if p.key in self.poses:
                by_cls.setdefault(getattr(p, "cls", ""), []).append(p.key)
        for w in pr["windows"]:
            ks = by_cls.get(w["app"])
            if ks:
                k = ks.pop(0)
                self.tweens[k] = (self.poses[k].copy(), S.Pose.from_json(w["pose"]), now)
                self.poses[k] = S.Pose.from_json(w["pose"])
        self.app.message = f"{pr['name']}"
        self.toast(pr["name"])
        self.save_places()

    def start_adjust_all(self):
        if self.app.settings.get("locked", False) or not self.poses:
            return
        self.adjust_all = {}
        self.toast("Adjust all: move to turn, scroll to push or pull, click to let go")
        self.app.message = "Adjust all: move to turn every window, scroll to push or pull, Smaller or Bigger to resize. Click to let go."

    def _apply_all(self, **kw):
        keys = list(self.poses)
        new = S.adjust_all([self.poses[k] for k in keys], **kw)
        for k, q in zip(keys, new):
            self.poses[k] = q

    def _adjust_all_turn(self, dyaw, dpitch):
        self._apply_all(dyaw=dyaw, dpitch=dpitch)

    def _adjust_all_depth(self, dy):
        self._apply_all(dist_factor=(1 + S.DEPTH_STEP * WHEEL_DEPTH_STEPS) if dy > 0 else 1 / (1 + S.DEPTH_STEP * WHEEL_DEPTH_STEPS))

    def scale_all_or_focused(self, step):
        if self.adjust_all is not None:
            self._apply_all(size_factor=1.1 if step > 0 else 1 / 1.1)
            return
        key = self.focus if self.focus in self.poses else next(iter(self.poses), None)
        if key is None or self.app.settings.get("locked", False):
            return
        p = self.poses[key].copy()
        k = 1.1 if step > 0 else 1 / 1.1
        p.wdeg = S.clamp(p.wdeg * k, S.MIN_SIZE_DEG, S.MAX_WIDTH_DEG)
        p.hdeg = S.clamp(p.hdeg * k, S.MIN_SIZE_DEG, S.MAX_HEIGHT_DEG)
        self.poses[key] = p
        if key != "deck":
            g = self.app.capture.glasses_rect
            self._fit_app_pixels(key, p, g[2:] if g else None)
        self.save_places()

    # ---------- launcher ----------
    def toggle_launcher(self):
        now = time.monotonic()
        if self.launcher is not None:
            self._close_card("launcher", now)
            return
        if self.app_list is None:
            self.app_list = appsmod.list_apps()
        yaw, pitch = S.angles(fusion.qrot(self.app.head.view(), (0.0, 0.0, -1.0))) if self.app.head else (0.0, 0.0)
        self.launcher = [None, 0, now]
        self.launcher[0] = self._card_pose(yaw, pitch - LAUNCHER_DROP, LAUNCHER_D, LAUNCHER_W, 1450, 950)
        if self.cc is not None:
            self._close_card("cc", now)

    def _page(self, step):
        if self.launcher is None or not self.app_list:
            return
        pages = max(1, math.ceil(len(self.app_list) / (COLS * ROWS)))
        self.launcher[1] = (self.launcher[1] + step) % pages

    @staticmethod
    def _card_pose(yaw, pitch, d, width_m, wpx, hpx):
        return S.Pose(yaw, pitch, d, S.m_to_deg(width_m, d), S.m_to_deg(width_m * hpx / wpx, d))

    def _close_card(self, kind, now):
        """Cards fade out over EXIT_S, as Pocket XR's do."""
        card = self.launcher if kind == "launcher" else self.cc
        if card is not None and card[0] is not None:
            self.closing.append((kind, card[0], self.card_specs.get(kind), now))
        if kind == "launcher":
            self.launcher = None
        else:
            self.cc = None

    # ---------- Control Center ----------
    def toggle_cc(self, now):
        if self.cc is not None:
            self._close_card("cc", now)
            return
        yaw, pitch = S.angles(fusion.qrot(self.app.head.view(), (0.0, 0.0, -1.0))) if self.app.head else (0.0, 0.0)
        self.cc = [None, now, yaw, pitch]
        if self.launcher is not None:
            self._close_card("launcher", now)

    def _cc_state(self):
        s = self.app.settings
        keys = self._ordered()
        n = len(keys)
        foc = self.poses.get(self.focus)
        return {
            "n": n, "focus": bool(foc), "locked": s.get("locked", False), "snap": s.get("snap", False),
            "cursor_follows_head": s.get("cursor_follows_head", True), "speed": s.get("cursor_speed", 5),
            "sbs_3d": s.get("sbs_3d", True),
            "recording": self.app.recorder.wanted,
            "curve": int(round((foc.curve / S.CURVE_MAX) * 100)) if foc else 0,
            "presets": [p["name"] for p in self.store.presets],
        }

    def _spec(self, kind):
        """The card's painted texture and its items, painted again only when what it shows changes."""
        if kind == "launcher":
            key = ("launcher", self.launcher[1], len(self.app_list or []), ui.clock12())
        else:
            st = self._cc_state()
            key = ("cc",) + tuple((k, tuple(v) if isinstance(v, list) else v) for k, v in sorted(st.items()))
        cur = self.card_specs.get(kind)
        if cur is not None and cur[0] == key:
            self._place_cc(cur[1])
            return cur
        if kind == "launcher":
            spec = ui.launcher_card(self.app_list or [], self.launcher[1], lambda a: a.icon, COLS, ROWS)
        else:
            st = self._cc_state()
            keys = self._ordered()
            main = keys.index(self.focus) if self.focus in keys else max(0, len(keys) - 1)
            poses = [self.poses[k] for k in keys]
            layouts = [(name, S.arrange(name, poses, main, 0.0) if poses else [], main)
                       for name in S.layout_choices(max(1, len(keys)))]
            st["layouts"] = layouts
            spec = ui.cc_card(st)
        old = self.tex.pop(("card", kind), None)
        if old:
            gl.glDeleteTextures(1, ctypes.byref(ctypes.c_uint(old[0])))
        tid = self._tex(("card", kind), lambda: (spec.data, spec.w, spec.h))
        cur = (key, spec, tid)
        self.card_specs[kind] = cur
        if kind == "cc" and self.cc is not None and self.cc[0] is not None:
            p = self.cc[0]  # its content changed size: keep its place, take the new height
            self.cc[0] = self._card_pose(p.yaw, p.pitch, CC_D, S.deg_to_m(CC_WDEG, CC_D), spec.w, spec.h)
        self._place_cc(spec)
        return cur

    def _place_cc(self, spec):
        """A Control Center just opened gets its place from its card's size. (Reopened with nothing changed, its card
        is reused unpainted, and that path once left it with no place: R5 crashed the app, 11 Nov 2026.)"""
        if self.cc is not None and self.cc[0] is None:
            self.cc[0] = self._card_pose(self.cc[2], self.cc[3], CC_D, S.deg_to_m(CC_WDEG, CC_D), spec.w, spec.h)

    def _item(self, it):
        now = time.monotonic()
        a = it.action
        if a == "launch":
            self.pending_spot = (self.launcher[0].yaw, self.launcher[0].pitch + LAUNCHER_DROP, now + 20.0)
            appsmod.launch(it.arg, self.log)
            self.toast(f"Opening {it.arg.name}")
            self._close_card("launcher", now)
        elif a == "pcvr":
            self._close_card("launcher", now)
            self._close_card("cc", now)
            self.app.start_pcvr()
        elif a == "page":
            self._page(it.arg)
        elif a == "launcher_close":
            self._close_card("launcher", now)
        elif a == "cc_close":
            self._close_card("cc", now)
        elif a == "record":
            self._close_card("cc", now)  # out of the way, so the video starts on the Space itself
            self.app.toggle_record()
        elif a == "recenter":
            self.app.recentre()
            self.toast("View recentred")
        elif a == "arrange":
            if self.app.settings.get("locked", False):
                self.toast("Screens are locked. Unlock them from the Control Center.")
            else:
                self.arrange(it.arg, now)
                self.toast(it.arg)
        elif a == "adjust_all":
            self._close_card("cc", now)
            self.start_adjust_all()
        elif a == "toggle":
            on = not self.app.settings.get(it.arg, it.arg in ("cursor_follows_head", "sbs_3d"))
            self.app.set_setting(it.arg, on)
            names = {"snap": "Snap", "locked": "Lock screens", "cursor_follows_head": "Cursor follows head",
                     "sbs_3d": "3D"}
            self.toast(f"{names.get(it.arg, it.arg)} {'on' if on else 'off'}")
        elif a == "speed":
            self.app.set_setting("cursor_speed", int(S.clamp(self.app.settings.get("cursor_speed", 5) + it.arg, 1, 10)))
        elif a == "curve":
            if self.focus in self.poses:
                self.curve(self.focus, it.arg)
        elif a == "preset":
            self.recall_preset(it.arg, now)
        elif a == "save_preset":
            self.save_preset()

    def toast(self, msg):
        self.toasts = [(msg, time.monotonic())]

    # ---------- drawing ----------
    def draw(self, panels, now, texture_of):
        # windows dim to 0.3 under a card (the Control Center, as in Pocket XR, and the launcher)
        dim_cc = DIM_UNDER_CC if (self.cc is not None or self.launcher is not None) else 1.0
        # Far to near: with no depth buffer (as on Pocket XR), the nearer window must be drawn last to hide what is
        # behind it. Mike, 11 Nov 2026: a window pulled close still showed the one behind it through it.
        shown = sorted((p for p in panels if p.key in self.poses), key=lambda p: -self._pose(p.key, now).distance)
        multi = len(shown) > 1
        locked = self.app.settings.get("locked", False)
        for p in shown:
            pose = self._pose(p.key, now)
            # appear: brightness and size ease in (black is see-through on the glasses, so dark is faded)
            t0 = self.appeared.setdefault(p.key, now)
            k = L.ease_enter((now - t0) / L.ENTER_S)
            scale = L.ENTER_SCALE + (1 - L.ENTER_SCALE) * k
            focused = p.key == self.focus
            held = bool((self.drag and self.drag["key"] == p.key) or (self.resize and self.resize["key"] == p.key) or
                        (self.wheel_hold and now < self.wheel_hold[1] and self.wheel_hold[0] == p.key))
            dim = dim_cc * k * (1.0 if (focused or not multi) else DIM_BEHIND)
            gl.glPushMatrix()
            gl.glRotatef(pose.yaw, 0.0, 1.0, 0.0)
            gl.glRotatef(pose.pitch, 1.0, 0.0, 0.0)
            if scale != 1.0:
                gl.glTranslatef(0.0, 0.0, -pose.distance)
                gl.glScalef(scale, scale, 1.0)
                gl.glTranslatef(0.0, 0.0, pose.distance)
            if (focused and multi) or held:
                self._halo(pose, L.HELD if held else L.ACCENT, HALO_ALPHA * dim_cc * k)
            self._surface(pose, texture_of(p), dim)
            self._rim(pose, (L.HELD[:3] + (0.9,)) if held else (L.RIM_FOCUS if focused else L.RIM), k * dim_cc)
            seen = self.ctl_seen.get(p.key)
            if seen is not None:
                age = now - seen
                alpha = 1.0 if age < S.CONTROLS_STAY_S else max(0.0, 1 - (age - S.CONTROLS_STAY_S) / S.CONTROLS_FADE_S)
                if alpha > 0:
                    self._controls(p.key, pose, alpha * dim_cc, locked, held, now)
            if p.key == "deck" and p.pointer is not None and p.w > 0:
                # The Deck screen's own pointer, where it is on that screen.
                u, v = p.pointer[0] / p.w, p.pointer[1] / p.h
                x, f = S.column(pose, u)
                y = (0.5 - v) * pose.height_m()
                self._marks(x, y, -f + 0.004, pose.distance, 1.0, 0.0, 1.0, L.INK[:3], False)
            gl.glPopMatrix()
        if self.fit and self.drag and self.drag["key"] in self.poses:
            q = self.poses[self.drag["key"]].copy()
            q.wdeg = self.fit[0]
            if self.fit[1]:
                q.hdeg = self.fit[1]
            gl.glPushMatrix()
            gl.glRotatef(q.yaw, 0.0, 1.0, 0.0)
            gl.glRotatef(q.pitch, 1.0, 0.0, 0.0)
            self._rim(q, L.ACCENT, 1.0, width=3.0)
            gl.glPopMatrix()
        for kind, pose, spec, t0 in list(self.closing):
            a = 1 - L.ease_exit((now - t0) / L.EXIT_S)
            if a <= 0:
                self.closing.remove((kind, pose, spec, t0))
                continue
            if spec:
                self._draw_card(pose, spec, kind, a, 1.0, None)
        if self.launcher is not None:
            spec = self._spec("launcher")
            k = L.ease_enter((now - self.launcher[2]) / L.ENTER_S)
            self._draw_card(self.launcher[0], spec, "launcher", k, L.ENTER_SCALE + (1 - L.ENTER_SCALE) * k, now)
        if self.cc is not None:
            spec = self._spec("cc")
            k = L.ease_enter((now - self.cc[1]) / L.ENTER_S)
            self._draw_card(self.cc[0], spec, "cc", k, L.ENTER_SCALE + (1 - L.ENTER_SCALE) * k, now)
        self._draw_toast(now)
        self._cursor(now)

    def _columns(self, pose, geo):
        """u values across the window: dense near the edges for round corners, every 1/32 in between."""
        W = pose.width_m()
        r = self._corner(pose)
        edge = min(0.5, r / W)
        us = {0.0, 1.0}
        for i in range(1, 7):
            us.add(edge * (1 - math.cos(math.pi / 2 * i / 6)))
            us.add(1 - edge * (1 - math.cos(math.pi / 2 * i / 6)))
        n = S.CURVE_COLUMNS if geo else 16
        for i in range(1, n):
            us.add(i / n)
        return sorted(us)

    @staticmethod
    def _corner(pose):
        """Corner radius: 3 % of the shorter side, 5 to 25 mm (Pocket XR WindowGlow)."""
        return S.clamp(0.03 * min(pose.width_m(), pose.height_m()), 0.005, 0.025)

    def _inset(self, pose, u):
        """How far the top and bottom come in at u, for round corners."""
        W = pose.width_m()
        r = self._corner(pose)
        dx = min(u, 1 - u) * W
        if dx >= r:
            return 0.0
        return r - math.sqrt(max(0.0, r * r - (r - dx) ** 2))

    def _surface(self, pose, tex, dim):
        geo = S.curve_geometry(pose)
        H = pose.height_m()
        hh = H / 2
        if tex:
            gl.glEnable(GL_TEXTURE_2D)
            gl.glBindTexture(GL_TEXTURE_2D, tex)
            gl.glColor3f(dim, dim, dim)
        else:
            c = L.GLASS
            gl.glColor3f(c[0] * dim, c[1] * dim, c[2] * dim)
        gl.glBegin(GL_QUAD_STRIP)
        for u in self._columns(pose, geo):
            x, f = S.column(pose, u, geo)
            ins = self._inset(pose, u)
            vt, vb = ins / H, 1 - ins / H
            gl.glTexCoord2f(u, vb); gl.glVertex3f(x, -hh + ins, -f)  # noqa: E702
            gl.glTexCoord2f(u, vt); gl.glVertex3f(x, hh - ins, -f)  # noqa: E702
        gl.glEnd()
        gl.glDisable(GL_TEXTURE_2D)

    def _outline(self, pose, grow=0.0, z=0.002):
        geo = S.curve_geometry(pose)
        hh = pose.height_m() / 2 + grow
        top, bot = [], []
        for u in self._columns(pose, geo):
            x, f = S.column(pose, u, geo)
            if u == 0.0:
                x -= grow
            elif u == 1.0:
                x += grow
            ins = self._inset(pose, u)
            top.append((x, hh - ins, -f + z))
            bot.append((x, -hh + ins, -f + z))
        return top, bot

    def _rim(self, pose, col, alpha, width=None):
        """The hairline light rim (white 14 %, 32 % in focus)."""
        top, bot = self._outline(pose)
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        gl.glLineWidth(width or 1.5)
        gl.glColor4f(col[0], col[1], col[2], (col[3] if len(col) > 3 else 1.0) * alpha)
        gl.glBegin(GL_LINE_LOOP)
        for v in top + bot[::-1]:
            gl.glVertex3f(*v)
        gl.glEnd()
        gl.glLineWidth(1.0)
        gl.glDisable(GL_BLEND)

    def _halo(self, pose, col, alpha):
        """A faint accent halo just outside the edge, fading out (one band, no blur)."""
        grow = HALO_PER_M * pose.distance
        t0, b0 = self._outline(pose, 0.0, -0.003)
        t1, b1 = self._outline(pose, grow, -0.003)
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        ring_in = t0 + b0[::-1] + [t0[0]]
        ring_out = t1 + b1[::-1] + [t1[0]]
        gl.glBegin(GL_QUAD_STRIP)
        for a, b in zip(ring_in, ring_out):
            gl.glColor4f(col[0], col[1], col[2], alpha)
            gl.glVertex3f(*a)
            gl.glColor4f(col[0], col[1], col[2], 0.0)
            gl.glVertex3f(*b)
        gl.glEnd()
        gl.glDisable(GL_BLEND)

    def _quad_tex(self, tid, x, y, z, w, h, alpha=1.0, rgb=(1.0, 1.0, 1.0)):
        """A premultiplied texture centred at (x, y, z) in the current frame, w x h metres, tinted [rgb]."""
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(GL_TEXTURE_2D)
        gl.glBindTexture(GL_TEXTURE_2D, tid)
        gl.glColor4f(rgb[0] * alpha, rgb[1] * alpha, rgb[2] * alpha, alpha)
        gl.glBegin(GL_QUADS)
        gl.glTexCoord2f(0, 1); gl.glVertex3f(x - w / 2, y - h / 2, z)  # noqa: E702
        gl.glTexCoord2f(1, 1); gl.glVertex3f(x + w / 2, y - h / 2, z)  # noqa: E702
        gl.glTexCoord2f(1, 0); gl.glVertex3f(x + w / 2, y + h / 2, z)  # noqa: E702
        gl.glTexCoord2f(0, 0); gl.glVertex3f(x - w / 2, y + h / 2, z)  # noqa: E702
        gl.glEnd()
        gl.glDisable(GL_TEXTURE_2D)
        gl.glDisable(GL_BLEND)

    def _controls(self, key, pose, alpha, locked, held, now):
        """The window's controls as glass capsules above it: Back, the Move pill, then Reset and Close."""
        btns, v0, v1 = S.buttons(pose, app=key != "deck")
        by = {n: (u0, u1) for n, u0, u1 in btns}
        H, W = pose.height_m(), pose.width_m()
        hb = H * (v1 - v0)
        pad = 0.16 * hb
        y = (0.5 - (v0 + v1) / 2) * H
        hname = self.hover[3] if self.hover and self.hover[0] == "window" and self.hover[1] == key else None
        groups = []
        if "back" in by:
            groups.append((["back"], by["back"]))
        if not locked:
            groups.append((["move"], by["move"]))
        groups.append((["reset", "close"] if not locked else ["close"],
                       (by["reset"][0] if not locked else by["close"][0], by["close"][1])))
        for names, (u0, u1) in groups:
            wm = (u1 - u0) * W + 2 * pad
            hm = hb + 2 * pad
            px_h = 72
            px_w = int(round(px_h * wm / hm))
            hov = hname if hname in names else None
            if names == ["move"]:
                key_ = ("cap", "move", px_w, hov is not None or held)
                t = self._tex(key_, lambda: ui.capsule(["move"], "move" if (hov or held) else None, h=px_h,
                                                        pill_w=px_w - 2 * round(px_h * 0.16), held=held))
            else:
                key_ = ("cap", tuple(names), px_w, hov)
                t = self._tex(key_, lambda names=names, hov=hov: ui.capsule(names, hov, h=px_h))
            if t:
                xc, f = S.column(pose, (u0 + u1) / 2)
                self._quad_tex(t[0], xc, y, -f + 0.003, wm, hm, alpha)
        # the resize handle, or a lock while screens are locked, when the pointer is on this window
        if self.hover and self.hover[0] == "window" and self.hover[1] == key or self.resize and self.resize["key"] == key:
            x, f = S.column(pose, 1.0)
            active = (self.hover and self.hover[2] == S.HANDLE) or self.resize is not None
            t = self._tex(("handle", bool(active), locked), lambda: ui.handle(60, active, locked))
            if t:
                s_ = hb * (0.8 if locked else 1.0)
                off = 0.25 * hb
                self._quad_tex(t[0], x + off - s_ / 2 + (0 if locked else 0.2 * hb), -H / 2 - off + s_ / 2 -
                               (0 if locked else 0.2 * hb), -f + 0.003, s_, s_, alpha)

    def _draw_card(self, pose, spec_entry, kind, alpha, scale, now):
        key, spec, tid = spec_entry
        if not tid or pose is None:
            return
        W, H = pose.width_m(), pose.height_m()
        gl.glPushMatrix()
        gl.glRotatef(pose.yaw, 0.0, 1.0, 0.0)
        gl.glRotatef(pose.pitch, 1.0, 0.0, 0.0)
        z = -pose.distance
        # fade and rise about 2 %
        rise = (1 - scale) / (1 - L.ENTER_SCALE) * 0.02 * H if scale < 1 else 0.0
        self._quad_tex(tid[0], 0.0, rise, z, W * scale, H * scale, alpha)
        # hover overlay on the item under the pointer
        if now is not None and self.hover and self.hover[0] == kind and self.hover[1] is not None:
            it = self.hover[1]
            x, y, w, h, r = it.x, it.y, it.w, it.h, it.r
            ov = self._tex(("ov", int(w), int(h), int(r)), lambda: ui.overlay(w, h, r, (1, 1, 1, 1), 0.08))
            if ov:
                cx = (x + w / 2) / spec.w * W - W / 2
                cy = H / 2 - (y + h / 2) / spec.h * H
                self._quad_tex(ov[0], cx * scale, cy * scale + rise, z + 0.002, w / spec.w * W * scale,
                               h / spec.h * H * scale, alpha)
            # app icons and labels sit on the card itself; launcher tiles also take a soft accent wash
        gl.glPopMatrix()

    def _card_hit(self, pose, kind):
        if pose is None:
            return None
        r = S.surface_uv(pose, self.ray)
        if r is None:
            return None
        u, v, depth = r
        if not (0 <= u <= 1 and 0 <= v <= 1):
            return None
        entry = self.card_specs.get(kind)
        if entry is None:
            return (kind, None, "card", None, u, v, depth)
        spec = entry[1]
        px, py = u * spec.w, v * spec.h
        for (x, y, w, h, action, arg, rad) in spec.items:
            if x <= px <= x + w and y <= py <= y + h:
                return (kind, CardItem(x, y, w, h, action, arg, rad), "item", action, u, v, depth)
        return (kind, None, "card", None, u, v, depth)

    def _draw_toast(self, now):
        if not self.toasts:
            return
        msg, t0 = self.toasts[0]
        age = now - t0
        if age > TOAST_S + L.EXIT_S:
            self.toasts = []
            return
        a = L.ease_enter(age / L.ENTER_S) if age < TOAST_S else 1 - L.ease_exit((age - TOAST_S) / L.EXIT_S)
        t = self._tex(("toast", msg), lambda: ui.toast(msg))
        if not t:
            return
        view = self.app.head.view() if self.app.head else (1.0, 0.0, 0.0, 0.0)
        yaw, pitch = S.angles(fusion.qrot(view, S.direction(0.0, -TOAST_DROP_DEG)))
        h = 2 * TOAST_D * math.tan(math.radians(2.2) / 2)
        w = h * t[1] / t[2]
        gl.glPushMatrix()
        gl.glRotatef(yaw, 0.0, 1.0, 0.0)
        gl.glRotatef(pitch, 1.0, 0.0, 0.0)
        self._quad_tex(t[0], 0.0, (1 - a) * -0.01, -TOAST_D, w, h, a)
        gl.glPopMatrix()

    def _cursor(self, now):
        """The cursor, exactly as Pocket XR on Android draws it (SpaceRenderer.drawCursor, 0.5.70 "Light on glass"): a crisp
        white dot with a dark hairline, so it reads on a bright page as on the room; a soft light bloom round it; a thin
        ring growing in over anything it can press (accent and a third bigger on a window's frame, where it moves the
        window); the accent while pressing or dragging; and a ripple ring on each press."""
        h = self.hover
        dt = min(0.2, now - self.cursor_t) if self.cursor_t else 0.0
        self.cursor_t = now
        step = dt / RETICLE_HOVER_S
        self.ring_k = min(1.0, self.ring_k + step) if h is not None else max(0.0, self.ring_k - step)
        depth = (h[6] - 0.005) if h else CURSOR_IDLE_M
        active = self.pressing or self.drag is not None or self.resize is not None
        colour = L.ACCENT[:3] if active else L.INK[:3]
        on_frame = h is not None and h[0] == "window" and h[2] == S.FRAME
        yaw, pitch = S.angles(self.ray)
        gl.glPushMatrix()
        gl.glRotatef(yaw, 0.0, 1.0, 0.0)
        gl.glRotatef(pitch, 1.0, 0.0, 0.0)
        press = RETICLE_PRESS_SCALE if self.pressing else 1.0
        self._marks(0.0, 0.0, -depth, depth, press, self.ring_k, 1.0, colour, on_frame, now)
        gl.glPopMatrix()

    def _marks(self, x, y, z, dist, dot_scale, ring_alpha, alpha, colour, on_frame, now=None):
        """The cursor's round marks at (x, y, z) facing the eyes, [dist] metres away: a unit is 0.8 degrees across."""
        u = dist * CURSOR_UNIT
        glow = self._tex(("cursor_mark", "glow"), lambda: ui.cursor_mark("glow", 128))
        ring = self._tex(("cursor_mark", "ring"), lambda: ui.cursor_mark("ring", 96, CURSOR_RING_INNER))
        dot = self._tex(("cursor_mark", "dot"), lambda: ui.cursor_mark("dot", 48, CURSOR_DOT_CORE))
        if not (glow and ring and dot):
            return
        s = CURSOR_GLOW * dot_scale * u
        self._quad_tex(glow[0], x, y, z, s, s, CURSOR_GLOW_ALPHA * alpha)
        if ring_alpha > 0.01:
            ring_scale = (RETICLE_HOVER_MIN + (1 - RETICLE_HOVER_MIN) * ring_alpha) * dot_scale
            s = CURSOR_RING * ring_scale * (1.35 if on_frame else 1.0) * u
            self._quad_tex(ring[0], x, y, z + 0.0005, s, s, 0.9 * alpha * ring_alpha,
                           L.ACCENT[:3] if on_frame else colour)
        if now is not None and self.ripple and now - self.ripple[1] < RIPPLE_S:
            t = (now - self.ripple[1]) / RIPPLE_S
            rip = self._tex(("cursor_mark", "ripple"), lambda: ui.cursor_mark("ring", 128, RIPPLE_INNER))
            if rip:
                s = (CURSOR_RING + (RIPPLE_TO - CURSOR_RING) * L.ease_enter(t)) * u
                self._quad_tex(rip[0], x, y, z + 0.0008, s, s, 0.7 * (1 - t) * alpha, L.ACCENT[:3])
        s = CURSOR_DOT * dot_scale * u
        self._quad_tex(dot[0], x, y, z + 0.001, s, s, alpha, colour)


class CardItem:
    __slots__ = ("x", "y", "w", "h", "action", "arg", "r")

    def __init__(self, x, y, w, h, action, arg, r):
        self.x, self.y, self.w, self.h, self.action, self.arg, self.r = x, y, w, h, action, arg, r

    def __eq__(self, o):
        return isinstance(o, CardItem) and (self.x, self.y, self.action) == (o.x, o.y, o.action)

    def __hash__(self):
        return hash((self.x, self.y, self.action))
