"""User-invoked Windows keyboard. No text is sent or recorded."""

import ctypes
import sys
from ctypes import wintypes
from pathlib import Path


def open_screen_keyboard() -> None:
    if sys.platform != "win32":
        raise OSError("On-screen keyboard requires Windows")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.GetSystemDirectoryW.argtypes = (wintypes.LPWSTR, wintypes.UINT)
    kernel32.GetSystemDirectoryW.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel32.GetSystemDirectoryW(buffer, len(buffer))
    if not length or length >= len(buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    path = Path(buffer.value) / "osk.exe"
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.ShellExecuteW.argtypes = (wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR,
                                     wintypes.LPCWSTR, wintypes.LPCWSTR, ctypes.c_int)
    shell32.ShellExecuteW.restype = ctypes.c_void_p
    result = shell32.ShellExecuteW(None, "open", str(path), None, None, 1)
    if (result or 0) <= 32:
        raise OSError(f"Windows could not open the on-screen keyboard (code {result})")
