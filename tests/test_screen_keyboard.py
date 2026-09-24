import unittest
from unittest.mock import MagicMock, patch

from gesture_control.screen_keyboard import open_screen_keyboard


class ScreenKeyboardTests(unittest.TestCase):
    def call_with_result(self, result):
        kernel, shell = MagicMock(), MagicMock()
        def system_directory(buffer, size):
            buffer.value = r"C:\Windows\System32"
            return len(buffer.value)
        kernel.GetSystemDirectoryW.side_effect = system_directory
        shell.ShellExecuteW.return_value = result
        with patch("gesture_control.screen_keyboard.sys.platform", "win32"), \
                patch("gesture_control.screen_keyboard.ctypes.WinDLL", side_effect=[kernel, shell]):
            open_screen_keyboard()
        return shell

    def test_launches_only_system_osk_without_text_arguments(self):
        shell = self.call_with_result(33)
        args = shell.ShellExecuteW.call_args.args
        self.assertEqual(args[1], "open")
        self.assertTrue(args[2].endswith("osk.exe"))
        self.assertIsNone(args[3])

    def test_shell_failure_is_reported(self):
        with self.assertRaises(OSError):
            self.call_with_result(5)
