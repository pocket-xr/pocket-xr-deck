"""Taps on the glasses, read from their own motion sensor: two taps recentre, three switch the view (Gaming Mode).

Asked for by a tester (Pierre Zammit, 23 Nov 2026) so the jobs work with any controller, or with the Deck put down.

A tap on the frame is a short, sharp jolt: the acceleration jumps away from its recent average and back within a few
hundredths of a second. Head turns and walking move the glasses too, but more slowly. In his recorded first seconds
(imu-raw.log, XBX A01+, head turning up to 93 degrees a second) the acceleration stayed within 0.23 g of its 30 ms
average, apart from the first report (a junk value, so the first half second is skipped). So a tap here is:

- the acceleration at least TAP_G away from its 30 ms average,
- back under QUIET_G within SPIKE_MAX_S,
- after QUIET_BEFORE_S under QUIET_G (so a jolt in the middle of shaking or a step is left out),
- while the head turned slower than TURN_MAX on average over the last 150 ms.

Taps TAP_GAP_MIN_S to TAP_GAP_MAX_S apart make a run; once RUN_END_S passes without another, a run of two or three
is reported. One tap, or four and more, does nothing.

The values are chosen from that recording and from what a tap does to a phone's sensor; they are not yet tried with a
real tap on glasses, so the Quick Access switch is off at first.
"""
import math

G = 9.81
TAP_G = 0.8
QUIET_G = 0.3
SPIKE_MAX_S = 0.04
QUIET_BEFORE_S = 0.06
TURN_MAX = math.radians(60)  # rad/s
TAP_GAP_MIN_S = 0.08
TAP_GAP_MAX_S = 0.45
RUN_END_S = 0.5
WARMUP_S = 0.5
AVG_S = 0.03
TURN_AVG_S = 0.15


class Taps:
    """feed(seconds, gyro rad/s, accel m/s2) with each motion report; calls on_taps(2) or on_taps(3)."""

    def __init__(self, on_taps):
        self.on_taps = on_taps
        self.reset()

    def reset(self):
        self.t0 = None
        self.last_t = None
        self.avg = None
        self.turn = 0.0
        self.loud_at = -1e9   # when the acceleration was last over QUIET_G (outside a spike)
        self.spike = None     # (start, peak) while over QUIET_G after a jolt over TAP_G
        self.taps = []        # start times of this run's taps

    def feed(self, t, gyro, accel):
        if self.last_t is None or not (0.0 < t - self.last_t < 0.1):
            self.reset()  # the first report, or a gap in the reports: start again
            self.t0 = t
            self.last_t = t
            self.avg = list(accel)
            return
        dt = t - self.last_t
        self.last_t = t
        d = math.sqrt(sum((x - m) ** 2 for x, m in zip(accel, self.avg))) / G
        k = 1.0 - math.exp(-dt / AVG_S)
        self.avg = [m + (x - m) * k for m, x in zip(self.avg, accel)]
        w = math.sqrt(sum(x * x for x in gyro))
        self.turn += (w - self.turn) * (1.0 - math.exp(-dt / TURN_AVG_S))
        if t - self.t0 < WARMUP_S:
            self.loud_at = t
            return
        if self.spike is not None:
            start, turn_before = self.spike
            if d < QUIET_G:
                self.spike = None
                if t - start <= SPIKE_MAX_S and turn_before < TURN_MAX:
                    self._tap(start)
                self.loud_at = t
            elif t - start > SPIKE_MAX_S:
                self.loud_at = t  # too long for a tap: a push or a knock, wait for it to settle
        elif d >= TAP_G and t - self.loud_at >= QUIET_BEFORE_S:
            self.spike = (t, self.turn)
        elif d >= QUIET_G:
            self.loud_at = t
        if self.taps and self.spike is None and t - self.taps[-1] > RUN_END_S:
            n = len(self.taps)
            self.taps = []
            if n in (2, 3):
                self.on_taps(n)

    def _tap(self, start):
        if self.taps:
            gap = start - self.taps[-1]
            if gap < TAP_GAP_MIN_S:
                return  # the same tap ringing on
            if gap > TAP_GAP_MAX_S:
                self.taps = []
        self.taps.append(start)
