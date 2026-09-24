import unittest

from gesture_control.command_engine import CommandEngine
from gesture_control.events import CommandEvent, CommandType, ControlState
from gesture_control.state_machine import ControlMachine
from gesture_control.windows_input import FakeInputBackend


class ControlTests(unittest.TestCase):
    def setUp(self):
        self.backend = FakeInputBackend()
        self.engine = CommandEngine(self.backend, clock=lambda: 10.0)
        self.control = ControlMachine(self.engine)

    def activate(self):
        self.control.enable(camera_ready=True, hotkey_ready=True)
        self.control.palm_confirmed()

    def command(self, kind=CommandType.POINTER_DOWN, **kwargs):
        return CommandEvent(kind, self.engine.session_id, "gesture", 11.0, **kwargs)

    def test_no_input_outside_active(self):
        for state in (ControlState.OFF, ControlState.STANDBY, ControlState.PAUSED):
            self.control.state = state
            self.assertFalse(self.control.submit(self.command(button="left")))
        self.assertEqual(self.backend.commands, [])

    def test_enable_requires_readiness(self):
        self.assertFalse(self.control.enable(camera_ready=True, hotkey_ready=False))
        self.assertFalse(self.control.enable(camera_ready=False, hotkey_ready=True))
        self.assertEqual(self.control.state, ControlState.OFF)

    def test_pause_releases_all_owned_input_and_cannot_resume_by_palm(self):
        self.activate()
        self.control.submit(self.command(button="left"))
        self.control.submit(self.command(CommandType.KEY_DOWN, key="ctrl"))
        self.control.emergency_stop()
        self.assertEqual(self.backend.releases, [(frozenset({"left"}), frozenset({"ctrl"}))])
        self.control.palm_confirmed()
        self.assertEqual(self.control.state, ControlState.PAUSED)
        self.control.resume(camera_ready=True, hotkey_ready=True)
        self.assertEqual(self.control.state, ControlState.STANDBY)

    def test_late_callback_cannot_execute_in_new_session(self):
        self.activate()
        late = self.command(button="left")
        self.control.pause()
        self.control.resume(camera_ready=True, hotkey_ready=True)
        self.control.palm_confirmed()
        self.assertFalse(self.control.submit(late))
        self.assertEqual(self.backend.commands, [])

    def test_duplicate_and_repeated_down_are_rejected(self):
        self.activate()
        command = self.command(button="left")
        self.assertTrue(self.control.submit(command))
        self.assertFalse(self.control.submit(command))
        self.assertFalse(self.control.submit(self.command(button="left")))
        self.assertTrue(self.control.submit(self.command(CommandType.POINTER_UP, button="left")))
        self.control.disable()
        self.assertEqual(len(self.backend.commands), 2)
        self.assertEqual(self.backend.releases, [])

    def test_expired_and_nonfinite_expiry_rejected(self):
        self.activate()
        for expiry in (9.0, 10.0, float("nan"), float("inf")):
            command = CommandEvent(CommandType.POINTER_DOWN, self.engine.session_id,
                                   "gesture", expiry, button="left")
            self.assertFalse(self.control.submit(command))

    def test_cleanup_is_idempotent(self):
        self.activate()
        self.control.submit(self.command(button="left"))
        self.control.disable()
        self.control.disable()
        self.assertEqual(len(self.backend.releases), 1)

    def test_send_failure_pauses_and_releases_possible_partial_press(self):
        self.activate()
        def fail(command):
            raise OSError("simulated partial send")
        self.backend.send = fail
        with self.assertLogs("gesture_control.command_engine", level="ERROR"):
            with self.assertRaises(OSError):
                self.control.submit(self.command(button="left"))
        self.assertEqual(self.control.state, ControlState.PAUSED)
        self.assertFalse(self.engine.enabled)
        self.assertEqual(self.backend.releases[0][0], frozenset({"left"}))

    def test_failed_release_keeps_gate_closed_and_ownership_for_retry(self):
        self.activate()
        self.control.submit(self.command(button="left"))
        release = self.backend.release
        def fail(buttons, keys):
            raise OSError("simulated release failure")
        self.backend.release = fail
        with self.assertRaises(OSError):
            self.control.pause()
        self.assertFalse(self.engine.enabled)
        self.assertEqual(self.engine.buttons, {"left"})
        self.assertEqual(self.control.state, ControlState.PAUSED)
        self.backend.release = release
        self.control.disable()
        self.assertFalse(self.engine.buttons)


if __name__ == "__main__":
    unittest.main()
