from dataclasses import replace
import unittest

from gesture_control.activation import StablePalmHold
from gesture_control.cursor import Screen
from gesture_control.events import CommandEvent, CommandType
from gesture_control.hand_tracking import TrackingSnapshot
from gesture_control.input_guard import InputLease
from gesture_control.interaction import InteractionSession
from gesture_control.pointer import VirtualPointer
from gesture_control.profiles import load_profiles
from gesture_control.settings import Settings
from gesture_control.windows_input import FakeInputBackend
from test_interaction import pose_hand


class Desktop(FakeInputBackend):
    def __init__(self):
        super().__init__()
        self.position = (.5, .5)
        self.anchors = 0

    def anchor(self):
        self.anchors += 1
        return Screen(1920, 1080), self.position

    def send(self, command):
        super().send(command)
        if command.type == CommandType.POINTER_MOVE:
            self.position = Screen(1920, 1080).normalized(command.position)


def shifted(hand, dx):
    return replace(hand, landmarks=tuple((x+dx, y, z) for x, y, z in hand.landmarks))


class PalmNavigationTests(unittest.TestCase):
    def test_relaxed_open_hand_activates_and_recovers_without_pinching(self):
        from test_relaxed_palm import relaxed_hand
        def relaxed(count):
            for _ in range(count):
                self.time += 1/30
                self.session.process(TrackingSnapshot(round(self.time*1000), self.time, self.time,
                    (relaxed_hand(),)), self.time, 640, 480)
        relaxed(12)
        self.assertEqual(self.session.view().state, 'ACTIVE')
        self.feed(None, 12)
        relaxed(7)
        self.assertEqual(self.session.view().state, 'ACTIVE')
        self.assertFalse(any(c.type == CommandType.POINTER_DOWN for c in self.backend.commands))

    def test_two_fingers_fist_and_pinched_open_hand_cannot_activate(self):
        from test_scroll import two_fingers
        from test_fist import fist_hand
        from gesture_control.activation import open_hand_for_activation
        for hand in (two_fingers(), fist_hand(), pose_hand('POINT'), pose_hand('THREE_FINGERS')):
            self.assertFalse(open_hand_for_activation(hand, 640, 480, .4))
        hand = pose_hand('OPEN_PALM')
        points = list(hand.landmarks)
        points[4] = points[8]
        self.assertFalse(open_hand_for_activation(replace(hand, landmarks=tuple(points)), 640, 480, .4))

    def test_quick_open_hand_recovery_requires_unpinched_thumb_and_index(self):
        self.feed(count=35)
        self.feed(None, 12)
        hand = pose_hand('OPEN_PALM')
        points = list(hand.landmarks)
        points[4] = points[8]
        for _ in range(12):
            self.time += 1/30
            self.session.process(TrackingSnapshot(round(self.time*1000), self.time, self.time,
                (replace(hand, landmarks=tuple(points)),)), self.time, 640, 480)
        self.assertEqual(self.session.view().state, 'PAUSED')
        self.feed(count=7)
        self.assertEqual(self.session.view().state, 'ACTIVE')
        self.assertFalse(any(c.type == CommandType.POINTER_DOWN for c in self.backend.commands))

    def test_default_palm_anchor_ignores_fingers_through_click(self):
        from test_pinch import pinched_hand
        from gesture_control.pointer import palm_geometry
        self.assertEqual(self.session.settings.pointer_anchor, 'PALM')
        self.feed(count=120)
        origin = self.backend.position
        center = palm_geometry(pose_hand('OPEN_PALM'))[0]
        self.assertEqual(self.session.pointer.snapshot.raw_position,
                         self.session.pointer.area.map(center, True))
        for hand, count in ((pinched_hand(), 12), (pose_hand('OPEN_PALM'), 25)):
            for _ in range(count):
                self.time += 1/30
                self.session.process(TrackingSnapshot(round(self.time*1000), self.time, self.time, (hand,)),
                                     self.time, 640, 480)
                self.assertAlmostEqual(self.backend.position[0], origin[0], places=5)
                self.assertAlmostEqual(self.backend.position[1], origin[1], places=5)
        self.assertEqual([c.type for c in self.backend.commands if c.type in
                          (CommandType.POINTER_DOWN, CommandType.POINTER_UP)],
                         [CommandType.POINTER_DOWN, CommandType.POINTER_UP])

    def setUp(self):
        self.time = 1.
        self.backend = Desktop()
        self.session = InteractionSession(Settings(), load_profiles(), clock=lambda: self.time,
                                          cursor_backend=self.backend)
        self.session.hotkey_ready = True

    def feed(self, pose='OPEN_PALM', count=1, dx=0):
        for _ in range(count):
            self.time += 1/30
            hands = () if pose is None else (shifted(pose_hand(pose), dx),)
            self.session.process(TrackingSnapshot(round(self.time*1000), self.time, self.time, hands),
                                 self.time, 640, 480)

    def test_palm_activates_and_navigates_without_toggling_off(self):
        self.feed(count=30)
        self.assertEqual(self.session.view().state, 'ACTIVE')
        self.assertTrue(self.backend.commands)
        initial = self.backend.position
        self.feed(count=60, dx=.05)
        self.assertLess(self.backend.position[0], initial[0])
        self.feed('POINT', 10)
        self.feed(count=90)
        self.assertEqual(self.session.view().state, 'ACTIVE')

    def test_repeated_recovery_with_noise_and_short_classification_gaps(self):
        self.feed(count=30)
        for cycle in range(5):
            self.feed(None, 15)
            self.assertTrue(self.session.recover_tracking)
            count = len(self.backend.commands)
            for i in range(3):
                self.feed('OPEN_PALM' if i % 7 else 'UNKNOWN', dx=.008*(-1)**i)
            self.assertEqual(len(self.backend.commands), count)
            self.assertEqual(self.session.view().state, 'PAUSED')
            for i in range(30):
                self.feed('OPEN_PALM' if i % 7 else 'UNKNOWN', dx=.008*(-1)**i)
            self.assertEqual(self.session.view().state, 'ACTIVE', f'cycle={cycle}')
            self.feed(count=35)
            self.assertEqual(self.session.view().state, 'ACTIVE')

    def test_emergency_stays_manual_even_after_tracking_loss(self):
        self.feed(count=30)
        self.session.emergency_stop()
        count = len(self.backend.commands)
        self.feed(None, 30)
        self.feed(count=90)
        self.assertEqual(self.session.view().state, 'PAUSED')
        self.assertFalse(self.session.recover_tracking)
        self.assertEqual(len(self.backend.commands), count)
        self.assertTrue(self.session.resume())
        self.feed(count=30)
        self.assertEqual(self.session.view().state, 'ACTIVE')

    def test_one_bad_pose_frame_freezes_without_reanchoring(self):
        self.feed(count=35)
        anchors, count = self.backend.anchors, len(self.backend.commands)
        self.feed('UNKNOWN')
        self.assertEqual(len(self.backend.commands), count)
        self.feed()
        self.assertEqual(self.backend.anchors, anchors)

    def test_finger_motion_does_not_move_palm_pointer(self):
        pointer = VirtualPointer(Settings(pointer_anchor='PALM'))
        hand = pose_hand('OPEN_PALM')
        before = pointer.process(TrackingSnapshot(1, 1, 1, (hand,)), 1).position
        points = list(hand.landmarks)
        for i in (4, 8, 12, 16, 20):
            points[i] = (.1, .1, 0)
        after = pointer.process(TrackingSnapshot(2, 1.03, 1.03,
                                (replace(hand, landmarks=tuple(points)),)), 1.03).position
        self.assertEqual(after, before)

    def test_index_tip_navigation_remains_available(self):
        settings = Settings(pointer_anchor='INDEX')
        self.assertEqual(settings.pointer_mode, 'PALM')
        pointer = VirtualPointer(settings)
        hand = pose_hand('OPEN_PALM')
        result = pointer.process(TrackingSnapshot(1, 1, 1, (hand,)), 1)
        self.assertEqual(result.raw_position, pointer.area.map(hand.landmarks[8][:2], True))
        points = list(hand.landmarks)
        points[8] = (.7, .1, 0)
        result = pointer.process(TrackingSnapshot(2, 1.03, 1.03,
                                 (replace(hand, landmarks=tuple(points)),)), 1.03)
        self.assertEqual(result.raw_position, pointer.area.map((.7, .1), True))

    def test_leaving_work_area_does_not_pause_input_session(self):
        self.session.pointer = VirtualPointer(Settings(pointer_anchor='INDEX'))
        self.feed(count=30)
        hand = pose_hand('OPEN_PALM')
        points = list(hand.landmarks)
        points[8] = (.95, .05, 0)
        self.time += 1/30
        self.session.process(TrackingSnapshot(1, self.time, self.time,
                             (replace(hand, landmarks=tuple(points)),)), self.time, 640, 480)
        self.assertEqual(self.session.pointer.snapshot.raw_position, (0., 0.))
        self.assertEqual(self.session.view().state, 'ACTIVE')
        count = len(self.backend.commands)
        self.feed(count=30)
        self.assertEqual(self.session.view().state, 'ACTIVE')
        self.assertGreater(len(self.backend.commands), count)

    def test_stationary_palm_noise_is_attenuated_at_system_cursor(self):
        self.feed(count=90)
        reference = self.backend.position[0]
        energy = 0.
        for i in range(90):
            self.feed(dx=.005*(-1)**i)
            energy += (self.backend.position[0]-reference)**2
        raw_energy = 90*(.005/.6)**2
        self.assertLess(energy, raw_energy*.2)

    def test_recovery_tolerates_single_missing_detection(self):
        self.feed(count=30)
        self.feed(None, 15)
        for i in range(60):
            self.feed(None if i % 13 == 0 else 'OPEN_PALM')
        self.assertEqual(self.session.view().state, 'ACTIVE')

    def test_tracking_loss_after_watchdog_deadline_stays_gesture_recoverable(self):
        lease = InputLease(self.backend, clock=lambda: self.time)
        class GuardProxy:
            def begin_session(_, epoch):
                lease.request('arm', epoch)
            def end_session(_):
                lease.request('stop')
            def heartbeat(_):
                lease.request('pulse')
            def anchor(_):
                return lease.request('anchor')
            def send(_, command):
                return lease.request('send', command)
        self.session = InteractionSession(Settings(), load_profiles(), clock=lambda: self.time,
                                          cursor_backend=GuardProxy())
        self.session.hotkey_ready = True
        self.feed(count=30)
        self.time += .6
        self.session.tick(self.time)
        self.assertEqual(self.session.view().state, 'PAUSED')
        self.assertTrue(self.session.recover_tracking)
        self.feed(count=35)
        self.assertEqual(self.session.view().state, 'ACTIVE')
        self.assertTrue(lease.engine.enabled)

    def test_expired_move_drops_without_fault_or_release(self):
        backend = FakeInputBackend()
        lease = InputLease(backend, clock=lambda: 2)
        lease.request('arm', 7)
        command = CommandEvent(CommandType.POINTER_MOVE, 7, 'stale', 1.9, position=(1, 1))
        self.assertFalse(lease.request('send', command))
        self.assertTrue(lease.engine.enabled)
        self.assertFalse(lease.fault)
        self.assertEqual(backend.releases, [])
        self.assertTrue(lease.request('send', replace(command, expires_at=2.1)))

    def test_fast_sweep_or_missing_data_cannot_confirm_hold(self):
        gate = StablePalmHold(800)
        self.assertFalse(any(gate.update(True, i/30, (i/30, .5)).fired for i in range(90)))
        gate.reset()
        gate.update(True, 0, (.5, .5))
        self.assertFalse(gate.update(True, 2, (.5, .5)).fired)
        self.assertFalse(gate.update(False, 3, (.5, .5)).fired)
