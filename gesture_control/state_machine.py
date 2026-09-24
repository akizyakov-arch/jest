"""Control lifecycle. Palm confirmation/rearm belongs to gesture recognition."""

import logging

from .command_engine import CommandEngine
from .events import CommandEvent, ControlState

log = logging.getLogger(__name__)


class ControlMachine:
    def __init__(self, commands: CommandEngine):
        self.commands = commands
        self.state = ControlState.OFF

    def _stop_into(self, state: ControlState) -> None:
        previous = self.state
        self.state = state
        self.commands.stop()
        log.info("state_changed previous=%s current=%s", previous.value, state.value)

    def enable(self, *, camera_ready: bool, hotkey_ready: bool) -> bool:
        if self.state != ControlState.OFF or not camera_ready or not hotkey_ready:
            return False
        self._stop_into(ControlState.STANDBY)
        return True

    def palm_confirmed(self) -> None:
        if self.state == ControlState.STANDBY:
            self.commands.activate()
            self.state = ControlState.ACTIVE
            log.info("state_changed current=ACTIVE session=%s", self.commands.session_id)
        elif self.state == ControlState.ACTIVE:
            self._stop_into(ControlState.STANDBY)

    def pause(self) -> None:
        if self.state != ControlState.OFF:
            self._stop_into(ControlState.PAUSED)

    def emergency_stop(self) -> None:
        self.pause()

    def resume(self, *, camera_ready: bool, hotkey_ready: bool) -> bool:
        if self.state != ControlState.PAUSED or not camera_ready or not hotkey_ready:
            return False
        self._stop_into(ControlState.STANDBY)
        return True

    def disable(self) -> None:
        self._stop_into(ControlState.OFF)

    def submit(self, command: CommandEvent) -> bool:
        if self.state != ControlState.ACTIVE:
            return False
        try:
            return self.commands.submit(command)
        except Exception:
            self.state = ControlState.PAUSED
            self.commands.stop()
            raise
