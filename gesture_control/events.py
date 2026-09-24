"""Immutable contracts; timestamps use the same monotonic clock."""

from dataclasses import dataclass, field
from enum import Enum
from uuid import uuid4


class ControlState(str, Enum):
    OFF = "OFF"
    STANDBY = "STANDBY"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"


class GesturePhase(str, Enum):
    START = "START"
    UPDATE = "UPDATE"
    END = "END"


class CommandType(str, Enum):
    POINTER_MOVE = "POINTER_MOVE"
    POINTER_DOWN = "POINTER_DOWN"
    POINTER_UP = "POINTER_UP"
    KEY_DOWN = "KEY_DOWN"
    KEY_UP = "KEY_UP"
    SCROLL = "SCROLL"


@dataclass(frozen=True)
class GestureEvent:
    type: str
    session_id: int
    frame_id: int
    hand_id: str
    phase: GesturePhase
    coordinate_space: str
    source_timestamp: float
    emitted_timestamp: float
    position: tuple[float, float] | None = None
    confidence: float | None = None
    event_id: str = field(default_factory=lambda: uuid4().hex)


@dataclass(frozen=True)
class CommandEvent:
    type: CommandType
    session_id: int
    source_event_id: str
    expires_at: float
    position: tuple[float, float] | None = None
    button: str | None = None
    key: str | None = None
    wheel_units: int = 0
    event_id: str = field(default_factory=lambda: uuid4().hex)
