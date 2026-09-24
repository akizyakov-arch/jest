"""Native mouse operations; production use is owned by the input watchdog."""

import ctypes as ct
import os
from contextlib import contextmanager
from time import monotonic

from .cursor import Screen
from .events import CommandType

BUTTONS = {'left': (0x0002, 0x0004, 1), 'right': (0x0008, 0x0010, 2),
           'middle': (0x0020, 0x0040, 4)}
KEYS = {'ESC': 0x1B, 'ALT': 0x12, 'SHIFT': 0x10, 'TAB': 0x09, 'CTRL': 0x11, 'WIN': 0x5B, 'D': 0x44}


class MouseInput(ct.Structure):
    _fields_ = [("dx", ct.c_int32), ("dy", ct.c_int32),
                ("mouseData", ct.c_uint32), ("dwFlags", ct.c_uint32),
                ("time", ct.c_uint32), ("dwExtraInfo", ct.c_size_t)]


class KeyboardInput(ct.Structure):
    _fields_ = [('wVk', ct.c_uint16), ('wScan', ct.c_uint16), ('dwFlags', ct.c_uint32),
                ('time', ct.c_uint32), ('dwExtraInfo', ct.c_size_t)]


class InputData(ct.Union):
    _fields_ = [("mi", MouseInput), ('ki', KeyboardInput)]


class Input(ct.Structure):
    _fields_ = [("type", ct.c_uint32), ("data", InputData)]


class Point(ct.Structure):
    _fields_ = [("x", ct.c_int32), ("y", ct.c_int32)]


