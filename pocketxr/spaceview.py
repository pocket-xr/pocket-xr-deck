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
from . import text
from .gl import (GL_BLEND, GL_LINEAR, GL_LINE_LOOP, GL_ONE_MINUS_SRC_ALPHA, GL_QUADS, GL_RGBA, GL_BGRA,
                 GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER, GL_UNSIGNED_BYTE, gl)

GL_ONE = 1
GL_QUAD_STRIP = 0x0008
ACCENT = (0x5A / 255, 0x93 / 255, 1.0)
HELD = (0x8F / 255, 0xB6 / 255, 1.0)
INK2 = (0.62, 0.62, 0.66)
HALO_PER_M = 0.012
HALO_ALPHA = 0.32
RIM_PER_M = 0.0007
CURSOR_DEG = 1.1
CURSOR_IDLE_M = 2.5
CURSOR_LIMIT = (28.0, 17.0)  # the space pointer stays inside the glasses' view (degrees from the centre)
DIM_UNDER_CC = 0.3
WHEEL_DEPTH_STEPS = 2  # one wheel notch = Further/Closer x2 (distance x (1 + 0.03 x 2))
LAUNCHER_D, LAUNCHER_W, LAUNCHER_H, LAUNCHER_DROP = 1.0, 1.007, 0.66, 5.0
CC_D, CC_WDEG = 1.8, 38.0
CC_OPEN_S = 0.22
COLS, ROWS = 5, 3
LEAVE_PUSH_DEG = 8.0
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

    def _card_hit(self, pose, kind):
        r = S.surface_uv(pose, self.ray)
        if r is None:
            return None
        u, v, depth = r
        if not (0 <= u <= 1 and 0 <= v <= 1):
            return None
        items = self._launcher_items() if kind == "launcher" else self._cc_items()
        for it in items:
            if it.u0 <= u <= it.u1 and it.v0 <= v <= it.v1:
                return (kind, it, "item", it.action, u, v, depth)
        return (kind, None, "card", None, u, v, depth)

    def _warp(self, panels, out_size):
        cap = self.app.capture
        h = self.hover
        if self.drag or self.resize or self.adjust_all is not None or h is None or h[0] != "window" or h[2] != S.BODY \
                or h[1] == "deck":
            cap.warp_target = None  # the view's clickable spot
            return
        p = next((q for q in panels if q.key == h[1]), None)
        if p is None or p.w <= 0:
            cap.warp_target = None
            return
        u, v = S.clamp(h[4], 0.0, 0.999), S.clamp(h[5], 0.0, 0.999)
        cap.warp_target = (p.root_x + u * p.w, p.root_y + v * p.h)
        if self.last_raised != p.key:
            cap.raise_window(p.key)
            self.last_raised = p.key

    # ---------- input ----------
    def mouse(self, button, down, now):
        h = self.hover
        if down:
            self.log(f"space: button {button} down over {h[0] + ' ' + str(h[1]) + ' ' + str(h[2]) + ' ' + str(h[3]) if h else 'nothing'}")
        if not down:
            if self.drag:
                self._drag_end()
            if self.resize:
                self._resize_end()
            return
        if button != 1:
            return
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
        key = self.drag["key"] if self.drag else (self.hover[1] if self.hover and self.hover[0] == "window" and
                                                   self.hover[2] in (S.FRAME, S.BUTTON) else None)
        if key is None or key not in self.poses or self.app.settings.get("locked", False):
            return
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
        if self.app.settings.get("snap", True):
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
        self.save_places()

    def start_adjust_all(self):
        if self.app.settings.get("locked", False) or not self.poses:
            return
        self.adjust_all = {}
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
        if self.launcher is not None:
            self.launcher = None
            return
        if self.app_list is None:
            self.app_list = appsmod.list_apps()
        yaw, pitch = S.angles(fusion.qrot(self.app.head.view(), (0.0, 0.0, -1.0))) if self.app.head else (0.0, 0.0)
        pose = S.Pose(yaw, pitch - LAUNCHER_DROP, LAUNCHER_D, S.m_to_deg(LAUNCHER_W, LAUNCHER_D),
                      S.m_to_deg(LAUNCHER_H, LAUNCHER_D))
        self.launcher = [pose, 0]
        self.cc = None

    def _page(self, step):
        if self.launcher is None or not self.app_list:
            return
        pages = max(1, math.ceil(len(self.app_list) / (COLS * ROWS)))
        self.launcher[1] = (self.launcher[1] + step) % pages

    def _launcher_items(self):
        items = [Item(0.92, 0.03, 0.98, 0.12, "launcher_close", label="close")]
        if not self.app_list:
            return items
        per = COLS * ROWS
        page = self.launcher[1]
        shown = self.app_list[page * per:(page + 1) * per]
        for i, a in enumerate(shown):
            r, c = divmod(i, COLS)
            u0 = 0.06 + c * 0.18
            v0 = 0.17 + r * 0.25
            items.append(Item(u0, v0, u0 + 0.16, v0 + 0.23, "launch", a, a.name, kind="app"))
        pages = max(1, math.ceil(len(self.app_list) / per))
        if pages > 1:
            items.append(Item(0.30, 0.92, 0.42, 0.99, "page", -1, "<"))
            items.append(Item(0.58, 0.92, 0.70, 0.99, "page", 1, ">"))
        return items

    # ---------- Control Center ----------
    def toggle_cc(self, now):
        if self.cc is not None:
            self.cc = None
            return
        yaw, pitch = S.angles(fusion.qrot(self.app.head.view(), (0.0, 0.0, -1.0))) if self.app.head else (0.0, 0.0)
        pose = S.Pose(yaw, pitch, CC_D, CC_WDEG, CC_WDEG * 0.72)
        self.cc = (pose, now)
        self.launcher = None

    def _cc_items(self):
        s = self.app.settings
        items = [Item(0.04, 0.04, 0.30, 0.13, "recenter", label="Recenter view"),
                 Item(0.88, 0.04, 0.96, 0.13, "cc_close", label="close")]
        n = len([k for k in self.poses if k != "deck"]) or len(self.poses)
        y = 0.20
        for i, name in enumerate(S.layout_choices(max(1, n)) + ["Adjust all"]):
            r, c = divmod(i, 2)
            items.append(Item(0.04 + c * 0.23, y + r * 0.11, 0.25 + c * 0.23, y + r * 0.11 + 0.09,
                              "adjust_all" if name == "Adjust all" else "arrange", name, name))
        toggles = [("snap", "Snap", s.get("snap", True)), ("locked", "Lock screens", s.get("locked", False)),
                   ("cursor_follows_head", "Cursor follows head", s.get("cursor_follows_head", True))]
        for i, (k, label, on) in enumerate(toggles):
            items.append(Item(0.54, 0.20 + i * 0.11, 0.96, 0.29 + i * 0.11, "toggle", k, label, on, kind="toggle"))
        sp = s.get("cursor_speed", 5)
        items.append(Item(0.54, 0.53, 0.62, 0.62, "speed", -1, "-"))
        items.append(Item(0.63, 0.53, 0.87, 0.62, "noop", None, f"Cursor speed {sp * 10}%", kind="text"))
        items.append(Item(0.88, 0.53, 0.96, 0.62, "speed", 1, "+"))
        foc = self.poses.get(self.focus)
        cpct = int(round((foc.curve / S.CURVE_MAX) * 100)) if foc else 0
        items.append(Item(0.54, 0.64, 0.62, 0.72, "curve", -1, "-"))
        items.append(Item(0.63, 0.64, 0.87, 0.72, "noop", None, f"Curve {cpct}%", kind="text"))
        items.append(Item(0.88, 0.64, 0.96, 0.72, "curve", 1, "+"))
        for i, pr in enumerate(self.store.presets[:2]):
            items.append(Item(0.54, 0.75 + i * 0.08, 0.96, 0.82 + i * 0.08, "preset", i, pr["name"]))
        n = min(2, len(self.store.presets))
        items.append(Item(0.54, 0.75 + n * 0.08, 0.96, 0.82 + n * 0.08, "save_preset", None, "Save layout"))
        return items

    def _item(self, it):
        now = time.monotonic()
        a = it.action
        if a == "launch":
            self.pending_spot = (self.launcher[0].yaw, self.launcher[0].pitch + LAUNCHER_DROP, now + 20.0)
            appsmod.launch(it.arg, self.log)
            self.launcher = None
        elif a == "page":
            self._page(it.arg)
        elif a == "launcher_close":
            self.launcher = None
        elif a == "cc_close":
            self.cc = None
        elif a == "recenter":
            self.app.recentre()
        elif a == "arrange":
            self.arrange(it.arg, now)
        elif a == "adjust_all":
            self.cc = None
            self.start_adjust_all()
        elif a == "toggle":
            self.app.set_setting(it.arg, not self.app.settings.get(it.arg, it.arg in ("snap", "cursor_follows_head")))
        elif a == "speed":
            self.app.set_setting("cursor_speed", int(S.clamp(self.app.settings.get("cursor_speed", 5) + it.arg, 1, 10)))
        elif a == "curve":
            if self.focus in self.poses:
                self.curve(self.focus, it.arg)
        elif a == "preset":
            self.recall_preset(it.arg, now)
        elif a == "save_preset":
            self.save_preset()

    # ---------- drawing ----------
    def draw(self, panels, now, texture_of):
        dim = DIM_UNDER_CC if self.cc is not None else 1.0
        multi = len([p for p in panels if p.key in self.poses]) > 1
        hover_key = self.hover[1] if self.hover and self.hover[0] == "window" else None
        locked = self.app.settings.get("locked", False)
        for p in panels:
            if p.key not in self.poses:
                continue
            pose = self._pose(p.key, now)
            tex = texture_of(p)
            gl.glPushMatrix()
            gl.glRotatef(pose.yaw, 0.0, 1.0, 0.0)
            gl.glRotatef(pose.pitch, 1.0, 0.0, 0.0)
            focused = p.key == self.focus
            held = (self.drag and self.drag["key"] == p.key) or (self.resize and self.resize["key"] == p.key)
            if focused and multi:
                self._halo(pose, HELD if held else ACCENT, HALO_ALPHA * dim)
            self._surface(pose, tex, dim)
            self._rim(pose, (HELD if held else ACCENT) if (focused or held) else (0.35, 0.36, 0.4), dim)
            seen = self.ctl_seen.get(p.key)
            if seen is not None:
                age = now - seen
                alpha = 1.0 if age < S.CONTROLS_STAY_S else max(0.0, 1 - (age - S.CONTROLS_STAY_S) / S.CONTROLS_FADE_S)
                if alpha > 0:
                    self._controls(p.key, pose, alpha * dim, hover_key == p.key, locked)
            if p.key == "deck" and p.pointer is not None and p.w > 0:
                # The Deck screen's own pointer, where it is on that screen.
                u, v = p.pointer[0] / p.w, p.pointer[1] / p.h
                x, f = S.column(pose, u)
                y = (0.5 - v) * pose.height_m()
                t = self._tex(("ring",), lambda: (text.ring(64), 64, 64))
                if t:
                    sz = 2 * pose.distance * math.tan(math.radians(CURSOR_DEG) / 2)
                    self._quad_tex(t[0], x, y, -f + 0.004, sz, sz)
            gl.glPopMatrix()
        if self.fit and self.drag and self.drag["key"] in self.poses:
            q = self.poses[self.drag["key"]].copy()
            q.wdeg = self.fit[0]
            if self.fit[1]:
                q.hdeg = self.fit[1]
            gl.glPushMatrix()
            gl.glRotatef(q.yaw, 0.0, 1.0, 0.0)
            gl.glRotatef(q.pitch, 1.0, 0.0, 0.0)
            self._rim(q, ACCENT, 1.0, width=3.0)
            gl.glPopMatrix()
        if self.launcher is not None:
            self._draw_card(self.launcher[0], self._launcher_items(), "launcher", now)
        if self.cc is not None:
            self._draw_card(self.cc[0], self._cc_items(), "cc", now)
        self._cursor()

    def _surface(self, pose, tex, dim):
        geo = S.curve_geometry(pose)
        hh = pose.height_m() / 2
        if tex:
            gl.glEnable(GL_TEXTURE_2D)
            gl.glBindTexture(GL_TEXTURE_2D, tex)
            gl.glColor3f(dim, dim, dim)
        else:
            gl.glColor3f(0.11 * dim, 0.12 * dim, 0.14 * dim)
        if geo is None:
            x0, f = S.column(pose, 0.0)
            x1, _ = S.column(pose, 1.0)
            gl.glBegin(GL_QUADS)
            gl.glTexCoord2f(0, 1); gl.glVertex3f(x0, -hh, -f)  # noqa: E702
            gl.glTexCoord2f(1, 1); gl.glVertex3f(x1, -hh, -f)  # noqa: E702
            gl.glTexCoord2f(1, 0); gl.glVertex3f(x1, hh, -f)  # noqa: E702
            gl.glTexCoord2f(0, 0); gl.glVertex3f(x0, hh, -f)  # noqa: E702
            gl.glEnd()
        else:
            gl.glBegin(GL_QUAD_STRIP)
            for i in range(S.CURVE_COLUMNS + 1):
                u = i / S.CURVE_COLUMNS
                x, f = S.column(pose, u, geo)
                gl.glTexCoord2f(u, 1); gl.glVertex3f(x, -hh, -f)  # noqa: E702
                gl.glTexCoord2f(u, 0); gl.glVertex3f(x, hh, -f)  # noqa: E702
            gl.glEnd()
        gl.glDisable(GL_TEXTURE_2D)

    def _outline_pts(self, pose, grow_m=0.0):
        geo = S.curve_geometry(pose)
        hh = pose.height_m() / 2 + grow_m
        n = S.CURVE_COLUMNS if geo else 1
        top, bot = [], []
        for i in range(n + 1):
            u = i / n
            x, f = S.column(pose, u, geo)
            if i == 0:
                x -= grow_m
            if i == n:
                x += grow_m
            top.append((x, hh, -f + 0.002))
            bot.append((x, -hh, -f + 0.002))
        return top, bot

    def _rim(self, pose, colour, dim, width=None):
        top, bot = self._outline_pts(pose)
        gl.glLineWidth(width or max(1.0, RIM_PER_M * 1500))
        gl.glColor3f(colour[0] * dim, colour[1] * dim, colour[2] * dim)
        gl.glBegin(GL_LINE_LOOP)
        for v in top + bot[::-1]:
            gl.glVertex3f(*v)
        gl.glEnd()
        gl.glLineWidth(1.0)

    def _halo(self, pose, colour, alpha):
        grow = HALO_PER_M * pose.distance
        top, bot = self._outline_pts(pose, grow)
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(0x0302, GL_ONE_MINUS_SRC_ALPHA)  # src alpha
        gl.glColor4f(colour[0], colour[1], colour[2], alpha)
        gl.glBegin(GL_QUAD_STRIP)
        for a, b in zip(top, bot):
            gl.glVertex3f(a[0], a[1], a[2] - 0.004)
            gl.glVertex3f(b[0], b[1], b[2] - 0.004)
        gl.glEnd()
        gl.glDisable(GL_BLEND)

    def _quad_tex(self, tid, x, y, z, w, h, alpha=1.0):
        """A premultiplied texture centred at (x, y, z) in the current frame, w x h metres."""
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA)
        gl.glEnable(GL_TEXTURE_2D)
        gl.glBindTexture(GL_TEXTURE_2D, tid)
        gl.glColor4f(alpha, alpha, alpha, alpha)
        gl.glBegin(GL_QUADS)
        gl.glTexCoord2f(0, 1); gl.glVertex3f(x - w / 2, y - h / 2, z)  # noqa: E702
        gl.glTexCoord2f(1, 1); gl.glVertex3f(x + w / 2, y - h / 2, z)  # noqa: E702
        gl.glTexCoord2f(1, 0); gl.glVertex3f(x + w / 2, y + h / 2, z)  # noqa: E702
        gl.glTexCoord2f(0, 0); gl.glVertex3f(x - w / 2, y + h / 2, z)  # noqa: E702
        gl.glEnd()
        gl.glDisable(GL_TEXTURE_2D)
        gl.glDisable(GL_BLEND)

    def _controls(self, key, pose, alpha, hovered, locked):
        btns, v0, v1 = S.buttons(pose, app=key != "deck")
        H = pose.height_m()
        W = pose.width_m()
        hb_m = H * (v1 - v0)
        hname = self.hover[3] if self.hover and self.hover[0] == "window" and self.hover[1] == key else None
        for name, u0, u1 in btns:
            if locked and name in ("move", "reset"):
                continue
            uc = (u0 + u1) / 2
            x, f = S.column(pose, uc)
            y = (0.5 - (v0 + v1) / 2) * H
            wpx = int(256 * (u1 - u0) * W / hb_m) if name == "move" else None
            on = hname == name
            t = self._tex(("btn", name, on, wpx), lambda: text.icon(
                name, 64, fg=(1, 1, 1, 1) if on else (0.89, 0.886, 0.902, 1),
                bg=(0.23, 0.48, 1.0, 0.9) if on else (0.114, 0.125, 0.141, 0.85), pill_w=(wpx // 4) if wpx else None))
            if t:
                self._quad_tex(t[0], x, y, -f + 0.003, (u1 - u0) * W, hb_m, alpha)
        # the resize handle: an L just outside the bottom right corner, or a lock while locked
        if hovered:
            hb = hb_m
            x, f = S.column(pose, 1.0)
            y = -H / 2
            z = -f + 0.003
            if locked:
                t = self._tex(("btn", "lock", False, None), lambda: text.icon("lock", 64))
                if t:
                    self._quad_tex(t[0], x - 0.4 * hb, y + 0.4 * hb, z, 0.8 * hb, 0.8 * hb, alpha)
            else:
                active = self.hover and self.hover[2] == S.HANDLE or self.resize is not None
                c = ACCENT if active else INK2
                off, th = 0.25 * hb, 0.2 * hb
                gl.glColor3f(c[0] * alpha, c[1] * alpha, c[2] * alpha)
                gl.glBegin(GL_QUADS)
                # horizontal bar under the corner
                gl.glVertex3f(x - hb + off, y - off - th, z)
                gl.glVertex3f(x + off, y - off - th, z)
                gl.glVertex3f(x + off, y - off, z)
                gl.glVertex3f(x - hb + off, y - off, z)
                # vertical bar right of the corner
                gl.glVertex3f(x + off, y - off - th, z)
                gl.glVertex3f(x + off + th, y - off - th, z)
                gl.glVertex3f(x + off + th, y - off + hb, z)
                gl.glVertex3f(x + off, y - off + hb, z)
                gl.glEnd()

    def _draw_card(self, pose, items, kind, now):
        W, H = pose.width_m(), pose.height_m()
        gl.glPushMatrix()
        gl.glRotatef(pose.yaw, 0.0, 1.0, 0.0)
        gl.glRotatef(pose.pitch, 1.0, 0.0, 0.0)
        z = -pose.distance
        grow = 1.0
        if kind == "cc":
            grow = min(1.0, (now - self.cc[1]) / CC_OPEN_S)
        gl.glEnable(GL_BLEND)
        gl.glBlendFunc(0x0302, GL_ONE_MINUS_SRC_ALPHA)
        gl.glColor4f(0.086, 0.086, 0.086, 0.88)
        gl.glBegin(GL_QUADS)
        gl.glVertex3f(-W / 2 * grow, -H / 2 * grow, z)
        gl.glVertex3f(W / 2 * grow, -H / 2 * grow, z)
        gl.glVertex3f(W / 2 * grow, H / 2 * grow, z)
        gl.glVertex3f(-W / 2 * grow, H / 2 * grow, z)
        gl.glEnd()
        gl.glDisable(GL_BLEND)
        if grow < 1.0:
            gl.glPopMatrix()
            return
        title = "Apps" if kind == "launcher" else "Control Center"
        t = self._tex(("title", title), lambda: text.label(title, 40, bg=(0, 0, 0, 0), bold=True))
        if t:
            h = 0.06 * H
            self._quad_tex(t[0], -W / 2 + 0.04 * W + h * t[1] / t[2] / 2, H / 2 - 0.08 * H, z + 0.002, h * t[1] / t[2], h)
        clock = time.strftime("%H:%M  %a %d %b")
        if kind == "launcher":
            t = self._tex(("clock", clock), lambda: text.label(clock, 30, bg=(0, 0, 0, 0)))
            if t:
                h = 0.045 * H
                self._quad_tex(t[0], 0.0, H / 2 - 0.08 * H, z + 0.002, h * t[1] / t[2], h)
        hit = self.hover[1] if self.hover and self.hover[0] == kind else None
        for it in items:
            cx = (it.u0 + it.u1) / 2 * W - W / 2
            cy = H / 2 - (it.v0 + it.v1) / 2 * H
            w, h = (it.u1 - it.u0) * W, (it.v1 - it.v0) * H
            on = hit is it
            if it.kind == "app":
                a = it.arg
                isz = min(w, h * 0.62)
                tid = self._tex(("appicon", a.id), lambda a=a: self._app_icon(a))
                if on:
                    gl.glEnable(GL_BLEND)
                    gl.glBlendFunc(0x0302, GL_ONE_MINUS_SRC_ALPHA)
                    gl.glColor4f(ACCENT[0], ACCENT[1], ACCENT[2], 0.25)
                    gl.glBegin(GL_QUADS)
                    gl.glVertex3f(cx - w / 2, cy - h / 2, z + 0.001)
                    gl.glVertex3f(cx + w / 2, cy - h / 2, z + 0.001)
                    gl.glVertex3f(cx + w / 2, cy + h / 2, z + 0.001)
                    gl.glVertex3f(cx - w / 2, cy + h / 2, z + 0.001)
                    gl.glEnd()
                    gl.glDisable(GL_BLEND)
                if tid:
                    self._quad_tex(tid[0], cx, cy + h * 0.14, z + 0.002, isz, isz)
                name = a.name if len(a.name) <= 18 else a.name[:17] + "..."
                lt = self._tex(("applabel", name), lambda name=name: text.label(name, 26, bg=(0, 0, 0, 0)))
                if lt:
                    lh = h * 0.16
                    lw = min(w, lh * lt[1] / lt[2])
                    self._quad_tex(lt[0], cx, cy - h * 0.34, z + 0.002, lw, lw * lt[2] / lt[1])
                continue
            if it.label == "close":
                tid = self._tex(("btn", "close", on, None), lambda on=on: text.icon(
                    "close", 64, bg=(0.23, 0.48, 1.0, 0.9) if on else (0.16, 0.17, 0.19, 0.9)))
                if tid:
                    s = min(w, h)
                    self._quad_tex(tid[0], cx, cy, z + 0.002, s, s)
                continue
            bg = (0.23, 0.48, 1.0, 0.95) if (it.on or on) else (0.16, 0.17, 0.19, 0.95)
            if it.kind == "text":
                bg = (0, 0, 0, 0)
            lab = it.label + ("  On" if it.kind == "toggle" and it.on else "  Off" if it.kind == "toggle" else "")
            tid = self._tex(("item", lab, bg), lambda lab=lab, bg=bg: text.label(lab, 30, bg=bg, min_w=int(30 * 7)))
            if tid:
                th = h
                tw = min(w, th * tid[1] / tid[2])
                self._quad_tex(tid[0], cx, cy, z + 0.002, tw, tw * tid[2] / tid[1])
        gl.glPopMatrix()

    def _app_icon(self, a):
        size = 128
        data = text.png(a.icon, size) if a.icon else None
        if data is None:
            data = text.letter_tile(a.name, size)
        return data, size, size

    def _cursor(self):
        h = self.hover
        depth = (h[6] - 0.005) if h else CURSOR_IDLE_M
        p = tuple(k * depth for k in self.ray)
        size = 2 * depth * math.tan(math.radians(CURSOR_DEG) / 2)
        t = self._tex(("ring",), lambda: (text.ring(64), 64, 64))
        if not t:
            return
        yaw, pitch = S.angles(self.ray)
        gl.glPushMatrix()
        gl.glRotatef(yaw, 0.0, 1.0, 0.0)
        gl.glRotatef(pitch, 1.0, 0.0, 0.0)
        self._quad_tex(t[0], 0.0, 0.0, -depth, size, size)
        gl.glPopMatrix()
        del p
