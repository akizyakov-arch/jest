"""Confirmed three-finger pinch, one vertical command until both contacts open."""
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
        self.stroke=SwipeGesture(SimpleNamespace(swipe_min_distance=settings.workspace_min_distance,
            swipe_min_speed=settings.workspace_min_speed,swipe_vertical_tolerance=.06,
            swipe_max_duration_ms=1600,swipe_rearm_speed=.025,
            swipe_rearm_ms=settings.swipe_rearm_ms,max_result_age_ms=settings.max_result_age_ms))

    def reset(self):
        self.stroke.reset()
        self.hold.reset()
        self.ready=False
        self.used=False

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
                if not self.ready:
                    return None
        # A comfortable arm movement follows a slight arc. Its vertical
        # component must still dominate, but need not be ruler-straight.
        direction=self.stroke.update(matched,(-center[1],center[0]*.5),timestamp)
        if direction:
            self.used=True
        return {'RIGHT':'TASK_VIEW','LEFT':'SHOW_DESKTOP'}.get(direction)

    def matches(self, hand, width, height):
        return (not closed_fist(hand,width,height) and all(
            (r:=pinch_ratio(hand,width,height,tip)) is not None and
            r <= self.settings.pinch_on_ratio for tip in (8,12)))
