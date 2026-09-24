from dataclasses import replace
import unittest

from gesture_control.activation import classify_pose
from gesture_control.events import CommandType
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.interaction import InteractionSession
from gesture_control.profiles import load_profiles
from gesture_control.settings import Settings
from test_interaction import pose_hand
from test_palm_navigation import Desktop, shifted


def relaxed_hand(bend=.0):
    hand = pose_hand('OPEN_PALM')
    points = list(hand.landmarks)
    for mcp in (5, 9, 13, 17):
        x, y, _ = points[mcp]
        points[mcp+2] = (x+.025, y-.14, -.02)
        points[mcp+3] = (x+.06, y-.11+bend, -.04)
    return replace(hand, landmarks=tuple(points))


class RelaxedPalmTests(unittest.TestCase):
    def test_bent_fingers_and_mirrored_hand_are_navigation(self):
        for bend in (-.01, 0, .02):
            hand = relaxed_hand(bend)
            for mirrored in (False, True):
                candidate = replace(hand, landmarks=tuple(
                    (1-x if mirrored else x, y, z) for x, y, z in hand.landmarks))
                self.assertEqual(classify_pose(candidate, 640, 480), 'RELAXED_PALM')

    def test_partially_straight_relaxed_hand_is_not_scroll_or_keyboard(self):
        for straight_count in (2, 3):
            points = list(relaxed_hand().landmarks)
            straight = pose_hand('OPEN_PALM').landmarks
            for mcp in (5, 9, 13)[:straight_count]:
                points[mcp:mcp+4] = straight[mcp:mcp+4]
            self.assertEqual(classify_pose(replace(relaxed_hand(), landmarks=tuple(points)), 640, 480),
                             'RELAXED_PALM')

    def test_folded_hand_remains_unknown(self):
        self.assertEqual(classify_pose(pose_hand('UNKNOWN'), 640, 480), 'UNKNOWN')

    def test_sustained_relaxed_navigation_moves_without_clicks(self):
        now = 1.
        backend = Desktop()
        session = InteractionSession(Settings(), load_profiles(), clock=lambda: now, cursor_backend=backend)
        session.hotkey_ready = True
        def feed(hand):
            nonlocal now
            now += 1/30
            session.process(TrackingSnapshot(round(now*1000), now, now, (hand,)), now, 640, 480)
        try:
            for _ in range(40):
                feed(pose_hand('OPEN_PALM'))
            for _ in range(20):
                feed(relaxed_hand())
            origin = backend.position
            for i in range(60):
                feed(shifted(relaxed_hand(.003*(-1)**i), .001*i))
                self.assertEqual(session.action, 'POINTER')
                self.assertEqual(session.view().state, 'ACTIVE')
            self.assertNotEqual(backend.position, origin)
            self.assertFalse(any(command.type == CommandType.POINTER_DOWN for command in backend.commands))
            self.assertFalse(session.take_keyboard_request())
        finally:
            session.close()
