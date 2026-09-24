import unittest
from threading import Event
from time import monotonic
from types import SimpleNamespace

from gesture_control.camera import CameraFrame
from gesture_control.hand_tracking import MediaPipeHandTracker, TrackingSnapshot
from gesture_control.tracking_runtime import LatestValue, TrackingRuntime
from gesture_control.settings import Settings


class MailboxTests(unittest.TestCase):
    def test_slow_consumer_only_receives_latest_frame(self):
        box = LatestValue()
        for value in range(100):
            box.publish(value)
        version, value = box.read(timeout=0)
        self.assertEqual((version, value), (100, 99))
        self.assertEqual(box.read(version, timeout=0), (100, None))


class FakeCamera:
    def __init__(self, fail=False):
        self.closed = Event()
        self.tick = Event()
        self.count = 0
        self.fail = fail

    def start(self):
        pass

    def read(self):
        self.tick.wait(0.005)
        if self.fail:
            raise RuntimeError("camera disconnected")
        self.count += 1
        return CameraFrame(self.count, monotonic(), 1, 1, b"\0\0\0")

    def close(self):
        self.closed.set()


class FakeTracker:
    def __init__(self, fail=False):
        self.closed = Event()
        self.fail = fail

    def process(self, frame):
        if self.fail:
            raise RuntimeError("inference failed")
        return TrackingSnapshot(frame.frame_id, frame.captured_at, monotonic(), ())

    def close(self):
        self.closed.set()


class RuntimeTests(unittest.TestCase):
    def test_no_hands_is_valid_and_closes_resources(self):
        camera, tracker = FakeCamera(), FakeTracker()
        runtime = TrackingRuntime(camera, tracker)
        try:
            runtime.start()
            _, result = runtime.results.read(timeout=2)
            self.assertIsNotNone(result)
            self.assertEqual(result.tracking.hands, ())
            self.assertEqual(result.frame.frame_id, result.tracking.frame_id)
        finally:
            runtime.close()
        self.assertTrue(camera.closed.is_set())
        self.assertTrue(tracker.closed.is_set())

    def test_camera_and_inference_failures_are_reported_and_closed(self):
        for camera_fail, tracker_fail in ((True, False), (False, True)):
            with self.subTest(camera=camera_fail):
                camera, tracker = FakeCamera(camera_fail), FakeTracker(tracker_fail)
                runtime = TrackingRuntime(camera, tracker)
                try:
                    runtime.start()
                    _, error = runtime.errors.read(timeout=2)
                    self.assertIsInstance(error, RuntimeError)
                finally:
                    runtime.close()
                self.assertTrue(camera.closed.is_set())
                self.assertTrue(tracker.closed.is_set())

    def test_invalid_camera_settings_are_rejected(self):
        for values in ({"camera_fps": 0}, {"max_hands": 3},
                       {"camera_start_timeout_ms": 0}, {"camera_frame_timeout_ms": True},
                       {"tracking_confidence": float("nan")}, {"preview_mirrored": 1}):
            with self.subTest(values=values), self.assertRaises(ValueError):
                Settings(**values)


class AdapterTests(unittest.TestCase):
    def test_timestamps_and_handedness_score_are_not_tracking_confidence(self):
        try:
            import numpy
        except ImportError:
            self.skipTest("CV environment not installed")
        tracker = MediaPipeHandTracker.__new__(MediaPipeHandTracker)
        tracker._last_timestamp_ms = -1
        tracker._mp = SimpleNamespace(Image=lambda **kwargs: kwargs,
                                      ImageFormat=SimpleNamespace(SRGB=1))
        timestamps = []
        points = [SimpleNamespace(x=0.2, y=0.4, z=0.0) for _ in range(21)]
        def detect(image, timestamp):
            timestamps.append(timestamp)
            return SimpleNamespace(hand_landmarks=[points], handedness=[[
                SimpleNamespace(category_name="Left", score=0.98)]])
        tracker._landmarker = SimpleNamespace(detect_for_video=detect)
        frame = CameraFrame(1, 1.0, 1, 1, b"\0\0\0")
        result = tracker.process(frame)
        tracker.process(frame)
        self.assertEqual(timestamps, [1000, 1001])
        self.assertIsNone(result.hands[0].tracking_confidence)
        self.assertEqual(result.hands[0].handedness_score, 0.98)
        self.assertEqual(len(result.hands[0].landmarks), 21)
