"""Pose heuristics and one-shot temporal confirmation. No Windows imports."""

from dataclasses import dataclass
from math import dist, hypot, isfinite

from .hand_tracking import TrackedHand


def classify_pose(hand: TrackedHand, width: int, height: int,
                  straight_cosine: float = 0.8, extension_ratio: float = 1.1,
                  thumb_spread_ratio: float = 0.8) -> str:
    if len(hand.landmarks) != 21 or not all(isfinite(v) for point in hand.landmarks for v in point):
        return "UNKNOWN"
    points = [(x * width, y * height) for x, y, _ in hand.landmarks]
    palm_size = dist(points[0], points[9])
    if palm_size < 1:
        return "UNKNOWN"
    extended = []
    relaxed = []
    reaches = []
    for mcp, pip, tip in ((5, 6, 8), (9, 10, 12), (13, 14, 16), (17, 18, 20)):
        a = (points[pip][0]-points[mcp][0], points[pip][1]-points[mcp][1])
        b = (points[tip][0]-points[pip][0], points[tip][1]-points[pip][1])
        denominator = hypot(*a) * hypot(*b)
        cosine = (a[0]*b[0]+a[1]*b[1])/denominator if denominator else -1
        extended.append(cosine >= straight_cosine and
                        dist(points[0], points[tip]) > extension_ratio * dist(points[0], points[pip]))
        # Navigation does not require straight distal joints. A naturally bent
        # finger still reaches beyond its knuckle in the MCP -> PIP direction.
        # Use palm-local geometry so rotation and finger spacing do not decide
        # whether a palm is navigable. Folded fingers point back toward the palm.
        proximal = hypot(*a)
        reach = ((points[tip][0]-points[mcp][0])*a[0] +
                 (points[tip][1]-points[mcp][1])*a[1]) / proximal if proximal else 0
        relaxed.append(proximal > .08*palm_size and reach >= .85*proximal
                       and dist(points[0], points[tip]) > dist(points[0], points[mcp]))
        reaches.append(reach/proximal if proximal else 0.)
    if all(extended) and dist(points[4], points[17]) > thumb_spread_ratio * palm_size:
        return "OPEN_PALM"
    # Curled ring/little fingertips can still project just beyond their PIP.
    # Distinguish a deliberate pair by relative extension before the broad
    # relaxed-palm fallback swallows it.
    if (all(extended[:2]) and not any(extended[2:])
            and max(reaches[2:]) < min(1.05, .7*min(reaches[:2]))):
        return 'TWO_FINGERS'
    if all(relaxed):
        return "RELAXED_PALM"
    if relaxed == [True, True, False, False]:
        return "TWO_FINGERS"
    if extended == [True, False, False, False]:
        return "POINT"
    if extended == [True, True, False, False]:
        return "TWO_FINGERS"
    if extended == [True, True, True, False]:
        return "THREE_FINGERS"
    if extended in ([True, False, True, True], [True, True, False, True]):
        return "RELAXED_PALM"
    return "UNKNOWN"


@dataclass(frozen=True)
class HoldResult:
    fired: bool = False
    progress: float = 0.0


def closed_fist(hand, width, height, fold_ratio=.8):
    """All distal joints curl back toward the palm; relaxed fingers are excluded."""
    if len(hand.landmarks) != 21 or not all(isfinite(v) for p in hand.landmarks for v in p):
        return False
    points = [(x*width, y*height) for x,y,_ in hand.landmarks]
    if dist(points[0], points[9]) < 1:
        return False
    for mcp in (5, 9, 13, 17):
        a = tuple(points[mcp+1][i]-points[mcp][i] for i in (0, 1))
        length2 = sum(v*v for v in a)
        if length2 < 1:
            return False
        for joint in (mcp+2, mcp+3):
            projected = sum((points[joint][i]-points[mcp][i])*a[i] for i in (0,1))/length2
            if projected >= fold_ratio:
                return False
    return True


def open_hand_for_activation(hand, width, height, pinch_off_ratio):
    """Open hand independent of the stricter navigation/gesture pose label."""
    if len(hand.landmarks) != 21 or not all(isfinite(v) for p in hand.landmarks for v in p):
        return False
    points = [(x*width, y*height) for x,y,_ in hand.landmarks]
    size = dist(points[0], points[9])
    if size < 1 or dist(points[4], points[8]) < pinch_off_ratio*size:
        return False
    for mcp in (5, 9, 13, 17):
        a = tuple(points[mcp+1][i]-points[mcp][i] for i in (0,1))
        length2 = sum(v*v for v in a)
        if length2 < 1:
            return False
        reach = sum((points[mcp+3][i]-points[mcp][i])*a[i] for i in (0,1))/length2
        if reach < .65 or dist(points[0], points[mcp+3]) <= dist(points[0], points[mcp]):
            return False
    return True


class HoldGate:
    def __init__(self, hold_ms: int, rearm_ms: int, max_speed: float):
        self.hold_seconds, self.rearm_seconds, self.max_speed = hold_ms/1000, rearm_ms/1000, max_speed
        self.reset()

    def reset(self):
        self.armed = True
        self._start = self._exit = self._time = self._position = None

    def cancel(self):
        # Missing data cannot count as a confirmed exit/rearm.
        self._start = self._exit = self._time = self._position = None

    def update(self, matched: bool, timestamp: float, position: tuple[float, float]) -> HoldResult:
        if self._time is not None and timestamp <= self._time:
            return HoldResult()
        speed = 0.0
        if self._time is not None and self._position is not None:
            speed = dist(position, self._position) / (timestamp-self._time)
        self._time, self._position = timestamp, position
        if not matched:
            self._start = None
            if self._exit is None:
                self._exit = timestamp
            if timestamp-self._exit >= self.rearm_seconds:
                self.armed = True
            return HoldResult()
        self._exit = None
        if not self.armed:
            return HoldResult()
        if speed > self.max_speed:
            self._start = None
            return HoldResult()
        if self._start is None:
            self._start = timestamp
        progress = min(1.0, (timestamp-self._start)/self.hold_seconds)
        if progress >= 1:
            self.armed = False
            self._start = None
            return HoldResult(True, 1.0)
        return HoldResult(False, progress)


class StablePalmHold:
    """Confirm a palm inside a small region; tolerate short classification gaps.

    Only matched frame intervals count toward the hold. Missing frames cannot
    complete it. A bounded region avoids amplifying landmark noise into speed.
    """
    def __init__(self, hold_ms, radius=.045, gap_ms=180):
        self.duration, self.radius, self.gap = hold_ms/1000, radius, gap_ms/1000
        self.reset()

    def reset(self):
        self.anchor = self.last_match = self.last_time = None
        self.elapsed = 0.
        self.armed = True

    def cancel(self):
        self.reset()

    def update(self, matched, timestamp, position):
        if self.last_time is not None and timestamp <= self.last_time:
            return HoldResult()
        if self.last_match is not None and timestamp-self.last_match > self.gap:
            self.reset()
        previous = self.last_time
        self.last_time = timestamp
        if not matched:
            return HoldResult(False, min(1., self.elapsed/self.duration))
        if self.anchor is None or dist(position, self.anchor) > self.radius:
            self.anchor, self.elapsed = position, 0.
            previous = None
        if previous is not None and self.last_match == previous:
            self.elapsed += min(timestamp-previous, self.gap)
        self.last_match = timestamp
        progress = min(1., self.elapsed/self.duration)
        if self.armed and progress >= 1:
            self.armed = False
            return HoldResult(True, 1.)
        return HoldResult(False, progress)
