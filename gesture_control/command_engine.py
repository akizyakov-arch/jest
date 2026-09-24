"""Single-threaded command gate; callers serialize state and command events."""

import logging
import math
from collections.abc import Callable
from time import monotonic

from .events import CommandEvent, CommandType
from .windows_input import InputBackend

log = logging.getLogger(__name__)


class CommandEngine:
    def __init__(self, backend: InputBackend, clock: Callable[[], float] = monotonic):
        self.backend = backend
        self.clock = clock
        self.session_id = 0
        self.enabled = False
        self.buttons: set[str] = set()
        self.keys: set[str] = set()
        self._seen: dict[str, float] = {}

    def activate(self) -> int:
        if self.buttons or self.keys:
            raise RuntimeError("Unreleased input prevents activation")
        self.session_id += 1
        self._seen.clear()
        begin = getattr(self.backend, 'begin_session', None)
        if begin is not None:
            begin(self.session_id)
        self.enabled = True
        return self.session_id

    def stop(self) -> None:
        # Close the gate before attempting fallible backend cleanup.
        self.enabled = False
        self.session_id += 1
        self._seen.clear()
        end = getattr(self.backend, 'end_session', None)
        if end is not None:
            end()
            self.buttons.clear()
            self.keys.clear()
        elif self.buttons or self.keys:
            self.backend.release(frozenset(self.buttons), frozenset(self.keys))
            self.buttons.clear()
            self.keys.clear()

    def submit(self, command: CommandEvent) -> bool:
        now = self.clock()
        if (not self.enabled or command.session_id != self.session_id
                or not math.isfinite(command.expires_at) or command.expires_at <= now):
            log.debug("command_rejected id=%s reason=inactive_stale_or_expired", command.event_id)
            return False
        self._seen = {k: expiry for k, expiry in self._seen.items() if expiry > now}
        if command.event_id in self._seen:
            return False
        self._validate(command)
        if command.type == CommandType.POINTER_DOWN and command.button in self.buttons:
            return False
        if command.type == CommandType.KEY_DOWN and command.key in self.keys:
            return False
        if command.type == CommandType.POINTER_UP and command.button not in self.buttons:
            return False
        if command.type == CommandType.KEY_UP and command.key not in self.keys:
            return False
        prepare = getattr(self.backend, 'prepare', None)
        if prepare is not None:
            prepare(command)
        self._seen[command.event_id] = command.expires_at
        # Record ownership before sending: backend errors can follow a partial send.
        if command.type == CommandType.POINTER_DOWN:
            self.buttons.add(command.button)
        elif command.type == CommandType.KEY_DOWN:
            self.keys.add(command.key)
        try:
            if self.backend.send(command) is False:
                if command.type != CommandType.POINTER_MOVE:
                    raise OSError('Backend rejected a button/key command')
                return False
        except Exception:
            log.exception("input_send_failed id=%s", command.event_id)
            self.stop()
            raise
        if command.type == CommandType.POINTER_UP:
            self.buttons.discard(command.button)
        elif command.type == CommandType.KEY_UP:
            self.keys.discard(command.key)
        log.debug("command_sent id=%s type=%s", command.event_id, command.type.value)
        return True

    @staticmethod
    def _validate(command: CommandEvent) -> None:
        if command.type == CommandType.SCROLL:
            if type(command.wheel_units) is not int or not 0 < abs(command.wheel_units) <= 1200:
                raise ValueError('Wheel delta must be a nonzero integer in -1200..1200')
        if not isinstance(command.type, CommandType):
            raise ValueError("Unknown command type")
        if command.type in (CommandType.POINTER_DOWN, CommandType.POINTER_UP):
            if command.button not in {"left", "right", "middle"}:
                raise ValueError("Invalid pointer button")
        if command.type in (CommandType.KEY_DOWN, CommandType.KEY_UP) and not command.key:
            raise ValueError("Key is required")
        if (command.type == CommandType.POINTER_MOVE or
                (command.type in (CommandType.POINTER_DOWN,CommandType.POINTER_UP) and command.position is not None)):
            if command.position is None or len(command.position) != 2:
                raise ValueError("Screen position is required")
            if not all(math.isfinite(v) for v in command.position):
                raise ValueError("Position must be finite")
