import tempfile
import unittest
from pathlib import Path

from gesture_control.settings import Settings, load_settings, save_settings


class SettingsTests(unittest.TestCase):
    def test_invalid_settings_fall_back_without_overwriting_evidence(self):
        for contents in ('{"schema_version":99}', '{"camera_index":true}',
                         '{"debug":"false"}', '{', '[]', '{"unknown": 1}'):
            with self.subTest(contents=contents), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "settings.json"
                path.write_text(contents, encoding="utf-8")
                result = load_settings(path)
                self.assertIsNotNone(result.warning)
                self.assertEqual(result.settings, Settings())
                self.assertEqual(path.read_text(encoding="utf-8"), contents)

    def test_atomic_save_retains_last_valid_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_settings(path, Settings())
            save_settings(path, Settings(camera_index=2))
            self.assertEqual(load_settings(path).settings.camera_index, 2)
            backup = path.with_suffix(".json.bak")
            self.assertEqual(load_settings(backup).settings.camera_index, 0)
            path.write_text("broken", encoding="utf-8")
            save_settings(path, Settings(camera_index=3))
            self.assertEqual(load_settings(backup).settings.camera_index, 0)
            self.assertEqual(list(Path(directory).glob("*.tmp")), [])

    def test_missing_file_uses_defaults(self):
        with tempfile.TemporaryDirectory() as directory:
            result = load_settings(Path(directory) / "absent.json")
            self.assertEqual(result.settings, Settings())
            self.assertIsNone(result.warning)
