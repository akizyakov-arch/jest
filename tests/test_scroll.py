import ctypes as ct
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace
import unittest

from gesture_control.activation import classify_pose
from gesture_control.command_engine import CommandEngine
from gesture_control.events import CommandEvent, CommandType
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.interaction import InteractionSession
from gesture_control.native_cursor import Input, WindowsCursorBackend
from gesture_control.profiles import load_profiles
from gesture_control.scroll import ScrollGesture
from gesture_control.settings import Settings
from test_interaction import pose_hand
from test_palm_navigation import Desktop
from test_pinch import pinched_hand


def two_fingers(dy=0):
    hand = pose_hand('POINT')
    points = list(hand.landmarks)
    points[9:13] = pose_hand('OPEN_PALM').landmarks[9:13]
    return replace(hand, landmarks=tuple((x, y+dy, z) for x, y, z in points))


class ScrollTests(unittest.TestCase):
    def test_repeated_strokes_accelerate_with_frequency_and_direction_reset(self):
        def run(interval):
            scroll = self.entered(scroll_reverse_confirm_ms=0)
            first = abs(scroll.update((.5, .7), 1.34))
            scroll.release(1.37)
            scroll.update((.5, .4), 1.37+interval)
            second = abs(scroll.update((.5, .6), 1.41+interval))
            gain = scroll.gain
            scroll.update((.5, .2), 1.45+interval)
            self.assertEqual(scroll.gain, 1.)
            return first, second, gain
        first, fast, gain = run(.1)
        _, slow, _ = run(.6)
        self.assertGreater(fast, first)
        self.assertGreater(fast, slow)
        self.assertGreater(gain, 1.)

    def test_burst_survives_cursor_return_but_not_pause_or_long_gap(self):
        scroll = self.entered()
        scroll.update((.5, .7), 1.34)
        scroll.reset(keep_burst=True)
        for i in range(5):
            scroll.update((.5, .3+i*.02), 1.5+i/30)
        self.assertGreater(scroll.gain, 1.)
        scroll.reset()
        self.assertEqual(scroll.gain, 1.)
        self.assertIsNone(scroll.burst_at)

    def entered(self, **changes):
        scroll = ScrollGesture(Settings(**changes))
        scroll.update((.5, .5), 1)
        scroll.update((.5, .5), 1.3)
        self.assertTrue(scroll.active)
        return scroll

    def test_pose(self):
        self.assertEqual(classify_pose(two_fingers(), 640, 480), 'TWO_FINGERS')

    def test_curled_ring_and_little_near_knuckles_do_not_mask_scroll(self):
        hand = two_fingers()
        points = list(hand.landmarks)
        for mcp in (13, 17):
            x, y, _ = points[mcp]
            points[mcp+3] = (x+.025, y-.095, -.05)
        self.assertEqual(classify_pose(replace(hand, landmarks=tuple(points)), 640, 480), 'TWO_FINGERS')

    def test_scroll_allows_naturally_bent_index_and_middle(self):
        hand = two_fingers()
        points = list(hand.landmarks)
        for mcp in (5, 9):
            x, y, _ = points[mcp]
            points[mcp+3] = (x+.06, y-.11, -.04)
        self.assertEqual(classify_pose(replace(hand, landmarks=tuple(points)), 640, 480), 'TWO_FINGERS')

    def test_moving_hand_can_confirm_scroll_without_stationary_hold(self):
        scroll = ScrollGesture(Settings())
        for i in range(12):
            scroll.update((.5, .3+i*.02), 1+i/30)
        self.assertTrue(scroll.active)

    def test_fast_stroke_starts_within_100ms_and_keeps_initial_motion(self):
        scroll = ScrollGesture(Settings(scroll_enter_ms=250))
        values = [scroll.update((.5, .3+i*.015), 1+i/30) for i in range(4)]
        self.assertTrue(scroll.active)
        self.assertEqual(values[:3], [0, 0, 0])
        self.assertLess(values[3], 0)
        self.assertLessEqual(abs(values[3]), 40)
        self.assertEqual(scroll.update((.5, .345), 1.14), 0)

    def test_small_jitter_does_not_trigger_fast_entry(self):
        scroll = ScrollGesture(Settings(scroll_enter_ms=250))
        for i in range(7):
            self.assertEqual(scroll.update((.5, .5+.005*(-1)**i), 1+i/30), 0)
        self.assertFalse(scroll.active)

    def test_flick_coasts_decays_and_finishes_without_unbounded_backlog(self):
        scroll = self.entered()
        scroll.update((.5, .7), 1.34)
        values = [scroll.release(1.34+i/30) for i in range(1, 40)]
        self.assertLess(values[0], 0)
        self.assertGreater(abs(values[0]), abs(values[5]))
        self.assertLess(abs(sum(values)), 300)
        self.assertFalse(scroll.active)
        self.assertEqual(values[-1], 0)

    def test_pose_gap_keeps_scroll_and_reentry_reanchors_without_jump(self):
        scroll = self.entered()
        self.assertEqual(scroll.release(1.34), 0)
        self.assertEqual(scroll.release(1.4), 0)
        self.assertTrue(scroll.active)
        self.assertEqual(scroll.update((.5, .8), 1.43), 0)
        self.assertEqual(scroll.update((.5, .8), 1.46), 0)

    def test_holding_two_fingers_still_brakes_flick(self):
        scroll = self.entered()
        scroll.update((.5, .7), 1.34)
        for i in range(1, 12):
            self.assertEqual(scroll.update((.5, .7), 1.34+i/30), 0)
        self.assertEqual(scroll.release(1.8), 0)

    def test_stationary_ten_seconds_and_dead_zone_emit_nothing(self):
        scroll = self.entered()
        self.assertTrue(all(scroll.update((.5, .5+.005*(-1)**i), 1.3+i/30) == 0
                            for i in range(1, 301)))

    def test_directions_inversion_rate_cap_and_no_backlog(self):
        for inverted in (False, True):
            scroll = self.entered(scroll_invert=inverted, scroll_reverse_confirm_ms=0)
            down = scroll.update((.5, .7), 1.34)
            self.assertEqual(down > 0, inverted)
            self.assertLessEqual(abs(down), 49)
            self.assertEqual(scroll.update((.5, .7), 1.38), 0)
            up = scroll.update((.5, .3), 1.42)
            self.assertEqual(up < 0, inverted)
            scroll.reset()
            self.assertEqual(scroll.remainder, 0)
            self.assertFalse(scroll.active)

    def test_fractional_units_accumulate_and_duplicate_frames_do_not_emit(self):
        scroll = self.entered(scroll_dead_zone=.001, scroll_sensitivity=120)
        outputs = [scroll.update((.5, .502+i*.001), 1.3+(i+1)/30) for i in range(30)]
        self.assertLess(sum(outputs), -2)
        self.assertEqual(scroll.update((.5, .9), scroll.time), 0)

    def test_short_return_stroke_is_ignored_but_deliberate_reverse_works(self):
        scroll = self.entered()
        self.assertLess(scroll.update((.5, .65), 1.34), 0)
        self.assertEqual(scroll.update((.5, .60), 1.38), 0)
        self.assertEqual(scroll.update((.5, .55), 1.42), 0)
        self.assertLess(scroll.update((.5, .70), 1.46), 0)
        values = [scroll.update((.5, .65-i*.04), 1.50+i*.04) for i in range(7)]
        self.assertEqual(values[:3], [0, 0, 0])
        self.assertTrue(any(value > 0 for value in values[3:]))
        self.assertEqual(scroll.gain, 1.)

    def test_native_signed_wheel_flag_and_expiry_without_real_input(self):
        received = []
        def send(count, ptr, size):
            mi = ct.cast(ptr, ct.POINTER(Input)).contents.data.mi
            received.append((mi.dwFlags, ct.c_int32(mi.mouseData).value))
            return 1
        backend = WindowsCursorBackend.__new__(WindowsCursorBackend)
        backend.user32 = SimpleNamespace(SendInput=send)
        for units in (-120, 120):
            backend.send(CommandEvent(CommandType.SCROLL, 1, 'wheel', monotonic()+1, wheel_units=units))
        self.assertEqual(received, [(0x800, -120), (0x800, 120)])
        with self.assertRaises(OSError):
            backend.send(CommandEvent(CommandType.SCROLL, 1, 'old', monotonic()-1, wheel_units=120))
        self.assertEqual(len(received), 2)

    def test_invalid_settings_and_wheel_units_are_rejected(self):
        for changes in ({'scroll_enter_ms': 0}, {'scroll_invert': 1},
                        {'scroll_sensitivity': float('nan')}, {'scroll_dead_zone': 0}):
            with self.assertRaises(ValueError):
                Settings(**changes)
        for units in (0, True, 1.5, 1201):
            with self.assertRaises(ValueError):
                CommandEngine._validate(CommandEvent(CommandType.SCROLL, 1, 'bad', 100, wheel_units=units))


