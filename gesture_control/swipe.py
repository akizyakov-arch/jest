"""Horizontal directional stroke, one event until a stable exit or stop."""
from collections import deque
from math import dist, atan2, radians, pi
from dataclasses import replace


def wrist_direction(hand, width, height):
    """Direction of the proximal fingers relative to the wrist, in pixel space.

    Translation and uniform scale cancel. PIP joints tolerate bent fingertips;
    folded fingers and degenerate geometry do not supply a flick candidate.
    """
    points = [(x*width, y*height) for x,y,_ in hand.landmarks]
    wrist = points[0]
    palm_size = dist(wrist, points[9])
    if palm_size < 1:
        return None
    extended = sum(dist(wrist,points[mcp+3]) > dist(wrist,points[mcp])*.95
                   for mcp in (5,9,13,17))
    if extended < 3:
        return None
    x = sum(points[i][0]-wrist[0] for i in (6,10,14,18))/4
    y = sum(points[i][1]-wrist[1] for i in (6,10,14,18))/4
    length = (x*x+y*y)**.5
    if length < palm_size*.8:
        return None
    return .5*x/length, .5*y/length


class SwipeGesture:
    def __init__(self, settings):
        self.settings = settings
        self.reset()

    def reset(self):
        self.samples = deque()
        self.armed = True
        self.idle_since = None
        self.last_time = self.last_position = None

    def update(self, matched, position, timestamp):
        if self.last_time is not None and timestamp <= self.last_time:
            return None
        if self.last_time is not None and timestamp-self.last_time > self.settings.max_result_age_ms/1000:
            self.reset()
        speed = (dist(position,self.last_position)/(timestamp-self.last_time)
                 if self.last_time is not None else 0.)
        self.last_time, self.last_position = timestamp, position
        if not matched or not self.armed:
            self.samples.clear()
            if not matched or speed <= self.settings.swipe_rearm_speed:
                if self.idle_since is None:
                    self.idle_since = timestamp
                if timestamp-self.idle_since >= self.settings.swipe_rearm_ms/1000:
                    self.armed = True
            else:
                self.idle_since = None
            return None
        self.idle_since = None
        if speed <= self.settings.swipe_rearm_speed:
            self.samples.clear()
        self.samples.append((timestamp,position))
        while self.samples and timestamp-self.samples[0][0] > self.settings.swipe_max_duration_ms/1000:
            self.samples.popleft()
        if len(self.samples) < 3:
            return None
        start, origin = self.samples[0]
        elapsed = timestamp-start
        dx,dy = position[0]-origin[0], position[1]-origin[1]
        travel = sum(abs(b[1][0]-a[1][0]) for a,b in zip(self.samples,list(self.samples)[1:]))
        vertical = max(p[1] for _,p in self.samples)-min(p[1] for _,p in self.samples)
        if (elapsed > 0 and abs(dx) >= self.settings.swipe_min_distance
                and abs(dx)/elapsed >= self.settings.swipe_min_speed
                and vertical <= self.settings.swipe_vertical_tolerance
                and abs(dy) <= abs(dx)*.35 and travel <= abs(dx)*1.25):
            self.armed = False
            self.samples.clear()
            return 'RIGHT' if dx > 0 else 'LEFT'
        return None


class WristFlick:
    """Screen-plane flick or palm turn in depth, with a shared rearm gate."""
    def __init__(self, settings):
        self.settings = settings
        self.plane = SwipeGesture(settings)
        self.depth = SwipeGesture(replace(settings,
            swipe_min_distance=radians(settings.wrist_turn_min_degrees)*.5,
            swipe_min_speed=radians(settings.wrist_turn_speed_degrees)*.5,
            swipe_max_duration_ms=650, swipe_rearm_speed=.1))
        self.reset()

    @property
    def armed(self):
        return self.plane.armed and self.depth.armed

    def reset(self):
        self.plane.reset()
        self.depth.reset()
        self.previous_angle = self.unwrapped_angle = None
        self.last_mode = None

    def update(self, hand, width, height, timestamp):
        vector = wrist_direction(hand, width, height)
        if vector is None:
            # Do not bridge missing/invalid pose geometry into a turn.
            self.reset()
            return None
        sign = -1 if self.settings.preview_mirrored else 1
        was_armed = self.armed
        plane_event = self.plane.update(True,(sign*vector[0],vector[1]),timestamp)
        a,b = hand.landmarks[5],hand.landmarks[17]
        dx,dz = b[0]-a[0],b[2]-a[2]
        palm_size = dist(hand.landmarks[0],hand.landmarks[9])
        if dx*dx+dz*dz < (palm_size*.15)**2:
            self.depth.reset()
            self.previous_angle = self.unwrapped_angle = None
            # Collapsed knuckle geometry cannot determine a depth turn.
            if plane_event and was_armed:
                self.last_mode = 'PLANE'
                self.depth.armed = False
                return plane_event
            return None
        # MediaPipe normalized z has approximately the same scale as x.
        # Angle is unwrapped to avoid a false stroke at the +/- pi boundary.
        angle = atan2(-dz,dx)
        if (self.depth.last_time is None or
                timestamp-self.depth.last_time > self.settings.max_result_age_ms/1000):
            self.previous_angle = self.unwrapped_angle = angle
        if timestamp <= (self.depth.last_time or float('-inf')):
            return None
        delta = (angle-self.previous_angle+pi)%(2*pi)-pi
        self.unwrapped_angle += delta
        self.previous_angle = angle
        depth_event = self.depth.update(True,(sign*self.unwrapped_angle*.5,0.),timestamp)
        event = depth_event or plane_event
        if event and was_armed:
            self.last_mode = 'DEPTH' if depth_event else 'PLANE'
            for gate in (self.plane,self.depth):
                gate.armed = False
                gate.idle_since = None
                gate.samples.clear()
            return event
        return None
