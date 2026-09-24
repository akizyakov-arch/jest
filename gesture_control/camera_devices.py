"""Enumerate backend-matched Windows devices without opening capture streams."""
from dataclasses import dataclass
import json
from pathlib import Path
from .settings import _atomic_write


@dataclass(frozen=True)
class CameraDevice:
    index: int
    name: str
    path: str
    backend: str

    @property
    def label(self):
        return f'{self.name} ({self.index})'


def enumerate_devices(backend='auto'):
    from cv2_enumerate_cameras import enumerate_cameras
    # OpenCV Windows auto prefers MSMF; use the same API for names and indices.
    backend = 'msmf' if backend == 'auto' else backend
    api = {'msmf': 1400, 'dshow': 700}[backend]
    return tuple(CameraDevice(c.index, c.name, c.path, backend) for c in enumerate_cameras(api))


def read_default(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_default(path, device):
    data = {} if device is None else {'path': device.path, 'backend': device.backend, 'name': device.name}
    if device is not None and not device.path:
        raise ValueError('У камеры нет постоянного идентификатора')
    _atomic_write(Path(path), json.dumps(data, ensure_ascii=False, indent=2))
