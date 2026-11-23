"""Taps on the glasses, read from their own motion sensor: two taps recentre, three switch the view (Gaming Mode).

Asked for by a tester (Pierre Zammit, 23 Nov 2026) so the jobs work with any controller, or with the Deck put down.

What a tap looks like, from his XBX A01+ (imu-raw.log, about 1000 reports a second):
- 0.7.5 wanted a jolt of 0.8 g, back under 0.3 g within 40 ms. His taps on the top of the frame, recorded with 0.7.6,
  were much softer: 0.33 to 0.51 g away from the 30 ms average, with a quick swing after them lasting 30 to 60 ms.
  He found double taps worked only twice in many tries.
- What sets a tap apart is how suddenly it starts: the acceleration jumped 0.23 to 0.42 g within 3 ms. In his four
  recordings of plain head movement (turning up to 93 degrees a second) no 3 ms jump went over 0.10 g.

So a jolt starts when the acceleration is LOG_G away from its 30 ms average, and ends once it has stayed under LOG_G
for SETTLE_S (the swing after a tap is part of the same jolt). It counts as a tap when:
- it peaked at TAP_G or more,
- it jumped JERK_G or more within 3 ms somewhere in it (sharp, not a push or a nod; his first tap of three dipped
  gently for 10 ms before its sharp part),
- it lasted no longer than SPIKE_MAX_S,
- QUIET_BEFORE_S passed since the last jolt ended,
- the head turned slower than TURN_MAX on average over the 150 ms before it.

With 0.7.7 his firm taps (0.8 to 5 g) lasted 61 to 101 ms, and three of them were left out as longer than 0.7.7's
80 ms; so SPIKE_MAX_S is 150 ms. His recordings of head movement and of putting the glasses on give no gesture even
at 200 ms. Each tap is followed 95 to 150 ms later by a small slow rebound (0.15 to 0.26 g, not sharp), which is not a
tap; a run of four of his (four firm taps about 440 ms apart) was four real taps, so it does nothing, as meant.

Taps TAP_GAP_MIN_S to TAP_GAP_MAX_S apart make a run: from about 1.5 to 5 taps a second, so 2 a second works. His
taps were about 320 ms apart. Putting the glasses on gave two sharp jolts 134 ms apart (his 16:05 recording): too
close together for a run. Once
RUN_END_S passes without another, a run of two or three is reported. One tap, or four and more, does nothing.

Every jolt goes to the log (on_log) with its peak, how long it lasted, the quiet before it, the head's turn, the gap
to the last tap and whether it counted (and why not), at most LOG_MAX lines a minute, so a missed tap shows up.
Not yet tried with these values on glasses; the Quick Access switch is off at first.
"""
import math

G = 9.81
LOG_G = 0.15          # a jolt starts here (and is logged)
TAP_G = 0.25          # a tap's peak, away from the 30 ms average
JERK_G = 0.15         # a tap's jump within JERK_S
JERK_S = 0.003
SETTLE_S = 0.008      # a jolt ends after this long under LOG_G
SPIKE_MAX_S = 0.15
QUIET_BEFORE_S = 0.06
TURN_MAX = math.radians(60)  # rad/s
TAP_GAP_MIN_S = 0.2
TAP_GAP_MAX_S = 0.7
RUN_END_S = 0.75
WARMUP_S = 0.5
AVG_S = 0.03
TURN_AVG_S = 0.15
LOG_MAX = 120         # jolt lines a minute


