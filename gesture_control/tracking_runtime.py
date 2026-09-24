"""Independent capture/inference workers with bounded latest-value mailboxes."""

from dataclasses import dataclass
from threading import Condition, Event, Thread
from time import monotonic
from typing import Generic, TypeVar
import logging

from .camera import CameraFrame, CameraSource
from .hand_tracking import HandTracker, TrackingSnapshot

T = TypeVar("T")
log = logging.getLogger(__name__)


class LatestValue(Generic[T]):
    def __init__(self):
        self._condition = Condition()
        self._version = 0
        self._value: T | None = None

    def publish(self, value: T) -> None:
        with self._condition:
            self._value = value
            self._version += 1
            self._condition.notify_all()

    def read(self, after: int = 0, timeout: float = 0.1) -> tuple[int, T | None]:
        with self._condition:
            self._condition.wait_for(lambda: self._version > after, timeout=timeout)
            return self._version, self._value if self._version > after else None


@dataclass(frozen=True)
class PreviewFrame:
    frame: CameraFrame
    tracking: TrackingSnapshot
    capture_fps: float
    inference_fps: float
    inference_ms: float
    skipped_frames: int


class TrackingRuntime:
    def __init__(self, camera: CameraSource, tracker: HandTracker | None = None, *, tracker_factory=None):
        if (tracker is None) == (tracker_factory is None):
            raise ValueError('Provide one tracker or tracker_factory')
        self.camera, self.tracker = camera, tracker
        self.tracker_factory = tracker_factory
        self.frames: LatestValue[tuple[CameraFrame, float]] = LatestValue()
        self.results: LatestValue[PreviewFrame] = LatestValue()
        self.errors: LatestValue[Exception] = LatestValue()
        self.stopped = Event()
        self._threads: list[Thread] = []

    @property
    def started(self) -> bool:
        return bool(self._threads)

    @property
    def is_alive(self) -> bool:
        return any(thread.is_alive() for thread in self._threads)

    def start(self) -> None:
        if self._threads:
            raise RuntimeError("Tracking runtime can only be started once")
        self._threads = [Thread(target=self._capture, name="camera", daemon=True),
                         Thread(target=self._infer, name="tracking", daemon=True)]
        for thread in self._threads:
            thread.start()

    def _fail(self, error: Exception) -> None:
        self.errors.publish(error)
        self.stopped.set()

    def _capture(self) -> None:
        try:
            self.camera.start()
            previous = None
            fps = 0.0
            while not self.stopped.is_set():
                frame = self.camera.read()
                if frame is None:
                    raise RuntimeError("Camera returned no frame")
                if previous is not None:
                    instant = 1.0 / max(frame.captured_at - previous, 0.000001)
                    fps = instant if fps == 0 else 0.9 * fps + 0.1 * instant
                previous = frame.captured_at
                self.frames.publish((frame, fps))
        except Exception as exc:
            self._fail(exc)
        finally:
            try:
                self.camera.close()
            except Exception as exc:
                self._fail(exc)

    def _infer(self) -> None:
        version = 0
        previous_done = None
        fps = 0.0
        skipped = 0
        max_pending_frames = 2
        try:
            if self.tracker_factory is not None:
                start = monotonic()
                self.tracker = self.tracker_factory()
                log.info('tracker_ready elapsed_ms=%.0f', (monotonic() - start) * 1000)
            while not self.stopped.is_set():
                new_version, value = self.frames.read(version)
                if value is None or self.stopped.is_set():
                    continue
                stale = max(0, new_version - version - 1)
                if stale > max_pending_frames:
                    version = new_version
                    skipped += stale
                    continue
                skipped += stale
                version = new_version
                frame, capture_fps = value
                start = monotonic()
                tracking = self.tracker.process(frame)
                done = monotonic()
                if previous_done is not None:
                    instant = 1 / max(done - previous_done, 0.000001)
                    fps = instant if fps == 0 else 0.9 * fps + 0.1 * instant
                previous_done = done
                if not self.stopped.is_set():
                    self.results.publish(PreviewFrame(frame, tracking, capture_fps, fps,
                                                       (done - start) * 1000, skipped))
        except Exception as exc:
            self._fail(exc)
        finally:
            try:
                if self.tracker is not None:
                    self.tracker.close()
            except Exception as exc:
                self._fail(exc)

    def close(self) -> None:
        self.stopped.set()
        deadline = monotonic() + 3
        for thread in self._threads:
            thread.join(timeout=max(0, deadline - monotonic()))
        if any(thread.is_alive() for thread in self._threads):
            raise RuntimeError("Camera/tracking driver did not stop within 3 seconds; restart the application")
