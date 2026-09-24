import ctypes as ct
import unittest
from contextlib import nullcontext
from math import hypot
from unittest.mock import Mock, patch

from gesture_control.cursor import CursorMotion, Screen
from gesture_control.events import CommandEvent, CommandType
from gesture_control.interaction import InteractionSession
from gesture_control.native_cursor import Input, WindowsCursorBackend
from gesture_control.profiles import load_profiles
from gesture_control.settings import Settings
from gesture_control.windows_input import FakeInputBackend
import test_interaction as interaction_tests


class CursorMappingTests(unittest.TestCase):
    def test_optional_jitter_filter_holds_noise_but_allows_slow_intent_and_edges(self):
        motion = CursorMotion(10, 0, jitter_radius_px=3)
        motion.step((.5,.5), 1, origin=(.5,.5), screen_size=(1001,1001))
        for i in range(20):
            self.assertEqual(motion.step((.5+(-1)**i*.002,.5), 1+(i+1)/30,
                                         screen_size=(1001,1001)), (.5,.5))
        for i in range(1,11):
            result = motion.step((.5+i*.001,.5), 2+i/30, screen_size=(1001,1001))
        self.assertGreater(result[0], .507)
        motion.reset()
        motion.step((.998,.5), 3, origin=(.998,.5), screen_size=(1001,1001))
        self.assertEqual(motion.step((1.,.5), 3.03, screen_size=(1001,1001)), (1.,.5))

    def test_jitter_disabled_preserves_small_movements_and_speed_ten_is_faster(self):
        motion = CursorMotion(10, 0)
        motion.step((.5,.5), 1, origin=(.5,.5))
        self.assertEqual(motion.step((.501,.5), 1.03), (.501,.5))
        outputs = []
        for speed in (4,10):
            motion = CursorMotion(speed, 0)
            motion.step((1.,.5), 1, origin=(0.,.5))
            outputs.append(motion.step((1.,.5), 1.03)[0])
        self.assertGreater(outputs[1], outputs[0]*2)

    def test_full_area_maps_to_display_edges(self):
        for size in ((1920, 1080), (3840, 2160), (1080, 1920)):
            screen = Screen(*size)
            self.assertEqual(screen.pixels((0, 0)), (0, 0))
            self.assertEqual(screen.pixels((1, 1)), (size[0]-1, size[1]-1))
            for point in ((0, 0), (123, 321), (size[0]-1, size[1]-1)):
                absolute = screen.absolute(point)
                self.assertEqual(tuple(int(v*s/65536) for v, s in zip(absolute, size)), point)

    def test_invalid_and_outside_coordinates(self):
        screen = Screen(1920, 1080)
        with self.assertRaises(ValueError):
            screen.pixels((float('nan'), 0))
        with self.assertRaises(ValueError):
            screen.absolute((-1, 0))
        self.assertEqual(screen.pixels((-1, 2)), (0, 1079))

    def test_acquisition_and_stall_have_no_jump(self):
        motion = CursorMotion(1.5)
        self.assertIsNone(motion.step((1, 1), 1, (0, 0)))
        point = motion.step((1, 1), 1+1/30)
        self.assertAlmostEqual(hypot(*point), .05)
        previous = point
        point = motion.step((1, 1), 10)
        self.assertAlmostEqual(hypot(point[0]-previous[0], point[1]-previous[1]), .075)
        for i in range(100):
            point = motion.step((1, 1), 10+(i+1)/30)
        self.assertEqual(point, (1, 1))
        motion.reset()
        self.assertIsNone(motion.step((0, 0), 20, (.8, .2)))
        self.assertEqual(motion.position, (.8, .2))

    def test_speed_setting_validation(self):
        for speed in (0, -1, float('nan'), True, 11):
            with self.assertRaises(ValueError):
                Settings(cursor_max_speed=speed)


class DesktopFake(FakeInputBackend):
    def __init__(self):
        super().__init__()
        self.origin = (.1, .9)
        self.fail = False

    def anchor(self):
        return Screen(1920, 1080), self.origin

    def send(self, command):
        if self.fail:
            raise OSError('simulated input failure')
        super().send(command)


