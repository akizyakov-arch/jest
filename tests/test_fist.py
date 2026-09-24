import ctypes as ct
from dataclasses import replace
from time import monotonic
from types import SimpleNamespace
import unittest

from gesture_control.activation import closed_fist
from gesture_control.events import CommandEvent, CommandType
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.interaction import InteractionSession
from gesture_control.native_cursor import Input, WindowsCursorBackend
from gesture_control.profiles import load_profiles
from gesture_control.settings import Settings
from test_interaction import pose_hand
from test_palm_navigation import Desktop
from test_pinch import pinched_hand
from test_scroll import two_fingers


def fist_hand():
    hand = pose_hand('UNKNOWN')
    points = list(hand.landmarks)
    for mcp in (5, 9, 13, 17):
        x, y, _ = points[mcp]
        points[mcp+2] = (x, y-.025, -.04)
        points[mcp+3] = (x, y+.03, -.02)
    return replace(hand, landmarks=tuple(points))


class FistTests(unittest.TestCase):
    def setUp(self):
        self.now = 1.
        self.backend = Desktop()
        self.session = InteractionSession(Settings(two_finger_action='SCROLL'), load_profiles(), clock=lambda:self.now,
                                          cursor_backend=self.backend)
        self.session.hotkey_ready = True

    def tearDown(self):
        self.session.close()

    def feed(self, hand, count=1):
        for _ in range(count):
            self.now += 1/30
            self.session.process(TrackingSnapshot(round(self.now*1000), self.now, self.now,
                () if hand is None else (hand,)), self.now, 640, 480)

    def keys(self):
        return [c for c in self.backend.commands if c.key]

    def test_fold_geometry_excludes_relaxed_hand(self):
        from test_relaxed_palm import relaxed_hand
        self.assertTrue(closed_fist(fist_hand(), 640, 480))
        self.assertFalse(closed_fist(relaxed_hand(), 640, 480))
        self.assertFalse(closed_fist(two_fingers(), 640, 480))

    def test_one_escape_requires_hold_and_open_rearm(self):
        self.feed(pose_hand('OPEN_PALM'), 35)
        self.feed(fist_hand(), 10)
        self.assertFalse(self.keys())
        self.feed(fist_hand(), 80)
        self.assertEqual([c.type for c in self.keys()], [CommandType.KEY_DOWN, CommandType.KEY_UP])
        self.assertFalse(self.session.machine.commands.keys)
        self.feed(pose_hand('OPEN_PALM'), 12)
        self.feed(fist_hand(), 25)
        self.assertEqual(len(self.keys()), 4)

    def test_standby_pause_and_tracking_loss_do_not_send_escape(self):
        self.feed(fist_hand(), 60)
        self.assertFalse(self.keys())
        self.feed(pose_hand('OPEN_PALM'), 35)
        self.feed(fist_hand(), 10)
        self.feed(None, 10)
        self.feed(fist_hand(), 40)
        self.assertFalse(self.keys())
        self.session.emergency_stop()
        self.feed(fist_hand(), 40)
        self.assertFalse(self.keys())

    def test_drag_and_scroll_exit_require_open_palm_before_escape(self):
        self.feed(pose_hand('OPEN_PALM'), 35)
        self.feed(pinched_hand(), 5)
        self.assertTrue(self.session.machine.commands.buttons)
        self.feed(fist_hand(), 45)
        self.assertFalse(self.keys())
        self.feed(pose_hand('OPEN_PALM'), 15)
        self.feed(two_fingers(), 15)
        self.feed(fist_hand(), 45)
        self.assertFalse(self.keys())

    def test_failed_key_up_releases_owned_escape_and_pauses(self):
        self.feed(pose_hand('OPEN_PALM'), 35)
        send = self.backend.send
        def fail_up(command):
            if command.type == CommandType.KEY_UP:
                raise OSError('simulated failure')
            return send(command)
        self.backend.send = fail_up
        with self.assertLogs(level='ERROR'):
            self.feed(fist_hand(), 25)
        self.assertEqual(self.session.view().state, 'PAUSED')
        self.assertTrue(any('ESC' in keys for _,keys in self.backend.releases))

    def test_native_escape_flags_and_cleanup_without_real_input(self):
        received = []
        def send(count, pointer, size):
            event = ct.cast(pointer, ct.POINTER(Input)).contents
            received.append((event.type, event.data.ki.wVk, event.data.ki.dwFlags))
            return 1
        backend = WindowsCursorBackend.__new__(WindowsCursorBackend)
        backend.user32 = SimpleNamespace(SendInput=send)
        for kind in (CommandType.KEY_DOWN, CommandType.KEY_UP):
            backend.send(CommandEvent(kind, 1, 'fist', monotonic()+1, key='ESC'))
        backend.release(frozenset(), frozenset({'ESC'}))
        self.assertEqual(received, [(1, 27, 0), (1, 27, 2), (1, 27, 2)])
