import unittest
from threading import Event
from time import monotonic
from pathlib import Path
from unittest.mock import Mock, patch

from gesture_control.control_loop import ControlLoop
from gesture_control.events import CommandEvent, CommandType
from gesture_control.input_guard import InputLease
from gesture_control.tracking_runtime import TrackingRuntime
from gesture_control.windows_input import FakeInputBackend
from gesture_control.preview import run_preview
from gesture_control.settings import Settings
from gesture_control.interaction import InteractionSession
from gesture_control.profiles import load_profiles
from test_tracking import FakeCamera, FakeTracker


class ControlLoopTests(unittest.TestCase):
    def test_preview_keeps_processing_while_window_event_pump_is_blocked(self):
        import cv2
        import numpy as np

        camera, tracker = FakeCamera(), FakeTracker()
        session = InteractionSession(Settings(), load_profiles())
        session.process = Mock(wraps=session.process)
        key_wait_counts = []

        def wait_key(delay):
            before = session.process.call_count
            Event().wait(.6)
            key_wait_counts.append(session.process.call_count-before)
            return ord('q')

        hotkey = Mock(registered=True)
        hotkey.start.return_value = True
        with patch('gesture_control.preview.OpenCVCamera', return_value=camera), \
             patch('gesture_control.preview.MediaPipeHandTracker', return_value=tracker), \
             patch('gesture_control.preview.InteractionSession', return_value=session), \
             patch('gesture_control.preview.EmergencyHotkey', return_value=hotkey), \
             patch('gesture_control.preview.render_preview', return_value=np.zeros((480, 1040, 3), np.uint8)), \
             patch.multiple(cv2, namedWindow=Mock(), resizeWindow=Mock(), setMouseCallback=Mock(),
                            imshow=Mock(), destroyAllWindows=Mock(),
                            waitKeyEx=wait_key, getWindowProperty=Mock(return_value=1)):
            self.assertEqual(run_preview(Settings(), Path('unused.task')), 0)
        self.assertGreater(key_wait_counts[0], 5)
        self.assertTrue(camera.closed.is_set())
        self.assertTrue(tracker.closed.is_set())
        self.assertEqual(session.view().state, 'OFF')

    def test_headless_frame_limit_stops_all_workers(self):
        camera, tracker = FakeCamera(), FakeTracker()
        with patch('gesture_control.preview.OpenCVCamera', return_value=camera), \
             patch('gesture_control.preview.MediaPipeHandTracker', return_value=tracker):
            self.assertEqual(run_preview(Settings(), Path('unused.task'), headless=True, max_frames=5), 0)
        self.assertTrue(camera.closed.is_set())
        self.assertTrue(tracker.closed.is_set())

    def test_blocked_ui_does_not_expire_active_input_lease(self):
        backend = FakeInputBackend()
        lease = InputLease(backend)
        ready = Event()
        updates = []

        def update():
            if not ready.is_set():
                lease.request('arm', 1)
                lease.request('send', CommandEvent(CommandType.POINTER_DOWN, 1,
                              'press', monotonic()+1, button='right'))
                ready.set()
            lease.request('pulse')
            updates.append(monotonic())

        worker = ControlLoop(update, lease.stop)
        worker.start()
        try:
            self.assertTrue(ready.wait(2))
            # Model a native UI/menu stall longer than the 400 ms input lease.
            Event().wait(.6)
            with worker.lock:
                lease.check()
                self.assertFalse(lease.fault)
                self.assertGreater(len(updates), 10)
                self.assertEqual(backend.releases, [])
                lease.stop()
                self.assertEqual(len(backend.releases), 1)
                worker.stopped.set()
        finally:
            worker.close()
            lease.stop()

    def test_worker_failure_releases_input_and_reports_error(self):
        backend = FakeInputBackend()
        lease = InputLease(backend)
        lease.request('arm', 1)
        lease.request('send', CommandEvent(CommandType.POINTER_DOWN, 1,
                      'press', monotonic()+1, button='right'))

        def fail():
            raise RuntimeError('tracking failed')

        worker = ControlLoop(fail, lease.stop)
        worker.start()
        self.assertTrue(worker.stopped.wait(2))
        worker.close()
        self.assertIsInstance(worker.error, RuntimeError)
        self.assertEqual(len(backend.releases), 1)

    def test_model_startup_does_not_block_capture_or_caller(self):
        constructing, release = Event(), Event()
        camera, tracker = FakeCamera(), FakeTracker()

        def factory():
            constructing.set()
            if not release.wait(2):
                raise RuntimeError('test factory timed out')
            return tracker

        runtime = TrackingRuntime(camera, tracker_factory=factory)
        try:
            runtime.start()
            self.assertTrue(constructing.wait(1))
            _, frame = runtime.frames.read(timeout=1)
            self.assertIsNotNone(frame)
            release.set()
            _, result = runtime.results.read(timeout=1)
            self.assertIsNotNone(result)
        finally:
            release.set()
            runtime.close()
        self.assertTrue(tracker.closed.is_set())
        self.assertTrue(camera.closed.is_set())

    def test_model_construction_failure_reaches_camera_session(self):
        def fail():
            raise RuntimeError('model unavailable')

        camera = FakeCamera()
        runtime = TrackingRuntime(camera, tracker_factory=fail)
        try:
            runtime.start()
            _, error = runtime.errors.read(timeout=2)
            self.assertEqual(str(error), 'model unavailable')
        finally:
            runtime.close()
        self.assertTrue(camera.closed.is_set())
