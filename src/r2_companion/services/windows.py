import ctypes
from ctypes import wintypes
import logging
import os
from pathlib import Path
import sys
import time

from PySide6.QtCore import QAbstractNativeEventFilter, QObject, Signal

log = logging.getLogger(__name__)
IS_WINDOWS = os.name == "nt"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "R2Companion"

if IS_WINDOWS:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
    kernel32.GetTickCount64.restype = ctypes.c_ulonglong
    kernel32.GetTickCount.restype = wintypes.DWORD
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.IsZoomed.argtypes = [wintypes.HWND]
    user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
    user32.MonitorFromWindow.restype = wintypes.HANDLE
    user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    wtsapi32.WTSRegisterSessionNotification.argtypes = [wintypes.HWND, wintypes.DWORD]
    wtsapi32.WTSUnRegisterSessionNotification.argtypes = [wintypes.HWND]


def uptime() -> float:
    return kernel32.GetTickCount64() / 1000 if IS_WINDOWS else time.monotonic()


def idle_seconds() -> float | None:
    if not IS_WINDOWS:
        return None

    class LastInput(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    info = LastInput(ctypes.sizeof(LastInput), 0)
    if not user32.GetLastInputInfo(ctypes.byref(info)):
        return None
    elapsed = ((kernel32.GetTickCount() - info.dwTime) & 0xFFFFFFFF) / 1000
    return elapsed if elapsed < 7 * 86400 else None


def foreground_fullscreen(pet_handle: int) -> bool:
    if not IS_WINDOWS:
        return False

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    foreground = user32.GetForegroundWindow()
    if not foreground or user32.IsZoomed(foreground):
        return False
    class_name = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(foreground, class_name, len(class_name))
    if class_name.value in {"Progman", "WorkerW", "Shell_TrayWnd", "Shell_SecondaryTrayWnd"}:
        return False
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(foreground, ctypes.byref(pid))
    if pid.value == os.getpid():
        return False
    monitor = user32.MonitorFromWindow(foreground, 2)
    if monitor != user32.MonitorFromWindow(pet_handle, 2):
        return False
    info = MonitorInfo()
    info.cbSize = ctypes.sizeof(info)
    rect = wintypes.RECT()
    if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)) or not user32.GetWindowRect(foreground, ctypes.byref(rect)):
        return False
    area = info.rcMonitor
    return (abs(rect.left - area.left) <= 1 and abs(rect.top - area.top) <= 1
            and abs(rect.right - area.right) <= 1 and abs(rect.bottom - area.bottom) <= 1)


class SessionSignals(QObject):
    suspended = Signal(bool)
    ending = Signal()


class SessionEvents(QAbstractNativeEventFilter):
    def __init__(self):
        super().__init__()
        self.signals = SessionSignals()
        self.handle = 0

    def bind(self, handle: int) -> None:
        self.close()
        if IS_WINDOWS and wtsapi32.WTSRegisterSessionNotification(handle, 0):
            self.handle = handle

    def nativeEventFilter(self, event_type, message):
        if IS_WINDOWS and bytes(event_type) in (b"windows_generic_MSG", b"windows_dispatcher_MSG"):
            msg = wintypes.MSG.from_address(int(message))
            if msg.message == 0x02B1:
                if msg.wParam in (7, 8):
                    self.signals.suspended.emit(msg.wParam == 7)
            elif msg.message == 0x0218:
                if msg.wParam == 4:
                    self.signals.suspended.emit(True)
                elif msg.wParam in (7, 18):
                    self.signals.suspended.emit(False)
            elif msg.message == 0x0016 and msg.wParam:
                self.signals.ending.emit()
        return False, 0

    def close(self) -> None:
        if self.handle and IS_WINDOWS:
            wtsapi32.WTSUnRegisterSessionNotification(self.handle)
        self.handle = 0


class StartupService:
    def __init__(self, executable: Path | None = None, registry=None):
        self.executable = executable
        if registry is None and IS_WINDOWS:
            import winreg
            registry = winreg
        self.registry = registry

    @property
    def available(self) -> bool:
        return self.registry is not None and self.executable is not None

    @property
    def command(self) -> str:
        if not self.available:
            raise ValueError("Inicialização automática disponível apenas no executável instalado em local estável.")
        path = self.executable.resolve()
        if not path.is_file() or path.suffix.lower() != ".exe" or '"' in str(path):
            raise ValueError("Executável de inicialização inválido.")
        command = f'"{path}"'
        if len(command) > 260:
            raise ValueError("Caminho excede o limite de 260 caracteres do Windows Run.")
        return command

    def read(self) -> str | None:
        if self.registry is None:
            return None
        try:
            with self.registry.OpenKey(self.registry.HKEY_CURRENT_USER, RUN_KEY) as key:
                return self.registry.QueryValueEx(key, RUN_NAME)[0]
        except FileNotFoundError:
            return None

    def enabled(self) -> bool:
        return self.available and self.read() == self.command

    def set_enabled(self, enabled: bool) -> None:
        command = self.command
        current = self.read()
        if current is not None and current != command:
            raise ValueError("Já existe um registro R2Companion diferente. Ele foi preservado.")
        registry = self.registry
        if enabled:
            with registry.CreateKeyEx(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE) as key:
                registry.SetValueEx(key, RUN_NAME, 0, registry.REG_SZ, command)
        elif current is not None:
            with registry.OpenKey(registry.HKEY_CURRENT_USER, RUN_KEY, 0, registry.KEY_SET_VALUE) as key:
                registry.DeleteValue(key, RUN_NAME)


def packaged_executable() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    executable = Path(sys.executable).resolve()
    if any(part.lower() in {"dist", "build", "temp", "tmp"} for part in executable.parts):
        return None
    return executable
