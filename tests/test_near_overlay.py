import math
import unittest
from time import monotonic

from gesture_control.cursor_overlay import CENTER, CursorOverlay, rune_strokes
from gesture_control.events import CommandEvent, CommandType
from gesture_control.interaction import InteractionSession
from gesture_control.pointer import VirtualPointer
from gesture_control.preview_controls import Action, keyboard_action
from gesture_control.profiles import load_profiles
from gesture_control.settings import Settings
from test_palm_navigation import Desktop


class NearAreaTests(unittest.TestCase):
    def test_central_half_reaches_all_screen_edges_in_both_mirror_modes(self):
        pointer = VirtualPointer(Settings(work_area_left=0, work_area_top=0,
                                          work_area_right=1, work_area_bottom=1))
        pointer.near_area()
        for mirrored in (False, True):
            for x, expected_x in ((.25, 0.), (.75, 1.)):
                for y, expected_y in ((.25, 0.), (.75, 1.)):
                    point = (1-x if mirrored else x, y)
                    self.assertEqual(pointer.area.map(point, mirrored), (expected_x, expected_y))
        self.assertEqual(pointer.area.map((.5, .5), False), (.5, .5))
        pointer.resize_area(1)
        self.assertEqual(pointer.area.map((.25, .75), False), (.25, .75))

    def test_near_preset_releases_drag_before_changing_mapping(self):
        backend = Desktop()
        session = InteractionSession(Settings(), load_profiles(), cursor_backend=backend)
        session.machine.enable(camera_ready=True, hotkey_ready=True)
        session.machine.palm_confirmed()
        session.machine.submit(CommandEvent(CommandType.POINTER_DOWN,
                               session.machine.commands.session_id, 'drag', monotonic()+1,
                               button='left'))
        session.resize_area(0, near=True)
        self.assertEqual(session.view().state, 'PAUSED')
        self.assertEqual(backend.releases, [(frozenset({'left'}), frozenset())])
        self.assertEqual(session.pointer.area.left, .25)
        self.assertFalse(session.machine.commands.enabled)

    def test_shortcuts(self):
        self.assertEqual(keyboard_action(ord('N')), Action('near_area'))
        self.assertEqual(keyboard_action(ord('v')), Action('visual_fx'))


class OverlayGeometryTests(unittest.TestCase):
    def test_button_feedback_belongs_only_to_owning_rune(self):
        blue = CursorOverlay()
        red = CursorOverlay(external=True)
        for action in ('PINCH_HELD', 'DRAG', 'LEFT_CLICK', 'RIGHT_CLICK'):
            blue.update('ACTIVE', action)
            red.update('ACTIVE', action)
            self.assertEqual(blue.state[1], action)
            self.assertEqual(red.state[1], '-')
            blue.update('ACTIVE', 'SECONDARY_'+action)
            red.update('ACTIVE', 'SECONDARY_'+action)
            self.assertEqual(blue.state[1], '-')
            self.assertEqual(red.state[1], action)
        self.assertIsNotNone(red.click_event)

    def test_scroll_loss_keeps_rune_until_return_or_manual_pause(self):
        now = 1.
        overlay = CursorOverlay('FULL', 2000, clock=lambda: now)
        overlay.update('ACTIVE', 'SCROLL')
        now += .1
        overlay.update('ACTIVE', 'SCROLL_END')
        self.assertTrue(overlay.visible(now))
        now += .1
        overlay.update('PAUSED', '-', recovering=True)
        now += 10
        overlay.update('PAUSED', '-', recovering=True)
        self.assertTrue(overlay.visible(now))
        self.assertFalse(overlay.visible(now+.31))
        overlay.update('PAUSED', '-', recovering=False)
        self.assertFalse(overlay.visible(now))

    def test_loss_grace_does_not_extend_forever_or_survive_manual_pause(self):
        now = 1.
        overlay = CursorOverlay('FULL', 2000, clock=lambda: now)
        overlay.update('ACTIVE', 'POINTER')
        now = 1.1
        overlay.update('PAUSED', '-', recovering=True)
        self.assertTrue(overlay.visible(now))
        now = 2.9
        overlay.update('PAUSED', '-', recovering=True)
        self.assertTrue(overlay.visible(now))
        now = 3.2
        overlay.update('PAUSED', '-', recovering=True)
        self.assertFalse(overlay.visible(now))
        overlay.update('ACTIVE', 'POINTER')
        self.assertTrue(overlay.visible(now))
        overlay.update('PAUSED', '-', recovering=True)
        overlay.update('PAUSED', '-', recovering=False)
        self.assertFalse(overlay.visible(now))

    def test_off_stale_updates_and_initial_loss_do_not_show_overlay(self):
        now = 1.
        overlay = CursorOverlay('FULL', 2000, clock=lambda: now)
        overlay.update('PAUSED', '-', recovering=True)
        self.assertFalse(overlay.visible(now))
        overlay.update('ACTIVE', 'POINTER')
        self.assertFalse(overlay.visible(now+.31))
        overlay.mode = 'OFF'
        self.assertFalse(overlay.visible(now))
    def test_rotating_glyphs_leave_cursor_center_clear(self):
        for phase in (0, .3, 2, 5):
            strokes = rune_strokes(phase)
            self.assertEqual(len(strokes), 24)
            for stroke in strokes:
                for x, y in zip(stroke[::2], stroke[1::2]):
                    distance = math.hypot(x-CENTER, y-CENTER)
                    self.assertGreater(distance, 40)
                    self.assertLess(distance, 60)

    def test_effect_modes_cycle_without_touching_input(self):
        overlay = CursorOverlay('FULL')
        self.assertEqual([overlay.cycle() for _ in range(3)], ['MINIMAL', 'OFF', 'FULL'])
        overlay.update('PAUSED', '-')
        self.assertEqual(overlay.state, ('PAUSED', '-'))
        overlay.close()