class WindowsCursorBackend:
    def set_cursor_hidden(self, hidden):
        if not hasattr(self, '_visibility'):
            from .cursor_visibility import CursorVisibility
            self._visibility=CursorVisibility()
        self._visibility.set_hidden(hidden)

    @property
    def cursor_hidden(self):
        return getattr(getattr(self,'_visibility',None),'hidden',False)

    def __init__(self):
        if os.name != "nt":
            raise OSError("Windows cursor control requires Windows")
        self.user32 = ct.WinDLL("user32", use_last_error=True)
        signatures = {
            "SetThreadDpiAwarenessContext": ([ct.c_void_p], ct.c_void_p),
            "GetSystemMetrics": ([ct.c_int], ct.c_int),
            "GetCursorPos": ([ct.POINTER(Point)], ct.c_int),
            "SendInput": ([ct.c_uint, ct.POINTER(Input), ct.c_int], ct.c_uint),
            "GetAsyncKeyState": ([ct.c_int], ct.c_int16),
            "GetDoubleClickTime": ([], ct.c_uint),
        }
        for name, (args, result) in signatures.items():
            function = getattr(self.user32, name)
            function.argtypes, function.restype = args, result
        self.screen = None

    @contextmanager
    def physical_coordinates(self):
        previous = self.user32.SetThreadDpiAwarenessContext(ct.c_void_p(-4))
        if not previous:
            raise OSError("Cannot enable physical display coordinates")
        try:
            yield
        finally:
            self.user32.SetThreadDpiAwarenessContext(previous)

    def _screen(self):
        return Screen(self.user32.GetSystemMetrics(0), self.user32.GetSystemMetrics(1))

    def anchor(self):
        with self.physical_coordinates():
            self.screen = self._screen()
            point = Point()
            if not self.user32.GetCursorPos(ct.byref(point)):
                raise OSError("Cannot read cursor on the current desktop")
            position = point.x, point.y
            if not self.screen.contains(position):
                raise OSError("Move the mouse to the primary display, then Resume")
            return self.screen, self.screen.normalized(position)

    def prepare(self, command):
        if command.type == CommandType.KEY_DOWN:
            if command.key not in KEYS:
                raise ValueError('Unsupported key')
            if self.user32.GetAsyncKeyState(KEYS[command.key]) & 0x8000:
                raise OSError('Key is already held; release it, then Resume')
            if command.key in ('ALT','CTRL','WIN') and any(self.user32.GetAsyncKeyState(key) & 0x8000 for key in (9,16,17,18,68,91,92) if key != KEYS[command.key]):
                raise OSError('Release keyboard modifiers and Tab before switching windows')
        if command.type == CommandType.POINTER_DOWN:
            if command.button not in BUTTONS:
                raise ValueError('Unsupported pointer button')
            if self.user32.GetAsyncKeyState(BUTTONS[command.button][2]) & 0x8000:
                raise OSError('Mouse button is already held; release it, then Resume')
            self.anchor()

    def double_click_limits(self):
        with self.physical_coordinates():
            return (self.user32.GetDoubleClickTime(), self.user32.GetSystemMetrics(36),
                    self.user32.GetSystemMetrics(37))

    def send(self, command):
        if command.type in (CommandType.KEY_DOWN, CommandType.KEY_UP):
            if command.key not in KEYS:
                raise ValueError('Unsupported key')
            if command.expires_at <= monotonic():
                raise OSError('Keyboard command expired')
            self._key(command.type == CommandType.KEY_UP, command.key)
            return
        if command.type == CommandType.SCROLL:
            if type(command.wheel_units) is not int or not 0 < abs(command.wheel_units) <= 1200:
                raise ValueError('Invalid wheel delta')
            if command.expires_at <= monotonic():
                raise OSError('Scroll command expired')
            event = Input(0, InputData(mi=MouseInput(0, 0, command.wheel_units & 0xffffffff, 0x0800, 0, 0)))
            if self.user32.SendInput(1, ct.byref(event), ct.sizeof(Input)) != 1:
                raise OSError('Windows rejected scroll input')
            return
        if command.type in (CommandType.POINTER_DOWN, CommandType.POINTER_UP):
            if command.button not in BUTTONS:
                raise ValueError('Unsupported pointer button')
            if command.expires_at <= monotonic():
                raise OSError('Mouse command expired')
            if command.position is not None:
                with self.physical_coordinates():
                    if self.screen is None or self._screen() != self.screen:
                        raise OSError('Display size changed. Click Resume')
                    x,y=self.screen.absolute(command.position)
                    flags=BUTTONS[command.button][0 if command.type==CommandType.POINTER_DOWN else 1]
                    event=Input(0,InputData(mi=MouseInput(x,y,0,0x8001|flags,0,0)))
                    if command.expires_at <= monotonic():
                        raise OSError('Positioned mouse command expired')
                    if self.user32.SendInput(1,ct.byref(event),ct.sizeof(Input)) != 1:
                        raise OSError('Windows rejected positioned mouse input')
                return
            if command.type == CommandType.POINTER_DOWN:
                self._button(BUTTONS[command.button][0])
            else:
                self._button(BUTTONS[command.button][1])
            return
        if command.type != CommandType.POINTER_MOVE:
            raise ValueError('Unsupported input command')
        with self.physical_coordinates():
            if self.screen is None or self._screen() != self.screen:
                raise OSError("Display size changed. Click Resume")
            x, y = self.screen.absolute(command.position)
            event = Input(0, InputData(mi=MouseInput(x, y, 0, 0x8001, 0, 0)))
            # Recheck freshness immediately before injection; no worker or move queue.
            if command.expires_at <= monotonic():
                return False
            if self.user32.SendInput(1, ct.byref(event), ct.sizeof(Input)) != 1:
                raise OSError("Windows rejected cursor input. Click Resume")

    def release(self, buttons, keys):
        if keys - KEYS.keys() or buttons - BUTTONS.keys():
            raise ValueError('Unsupported owned input')
        flags = sum(BUTTONS[button][1] for button in buttons)
        errors = []
        try:
            if flags:
                self._button(flags)
        except OSError as exc:
            errors.append(exc)
        for key in ('TAB', 'D', 'SHIFT', 'ALT', 'CTRL', 'WIN', 'ESC'):
            if key in keys:
                try:
                    self._key(True, key)
                except OSError as exc:
                    errors.append(exc)
        if errors:
            raise errors[0]

    def _key(self, up, key='ESC'):
        event = Input(1, InputData(ki=KeyboardInput(KEYS[key], 0, 0x0002 if up else 0, 0, 0)))
        if self.user32.SendInput(1, ct.byref(event), ct.sizeof(Input)) != 1:
            raise OSError('Windows rejected keyboard input')

    def _button(self, flags):
        event = Input(0, InputData(mi=MouseInput(0, 0, 0, flags, 0, 0)))
        if self.user32.SendInput(1, ct.byref(event), ct.sizeof(Input)) != 1:
            raise OSError('Windows rejected mouse button input')
