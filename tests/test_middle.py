import ctypes as ct
from time import monotonic
from types import SimpleNamespace
import unittest
from gesture_control.events import CommandType, CommandEvent
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.interaction import InteractionSession
from gesture_control.native_cursor import WindowsCursorBackend, Input
from gesture_control.profiles import load_profiles
from gesture_control.settings import Settings
from test_interaction import pose_hand
from test_palm_navigation import Desktop, shifted
from test_scroll import two_fingers
from test_pinch import pinched_hand


class MiddleTests(unittest.TestCase):
    def setUp(self):
        self.now = 1.
        self.backend = Desktop()
        self.session = InteractionSession(Settings(), load_profiles(), clock=lambda:self.now,
                                          cursor_backend=self.backend)
        self.session.hotkey_ready = True
        self.feed(pose_hand('OPEN_PALM'), 35)
        self.backend.commands.clear()

    def tearDown(self):
        self.session.close()

    def feed(self, hand, count=1):
        for _ in range(count):
            self.now += 1/30
            self.session.process(TrackingSnapshot(round(self.now*1000), self.now, self.now,
                () if hand is None else (hand,)), self.now, 640, 480)

    def buttons(self):
        return [(c.type,c.button) for c in self.backend.commands if c.button]

    def test_confirm_hold_and_release_one_middle_click_without_wheel(self):
        self.feed(two_fingers(), 2)
        self.assertFalse(self.buttons())
        self.feed(two_fingers(), 30)
        self.assertEqual(self.buttons(), [(CommandType.POINTER_DOWN,'middle'), (CommandType.POINTER_UP,'middle')])
        self.feed(pose_hand('OPEN_PALM'), 5)
        self.assertEqual(self.buttons(), [(CommandType.POINTER_DOWN,'middle'), (CommandType.POINTER_UP,'middle')])
        self.assertFalse(any(c.type == CommandType.SCROLL for c in self.backend.commands))
        self.assertFalse(self.session.machine.commands.buttons)

    def test_moving_two_fingers_does_not_drag_or_repeat_click(self):
        self.feed(two_fingers(), 8)
        origin = self.backend.position
        for i in range(1, 15):
            self.feed(shifted(two_fingers(), i*.004))
        self.assertEqual(self.session.action, 'PRIMARY_SCROLL')
        self.assertNotEqual(self.backend.position, origin)
        self.assertFalse(self.session.machine.commands.buttons)
        self.assertEqual(len(self.buttons()), 2)
        self.feed(pose_hand('OPEN_PALM'), 4)
        self.assertFalse(self.session.machine.commands.buttons)

    def test_loss_releases_middle_and_does_not_restart_capture(self):
        self.feed(two_fingers(), 8)
        self.feed(None)
        self.assertEqual(self.buttons()[-1], (CommandType.POINTER_UP,'middle'))
        self.feed(two_fingers(), 12)
        self.assertEqual(len(self.buttons()), 2)

    def test_manual_pause_has_no_middle_button_left_held(self):
        self.feed(two_fingers(), 8)
        self.session.emergency_stop()
        self.assertFalse(self.session.machine.commands.buttons)
        self.assertEqual(len(self.buttons()), 2)

    def test_next_middle_click_requires_pose_exit(self):
        self.feed(two_fingers(), 20)
        self.feed(pose_hand('OPEN_PALM'), 5)
        self.feed(two_fingers(), 20)
        self.assertEqual(len(self.buttons()), 2)
        self.assertFalse(self.session.primary_scroll_active)
        self.assertEqual([c.key for c in self.backend.commands if c.key],['ESC','ESC'])

    def test_key_up_failure_releases_middle(self):
        send = self.backend.send
        def fail_up(command):
            if command.type == CommandType.POINTER_UP:
                raise OSError('simulated release failure')
            return send(command)
        self.backend.send = fail_up
        with self.assertLogs(level='ERROR'):
            self.feed(two_fingers(), 12)
        self.assertEqual(self.session.view().state, 'PAUSED')
        self.assertIn((frozenset({'middle'}), frozenset()), self.backend.releases)

    def test_left_drag_retains_priority(self):
        self.feed(pinched_hand(), 5)
        self.feed(two_fingers(), 2)
        self.assertFalse(any(button == 'middle' for _,button in self.buttons()))

    def test_native_middle_flags_and_physical_button_check(self):
        sent=[]
        def send(count, ptr, size):
            sent.append(ct.cast(ptr, ct.POINTER(Input)).contents.data.mi.dwFlags)
            return 1
        backend = WindowsCursorBackend.__new__(WindowsCursorBackend)
        backend.user32 = SimpleNamespace(SendInput=send, GetAsyncKeyState=lambda key:0x8000 if key==4 else 0)
        down=CommandEvent(CommandType.POINTER_DOWN,1,'middle',monotonic()+1,button='middle')
        with self.assertRaises(OSError):
            backend.prepare(down)
        self.assertFalse(sent)
        backend.send(down)
        backend.send(CommandEvent(CommandType.POINTER_UP,1,'middle',monotonic()+1,button='middle'))
        backend.release(frozenset({'middle'}),frozenset())
        self.assertEqual(sent,[0x20,0x40,0x40])
