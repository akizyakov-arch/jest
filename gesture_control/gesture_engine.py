"""Recognition contract; no dependency on Windows input."""

from typing import Protocol

from .events import GestureEvent
from .hand_tracking import TrackingSnapshot


class GestureRecognizer(Protocol):
    def process(self, tracking: TrackingSnapshot, session_id: int) -> tuple[GestureEvent, ...]: ...
    def reset(self) -> None: ...
