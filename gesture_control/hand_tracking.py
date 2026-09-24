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

    def __new__(cls, *args, **kwargs):
        instance = super().__new__(cls)
        instance._image_scale = 1.0
        instance._cv2 = None
        return instance

    def __init__(self, model_path: Path, num_hands: int = 2,
                 detection_confidence: float = 0.5, presence_confidence: float = 0.5,
                 tracking_confidence: float = 0.5, image_scale: float = 0.8):
        # MediaPipe imports matplotlib transitively; keep its cache writable in
        # portable/restricted environments and honor explicit user overrides.
        os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "gesture-control-matplotlib"))
        import cv2
        import mediapipe as mp

        if not model_path.is_file():
            raise FileNotFoundError(f"Model not found: {model_path}. Run: python -m gesture_control --download-model")
        if not 0.5 <= image_scale <= 1.0:
            raise ValueError('image_scale must be in 0.5..1.0')
        self._mp = mp
        self._cv2 = cv2
        self._image_scale = float(image_scale)
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

    def _effective_scale(self, frame: CameraFrame) -> float:
        scale = float(getattr(self, '_image_scale', 1.0))
        if scale <= 0:
            return 1.0
        # Aggressive but safe default: large full-HD inputs are resized early to reduce HandLandmarker cost.
        if frame.width * frame.height >= 1280 * 720:
            return min(scale, 0.75)
        if frame.width * frame.height >= 960 * 540:
            return min(scale, 0.85)
        return scale

    def _prepare_image(self, frame: CameraFrame):
        import numpy as np

        rgb = np.frombuffer(frame.pixels, dtype=np.uint8).reshape(frame.height, frame.width, 3)
        scale = self._effective_scale(frame)
        cv2 = getattr(self, '_cv2', None)
        if scale < 1.0 and cv2 is not None:
            target_w = max(1, int(round(frame.width * scale)))
            target_h = max(1, int(round(frame.height * scale)))
            if target_w != frame.width or target_h != frame.height:
                rgb = cv2.resize(rgb, (target_w, target_h), interpolation=cv2.INTER_AREA)
        return rgb

    def process(self, frame: CameraFrame) -> TrackingSnapshot:
        rgb = self._prepare_image(frame)
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
