"""The Space's geometry, snapping and layouts, without glasses or a screen."""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from pocketxr import space as S  # noqa: E402


def ray_to(p, u, v):
    """A ray from the head through the window point (u, v)."""
    x, f = S.column(p, u)
    y = (0.5 - v) * S.deg_to_m(p.hdeg, p.distance)
    # local (x, y, -f) back to the head frame: pitch then yaw
    pr, yr = math.radians(p.pitch), math.radians(p.yaw)
    z = -f
    y2 = y * math.cos(pr) - z * math.sin(pr)
    z2 = y * math.sin(pr) + z * math.cos(pr)
    x3 = x * math.cos(yr) + z2 * math.sin(yr)
    z3 = -x * math.sin(yr) + z2 * math.cos(yr)
    return (x3, y2, z3)


def test_flat_and_curved_hits_round_trip():
    for curve in (0.0, 0.6, 1.0, 2.0):
        p = S.Pose(20, 10, 1.4, 40, 22.5, curve)
        for u, v in ((0.5, 0.5), (0.1, 0.2), (0.9, 0.8)):
            r = ray_to(p, u, v)
            uu, vv, _ = S.surface_uv(p, r)
            assert abs(uu - u) < 1e-3 and abs(vv - v) < 1e-3, (curve, u, v, uu, vv)


def test_centre_ray_hits_the_middle():
    p = S.Pose(-30, 0, 2.0)
    u, v, d = S.surface_uv(p, S.direction(-30, 0))
    assert abs(u - 0.5) < 1e-6 and abs(v - 0.5) < 1e-6 and abs(d - 2.0) < 1e-6


def test_curve_keeps_angular_width():
    p = S.Pose(0, 0, 1.4, 40, 22.5, 1.0)
    for u, want in ((0.0, 20.0), (1.0, -20.0)):
        x, f = S.column(p, u)
        assert abs(math.degrees(math.atan2(-x, f)) - want) < 0.05


def test_zones():
    p = S.Pose(0, 0, 1.4)
    assert S.zone(p, 0.5, 0.5) == (S.BODY, None)
    btns, v0, v1 = S.buttons(p)
    names = [b[0] for b in btns]
    assert names == ["back", "move", "close", "reset"]
    mid_v = (v0 + v1) / 2
    assert S.zone(p, 0.5, mid_v) == (S.BUTTON, "move")
    assert S.zone(p, 0.999, 0.999)[0] == S.HANDLE
    assert S.zone(p, -0.02, 0.5)[0] == S.FRAME
    assert S.zone(p, -0.02, 0.5, locked=True) == (None, None)
    assert S.zone(p, 0.5, mid_v, locked=True) == (None, None)
    assert S.zone(p, 1.2, 0.5) == (None, None)


def test_place_new_steps_right_when_front_is_taken():
    a = S.Pose(0, 0)
    b = S.place_new([a], 40, 22.5, 0)
    assert b.yaw < 0 and not S.overlaps(a, b)


def test_snap_docks_beside_with_gap():
    q = S.Pose(0, 0, 1.4, 40, 22.5)
    p = S.Pose(q.right - 20 - 2.0, 1.0, 1.4, 40, 22.5)  # near the right side, a bit off
    yaw, pitch, part, fit = S.snap(p, [q])
    assert abs((q.right - yaw - 20) - S.SNAP_GAP_DEG) < 1e-6 and abs(pitch) < 1e-6 and part == 0


def test_snap_between_two_fits_the_gap():
    a = S.Pose(40, 0, 1.4, 30, 20)
    b = S.Pose(-40, 0, 1.4, 30, 20)
    p = S.Pose(2, 0, 1.4, 30, 20)
    yaw, pitch, part, fit = S.snap(p, [a, b])
    assert abs(yaw) < 1e-6 and fit is not None and abs(fit[0] - (a.right - b.left - 2 * S.SNAP_GAP_DEG)) < 1e-6


def test_arrange_layouts_give_every_window_a_place():
    for n in range(1, 7):
        poses = [S.Pose(i * 10, 0, 1.4, 40, 22.5) for i in range(n)]
        for name in S.layout_choices(n):
            out = S.arrange(name, poses, 0, 0.0)
            assert len(out) == n and all(o is not None for o in out), (n, name)
            if name in ("Side by side", "Three across", "Four across", "2x2 grid", "Grid", "All around you"):
                for i in range(n):
                    for j in range(i + 1, n):
                        assert not S.overlaps(out[i], out[j], gap=0.1), (n, name, i, j)


def test_adjust_all_scales_gaps_too():
    poses = [S.Pose(25, 0, 1.4, 40, 22.5), S.Pose(-25, 0, 1.4, 40, 22.5)]
    out = S.adjust_all(poses, size_factor=1.2)
    assert abs((out[0].yaw - out[1].yaw) - 60) < 1e-6 and abs(out[0].wdeg - 48) < 1e-6
    assert S.adjust_all(poses, size_factor=10) is poses  # past a limit: nothing moves


def test_pixels():
    assert S.Pose(wdeg=40, hdeg=22.5).pixels() == (1760, 990)
    w, h = S.Pose(wdeg=100, hdeg=70).pixels()
    assert w <= 2560 and h <= 1440


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
