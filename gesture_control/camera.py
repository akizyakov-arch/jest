"""Camera capture with packed RGB bytes and explicit device ownership."""

from dataclasses import dataclass
from typing import Protocol
from time import monotonic
import logging
import os

# Configure before importing OpenCV (it may cache environment options).
# MSMF hardware-transform probing can make webcam initialization very slow.
if os.name == 'nt':
    os.environ.setdefault('OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS', '0')

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class CameraFrame:
    frame_id: int
    captured_at: float
    width: int
    height: int
    pixels: bytes


class CameraSource(Protocol):
    def start(self) -> None: ...
    def read(self) -> CameraFrame | None: ...
    def close(self) -> None: ...


class CameraError(RuntimeError):
    pass


class OpenCVCamera:
    def __init__(self, index: int = 0, width: int = 640, height: int = 480,
                 fps: int = 30, backend: str = "auto"):
        self.index, self.width, self.height, self.fps = index, width, height, fps
        self.backend = backend
        self._capture = None
        self._frame_id = 0

    def start(self) -> None:
        import cv2

        self.close()
        started = monotonic()
        self._started_at = started
        self._frame_id = 0
        apis = {"auto": cv2.CAP_ANY, "dshow": cv2.CAP_DSHOW, "msmf": cv2.CAP_MSMF}
        capture = cv2.VideoCapture(self.index, apis[self.backend])
        opened = monotonic()
        try:
            if not capture.isOpened():
                raise CameraError(f"Cannot open camera {self.index}. Check camera index, Windows camera permissions, and other apps using it.")
            capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)
            capture.set(cv2.CAP_PROP_FPS, self.fps)
            self._capture = capture
            log.info('camera_opened index=%d backend=%s open_ms=%.0f configure_ms=%.0f',
                     self.index, capture.getBackendName(), (opened-started)*1000,
                     (monotonic()-opened)*1000)
        except Exception:
            capture.release()
            raise

    def read(self) -> CameraFrame:
        import cv2

        if self._capture is None:
            raise CameraError("Camera is not open")
        ok, bgr = self._capture.read()
        captured_at = monotonic()
        if not ok or bgr is None or bgr.size == 0:
            raise CameraError("Camera stopped delivering frames. Reconnect it and restart preview.")
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        height, width = rgb.shape[:2]
        self._frame_id += 1
        if self._frame_id == 1:
            log.info('camera_first_frame index=%d elapsed_ms=%.0f',
                     self.index, (captured_at-self._started_at)*1000)
        return CameraFrame(self._frame_id, captured_at, width, height, rgb.tobytes())

    def close(self) -> None:
        if self._capture is not None:
            self._capture.release()
            self._capture = None