class CursorInteractionTests(interaction_tests.InteractionTests):
    def setUp(self):
        self.time = 1.0
        self.backend = DesktopFake()
        self.session = InteractionSession(Settings(pointer_mode='INDEX'), load_profiles(), clock=lambda: self.time,
                                          cursor_backend=self.backend)
        self.session.hotkey_ready = True

    def test_no_input_before_activation_or_on_first_point(self):
        self.feed('POINT', 30)
        self.assertEqual(self.backend.commands, [])
        self.activate()
        self.feed('POINT')
        self.assertEqual(self.backend.commands, [])
        self.feed('POINT')
        self.assertEqual(len(self.backend.commands), 1)
        command = self.backend.commands[0]
        self.assertEqual(command.type, CommandType.POINTER_MOVE)
        self.assertTrue(Screen(1920, 1080).contains(command.position))

    def test_stop_blocks_input_and_resume_reanchors(self):
        self.activate()
        self.feed('POINT', 5)
        count = len(self.backend.commands)
        self.session.emergency_stop()
        self.feed('POINT', 10)
        self.assertEqual(len(self.backend.commands), count)
        self.assertTrue(self.session.resume())
        self.activate()
        self.backend.origin = (.9, .8)
        self.feed('POINT')
        self.assertEqual(len(self.backend.commands), count)
        self.assertEqual(self.session.display_pointer().position, (.9, .8))

    def test_hand_loss_and_resize_pause(self):
        self.activate()
        self.feed('POINT', 5)
        count = len(self.backend.commands)
        self.feed(None, 15)
        self.feed('POINT', 15)
        self.assertEqual(len(self.backend.commands), count)
        self.assertEqual(self.session.view().state, 'PAUSED')
        self.session.resume()
        self.activate()
        self.session.resize_area(-.05)
        self.feed('POINT', 10)
        self.assertEqual(len(self.backend.commands), count)
        self.assertEqual(self.session.view().state, 'PAUSED')

    def test_backend_failure_latches_pause(self):
        self.activate()
        self.backend.fail = True
        with self.assertLogs(level='ERROR'):
            self.feed('POINT', 2)
        self.assertEqual(self.session.view().state, 'PAUSED')
        self.backend.fail = False
        self.feed('POINT', 10)
        self.assertEqual(self.backend.commands, [])

    def test_lost_hotkey_prevents_next_move(self):
        self.activate()
        self.feed('POINT', 3)
        count = len(self.backend.commands)
        self.session.hotkey_ready = False
        self.feed('POINT', 3)
        self.assertEqual(self.session.view().state, 'PAUSED')
        self.assertEqual(len(self.backend.commands), count)

    def test_stale_frame_cannot_move_cursor(self):
        self.activate()
        self.feed('POINT', 3)
        count = len(self.backend.commands)
        from gesture_control.hand_tracking import TrackingSnapshot
        stale = TrackingSnapshot(999, self.time, self.time,
                                 (interaction_tests.pose_hand('POINT'),))
        self.time += 1
        self.session.process(stale, self.time, 640, 480)
        self.assertEqual(len(self.backend.commands), count)
        self.assertEqual(self.session.view().state, 'PAUSED')

    def test_nonpoint_pose_reanchors_without_move(self):
        self.activate()
        self.feed('POINT', 3)
        count = len(self.backend.commands)
        self.feed('UNKNOWN', 3)
        self.backend.origin = (.2, .3)
        self.feed('POINT')
        self.assertEqual(len(self.backend.commands), count)
        self.assertEqual(self.session.display_pointer().position, (.2, .3))


