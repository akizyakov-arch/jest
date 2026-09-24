import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread

from gesture_control.activation import HoldGate, classify_pose
from gesture_control.hand_tracking import TrackedHand, TrackingSnapshot
from gesture_control.hotkeys import parse_hotkey
from gesture_control.interaction import InteractionSession
from gesture_control.profiles import load_profile, load_profiles
from gesture_control.settings import Settings


def pose_hand(pose):
    points = [(0.5, 0.7, 0.0)] * 21
    points[0] = (0.5, 0.85, 0)
    points[4] = (0.22, 0.62, 0)
    counts = {"OPEN_PALM": 4, "POINT": 1, "THREE_FINGERS": 3, "UNKNOWN": 0}
    for index, (mcp, x, y) in enumerate(((5, .42, .6), (9, .5, .57), (13, .58, .61), (17, .65, .65))):
        points[mcp] = (x, y, 0)
        points[mcp+1] = (x, y-.1, 0)
        points[mcp+2] = (x, y-.2, 0)
        points[mcp+3] = (x, y-.3 if index < counts[pose] else y+.03, 0)
    return TrackedHand("sample", "Right", tuple(points), handedness_score=.99)


class PoseTests(unittest.TestCase):
    def test_four_poses_are_distinct(self):
        for pose in ("OPEN_PALM", "POINT", "THREE_FINGERS", "UNKNOWN"):
            with self.subTest(pose=pose):
                self.assertEqual(classify_pose(pose_hand(pose), 640, 480), pose)

    def test_hold_is_one_shot_and_requires_sustained_exit(self):
        gate = HoldGate(800, 250, .35)
        events = [gate.update(True, i/30, (.5, .5)).fired for i in range(150)]
        self.assertEqual(sum(events), 1)
        gate.update(False, 5, (.5, .5))
        self.assertFalse(gate.update(True, 5.1, (.5, .5)).fired)
        for i in range(10):
            gate.update(False, 5.2+i/30, (.5, .5))
        self.assertTrue(gate.armed)

    def test_fast_motion_cannot_confirm_palm_hold(self):
        gate = HoldGate(800, 250, .35)
        events = [gate.update(True, i/30, (i/30, .5)).fired for i in range(60)]
        self.assertFalse(any(events))


class InteractionTests(unittest.TestCase):
    def setUp(self):
        self.time = 1.0
        self.session = InteractionSession(Settings(pointer_mode='INDEX'), load_profiles(), clock=lambda: self.time)
        self.session.hotkey_ready = True

    def feed(self, pose, count=1):
        for _ in range(count):
            self.time += 1/30
            hands = () if pose is None else (pose_hand(pose),)
            tracking = TrackingSnapshot(round(self.time*1000), self.time, self.time, hands)
            self.session.process(tracking, self.time, 640, 480)

    def activate(self):
        self.feed("OPEN_PALM", 30)
        self.assertEqual(self.session.view().state, "ACTIVE")

    def test_appearance_does_not_activate(self):
        self.feed("POINT", 30)
        self.assertEqual(self.session.view().state, "STANDBY")
        self.assertIsNone(self.session.display_pointer().position)

    def test_palm_toggles_once_until_exit_and_rearm(self):
        self.activate()
        self.feed("OPEN_PALM", 60)
        self.assertEqual(self.session.view().state, "ACTIVE")
        self.feed("POINT", 15)
        self.feed("OPEN_PALM", 30)
        self.assertEqual(self.session.view().state, "STANDBY")

    def test_pointer_moves_only_when_active_and_pointing(self):
        self.activate()
        self.assertIsNone(self.session.display_pointer().position)
        self.feed("POINT", 2)
        self.assertIsNotNone(self.session.display_pointer().position)
        position = self.session.display_pointer().position
        self.session.emergency_stop()
        self.feed("POINT", 10)
        self.assertEqual(self.session.display_pointer().position, position)

    def test_emergency_independent_callback_and_manual_resume(self):
        self.activate()
        thread = Thread(target=self.session.emergency_stop)
        thread.start()
        thread.join(timeout=1)
        self.assertFalse(thread.is_alive())
        self.feed("OPEN_PALM", 40)
        self.assertEqual(self.session.view().state, "PAUSED")
        self.assertTrue(self.session.resume())
        self.assertEqual(self.session.view().state, "STANDBY")

    def test_missing_hotkey_prevents_activation(self):
        self.session.hotkey_ready = False
        self.feed("OPEN_PALM", 60)
        self.assertEqual(self.session.view().state, "OFF")

    def test_lost_hand_requires_palm_then_resumes(self):
        self.activate()
        self.feed(None, 15)
        self.feed("POINT", 30)
        self.assertEqual(self.session.view().state, "PAUSED")
        self.feed("OPEN_PALM", 30)
        self.assertEqual(self.session.view().state, "ACTIVE")

    def test_loss_before_activation_can_be_recovered_with_resume(self):
        self.feed("POINT")
        self.feed(None, 15)
        self.assertEqual(self.session.view().state, "PAUSED")
        self.assertTrue(self.session.resume())
        self.assertEqual(self.session.view().state, "STANDBY")

    def test_three_finger_hold_does_not_request_keyboard(self):
        self.activate()
        self.feed("THREE_FINGERS", 35)
        self.assertFalse(self.session.take_keyboard_request())
        self.feed("THREE_FINGERS", 40)
        self.assertFalse(self.session.take_keyboard_request())
        self.feed("POINT", 15)
        self.feed("THREE_FINGERS", 35)
        self.session.emergency_stop()
        self.assertFalse(self.session.take_keyboard_request())

    def test_camera_and_profile_changes_pause_control(self):
        self.activate()
        self.session.cycle_profile()
        self.assertEqual(self.session.view().state, "PAUSED")
        self.assertEqual(self.session.profile.id, "creative-3d")
        self.session.camera_changed()
        self.assertFalse(self.session.resume())
        self.feed("POINT")
        self.assertTrue(self.session.resume())

    def test_bad_timestamp_does_not_start_camera_session(self):
        tracking = TrackingSnapshot(1, float("nan"), 1, (pose_hand("OPEN_PALM"),))
        self.session.process(tracking, 1, 640, 480)
        self.assertEqual(self.session.view().state, "OFF")


class ProfileTests(unittest.TestCase):
    def test_meanings_change_but_system_gestures_do_not(self):
        desktop, three_d, video = load_profiles()
        self.assertEqual(desktop.resolve("DRAG"), "DRAG")
        self.assertEqual(three_d.resolve("DRAG"), "TRANSLATE")
        self.assertEqual(video.resolve("DRAG"), "SCRUB")
        for profile in (desktop, three_d, video):
            self.assertEqual(profile.resolve("PALM_HOLD"), "CONTROL_TOGGLE")
            self.assertEqual(profile.resolve("THREE_FINGER_HOLD"), "SHOW_KEYBOARD")

    def test_profile_cannot_override_activation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"custom.json"
            data = {"schema_version": 1, "id": "custom", "name": "Custom", "template": True,
                    "applications": [], "bindings": {"PALM_HOLD": "SELECT"}}
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_profile(path)

    def test_invalid_hotkeys_rejected(self):
        self.assertEqual(parse_hotkey("ctrl+alt+g"), (0x4003, ord("G")))
        for text in ("g", "ctrl+ctrl+g", "ctrl+", "ctrl+unknown", "bad+g"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                parse_hotkey(text)
