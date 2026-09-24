import unittest

from gesture_control.double_click import DoubleClick
from gesture_control.events import CommandType
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.interaction import InteractionSession
from gesture_control.profiles import load_profiles
from gesture_control.settings import Settings
from test_interaction import pose_hand
from test_pinch import pinched_hand
from test_palm_navigation import Desktop, shifted


class DoubleClickTests(unittest.TestCase):
    def test_sustained_small_departure_breaks_wait_without_a_large_jump(self):
        click = self.first()
        self.assertTrue(click.hold(1.13, (.502, .5)))
        self.assertTrue(click.hold(1.16, (.504, .5)))
        self.assertFalse(click.hold(1.19, (.508, .5)))
        self.assertIsNone(click.pending)

    def test_small_opening_jitter_keeps_double_click_target(self):
        click = self.first()
        for i, dx in enumerate((.001, -.001, .002, -.002, .001)):
            self.assertTrue(click.hold(1.12+i*.03, (.5+dx, .5)))

    def first(self, limit=500):
        click = DoubleClick()
        click.down(1, (500, 300), (limit, 4, 4))
        self.assertFalse(click.up(1.1, (.5, .5), False))
        return click

    def test_time_measured_between_presses_and_rectangle_half_width(self):
        for time, point, expected in ((1.45, (501, 301), True), (1.501, (500, 300), False),
                                      (1.2, (502, 300), False), (1.2, (500, 303), False)):
            with self.subTest(time=time, point=point):
                click = self.first()
                click.down(time, point, (500, 4, 4))
                self.assertEqual(click.up(time+.1, (.5, .5), False), expected)

    def test_stabilization_expires_or_breaks_on_intentional_motion(self):
        click = self.first()
        self.assertTrue(click.hold(1.2, (.501, .5)))
        self.assertFalse(click.hold(1.41, (.501, .5)))
        click = self.first()
        self.assertFalse(click.hold(1.2, (.54, .5)))
        self.assertIsNone(click.pending)

    def test_short_system_interval_caps_stabilization(self):
        self.assertFalse(self.first(150).hold(1.16, (.5, .5)))

    def test_drag_and_reset_remove_candidate(self):
        click = self.first()
        click.down(1.2, (500, 300), (500, 4, 4))
        self.assertFalse(click.up(1.3, (.5, .5), True))
        self.assertIsNone(click.pending)
        click = self.first()
        click.reset()
        self.assertFalse(click.hold(1.2, (.5, .5)))

    def test_settings_validation(self):
        for changes in ({'double_click_stabilize_ms': -1}, {'double_click_stabilize_ms': True},
                        {'double_click_escape_distance': float('nan')}):
            with self.assertRaises(ValueError):
                Settings(**changes)
        Settings(double_click_stabilize_ms=0)


class DoublePinchTests(unittest.TestCase):
    def setUp(self):
        self.now = 1.
        self.backend = Desktop()
        self.backend.double_click_limits = lambda: (500, 4, 4)
        self.session = InteractionSession(Settings(), load_profiles(), clock=lambda: self.now,
                                          cursor_backend=self.backend)
        self.session.hotkey_ready = True
        self.feed(pose_hand('OPEN_PALM'), 35)
        self.feed(pose_hand('POINT'), 20)
        self.actions = []

    def feed(self, hand, count):
        for i in range(count):
            self.now += 1/30
            self.session.process(TrackingSnapshot(round(self.now*1000), self.now, self.now,
                                 (hand,) if hand else ()), self.now, 640, 480)
            if hasattr(self, 'actions'):
                self.actions.append(self.session.action)

    def test_two_pinches_send_only_two_pairs_at_same_point(self):
        self.feed(pinched_hand(), 4)
        point = self.backend.position
        self.feed(pose_hand('POINT'), 4)
        self.feed(shifted(pose_hand('POINT'), .001), 2)
        self.assertEqual(self.backend.position, point)
        self.feed(pinched_hand(), 4)
        self.feed(pose_hand('POINT'), 4)
        self.assertIn('DOUBLE_CLICK', self.actions)
        events = [c.type for c in self.backend.commands if c.type != CommandType.POINTER_MOVE]
        self.assertEqual(events, [CommandType.POINTER_DOWN, CommandType.POINTER_UP]*2)
        self.assertFalse(self.session.machine.commands.buttons)

    def test_loss_clears_wait_and_does_not_generate_second_click(self):
        self.feed(pinched_hand(), 4)
        self.feed(pose_hand('POINT'), 4)
        self.assertIsNotNone(self.session.double_click.pending)
        self.feed(None, 10)
        self.assertIsNone(self.session.double_click.pending)
        self.assertNotIn('DOUBLE_CLICK', self.actions)

    def test_system_short_interval_does_not_label_slow_pair_double(self):
        self.backend.double_click_limits = lambda: (100, 4, 4)
        for _ in range(2):
            self.feed(pinched_hand(), 4)
            self.feed(pose_hand('POINT'), 4)
        self.assertNotIn('DOUBLE_CLICK', self.actions)
