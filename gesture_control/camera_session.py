"""Camera switching lifecycle; the old device closes before the new one opens."""

import logging
from collections.abc import Callable
from time import monotonic

from .tracking_runtime import PreviewFrame, TrackingRuntime

log = logging.getLogger(__name__)


class CameraSession:
    def __init__(self, factory: Callable[[int], TrackingRuntime], index: int,
                 start_timeout_ms: int, frame_timeout_ms: int, clock=monotonic):
        self.factory, self.clock = factory, clock
        self.index = index
        self.runtime: TrackingRuntime | None = None
        self.error: str | None = None
        self.pending = True
        self.version = self.frames_received = 0
        self.last_frame_at = clock()
        self.start_timeout_ms, self.frame_timeout_ms = start_timeout_ms, frame_timeout_ms

    @property
    def status(self) -> str:
        if self.error:
            return f"Camera {self.index}: unavailable"
        if self.pending and self.runtime is not None and self.runtime.is_alive:
            return f"Camera {self.index}: releasing previous camera..."
        return f"Camera {self.index}: {'streaming' if self.frames_received else 'opening...'}"

    def select(self, index: int, *, retry: bool = False) -> bool:
        if index < 0:
            raise ValueError("Camera index must be nonnegative")
        if index == self.index and not retry and not self.error:
            return False
        self.index = index
        self.error = None
        self.pending = True
        self.version = self.frames_received = 0
        if self.runtime is not None:
            self.runtime.stopped.set()
        log.info("camera_selected index=%d", index)
        return True

    def _fail(self, error: Exception) -> None:
        self.error = str(error)
        if self.runtime is not None:
            self.runtime.stopped.set()
        log.error("camera_session_failed index=%d reason=%s", self.index, error)

    def poll(self) -> PreviewFrame | None:
        if self.error:
            return None
        if self.pending:
            if self.runtime is not None:
                # Keep processing UI events while a driver finishes opening/closing.
                if self.runtime.is_alive:
                    return None
                self.runtime.close()
                self.runtime = None
            try:
                self.runtime = self.factory(self.index)
                self.runtime.start()
            except Exception as exc:
                self._fail(exc)
                return None
            self.pending = False
            self.last_frame_at = self.clock()
        _, error = self.runtime.errors.read(timeout=0)
        if error is not None:
            self._fail(error)
            return None
        self.version, result = self.runtime.results.read(self.version, timeout=0)
        if result is not None:
            self.frames_received += 1
            self.last_frame_at = self.clock()
            return result
        timeout = self.frame_timeout_ms if self.frames_received else self.start_timeout_ms
        if (self.clock() - self.last_frame_at) * 1000 > timeout:
            self._fail(TimeoutError("No frames received. Select another camera or click Retry."))
        return None

    def close(self) -> None:
        if self.runtime is not None:
            self.runtime.close()
