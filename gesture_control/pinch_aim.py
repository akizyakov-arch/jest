"""Freeze navigation during the approach to a pinch, before button confirmation."""

from collections import deque


class PinchAim:
    def __init__(self, ratio=.75, timeout_ms=900, release_ms=120, stall_ms=150):
        self.ratio, self.timeout, self.release = ratio, timeout_ms/1000, release_ms/1000
        self.stall = stall_ms/1000
        self.reset()

    def reset(self):
        self.locked = self.blocked = False
        self.minimum = self.started = None
        self.progress_ratio = self.progress_at = None
        self.release_until = None
        self.samples = deque(maxlen=64)

    def released(self, timestamp, dragged=False):
        self.locked = False
        self.blocked = True
        self.samples.clear()
        self.release_until = timestamp+(0 if dragged else self.release)

    def inhibit(self):
        """A neighboring finger's capture is not a new pre-aim gesture."""
        self.reset()
        self.blocked = True

    def update(self, ratio, timestamp, armed, held, approaching=False):
        if ratio is None:
            self.reset()
            return False
        while self.samples and timestamp-self.samples[0][0] > .2:
            self.samples.popleft()
        newest, drop, steps = ratio, 0., 0
        for _, value in reversed(self.samples):
            if value < newest-.015:
                break
            if value > newest+.005:
                steps += 1
            drop = max(drop, value-ratio)
            newest = value
        closing = drop >= .12 or (drop >= .06 and steps >= 2)
        self.samples.append((timestamp, ratio))
        if held:
            return True
        if self.release_until is not None:
            if timestamp < self.release_until:
                return True
            self.release_until = None
        if self.locked:
            if (ratio <= self.progress_ratio-.012 or
                    (approaching and ratio <= self.progress_ratio-.004)):
                self.progress_ratio, self.progress_at = ratio, timestamp
            self.minimum = min(self.minimum, ratio)
            if ratio >= self.minimum+.12:
                self.locked, self.blocked = False, True
            elif timestamp-self.started >= self.timeout:
                self.locked, self.blocked = False, True
            elif timestamp-self.progress_at >= self.stall:
                self.locked, self.blocked = False, True
            else:
                return True
        if self.blocked:
            if ratio > self.ratio+.12:
                self.blocked = False
            return False
        if armed and (closing or approaching):
            self.locked, self.minimum, self.started = True, ratio, timestamp
            self.progress_ratio, self.progress_at = ratio, timestamp
            return True
        return False