class Taps:
    """feed(seconds, gyro rad/s, accel m/s2) with each motion report; calls on_taps(2) or on_taps(3), and
    on_log(line) for each jolt."""

    def __init__(self, on_taps, on_log=None):
        self.on_taps = on_taps
        self.on_log = on_log
        self.logged = []  # times of the jolt lines, for LOG_MAX
        self.reset()

    def reset(self):
        self.t0 = None
        self.last_t = None
        self.avg = None
        self.turn = 0.0
        self.recent = []      # (t, accel) of the last few reports, for the 3 ms jump
        self.quiet_from = -1e9  # when the last jolt ended
        self.jolt = None      # while one lasts: dict(start, peak, jerk, turn, quiet, under)
        self.taps = []        # start times of this run's taps

    def feed(self, t, gyro, accel):
        if self.last_t is None or not (0.0 < t - self.last_t < 0.1):
            self.reset()  # the first report, or a gap in the reports: start again
            self.t0 = t
            self.last_t = t
            self.avg = list(accel)
            self.recent = [(t, accel)]
            return
        dt = t - self.last_t
        self.last_t = t
        d = math.sqrt(sum((x - m) ** 2 for x, m in zip(accel, self.avg))) / G
        self.avg = [m + (x - m) * (1.0 - math.exp(-dt / AVG_S)) for m, x in zip(self.avg, accel)]
        old = None
        for tt, a in reversed(self.recent):
            if t - tt >= JERK_S:
                old = a
                break
        jump = math.sqrt(sum((x - y) ** 2 for x, y in zip(accel, old))) / G if old else 0.0
        self.recent.append((t, accel))
        while len(self.recent) > 2 and t - self.recent[1][0] >= JERK_S:
            self.recent.pop(0)
        w = math.sqrt(sum(x * x for x in gyro))
        turn_before = self.turn
        self.turn += (w - self.turn) * (1.0 - math.exp(-dt / TURN_AVG_S))
        if t - self.t0 < WARMUP_S:
            self.quiet_from = t
            return
        j = self.jolt
        if j is None:
            if d >= LOG_G:
                self.jolt = {"start": t, "peak": d, "jerk": jump, "turn": turn_before,
                             "quiet": t - self.quiet_from, "under": None}
        else:
            j["peak"] = max(j["peak"], d)
            j["jerk"] = max(j["jerk"], jump)
            if d >= LOG_G:
                j["under"] = None
            elif j["under"] is None:
                j["under"] = t
            if (j["under"] is not None and t - j["under"] >= SETTLE_S) or t - j["start"] > 0.3:
                self.jolt = None
                self.quiet_from = t
                self._judge(j, (j["under"] or t) - j["start"])
        if self.taps and self.jolt is None and t - self.taps[-1] > RUN_END_S:
            n = len(self.taps)
            self.taps = []
            if n in (2, 3):
                self.on_taps(n)
            elif self.on_log:
                self._log(t, f"taps: a run of {n} ended: only two or three do something")

    def _judge(self, j, lasted):
        gap = j["start"] - self.taps[-1] if self.taps else None
        why = None
        if j["peak"] < TAP_G:
            why = f"too soft (under {TAP_G:g} g)"
        elif j["jerk"] < JERK_G:
            why = f"not sharp (a tap jumps {JERK_G:g} g within {JERK_S * 1000:g} ms)"
        elif lasted > SPIKE_MAX_S:
            why = f"too long (a tap is under {SPIKE_MAX_S * 1000:g} ms)"
        elif j["quiet"] < QUIET_BEFORE_S:
            why = f"too soon after other movement (needs {QUIET_BEFORE_S * 1000:g} ms still)"
        elif j["turn"] >= TURN_MAX:
            why = f"the head was turning (over {math.degrees(TURN_MAX):g} deg/s)"
        elif gap is not None and gap < TAP_GAP_MIN_S:
            why = f"too soon after the last tap (under {TAP_GAP_MIN_S * 1000:g} ms)"
        if why is None:
            if gap is not None and gap > TAP_GAP_MAX_S:
                self.taps = []
            self.taps.append(j["start"])
            verdict = f"a tap, {len(self.taps)} in this run"
        else:
            verdict = "not a tap: " + why
        if self.on_log:
            gap_text = f"{gap * 1000:.0f} ms" if gap is not None else "none"
            self._log(j["start"], f"taps: jolt {j['peak']:.2f} g (jump {j['jerk']:.2f} g in 3 ms), {lasted * 1000:.0f} ms, "
                                  f"still {min(j['quiet'], 9.99) * 1000:.0f} ms before, head turning "
                                  f"{math.degrees(j['turn']):.0f} deg/s, last tap {gap_text} before: {verdict}")

    def _log(self, t, line):
        self.logged = [x for x in self.logged if t - x < 60.0]
        if len(self.logged) >= LOG_MAX:
            return
        self.logged.append(t)
        self.on_log(line)
