"""Global emergency hotkey with an independent Windows message loop."""

import ctypes
import logging
import sys
from ctypes import wintypes
from threading import Event, Thread

log = logging.getLogger(__name__)


def parse_hotkey(value: str) -> tuple[int, int]:
    parts = value.lower().split("+")
    modifiers = {"alt": 1, "ctrl": 2, "shift": 4, "win": 8}
    if len(parts) < 2 or len(set(parts)) != len(parts) or any(p not in modifiers for p in parts[:-1]):
        raise ValueError("Hotkey requires modifiers and one letter/digit, e.g. ctrl+alt+g")
    key = parts[-1]
    if len(key) != 1 or key not in "abcdefghijklmnopqrstuvwxyz0123456789":
        raise ValueError("Hotkey key must be A-Z or 0-9")
    return 0x4000 | sum(modifiers[p] for p in parts[:-1]), ord(key.upper())


class EmergencyHotkey:
    def __init__(self, combination: str, callback):
        self.modifiers, self.key = parse_hotkey(combination)
        self.callback = callback
        self.registered = False
        self.error: str | None = None
        self._ready, self._stop = Event(), Event()
        self._thread: Thread | None = None
        self._thread_id = 0

    def start(self) -> bool:
        if self._thread is not None:
            raise RuntimeError("Hotkey service already started")
        self._thread = Thread(target=self._run, name="emergency-hotkey", daemon=True)
        self._thread.start()
        if not self._ready.wait(2):
            self.error = "Hotkey registration timed out"
            self._stop.set()
        return self.registered and self.error is None

    def _run(self):
        user32 = None
        try:
            if sys.platform != "win32":
                raise OSError("Global hotkey requires Windows")
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.GetCurrentThreadId.restype = wintypes.DWORD
            self._thread_id = kernel32.GetCurrentThreadId()
            user32.RegisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT)
            user32.RegisterHotKey.restype = wintypes.BOOL
            user32.UnregisterHotKey.argtypes = (wintypes.HWND, ctypes.c_int)
            user32.GetMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT)
            user32.GetMessageW.restype = ctypes.c_int
            user32.PeekMessageW.argtypes = (ctypes.POINTER(wintypes.MSG), wintypes.HWND,
                                            wintypes.UINT, wintypes.UINT, wintypes.UINT)
            message = wintypes.MSG()
            user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)
            if not user32.RegisterHotKey(None, 1, self.modifiers, self.key):
                raise ctypes.WinError(ctypes.get_last_error())
            self.registered = True
            self._ready.set()
            while not self._stop.is_set():
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result == -1:
                    raise ctypes.WinError(ctypes.get_last_error())
                if result == 0:
                    break
                if message.message == 0x0312:
                    self.callback()
        except Exception as exc:
            self.error = str(exc)
            log.error("emergency_hotkey_failed: %s", exc)
            self.callback()
        finally:
            if user32 is not None and self.registered:
                user32.UnregisterHotKey(None, 1)
            self.registered = False
            self._ready.set()

    def close(self):
        self._stop.set()
        if self._thread_id and sys.platform == "win32":
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.PostThreadMessageW.argtypes = (wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            user32.PostThreadMessageW(self._thread_id, 0x0012, 0, 0)
        if self._thread is not None:
            self._thread.join(timeout=2)
            if self._thread.is_alive():
                raise RuntimeError("Hotkey thread did not stop")
