"""Read-only presentation contract; effects cannot execute commands."""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol

from .events import ControlState


class FxMode(str, Enum):
    FULL = "FULL"
    MINIMAL = "MINIMAL"
    OFF = "OFF"


@dataclass(frozen=True)
class VisualSnapshot:
    state: ControlState
    cursor: tuple[float, float] | None = None
    gesture_label: str | None = None


class VisualEffects(Protocol):
    def render(self, snapshot: VisualSnapshot) -> None: ...
    def set_mode(self, mode: FxMode) -> None: ...
    def close(self) -> None: ...
