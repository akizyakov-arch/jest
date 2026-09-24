"""Timestamp-based thumb/index pinch with hysteresis and mandatory open rearm."""

from math import dist, isfinite


def pinch_ratio(hand, width, height, tip=8):
    if len(hand.landmarks) != 21 or not all(isfinite(v) for p in hand.landmarks for v in p):
        return None
    points = [(x*width, y*height) for x, y, _ in hand.landmarks]
    scale = dist(points[0], points[9])
    return dist(points[4], points[tip])/scale if scale > 1 else None


class PinchGate:
    def __init__(self, on_ratio, off_ratio, confirm_ms, release_ms):
        self.on, self.off = on_ratio, off_ratio
        self.confirm, self.release = confirm_ms/1000, release_ms/1000
        self.reset()

    def reset(self):
        self.held = self.armed = False
        self.pending = False
        self._since = None
        self._last = float('-inf')

    def update(self, ratio, timestamp):
        if timestamp <= self._last:
            return None
        self._last = timestamp
        if ratio is None:
            was_held = self.held
            self.reset()
            return 'up' if was_held else None
        if self.held or not self.armed:
            if ratio >= self.off:
                if self._since is None:
                    self._since = timestamp
                if timestamp-self._since >= self.release:
                    was_held = self.held
                    self.held, self.armed = False, True
                    self._since = None
                    return 'up' if was_held else None
            else:
                self._since = None
            return None
        self.pending = ratio <= self.on
        if self.pending:
            if self._since is None:
                self._since = timestamp
            if timestamp-self._since >= self.confirm:
                self.held, self.armed, self.pending = True, False, False
                self._since = None
                return 'down'
        else:
            self._since = None
        return None
