import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QTest

from r2_companion.app import Companion
from r2_companion.services.storage import ConfigStore


@pytest.mark.skipif(os.name != "nt", reason="Requires a real Windows desktop")
@pytest.mark.windows_native
def test_native_transparency_passes_hit_test_to_another_process(qapp, tmp_path):
    ready = tmp_path / "underlay.json"
    helper = Path(__file__).parent / "helpers/native_underlay.py"
    companion = child = None
    try:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.WindowFromPoint.argtypes = [wintypes.POINT]
        user32.WindowFromPoint.restype = wintypes.HWND
        startup_foreground = user32.GetForegroundWindow()
        store = ConfigStore(tmp_path / "data")
        assert store.acquire()
        companion = Companion(qapp, store)
        assert user32.GetForegroundWindow() == startup_foreground, "Mascot stole startup activation"

        child = subprocess.Popen([sys.executable, str(helper), str(ready)],
                                 creationflags=subprocess.CREATE_NO_WINDOW,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            if ready.exists():
                break
            QTest.qWait(50)
        assert ready.exists(), "Underlay did not start"
        underlay_handle = json.loads(ready.read_text())["hwnd"]
        before = user32.GetForegroundWindow()
        companion.positioning.place(QPointF(150, 150))
        QTest.qWait(250)
        pet_handle = int(companion.window.winId())
        assert user32.WindowFromPoint(wintypes.POINT(155, 155)) == underlay_handle
        assert user32.WindowFromPoint(wintypes.POINT(230, 190)) == pet_handle
        assert user32.GetForegroundWindow() == before, "Mascot stole foreground activation"
        get_style = user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.GetWindowLongW
        get_style.argtypes = [wintypes.HWND, ctypes.c_int]
        get_style.restype = ctypes.c_ssize_t
        extended = get_style(pet_handle, -20)
        assert extended & 0x00000008
        assert extended & 0x00080000
        assert extended & 0x08000000
        companion.window.set_pass_through(True)
        QTest.qWait(100)
        assert user32.WindowFromPoint(wintypes.POINT(230, 190)) == underlay_handle
        companion.window.set_pass_through(False)
        QTest.qWait(100)
        assert user32.WindowFromPoint(wintypes.POINT(230, 190)) == int(companion.window.winId())

        companion.positioning.place(QPointF(200, 300))
        assert companion.window.show_projection("date")
        QTest.qWait(100)
        overlay = companion.window.projection_overlay
        assert overlay.isVisible()
        center, dpr = overlay.card.center(), overlay.devicePixelRatioF()
        point = wintypes.POINT(round(center.x() * dpr), round(center.y() * dpr))
        user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
        user32.ClientToScreen.restype = wintypes.BOOL
        assert user32.ClientToScreen(int(overlay.winId()), ctypes.byref(point))
        assert user32.WindowFromPoint(point) == underlay_handle
        assert user32.GetForegroundWindow() == before, "Projection stole foreground activation"
    finally:
        if companion is not None:
            companion.shutdown()
        if child is not None:
            child.terminate()
            child.wait(timeout=5)
