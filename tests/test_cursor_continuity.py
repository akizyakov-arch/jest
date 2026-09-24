from dataclasses import replace
import unittest
from unittest.mock import patch

from gesture_control.events import CommandType
from gesture_control.cursor import CursorMotion
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.interaction import InteractionSession
from gesture_control.pinch_aim import PinchAim
from gesture_control.profiles import load_profiles
from gesture_control.settings import Settings
from test_interaction import pose_hand
from test_palm_navigation import Desktop, shifted
from test_right_pinch import right_hand
from gesture_control.smoothing import OneEuroFilter


class CursorContinuityTests(unittest.TestCase):
    def test_slow_index_closure_locks_without_a_jerk(self):
        now = 1.
        backend = Desktop()
        session = InteractionSession(Settings(), load_profiles(), clock=lambda: now, cursor_backend=backend)
        session.hotkey_ready = True
        def feed(hand):
            nonlocal now
            now += 1/30
            session.process(TrackingSnapshot(round(now*1000), now, now, (hand,)), now, 640, 480)
        try:
            for _ in range(80):
                feed(pose_hand('OPEN_PALM'))
            locked_position = None
            for i in range(1, 23):
                points = list(pose_hand('OPEN_PALM').landmarks)
                x, y, z = points[8]
                points[8] = (x-.001*i, y+.002*i, z)
                feed(replace(pose_hand('OPEN_PALM'), landmarks=tuple(points)))
                if i >= 7:
                    self.assertEqual(session.action, 'AIM_LOCK')
                    if locked_position is None:
                        locked_position = backend.position
                    self.assertEqual(backend.position, locked_position)
            self.assertFalse(session.machine.commands.buttons)
        finally:
            session.close()

    def test_folding_index_on_open_palm_locks_before_downward_drift(self):
        now = 1.
        backend = Desktop()
        session = InteractionSession(Settings(), load_profiles(), clock=lambda: now, cursor_backend=backend)
        session.hotkey_ready = True
        def feed(hand):
            nonlocal now
            now += 1/30
            session.process(TrackingSnapshot(round(now*1000), now, now, (hand,)), now, 640, 480)
        for _ in range(100):
            feed(pose_hand('OPEN_PALM'))
        origin = backend.position
        for i in range(1, 7):
            hand = pose_hand('OPEN_PALM')
            points = list(hand.landmarks)
            x, y, z = points[8]
            points[8] = (x-.005*i, y+.01*i, z)
            feed(replace(hand, landmarks=tuple(points)))
            self.assertEqual(session.action, 'AIM_LOCK')
            self.assertEqual(backend.position, origin)
        self.assertFalse(session.machine.commands.buttons)
    def test_relaxed_near_fingers_release_aim_when_closure_stops(self):
        aim = PinchAim()
        aim.update(1.1, 0, True, False)
        self.assertTrue(aim.update(.65, .03, True, False))
        self.assertTrue(aim.update(.64, .1, True, False))
        self.assertFalse(aim.update(.65, .20, True, False))
        for i in range(30):
            self.assertFalse(aim.update(.65+.004*(-1)**i, .23+i/30, True, False))

    def test_open_palm_thumb_motion_does_not_start_far_aim_lock(self):
        now = 1.
        session = InteractionSession(Settings(), load_profiles(), clock=lambda: now)
        session.hotkey_ready = True
        for i in range(40):
            now += 1/30
            session.process(TrackingSnapshot(i, now, now, (pose_hand('OPEN_PALM'),)), now, 640, 480)
        for i in range(6):
            # Thumb moves inward, but remains well away from the index fingertip.
            points = list(pose_hand('OPEN_PALM').landmarks)
            points[4] = (.22+i*.02, .62-i*.018, 0)
            now += 1/30
            hand = replace(pose_hand('OPEN_PALM'), landmarks=tuple(points))
            session.process(TrackingSnapshot(100+i, now, now, (hand,)), now, 640, 480)
            self.assertEqual(session.pose, 'OPEN_PALM')
            self.assertEqual(session.action, 'POINTER')

    def test_short_unknown_pose_keeps_navigation_but_cannot_extend_itself(self):
        now = 1.
        session = InteractionSession(Settings(), load_profiles(), clock=lambda: now)
        session.hotkey_ready = True
        hand = pose_hand('OPEN_PALM')
        for i in range(40):
            now += 1/30
            session.process(TrackingSnapshot(i, now, now, (hand,)), now, 640, 480)
        with patch('gesture_control.interaction.classify_pose', return_value='UNKNOWN'):
            for i in range(8):
                now += 1/30
                session.process(TrackingSnapshot(100+i, now, now, (hand,)), now, 640, 480)
                if i < 2:
                    self.assertEqual(session.action, 'POINTER')
                if i > 3:
                    self.assertEqual(session.action, '-')
        now += 1/30
        session.process(TrackingSnapshot(200, now, now, ()), now, 640, 480)
        self.assertEqual(session.action, '-')

    def test_adaptive_filter_reduces_rest_jitter_and_step_lag(self):
        def measure(cutoff, beta):
            f = OneEuroFilter(cutoff, beta)
            values = [f.update(.5+.003*(-1)**i, i/30) for i in range(120)]
            jitter = max(values[60:])-min(values[60:])
            step = [f.update(.7, i/30) for i in range(120, 150)]
            frames = next(i for i, value in enumerate(step) if value >= .68)
            return jitter, frames
        old = measure(1.5, .4)
        settings = Settings()
        new = measure(settings.smoothing_min_cutoff, settings.smoothing_beta)
        self.assertLess(new[0], old[0])
        self.assertLess(new[1], old[1])

    def test_small_target_change_is_approached_smoothly_without_overshoot(self):
        motion = CursorMotion(1.5, 60)
        motion.step((.5, .5), 1, (.5, .5))
        first = motion.step((.51, .5), 1+1/30)
        self.assertGreater(first[0], .5)
        self.assertLess(first[0], .506)
        previous = first[0]
        for i in range(2, 40):
            value = motion.step((.51, .5), 1+i/30)[0]
            self.assertGreaterEqual(value, previous)
            self.assertLessEqual(value, .51)
            previous = value
        self.assertEqual(previous, .51)

    def test_open_relaxed_navigation_pose_can_activate_control(self):
        now = 1.
        session = InteractionSession(Settings(), load_profiles(), clock=lambda: now)
        session.hotkey_ready = True
        points = list(right_hand().landmarks)
        points[12] = (.65, .48, 0)
        hand = replace(right_hand(), landmarks=tuple(points))
        for i in range(60):
            now += 1/30
            session.process(TrackingSnapshot(i, now, now, (hand,)), now, 640, 480)
        self.assertEqual(session.pose, 'RELAXED_PALM')
        self.assertEqual(session.view().state, 'ACTIVE')

    def test_release_does_not_restart_aim_at_static_half_open_distance(self):
        aim = PinchAim()
        aim.update(.1, 1, False, True)
        aim.released(1.1)
        self.assertFalse(aim.update(.55, 1.3, True, False))

    def test_alternating_distance_noise_does_not_freeze_navigation(self):
        aim = PinchAim()
        results = [aim.update(1.1 + .04*(-1)**i, i/30, True, False) for i in range(90)]
        self.assertFalse(any(results))

    def test_navigation_returns_with_middle_still_bent_after_right_up(self):
        now = 1.
        backend = Desktop()
        session = InteractionSession(Settings(), load_profiles(), clock=lambda: now, cursor_backend=backend)
        session.hotkey_ready = True
        def feed(hand, count):
            nonlocal now
            for _ in range(count):
                now += 1/30
                session.process(TrackingSnapshot(round(now*1000), now, now, (hand,)), now, 640, 480)
        feed(pose_hand('OPEN_PALM'), 40)
        feed(right_hand(), 6)
        points = list(right_hand().landmarks)
        points[12] = (.65, .48, 0)  # Released, but not the rigid OPEN_PALM pose.
        relaxed = replace(right_hand(), landmarks=tuple(points))
        feed(relaxed, 6)
        self.assertFalse(session.machine.commands.buttons)
        before = len(backend.commands)
        feed(shifted(relaxed, .04), 10)
        moves = [c for c in backend.commands[before:] if c.type == CommandType.POINTER_MOVE]
        self.assertTrue(moves)
        self.assertEqual(session.view().state, 'ACTIVE')
