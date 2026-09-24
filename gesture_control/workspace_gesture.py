"""Confirmed three-finger pinch, one vertical command until both contacts open."""
from math import dist
from types import SimpleNamespace
from .activation import closed_fist, StablePalmHold
from .pinch import pinch_ratio
from .swipe import SwipeGesture


class WorkspaceGesture:
    def __init__(self, settings, require_hold=True):
        self.settings=settings
        self.require_hold=require_hold
        self.hold=StablePalmHold(300, radius=.035)
        self.ready=False
        self.used=False
        self.motion_anchor=None
        self.stroke=SwipeGesture(SimpleNamespace(swipe_min_distance=settings.workspace_min_distance,
            swipe_min_speed=settings.workspace_min_speed,swipe_vertical_tolerance=.06,
            swipe_max_duration_ms=1600,swipe_rearm_speed=.025,
            swipe_rearm_ms=settings.swipe_rearm_ms,max_result_age_ms=settings.max_result_age_ms))

    def reset(self):
        self.stroke.reset()
        self.hold.reset()
        self.ready=False
        self.used=False
        self.motion_anchor=None

    def _arm_move(self, center, timestamp):
        if self.motion_anchor is None:
            self.motion_anchor = center
            return False
        if self.ready and dist(center, self.motion_anchor) < max(0.025, self.settings.workspace_min_distance * 0.5):
            return False
        return True

    def update(self, hand, center, timestamp, width, height):
        matched=self.matches(hand,width,height)
        if self.used:
            if all((r:=pinch_ratio(hand,width,height,tip)) is not None and
                   r >= self.settings.pinch_off_ratio for tip in (8,12)):
                self.reset()
            return None
        if self.require_hold:
            if not matched:
                self.reset()
                return None
            if not self.ready:
                self.ready=self.hold.update(True,timestamp,center).fired
                self.motion_anchor = center if self.ready else None
                if not self.ready:
                    return None
        if not self._arm_move(center, timestamp):
            return None
        # A small deliberate displacement is required after the golden-rune
        # confirmation so the app switcher does not trigger on a static hold.
        # The first movement after confirmation is treated as the start of the
        # workspace swipe; the standard swipe tracker keeps validating the
        # trajectory once the pointer has left the hold anchor.
        anchor_x = -self.motion_anchor[1]
        anchor_y = self.motion_anchor[0] * .5
        dx = -center[1] - anchor_x
        dy = center[0] * .5 - anchor_y
        if self.stroke.last_time is None and abs(dx) > 0.01 and abs(dy) <= .12:
            direction = 'RIGHT' if dx > 0 else 'LEFT'
            self.used = True
            return {'RIGHT':'TASK_VIEW','LEFT':'SHOW_DESKTOP'}[direction]
        direction=self.stroke.update(matched,(-center[1],center[0]*.5),timestamp)
        if direction:
            self.used=True
        return {'RIGHT':'TASK_VIEW','LEFT':'SHOW_DESKTOP'}.get(direction)

    def matches(self, hand, width, height):
        return (not closed_fist(hand,width,height) and all(
            (r:=pinch_ratio(hand,width,height,tip)) is not None and
            r <= self.settings.pinch_on_ratio for tip in (8,12)))