class ScrollInteractionTests(unittest.TestCase):
    def test_two_fingers_with_thumb_contact_never_select_text(self):
        hand = two_fingers()
        points = list(hand.landmarks)
        points[4] = points[8]
        hand = replace(hand, landmarks=tuple(points))
        self.feed(hand, 12)
        for i in range(1, 10):
            self.feed(replace(hand, landmarks=tuple((x,y+i*.008,z) for x,y,z in hand.landmarks)))
        self.assertTrue(any(c.type == CommandType.SCROLL for c in self.backend.commands))
        self.assertFalse(any(c.type == CommandType.POINTER_DOWN for c in self.backend.commands))

    def test_scroll_transition_cannot_rearm_click_on_brief_finger_separation(self):
        self.feed(two_fingers(), 12)
        self.feed(pose_hand('POINT'), 15)
        self.feed(pinched_hand(), 12)
        self.assertFalse(any(c.type == CommandType.POINTER_DOWN for c in self.backend.commands))
        self.feed(pose_hand('OPEN_PALM'), 20)
        self.feed(pinched_hand(), 12)
        self.assertTrue(any(c.type == CommandType.POINTER_DOWN for c in self.backend.commands))

    def test_quick_two_fingertip_swipe_scrolls_without_wrist_motion(self):
        hand = two_fingers()
        for i in range(3):
            points = list(hand.landmarks)
            for tip in (8, 12):
                x,y,z = points[tip]
                points[tip] = (x,y+.035*i,z)
            self.feed(replace(hand, landmarks=tuple(points)))
        wheels = [c for c in self.backend.commands if c.type == CommandType.SCROLL]
        self.assertTrue(wheels)
        self.assertLess(wheels[0].wheel_units, 0)
        self.assertFalse(any(c.type == CommandType.POINTER_DOWN for c in self.backend.commands))

    def test_lowering_fingers_keeps_palm_navigation_after_scroll(self):
        from test_palm_navigation import shifted
        self.feed(two_fingers(), 12)
        self.feed(two_fingers(.04))
        self.feed(pose_hand('UNKNOWN'), 5)
        self.assertFalse(self.session.scroll.active)
        self.assertEqual(self.session.action, 'POINTER')
        origin = self.backend.position
        for i in range(1, 15):
            self.feed(shifted(pose_hand('UNKNOWN'), i*.003))
        self.assertNotEqual(self.backend.position, origin)
        self.feed(None)
        self.assertFalse(self.session._after_scroll)

    def setUp(self):
        self.now = 1.
        self.backend = Desktop()
        self.session = InteractionSession(Settings(two_finger_action='SCROLL'), load_profiles(), clock=lambda: self.now,
                                          cursor_backend=self.backend)
        self.session.hotkey_ready = True
        self.feed(pose_hand('OPEN_PALM'), 35)
        self.backend.commands.clear()

    def feed(self, hand, count=1):
        for _ in range(count):
            self.now += 1/30
            self.session.process(TrackingSnapshot(round(self.now*1000), self.now, self.now,
                () if hand is None else (hand,)), self.now, 640, 480)

    def test_confirm_scroll_both_directions_without_cursor_or_click(self):
        self.feed(two_fingers(), 5)
        self.assertFalse(self.backend.commands)
        self.feed(two_fingers(), 6)
        self.assertEqual(self.session.action, 'SCROLL')
        for i in range(1, 16):
            self.feed(two_fingers(i*.003))
        for i in range(15, -16, -1):
            self.feed(two_fingers(i*.003))
        self.assertTrue(self.backend.commands)
        self.assertTrue(all(c.type == CommandType.SCROLL for c in self.backend.commands))
        self.assertTrue(any(c.wheel_units > 0 for c in self.backend.commands))
        self.assertTrue(any(c.wheel_units < 0 for c in self.backend.commands))

    def test_exit_into_pinch_cannot_create_click_and_loss_clears_mode(self):
        self.feed(two_fingers(), 12)
        self.feed(pinched_hand())
        self.assertFalse(self.backend.commands)
        self.feed(pinched_hand(), 14)
        self.assertTrue(all(c.type == CommandType.POINTER_MOVE for c in self.backend.commands))
        self.feed(two_fingers(), 12)
        self.feed(None, 10)
        self.assertFalse(self.session.scroll.active)
        self.assertEqual(self.session.scroll.remainder, 0)

    def test_held_pinch_keeps_priority_over_scroll_candidate(self):
        self.feed(pinched_hand(), 5)
        self.assertTrue(self.session.machine.commands.buttons)
        self.feed(two_fingers(), 2)
        self.assertFalse(self.session.scroll.active)
        self.assertFalse(any(c.type == CommandType.SCROLL for c in self.backend.commands))

    def test_thumb_between_click_and_release_threshold_does_not_block_scroll(self):
        hand = two_fingers()
        points = list(hand.landmarks)
        x, y, _ = points[8]
        points[4] = (x, y+.09, 0)  # Ratio ~.32: separated, not a pinch.
        hand = replace(hand, landmarks=tuple(points))
        self.feed(hand, 12)
        self.assertEqual(self.session.action, 'SCROLL')
        for i in range(1, 10):
            self.feed(replace(hand, landmarks=tuple((x,y+i*.008,z) for x,y,z in hand.landmarks)))
        self.assertTrue(any(c.type == CommandType.SCROLL for c in self.backend.commands))
        self.assertFalse(any(c.type == CommandType.POINTER_DOWN for c in self.backend.commands))

    def test_brief_pose_loss_does_not_move_cursor_or_click(self):
        self.feed(two_fingers(), 12)
        self.feed(two_fingers(.03))
        self.backend.commands.clear()
        self.feed(pose_hand('OPEN_PALM'), 3)
        self.assertTrue(self.session.scroll.active)
        self.assertTrue(all(c.type == CommandType.SCROLL for c in self.backend.commands))
        self.feed(two_fingers(.08))
        self.assertEqual(self.session.action, 'SCROLL')
        self.assertTrue(all(c.type == CommandType.SCROLL for c in self.backend.commands))

    def test_return_to_palm_brakes_inertia_and_moves_within_four_frames(self):
        self.feed(two_fingers(), 12)
        self.feed(two_fingers(.05))
        self.feed(pose_hand('OPEN_PALM'), 4)
        self.assertFalse(self.session.scroll.active)
        self.assertEqual(self.session.action, 'POINTER')
        self.backend.commands.clear()
        self.feed(pose_hand('OPEN_PALM'), 12)
        self.assertFalse(any(c.type == CommandType.SCROLL for c in self.backend.commands))

    def test_inertia_cancels_on_missing_hand_and_manual_pause(self):
        for pause in (False, True):
            self.session.scroll.reset()
            self.feed(two_fingers(), 12)
            self.feed(two_fingers(.03))
            self.feed(pose_hand('OPEN_PALM'))
            self.assertTrue(self.session.scroll.active)
            count = len(self.backend.commands)
            if pause:
                self.session.emergency_stop()
            else:
                self.feed(None)
            self.assertFalse(self.session.scroll.active)
            self.assertEqual(self.session.scroll.velocity, 0)
            self.session.tick(self.now+.03)
            self.assertEqual(len(self.backend.commands), count)

    def test_twenty_entries_exits_produce_no_scroll_or_click_at_rest(self):
        for _ in range(20):
            self.feed(two_fingers(), 12)
            self.feed(pose_hand('POINT'))
        self.assertFalse(self.backend.commands)
