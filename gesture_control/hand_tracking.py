"""Perception types do not depend on gesture or input engines."""

from dataclasses import dataclass
from typing import Protocol
from pathlib import Path
from time import monotonic
import os
import tempfile

from .camera import CameraFrame


@dataclass(frozen=True)
class TrackedHand:
    hand_id: str
    handedness: str
    landmarks: tuple[tuple[float, float, float], ...]
    tracking_confidence: float | None = None
    handedness_score: float | None = None


@dataclass(frozen=True)
class TrackingSnapshot:
    frame_id: int
    source_timestamp: float
    completed_timestamp: float
    hands: tuple[TrackedHand, ...]


class HandTracker(Protocol):
    def process(self, frame: CameraFrame) -> TrackingSnapshot: ...
    def close(self) -> None: ...


class MediaPipeHandTracker:
    """VIDEO inference runs on a worker; latest-frame capture avoids backlog.

    IDs are frame-local in this diagnostic stage, not persistent hand identity.
    """

    def __init__(self, model_path: Path, num_hands: int = 2,
                 detection_confidence: float = 0.5, presence_confidence: float = 0.5,
                 tracking_confidence: float = 0.5):
        # MediaPipe imports matplotlib transitively; keep its cache writable in
        # portable/restricted environments and honor explicit user overrides.
        os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "gesture-control-matplotlib"))
        import mediapipe as mp

        if not model_path.is_file():
            raise FileNotFoundError(f"Model not found: {model_path}. Run: python -m gesture_control --download-model")
        self._mp = mp
        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_buffer=model_path.read_bytes()),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=num_hands,
            min_hand_detection_confidence=detection_confidence,
            min_hand_presence_confidence=presence_confidence,
            min_tracking_confidence=tracking_confidence,
        )
        self._landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1

    def process(self, frame: CameraFrame) -> TrackingSnapshot:
        import numpy as np

        rgb = np.frombuffer(frame.pixels, dtype=np.uint8).reshape(frame.height, frame.width, 3)
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        timestamp_ms = max(self._last_timestamp_ms + 1, int(frame.captured_at * 1000))
        self._last_timestamp_ms = timestamp_ms
        result = self._landmarker.detect_for_video(image, timestamp_ms)
        hands = []
        for index, landmarks in enumerate(result.hand_landmarks):
            categories = result.handedness[index] if index < len(result.handedness) else []
            category = categories[0] if categories else None
            hands.append(TrackedHand(
                hand_id=f"frame-{frame.frame_id}-hand-{index}",
                handedness=category.category_name if category else "Unknown",
                landmarks=tuple((point.x, point.y, point.z) for point in landmarks),
                handedness_score=category.score if category else None,
            ))
        return TrackingSnapshot(frame.frame_id, frame.captured_at, monotonic(), tuple(hands))

    def close(self) -> None:
        if self._landmarker is not None:
            self._landmarker.close()
            self._landmarker = None
