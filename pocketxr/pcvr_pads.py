"""PC VR's controllers: the Deck's own controls as a pair of Quest Touch controllers, as ALVR presents them to SteamVR.

The Deck's left half is the left hand and its right half the right hand:

    left hand                       right hand
    L2 trigger    trigger           R2 trigger    trigger
    L1            grip              R1            grip
    left stick    thumbstick        right stick   thumbstick
    X             X                 A             A
    Y             Y                 B             B
    Menu (three lines)  menu

L5 and R5 stay Pocket XR's (hold two seconds to leave PC VR); L4, R4 and the Steam button are not sent.

The Deck has no tracking for hands, so both controllers are held in front of you, low, as you hold the Deck, and turn
with your body (the head's turn, followed slowly) rather than with every look around. The trackpads aim them: drag on
the right pad to point the right hand (at a menu, say), the left pad for the left; the aim stays where you leave it,
and pressing the pad in brings that hand back to straight ahead. Games played with a gamepad's sticks and buttons
work; games that need you to reach with each hand need tracked controllers.

The state comes from the same hidraw report as the back buttons (deckpad.py): sticks and triggers after the buttons.
Byte offsets from the report's layout (as SDL reads it): pads 16, motion 24, triggers 44 and 46 (0 to 32767), left
stick 48 and 50, right stick 52 and 54 (-32768 to 32767, up positive).
"""
import math
import struct

BIT = {
    "R2": 0, "L2": 1, "R1": 2, "L1": 3, "Y": 4, "B": 5, "X": 6, "A": 7,
    "MENU": 14, "LCLICK": 17, "RCLICK": 18, "LPAD": 19, "RPAD": 20, "L3": 22, "R3": 26, "LTOUCH": 45, "RTOUCH": 46,
}
STICK_DEAD = 0.12  # the Deck's sticks rest up to about 4 % off centre
TRIGGER_TOUCH = 0.05

# Where the hands are held, metres from the eyes in the body's frame (x right, y up, z back), and their tilt
HAND_AT = ((-0.17, -0.32, -0.35), (0.17, -0.32, -0.35))
HAND_PITCH = math.radians(0.0)
PAD_DEG = 70.0  # a drag across the whole pad turns the aim this much
AIM_YAW = math.radians(80.0)
AIM_PITCH = (math.radians(-60.0), math.radians(60.0))
BODY_FOLLOW = 0.05  # share of the head's turn the body takes each frame


def _stick(x, y):
    x, y = x / 32767.0, y / 32767.0
    r = math.hypot(x, y)
    if r < STICK_DEAD:
        return 0.0, 0.0
    k = min(1.0, (r - STICK_DEAD) / (1.0 - STICK_DEAD)) / r
    return x * k, y * k


def deck_buttons(report):
    """The Deck's controls as two hands: [(buttons, trigger, squeeze, stick_x, stick_y), ...] left then right, in the
    bridge's button bits (1 primary, 2 secondary, 4 menu, 8 stick click; touches 0x10, 0x20, 0x40 trigger, 0x80
    stick)."""
    bits = struct.unpack_from("<Q", report, 8)[0]
    tl, tr = struct.unpack_from("<2H", report, 44)
    lx, ly, rx, ry = struct.unpack_from("<4h", report, 48)

    def on(name):
        return bool(bits & (1 << BIT[name]))

    out = []
    for side in (0, 1):
        prim, sec, click, touch = (("X", "Y", "L3", "LTOUCH"), ("A", "B", "R3", "RTOUCH"))[side]
        trig = min(1.0, (tl if side == 0 else tr) / 32767.0)
        sx, sy = _stick(lx, ly) if side == 0 else _stick(rx, ry)
        b = 0
        if on(prim):
            b |= 1 | 0x10
        if on(sec):
            b |= 2 | 0x20
        if side == 0 and on("MENU"):
            b |= 4
        if on(click):
            b |= 8 | 0x80
        if on(touch) or sx or sy:
            b |= 0x80
        if trig > TRIGGER_TOUCH or on("L2" if side == 0 else "R2"):
            b |= 0x40
        squeeze = 1.0 if on("L1" if side == 0 else "R1") else 0.0
        out.append((b, trig, squeeze, sx, sy))
    return out


def _yaw_of(q):
    w, x, y, z = q
    fx = -(2 * (x * z + y * w))
    fz = -(1 - 2 * (x * x + y * y))
    return math.atan2(-fx, -fz)


class DeckHands:
    """Both hands held in front, low, turning with the body."""

    def __init__(self):
        self.body_yaw = None
        self.aim = [[0.0, 0.0], [0.0, 0.0]]  # each hand's (yaw, pitch) from straight ahead, radians
        self.last_pad = [None, None]

    def recentre(self):
        self.body_yaw = None
        self.aim = [[0.0, 0.0], [0.0, 0.0]]

    def steer(self, report):
        """Trackpad drags aim the hands; pressing a pad in points that hand straight ahead again."""
        bits = struct.unpack_from("<Q", report, 8)[0]
        pads = struct.unpack_from("<4h", report, 16)
        k = math.radians(PAD_DEG) / 65535.0
        for side in (0, 1):
            if bits & (1 << BIT["LCLICK" if side == 0 else "RCLICK"]):
                self.aim[side] = [0.0, 0.0]
            if not bits & (1 << BIT["LPAD" if side == 0 else "RPAD"]):
                self.last_pad[side] = None
                continue
            x, y = pads[2 * side], pads[2 * side + 1]
            if self.last_pad[side] is not None:
                lx, ly = self.last_pad[side]
                a = self.aim[side]
                a[0] = max(-AIM_YAW, min(AIM_YAW, a[0] - (x - lx) * k))
                a[1] = max(AIM_PITCH[0], min(AIM_PITCH[1], a[1] + (y - ly) * k))
            self.last_pad[side] = (x, y)

    def poses(self, head_q, eye_height):
        """28 floats for pxr_send_tracking: per hand valid, orientation x y z w, position, angular and linear
        velocity (zero)."""
        yaw = _yaw_of(head_q)
        if self.body_yaw is None:
            self.body_yaw = yaw
        d = (yaw - self.body_yaw + math.pi) % (2 * math.pi) - math.pi
        self.body_yaw += d * BODY_FOLLOW
        c, s = math.cos(self.body_yaw), math.sin(self.body_yaw)
        out = []
        for side, (hx, hy, hz) in enumerate(HAND_AT):
            ay = self.body_yaw + self.aim[side][0]
            ap = HAND_PITCH + self.aim[side][1]
            # yaw (about y) then pitch (about x), as one quaternion
            qy = (math.cos(ay / 2), 0.0, math.sin(ay / 2), 0.0)
            qp = (math.cos(ap / 2), math.sin(ap / 2), 0.0, 0.0)
            q = (qy[0] * qp[0], qy[0] * qp[1], qy[2] * qp[0], -qy[2] * qp[1])
            px = c * hx + s * hz
            pz = -s * hx + c * hz
            out += [1.0, q[1], q[2], q[3], q[0], px, eye_height + hy, pz, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
        return out
