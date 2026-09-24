import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from gesture_control.model_assets import download_model


class ModelTests(unittest.TestCase):
    def test_existing_invalid_model_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.task"
            path.write_bytes(b"invalid")
            with patch("gesture_control.model_assets.urlopen") as network:
                with self.assertRaises(ValueError):
                    download_model(path)
                network.assert_not_called()
            self.assertEqual(path.read_bytes(), b"invalid")

    def test_network_failure_removes_partial_download(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "model.task"
            with patch("gesture_control.model_assets.urlopen", side_effect=OSError("offline")):
                with self.assertRaises(OSError):
                    download_model(path)
            self.assertEqual(list(Path(directory).iterdir()), [])
