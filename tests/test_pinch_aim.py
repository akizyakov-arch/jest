from dataclasses import replace
import unittest

from gesture_control.events import CommandType
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.interaction import InteractionSession
from gesture_control.pinch_aim import PinchAim
from gesture_control.pointer import VirtualPointer, WorkArea
from gesture_control.preview_controls import Action, buttons, keyboard_action
from gesture_control.profiles import load_profiles
from gesture_control.settings import Settings
from test_interaction import pose_hand
from test_palm_navigation import Desktop


def closing_hand(amount):
    hand = pose_hand('POINT')
    points = list(hand.landmarks)
    for index in (4, 8):
        x, y, _ = points[index]
        points[index] = (x+(.43-x)*amount, y+(.45-y)*amount, 0)
    return replace(hand, landmarks=tuple(points))


class AimTests(unittest.TestCase):
    def test_gentle_continuing_closure_does_not_stall(self):
        aim = PinchAim(stall_ms=150)
        aim.update(1., 0, True, False)
        self.assertTrue(aim.update(.8, .03, True, False))
        for i in range(1, 8):
            self.assertTrue(aim.update(.8-i*.015, .03+i*.1, True, False))
        self.assertFalse(aim.update(.695, .9, True, False))

    def test_drag_release_has_no_settle_freeze(self):
        aim = PinchAim()
        aim.update(.1, 1, False, True)
        aim.released(2, dragged=True)
        self.assertFalse(aim.update(1.2, 2.01, True, False))

    def test_early_freeze_cancel_and_timeout(self):
        aim = PinchAim()
        self.assertFalse(aim.update(1.2, 0, True, False))
        self.assertTrue(aim.update(1., .03, True, False))
        self.assertTrue(aim.update(.8, .1, True, False))
        self.assertFalse(aim.update(1.2, .15, True, False))
        self.assertTrue(aim.update(.6, .2, True, False))
        self.assertFalse(aim.update(.6, 1.2, True, False))
        self.assertFalse(aim.update(.6, 1.3, True, False))
        self.assertFalse(aim.update(1.2, 1.4, True, False))
        self.assertTrue(aim.update(.6, 1.5, True, False))

    def test_hold_has_no_timeout_and_release_has_short_settle(self):
        aim = PinchAim()
        self.assertTrue(aim.update(.1, 10, False, True))
        self.assertTrue(aim.update(.1, 20, False, True))
        aim.released(20)
        self.assertTrue(aim.update(1.2, 20.05, True, False))
        self.assertFalse(aim.update(1.2, 20.2, True, False))

    def test_inactive_or_reset_cannot_latch_aim(self):
        aim = PinchAim()
        self.assertFalse(aim.update(.1, 0, False, False))
        aim.update(.1, .1, True, False)
        aim.reset()
        self.assertFalse(aim.update(1.2, 1, True, False))


class AimInteractionTests(unittest.TestCase):
    def setUp(self):
        self.time = 1.
        self.backend = Desktop()
        self.session = InteractionSession(Settings(), load_profiles(), clock=lambda: self.time,
                                          cursor_backend=self.backend)
        self.session.hotkey_ready = True
        self.feed(pose_hand('OPEN_PALM'), 30)
        self.feed(pose_hand('POINT'), 60)

    def feed(self, hand, count=1):
        for _ in range(count):
            self.time += 1/30
            self.session.process(TrackingSnapshot(round(self.time*1000), self.time, self.time,
                                 () if hand is None else (hand,)), self.time, 640, 480)

    def test_slow_closure_clicks_exact_hover_position_and_opens_without_drift(self):
        hover = self.backend.position
        before = len(self.backend.commands)
        for amount in (.1, .2, .3, .4, .5, .6, .7, .8, .9, 1.):
            self.feed(closing_hand(amount), 2)
            self.assertEqual(self.backend.position, hover)
        self.feed(closing_hand(1), 4)
        self.feed(pose_hand('POINT'), 4)
        commands = self.backend.commands[before:]
        self.assertEqual([c.type for c in commands], [CommandType.POINTER_DOWN, CommandType.POINTER_UP])
        self.assertEqual(self.backend.position, hover)

    def test_cancelled_pinch_sends_no_click_and_navigation_returns(self):
        before = len(self.backend.commands)
        self.feed(closing_hand(.2), 2)
        self.assertEqual(self.session.action, 'AIM_LOCK')
        self.feed(pose_hand('POINT'), 15)
        self.assertFalse(any(c.type != CommandType.POINTER_MOVE for c in self.backend.commands[before:]))
        self.assertEqual(self.session.action, 'POINTER')

    def test_gradual_closure_freezes_before_drifting_off_a_small_target(self):
        hover = self.backend.position
        locked_position = None
        for i in range(1, 31):
            self.feed(closing_hand(i/30))
            if self.session.action == 'AIM_LOCK' and locked_position is None:
                locked_position = self.backend.position
            if locked_position is not None:
                self.assertEqual(self.backend.position, locked_position)
        self.assertIsNotNone(locked_position)
        self.assertLess(abs(locked_position[0]-hover[0])*1920, 4)
        self.assertLess(abs(locked_position[1]-hover[1])*1080, 4)

    def test_loss_during_aim_cannot_click_on_return(self):
        self.feed(closing_hand(.4), 2)
        before = len(self.backend.commands)
        self.feed(None, 15)
        self.feed(closing_hand(1), 15)
        self.assertEqual(len(self.backend.commands), before)
        self.assertEqual(self.session.view().state, 'PAUSED')


class FullAreaTests(unittest.TestCase):
    def test_off_center_area_can_reach_exact_full_frame(self):
        pointer = VirtualPointer(Settings(work_area_left=.05, work_area_right=.45,
                                          work_area_top=.1, work_area_bottom=.7))
        pointer.resize_area(1.)
        self.assertEqual(pointer.area, WorkArea(0, 0, 1, 1))
        pointer.resize_area(-.05)
        self.assertAlmostEqual(pointer.area.right-pointer.area.left, .95)
        self.assertAlmostEqual(pointer.area.left, .025)

    def test_full_area_has_button_and_key(self):
        self.assertEqual(keyboard_action(ord('b')), Action('full_area'))
        self.assertTrue(any(b.action == Action('full_area') for b in buttons(1040, 480)))
