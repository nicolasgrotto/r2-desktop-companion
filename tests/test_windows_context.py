import ctypes
from ctypes import wintypes
import os
from types import SimpleNamespace

import pytest

from r2_companion.services import windows


@pytest.mark.skipif(os.name != "nt", reason="Win32 bindings")
@pytest.mark.parametrize("rect,own,cls,expected", [
    ((0, 0, 1920, 1080), False, "Game", True),
    ((-8, -8, 1928, 1048), False, "Editor", False),
    ((0, 0, 1920, 1080), True, "R2", False),
    ((0, 0, 1920, 1080), False, "WorkerW", False),
    ((0, 0, 1920, 1080), False, "Shell_TrayWnd", False),
])
def test_win32_fullscreen_detection_without_window_content(monkeypatch, rect, own, cls, expected):
    def class_name(handle, buffer, maximum):
        buffer.value = cls
        return len(cls)
    def process(handle, pointer):
        pointer._obj.value = os.getpid() if own else os.getpid() + 1
    def monitor_info(handle, pointer):
        info = pointer._obj
        info.rcMonitor = wintypes.RECT(0, 0, 1920, 1080)
        return True
    def window_rect(handle, pointer):
        value = pointer._obj
        value.left, value.top, value.right, value.bottom = rect
        return True
    fake = SimpleNamespace(GetForegroundWindow=lambda: 1, GetClassNameW=class_name,
        GetWindowThreadProcessId=process, MonitorFromWindow=lambda handle, flag: 2,
        GetMonitorInfoW=monitor_info, GetWindowRect=window_rect)
    monkeypatch.setattr(windows, "user32", fake)
    assert windows.foreground_fullscreen(3) is expected


@pytest.mark.skipif(os.name != "nt", reason="Win32 bindings")
def test_idle_seconds_handles_counter_wrap_and_api_failure(monkeypatch):
    def last_input(pointer):
        pointer._obj.dwTime = 0xFFFFFFF0
        return True
    monkeypatch.setattr(windows, "user32", SimpleNamespace(GetLastInputInfo=last_input))
    monkeypatch.setattr(windows, "kernel32", SimpleNamespace(GetTickCount=lambda: 20))
    assert windows.idle_seconds() == pytest.approx(0.036)
    monkeypatch.setattr(windows, "user32", SimpleNamespace(GetLastInputInfo=lambda pointer: False))
    assert windows.idle_seconds() is None
