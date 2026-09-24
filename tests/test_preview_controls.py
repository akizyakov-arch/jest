import unittest
from threading import Event
from types import SimpleNamespace

from gesture_control.camera_session import CameraSession
from gesture_control.preview_controls import Action, buttons, click_action, keyboard_action
from gesture_control.pointer import VirtualPointer
from gesture_control.settings import Settings
from gesture_control.tracking_runtime import LatestValue


class ControlsTests(unittest.TestCase):
    def test_plus_minus_resize_without_square_brackets(self):
        pointer = VirtualPointer(Settings())
        for key in (ord("-"), ord("="), ord("+")):
            action = keyboard_action(key)
            self.assertEqual(action.kind, "resize")
            pointer.resize_area(action.value * 0.05)
        self.assertAlmostEqual(pointer.area.right - pointer.area.left, 0.65)

    def test_buttons_work_without_keyboard_layout(self):
        for button in buttons(1040, 480):
            x0, y0, x1, y1 = button.bounds
            self.assertEqual(click_action((x0+x1)//2, (y0+y1)//2, 1040, 480), button.action)
        self.assertIsNone(click_action(20, 20, 1040, 480))

    def test_camera_digits_and_no_key(self):
        self.assertEqual(keyboard_action(ord("0")), Action("camera", 0))
        self.assertEqual(keyboard_action(ord("1")), Action("camera", 1))
        self.assertEqual(keyboard_action(ord("9")), Action("camera", 9))
        self.assertIsNone(keyboard_action(-1))


class FakeRuntime:
    def __init__(self, index, history):
        self.index, self.history = index, history
        self.stopped = Event()
        self.is_alive = False
        self.errors, self.results = LatestValue(), LatestValue()

    def start(self):
        self.history.append(("start", self.index))
        self.is_alive = True

    def close(self):
        self.history.append(("close", self.index))
        self.stopped.set()
        self.is_alive = False


class CameraSessionTests(unittest.TestCase):
    def setUp(self):
        self.history = []
        self.time = 1.0
        self.session = CameraSession(lambda index: FakeRuntime(index, self.history),
                                     0, 30000, 5000, clock=lambda: self.time)

    def test_switch_waits_for_release_and_discards_old_results(self):
        self.session.poll()
        old = self.session.runtime
        old.results.publish(SimpleNamespace(frame="old"))
        self.assertTrue(self.session.select(1))
        self.assertTrue(old.stopped.is_set())
        self.assertIsNone(self.session.poll())
        self.assertEqual(self.history, [("start", 0)])
        old.is_alive = False
        self.assertIsNone(self.session.poll())
        self.assertEqual(self.history, [("start", 0), ("close", 0), ("start", 1)])
        self.assertEqual(self.session.frames_received, 0)

    def test_unavailable_camera_can_be_replaced(self):
        self.session.poll()
        old = self.session.runtime
        old.errors.publish(RuntimeError("camera unavailable"))
        old.is_alive = False
        with self.assertLogs("gesture_control.camera_session", level="ERROR"):
            self.session.poll()
        self.assertIsNotNone(self.session.error)
        self.session.select(1)
        self.session.poll()
        self.assertIsNone(self.session.error)
        self.assertEqual(self.session.runtime.index, 1)

    def test_timeout_and_retry_same_camera(self):
        self.session.poll()
        self.time = 32
        with self.assertLogs("gesture_control.camera_session", level="ERROR"):
            self.session.poll()
        self.assertIsNotNone(self.session.error)
        self.session.runtime.is_alive = False
        self.session.select(0, retry=True)
        self.session.poll()
        self.assertIsNone(self.session.error)
        self.assertEqual(self.history[-2:], [("close", 0), ("start", 0)])

    def test_rapid_selection_opens_only_last_requested_device(self):
        self.session.poll()
        self.session.select(1)
        self.session.select(2)
        self.session.select(1)
        self.session.runtime.is_alive = False
        self.session.poll()
        self.assertEqual(self.history, [("start", 0), ("close", 0), ("start", 1)])

    def test_same_working_camera_is_not_restarted(self):
        self.session.poll()
        self.assertFalse(self.session.select(0))
        self.assertFalse(self.session.runtime.stopped.is_set())
