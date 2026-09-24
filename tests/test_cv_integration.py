"""Real model smoke test on generated pixels, never opens a camera."""

import importlib.util
import unittest
from time import monotonic

from gesture_control.camera import CameraFrame
from gesture_control.hand_tracking import MediaPipeHandTracker
from gesture_control.model_assets import DEFAULT_MODEL
from gesture_control.tracking_runtime import PreviewFrame
from gesture_control.pointer import PointerSnapshot, WorkArea


@unittest.skipUnless(importlib.util.find_spec("mediapipe") and importlib.util.find_spec("cv2")
                     and DEFAULT_MODEL.is_file(), "Requires CV dependencies and local model")
class CvIntegrationTests(unittest.TestCase):
    def test_real_model_handles_empty_frames_and_preview_renders(self):
        from gesture_control.preview import render_preview

        tracker = MediaPipeHandTracker(DEFAULT_MODEL)
        try:
            for frame_id in range(3):
                frame = CameraFrame(frame_id, monotonic(), 640, 480, bytes(640 * 480 * 3))
                snapshot = tracker.process(frame)
                self.assertEqual(snapshot.hands, ())
                self.assertEqual(snapshot.frame_id, frame_id)
            result = PreviewFrame(frame, snapshot, 30.0, 30.0, 10.0, 0)
            canvas = render_preview(result, mirrored=True, show_image=False)
            self.assertEqual(canvas.shape, (480, 640, 3))
            canvas = render_preview(result, mirrored=False, show_image=False,
                                    pointer=PointerSnapshot("TRACKING", (0.5, 0.5), (0.6, 0.6)),
                                    area=WorkArea(0.2, 0.2, 0.8, 0.8))
            self.assertEqual(canvas.shape, (480, 1040, 3))
        finally:
            tracker.close()
            tracker.close()
