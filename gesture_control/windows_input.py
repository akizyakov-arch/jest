"""Input interface and deterministic fake; native cursor lives in native_cursor."""

from typing import Protocol

from .events import CommandEvent


class InputBackend(Protocol):
    def send(self, command: CommandEvent) -> bool | None:
        """Send once or raise; False means an expired move was safely dropped."""
        ...

    def release(self, buttons: frozenset[str], keys: frozenset[str]) -> None:
        """Idempotently release only input owned by this application."""
        ...


class FakeInputBackend:
    def __init__(self) -> None:
        self.commands: list[CommandEvent] = []
        self.releases: list[tuple[frozenset[str], frozenset[str]]] = []

    def send(self, command: CommandEvent) -> None:
        self.commands.append(command)

    def release(self, buttons: frozenset[str], keys: frozenset[str]) -> None:
        self.releases.append((buttons, keys))
