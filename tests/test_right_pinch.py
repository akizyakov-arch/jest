from dataclasses import replace
import unittest

from gesture_control.events import CommandType
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.interaction import InteractionSession
from gesture_control.profiles import load_profiles
from gesture_control.settings import Settings
from test_interaction import pose_hand
from test_palm_navigation import Desktop, shifted
from test_pinch import pinched_hand


def right_hand(tip=12, ambiguous=False):
    hand = pose_hand('OPEN_PALM')
    points = list(hand.landmarks)
    points[4] = points[tip] = (.5, .48, 0)
    if ambiguous:
        points[8] = points[4]
    return replace(hand, landmarks=tuple(points))


class RightPinchTests(unittest.TestCase):
    def setUp(self):
        self.time = 1.
        self.backend = Desktop()
        self.make_session(Settings())

    def make_session(self, settings):
        self.session = InteractionSession(settings, load_profiles(), clock=lambda: self.time,
                                          cursor_backend=self.backend)
        self.session.hotkey_ready = True
        self.feed(pose_hand('OPEN_PALM'), 35)

    def feed(self, hand, count=1):
        for _ in range(count):
            self.time += 1/30
            self.session.process(TrackingSnapshot(round(self.time*1000), self.time, self.time,
                                 () if hand is None else (hand,)), self.time, 640, 480)

    def button_commands(self):
        return [(c.type, c.button) for c in self.backend.commands if c.type != CommandType.POINTER_MOVE]

    def test_right_click_one_pair_fixed_cursor_and_no_repeat(self):
        before, position = len(self.backend.commands), self.backend.position
        self.feed(right_hand(), 30)
        self.assertEqual(self.button_commands(), [(CommandType.POINTER_DOWN, 'right')])
        for i in range(10):
            self.feed(shifted(right_hand(), i*.005))
        self.assertEqual(self.backend.position, position)
        self.assertFalse(self.session.dragging)
        self.assertEqual(len(self.backend.commands), before+1)
        self.feed(pose_hand('OPEN_PALM'), 4)
        self.assertEqual(self.button_commands(), [(CommandType.POINTER_DOWN, 'right'),
                                                   (CommandType.POINTER_UP, 'right')])

    def test_ambiguous_new_pinch_is_rejected_until_open_rearm(self):
        self.session.settings=replace(self.session.settings,gesture_workspace=False)
        self.feed(right_hand(ambiguous=True), 30)
        self.assertEqual(self.button_commands(), [])
        self.assertEqual(self.session.action, 'PINCH_AMBIGUOUS')
        self.feed(right_hand(), 15)
        self.assertEqual(self.button_commands(), [])
        self.feed(pose_hand('OPEN_PALM'), 5)
        self.feed(right_hand(), 5)
        self.assertEqual(self.button_commands(), [(CommandType.POINTER_DOWN, 'right')])

    def test_existing_left_capture_wins_over_new_right_candidate(self):
        self.feed(pinched_hand(), 5)
        self.assertEqual(self.session.machine.commands.buttons, {'left'})
        hand = pinched_hand()
        points = list(hand.landmarks)
        points[12] = points[4]
        hand = replace(hand, landmarks=tuple(points))
        for i in range(12):
            self.feed(shifted(hand, i*.004))
        self.assertTrue(self.session.dragging)
        self.assertEqual(self.button_commands(), [(CommandType.POINTER_DOWN, 'left')])

    def test_ambiguous_fingers_do_not_freeze_palm_navigation(self):
        self.session.settings=replace(self.session.settings,gesture_workspace=False)
        start = self.backend.position
        for i in range(30):
            self.feed(shifted(right_hand(ambiguous=True), i*.003))
        self.assertGreater(abs(self.backend.position[0]-start[0]), .03)
        self.assertEqual(self.button_commands(), [])
        self.assertEqual(self.session.action, 'PINCH_AMBIGUOUS')

    def test_existing_right_capture_wins_and_never_drags(self):
        self.feed(right_hand(), 5)
        position = self.backend.position
        for i in range(12):
            self.feed(shifted(right_hand(ambiguous=True), i*.004))
        self.assertEqual(self.backend.position, position)
        self.assertEqual(self.button_commands(), [(CommandType.POINTER_DOWN, 'right')])
        self.assertFalse(self.session.dragging)

    def test_ring_alternative_replaces_middle(self):
        self.make_session(Settings(right_pinch_finger='RING'))
        self.feed(right_hand(12), 10)
        self.assertEqual(self.button_commands(), [])
        self.feed(pose_hand('OPEN_PALM'), 5)
        self.feed(right_hand(16), 5)
        self.feed(pose_hand('OPEN_PALM'), 4)
        self.assertEqual(self.button_commands(), [(CommandType.POINTER_DOWN, 'right'),
                                                   (CommandType.POINTER_UP, 'right')])

    def test_loss_sends_correct_up_without_transferring_capture(self):
        self.feed(right_hand(), 5)
        self.feed(None)
        self.assertEqual(self.button_commands()[-1], (CommandType.POINTER_UP, 'right'))
        self.feed(right_hand(), 15)
        self.assertEqual(len(self.button_commands()), 2)

    def test_manual_stop_releases_right_owned_input(self):
        self.feed(right_hand(), 5)
        self.session.emergency_stop()
        self.assertEqual(self.backend.releases[-1], (frozenset({'right'}), frozenset()))
        self.feed(right_hand(), 20)
        self.assertEqual(len(self.button_commands()), 1)

    def test_template_profile_does_not_execute_right_click(self):
        self.make_session(Settings(profile_id='creative-3d'))
        self.feed(right_hand(), 20)
        self.assertEqual(self.button_commands(), [])

    def test_invalid_alternative_rejected(self):
        with self.assertRaises(ValueError):
            Settings(right_pinch_finger='INDEX')
