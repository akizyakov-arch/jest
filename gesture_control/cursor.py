"""Physical primary-display mapping and bounded cursor acquisition."""

from dataclasses import dataclass
from math import exp, hypot, isfinite


@dataclass(frozen=True)
class Screen:
    width: int
    height: int

    def __post_init__(self):
        if self.width < 2 or self.height < 2:
            raise ValueError("Invalid primary display size")

    def pixels(self, point):
        if len(point) != 2 or not all(isfinite(v) for v in point):
            raise ValueError("Invalid cursor position")
        return tuple(round(max(0, min(1, v)) * (size-1))
                     for v, size in zip(point, (self.width, self.height)))

    def normalized(self, point):
        return point[0]/(self.width-1), point[1]/(self.height-1)

    def contains(self, point):
        return 0 <= point[0] < self.width and 0 <= point[1] < self.height

    def absolute(self, point):
        if not self.contains(point) or not all(isfinite(v) for v in point):
            raise ValueError("Cursor position is outside the primary display")
        # Target the pixel center in the 16-bit absolute input range.
        return tuple(min(65535, int((v + .5)*65536/size))
                     for v, size in zip(point, (self.width, self.height)))


class CursorMotion:
    """No backlog: first sample anchors, subsequent fresh samples approach target."""

    def __init__(self, speed: float, response_ms: float = 60, precision=False, jitter_radius_px=0):
        self.speed = speed
        self.response = response_ms/1000
        self.precision = precision
        self.jitter_radius_px = jitter_radius_px
        self.reset()

    def reset(self):
        self.position = None
        self.timestamp = None
        self.previous_target = None
        self.stable_target = None

    def step(self, target, timestamp, origin=None, screen_size=(1920,1080)):
        if self.jitter_radius_px:
            if self.stable_target is not None and not any(v in (0.,1.) for v in target):
                jitter = hypot((target[0]-self.stable_target[0])*(screen_size[0]-1),
                               (target[1]-self.stable_target[1])*(screen_size[1]-1))
                if jitter <= self.jitter_radius_px:
                    target = self.stable_target
            self.stable_target = target
        if self.position is None:
            if origin is None:
                raise ValueError("Current cursor position is required")
            self.position, self.timestamp = origin, timestamp
            self.previous_target = target
            return None
        dt = max(0, min(.05, timestamp-self.timestamp))
        self.timestamp = max(timestamp, self.timestamp)
        dx, dy = target[0]-self.position[0], target[1]-self.position[1]
        distance = hypot(dx, dy)
        response_time = self.response
        if self.precision and dt > 0:
            velocity = hypot(target[0]-self.previous_target[0],target[1]-self.previous_target[1])/dt
            blend = max(0.,min(1.,(velocity-.03)/.47))
            # More damping near a target; less trailing behind broad movement.
            response_time *= 1.25-.9*blend
            pixels = hypot(dx*(screen_size[0]-1),dy*(screen_size[1]-1))
            at_edge = any(v in (0.,1.) for v in target)
            if pixels < .8 and not at_edge and velocity < .03:
                self.previous_target = target
                return self.position
        self.previous_target = target
        response = 1-exp(-dt/response_time) if response_time else 1
        if 0 < distance < 1e-5:
            response = 1  # Subpixel settling preserves exact reachability.
        factor = min(response, self.speed*dt/distance) if distance else 0
        self.position = self.position[0]+dx*factor, self.position[1]+dy*factor
        return self.position
