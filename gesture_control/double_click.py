"""Stabilize a second pinch without delaying or synthesizing mouse clicks."""

from math import dist


class DoubleClick:
    def __init__(self, settle_ms=300, escape_distance=.025):
        self.settle = settle_ms/1000
        self.escape = escape_distance
        self.reset()

    def reset(self):
        self.pending = None
        self.current = None
        self.second = False
        self.motion_origin = None
        self.motion_steps = 0

    def down(self, now, pixels, limits):
        interval, width, height = limits
        self.second = False
        if self.pending is not None:
            first, released, origin, center, deadline = self.pending
            dx, dy = pixels[0]-origin[0], pixels[1]-origin[1]
            self.second = (0 <= now-first <= interval/1000
                           and -width/2 <= dx < width/2 and -height/2 <= dy < height/2)
        self.pending = None
        self.current = (now, pixels, interval/1000)

    def up(self, now, center, dragged):
        if dragged or self.current is None:
            self.reset()
            return False
        second = self.second
        started, pixels, interval = self.current
        self.current = None
        self.second = False
        self.pending = None if second else (started, now, pixels, center, started+interval)
        self.motion_origin = center
        self.motion_steps = 0
        return second

    def hold(self, now, center):
        if self.pending is None:
            return False
        started, released, pixels, anchor, deadline = self.pending
        # A sustained departure is navigation, even inside the old large
        # escape radius. Tiny opening jitter still keeps the double-click aim.
        previous = self.motion_origin or anchor
        step = tuple(c-p for c,p in zip(center, previous))
        offset = tuple(c-a for c,a in zip(center, anchor))
        outward = sum(s*d for s,d in zip(step, offset)) > 0
        self.motion_steps = self.motion_steps+1 if outward and dist(center, previous) > .0002 else 0
        self.motion_origin = center
        departing = self.motion_steps >= 3 and dist(center, anchor) > min(.006, self.escape)
        if now > deadline or dist(center, anchor) > self.escape or departing:
            self.pending = None
            return False
        return now-released < self.settle