class NativeCursorTests(unittest.TestCase):
    def test_positioned_buttons_include_red_coordinates_in_every_packet(self):
        backend=self.backend()
        packets=[]
        def capture(count,pointer,size):
            mouse=ct.cast(pointer,ct.POINTER(Input)).contents.data.mi
            packets.append((mouse.dx,mouse.dy,mouse.dwFlags))
            return 1
        backend.user32.SendInput.side_effect=capture
        with patch('gesture_control.native_cursor.monotonic',return_value=1):
            for button,down,up in (('left',2,4),('right',8,16),('middle',32,64)):
                for kind,flag in ((CommandType.POINTER_DOWN,down),(CommandType.POINTER_UP,up)):
                    backend.send(CommandEvent(kind,1,'red',2,position=(1400,320),button=button))
                    self.assertEqual(packets[-1],(*backend.screen.absolute((1400,320)),0x8001|flag))

    def test_positioned_click_rejects_outside_screen_and_expiry(self):
        backend=self.backend()
        with patch('gesture_control.native_cursor.monotonic',return_value=1):
            with self.assertRaises(ValueError):
                backend.send(CommandEvent(CommandType.POINTER_DOWN,1,'red',2,position=(-1,50),button='left'))
            with self.assertRaises(OSError):
                backend.send(CommandEvent(CommandType.POINTER_DOWN,1,'red',.5,position=(50,50),button='left'))
        backend.user32.SendInput.assert_not_called()

    def backend(self):
        backend = WindowsCursorBackend.__new__(WindowsCursorBackend)
        backend.user32 = Mock()
        backend.user32.SendInput.return_value = 1
        backend.physical_coordinates = nullcontext
        backend.screen = Screen(1920, 1080)
        backend._screen = Mock(return_value=backend.screen)
        return backend

    def command(self, expiry=2):
        return CommandEvent(CommandType.POINTER_MOVE, 1, 'test', expiry, position=(1919, 1079))

    def test_native_layout_and_move_flags(self):
        self.assertEqual(ct.sizeof(Input), 40 if ct.sizeof(ct.c_void_p) == 8 else 28)
        backend = self.backend()
        def capture(count, pointer, size):
            event = ct.cast(pointer, ct.POINTER(Input)).contents
            self.assertEqual(event.type, 0)
            self.assertEqual(event.data.mi.dwFlags, 0x8001)
            self.assertEqual((event.data.mi.dx, event.data.mi.dy), backend.screen.absolute((1919, 1079)))
            return 1
        backend.user32.SendInput.side_effect = capture
        with patch('gesture_control.native_cursor.monotonic', return_value=1):
            backend.send(self.command())
        backend.user32.SendInput.assert_called_once()

    def test_stale_or_changed_display_never_injected(self):
        backend = self.backend()
        with patch('gesture_control.native_cursor.monotonic', return_value=3):
            self.assertFalse(backend.send(self.command()))
        backend.user32.SendInput.assert_not_called()
        backend._screen.return_value = Screen(1280, 720)
        with self.assertRaises(OSError):
            backend.send(self.command())
        backend.user32.SendInput.assert_not_called()

    def test_rejected_input_is_reported(self):
        backend = self.backend()
        backend.user32.SendInput.return_value = 0
        with patch('gesture_control.native_cursor.monotonic', return_value=1), self.assertRaises(OSError):
            backend.send(self.command())

    def test_unimplemented_button_not_sent(self):
        backend = self.backend()
        with self.assertRaises(ValueError):
            backend.send(CommandEvent(CommandType.POINTER_DOWN, 1, 'test', 2, button='unsupported'))
        backend.user32.SendInput.assert_not_called()

    def test_physical_button_is_not_released_when_acquisition_rejected(self):
        from gesture_control.command_engine import CommandEngine
        backend = self.backend()
        backend.user32.GetAsyncKeyState.return_value = 0x8000
        engine = CommandEngine(backend, clock=lambda: 1)
        session = engine.activate()
        with self.assertRaises(OSError):
            engine.submit(CommandEvent(CommandType.POINTER_DOWN, session, 'test', 2, button='left'))
        engine.stop()
        self.assertFalse(engine.buttons)
        backend.user32.SendInput.assert_not_called()

    def test_native_button_pair_and_owned_release_flags(self):
        backend = self.backend()
        flags = []
        def capture(count, pointer, size):
            flags.append(ct.cast(pointer, ct.POINTER(Input)).contents.data.mi.dwFlags)
            return 1
        backend.user32.SendInput.side_effect = capture
        with patch('gesture_control.native_cursor.monotonic', return_value=1):
            backend.send(CommandEvent(CommandType.POINTER_DOWN, 1, 'test', 2, button='left'))
            backend.send(CommandEvent(CommandType.POINTER_UP, 1, 'test', 2, button='left'))
        backend.release(frozenset({'left'}), frozenset())
        self.assertEqual(flags, [0x0002, 0x0004, 0x0004])

    def test_native_right_pair_and_cleanup_only_owned_buttons(self):
        backend = self.backend()
        flags = []
        def capture(count, pointer, size):
            flags.append(ct.cast(pointer, ct.POINTER(Input)).contents.data.mi.dwFlags)
            return 1
        backend.user32.SendInput.side_effect = capture
        with patch('gesture_control.native_cursor.monotonic', return_value=1):
            backend.send(CommandEvent(CommandType.POINTER_DOWN, 1, 'right', 2, button='right'))
            backend.send(CommandEvent(CommandType.POINTER_UP, 1, 'right', 2, button='right'))
        backend.release(frozenset({'right'}), frozenset())
        backend.release(frozenset({'left', 'right'}), frozenset())
        self.assertEqual(flags, [0x0008, 0x0010, 0x0010, 0x0014])

    def test_right_physical_button_preflight_prevents_acquisition(self):
        from gesture_control.command_engine import CommandEngine
        backend = self.backend()
        backend.user32.GetAsyncKeyState.return_value = 0x8000
        engine = CommandEngine(backend, clock=lambda: 1)
        session = engine.activate()
        with self.assertRaises(OSError):
            engine.submit(CommandEvent(CommandType.POINTER_DOWN, session, 'test', 2, button='right'))
        engine.stop()
        backend.user32.GetAsyncKeyState.assert_called_once_with(2)
        backend.user32.SendInput.assert_not_called()
