from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
import unittest
from gesture_control.camera_devices import CameraDevice, enumerate_devices, read_default, write_default


class DeviceTests(unittest.TestCase):
    def test_backend_matched_names_and_indices(self):
        with patch('cv2_enumerate_cameras.enumerate_cameras', return_value=[
                SimpleNamespace(index=3, name='USB camera', path='persistent-id')]) as scan:
            devices = enumerate_devices('auto')
            scan.assert_called_once_with(1400)
            self.assertEqual(devices, (CameraDevice(3, 'USB camera', 'persistent-id', 'msmf'),))

    def test_default_persists_identity_not_index_and_can_be_cleared(self):
        with TemporaryDirectory() as folder:
            path = Path(folder)/'camera-default.json'
            self.assertEqual(read_default(path), {})
            write_default(path, CameraDevice(1, 'USB', 'device-id', 'msmf'))
            saved = read_default(path)
            self.assertEqual(saved['path'], 'device-id')
            self.assertNotIn('index', saved)
            write_default(path, None)
            self.assertEqual(read_default(path), {})
