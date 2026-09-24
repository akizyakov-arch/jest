"""Mapping contract, separate from recognition and command execution."""

from typing import Protocol

from .events import CommandEvent, GestureEvent


class CommandMapper(Protocol):
    def map(self, event: GestureEvent) -> tuple[CommandEvent, ...]: ...
