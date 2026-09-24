from dataclasses import replace
import unittest

from gesture_control.events import CommandType
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.interaction import InteractionSession
from gesture_control.pinch import PinchGate, pinch_ratio
from gesture_control.profiles import load_profiles
from gesture_control.settings import Settings
from test_interaction import pose_hand
from test_cursor import DesktopFake


def pinched_hand(dx=0):
    hand = pose_hand('POINT')
    points = list(hand.landmarks)
    points[4] = points[8] = (.43, .45, 0)
    points = tuple((x+dx, y, z) for x, y, z in points)
    return replace(hand, landmarks=points)


class PinchTests(unittest.TestCase):
    def test_hysteresis_debounce_rearm_and_no_repeat(self):
        gate = PinchGate(.25, .4, 70, 60)
        self.assertFalse(any(gate.update(0, i/30) for i in range(30)))
        for i in range(4):
            gate.update(.6, 1+i/30)
        self.assertTrue(gate.armed)
        events = [gate.update(0, 2+i/30) for i in range(60)]
        self.assertEqual(events.count('down'), 1)
        self.assertIsNone(gate.update(.35, 4))
        self.assertTrue(gate.held)
        events = [gate.update(.6, 5+i/30) for i in range(10)]
        self.assertEqual(events.count('up'), 1)
        self.assertTrue(gate.armed)

    def test_short_spikes_and_invalid_geometry(self):
        gate = PinchGate(.25, .4, 70, 60)
        gate.update(.6, 0)
        gate.update(.6, .1)
        self.assertIsNone(gate.update(0, .2))
        self.assertIsNone(gate.update(.6, .23))
        self.assertFalse(gate.held)
        self.assertEqual(pinch_ratio(pinched_hand(), 640, 480), 0)
        self.assertIsNone(pinch_ratio(replace(pinched_hand(), landmarks=()), 640, 480))


class PinchInteractionTests(unittest.TestCase):
    def setUp(self):
        self.time = 1.
        self.backend = DesktopFake()
        self.session = InteractionSession(Settings(), load_profiles(), clock=lambda: self.time,
                                          cursor_backend=self.backend)
        self.session.hotkey_ready = True

    def feed(self, hand, count=1):
        for _ in range(count):
            self.time += 1/30
            hands = () if hand is None else (hand,)
            self.session.process(TrackingSnapshot(round(self.time*1000), self.time, self.time, hands),
                                 self.time, 640, 480)

    def activate(self):
        self.feed(pose_hand('OPEN_PALM'), 30)
        self.feed(pose_hand('POINT'), 5)

    def buttons(self):
        return [c.type for c in self.backend.commands if c.type != CommandType.POINTER_MOVE]

    def test_click_is_one_down_up_without_extra_click(self):
        self.activate()
        moves = len(self.backend.commands)
        self.feed(pinched_hand(), 30)
        self.assertEqual(self.buttons(), [CommandType.POINTER_DOWN])
        self.assertEqual(len(self.backend.commands), moves+1)
        self.feed(pose_hand('POINT'), 4)
        self.assertEqual(self.buttons(), [CommandType.POINTER_DOWN, CommandType.POINTER_UP])
        self.assertFalse(self.session.machine.commands.buttons)

    def test_drag_moves_only_after_threshold_and_releases_once(self):
        self.activate()
        self.feed(pinched_hand(), 5)
        before = len(self.backend.commands)
        self.feed(pinched_hand(.002), 5)
        self.assertEqual(len(self.backend.commands), before)
        for i in range(1, 11):
            self.feed(pinched_hand(i*.005))
        self.assertTrue(self.session.dragging)
        self.assertGreater(len(self.backend.commands), before)
        self.feed(pose_hand('POINT'), 4)
        self.assertEqual(self.buttons(), [CommandType.POINTER_DOWN, CommandType.POINTER_UP])

    def test_loss_releases_immediately_and_recovery_never_resumes_drag(self):
        self.activate()
        self.feed(pinched_hand(), 5)
        self.feed(None)
        self.assertEqual(self.buttons(), [CommandType.POINTER_DOWN, CommandType.POINTER_UP])
        self.feed(None, 15)
        self.feed(pinched_hand(), 30)
        self.assertEqual(self.session.view().state, 'PAUSED')
        for _ in range(35):
            self.feed(pose_hand('OPEN_PALM'))
            if self.session.view().state == 'ACTIVE':
                break
        self.assertEqual(self.session.view().state, 'ACTIVE')
        self.feed(pinched_hand(), 15)
        self.assertEqual(len(self.buttons()), 2)  # Explicit open rearm after activation.

    def test_emergency_and_profile_change_release_owned_input(self):
        for action in ('emergency_stop', 'cycle_profile', 'camera_changed', 'close'):
            with self.subTest(action=action):
                self.setUp()
                self.activate()
                self.feed(pinched_hand(), 5)
                getattr(self.session, action)()
                self.assertEqual(self.backend.releases[-1], (frozenset({'left'}), frozenset()))
                self.feed(pose_hand('OPEN_PALM'), 35)
                self.assertNotEqual(self.session.view().state, 'ACTIVE')

    def test_recovery_requires_single_stable_palm_and_stops_after_emergency(self):
        self.activate()
        self.feed(None, 15)
        self.feed(pose_hand('OPEN_PALM'), 3)
        self.assertEqual(self.session.view().state, 'PAUSED')
        for _ in range(40):
            self.time += 1/30
            hand = pose_hand('OPEN_PALM')
            self.session.process(TrackingSnapshot(1, self.time, self.time, (hand, hand)),
                                 self.time, 640, 480)
        self.assertEqual(self.session.view().state, 'PAUSED')
        self.session.emergency_stop()
        self.feed(pose_hand('OPEN_PALM'), 35)
        self.assertEqual(self.session.view().state, 'PAUSED')

    def test_preview_simulates_click_without_native_backend(self):
        self.session = InteractionSession(Settings(), load_profiles(), clock=lambda: self.time)
        self.session.hotkey_ready = True
        self.backend = self.session.machine.commands.backend
        self.activate()
        self.feed(pinched_hand(), 5)
        self.feed(pose_hand('POINT'), 4)
        self.assertEqual(self.buttons(), [CommandType.POINTER_DOWN, CommandType.POINTER_UP])
