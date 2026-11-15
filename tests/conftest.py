import ctypes
import json
import os
from pathlib import Path
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtWidgets import QApplication


GROUPS = {"logic", "qt", "windows_native"}


def pytest_addoption(parser):
    parser.addoption("--test-inventory", help="Write selected test groups and fixture dependencies as JSON")


@pytest.hookimpl(tryfirst=True)
def pytest_collection_modifyitems(items):
    # Run before pytest's -m selection. fixturenames includes indirect/autouse
    # dependencies, including fixtures imported from another test module.
    for item in items:
        explicit = GROUPS.intersection(mark.name for mark in item.iter_markers())
        if len(explicit) > 1:
            raise pytest.UsageError(f"Conflicting test groups: {item.nodeid}")
        required = ("windows_native" if "native_desktop" in item.fixturenames else
                    "qt" if "qapp" in item.fixturenames else "logic")
        group = next(iter(explicit), required)
        if (required == "windows_native" and group != required or
                required == "qt" and group == "logic"):
            raise pytest.UsageError(f"Test group understates fixture requirements: {item.nodeid}")
        if not explicit:
            item.add_marker(getattr(pytest.mark, group))
        item.user_properties.append(("test_group", group))


def pytest_collection_finish(session):
    inventory = session.config.getoption("--test-inventory")
    if inventory:
        path = Path(inventory)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps([
            {"nodeid": item.nodeid, "group": next(g for g in GROUPS if item.get_closest_marker(g)),
             "fixtures": item.fixturenames} for item in session.items
        ], indent=2), encoding="utf-8")
    if session.config.option.collectonly:
        return
    if any(item.get_closest_marker("windows_native") for item in session.items):
        platform = os.environ.get("QT_QPA_PLATFORM", "windows").split(":")[0]
        if sys.platform != "win32" or platform != "windows":
            raise pytest.UsageError("Native validation unavailable: use Windows with QT_QPA_PLATFORM=windows; "
                                    "select -m 'logic or qt' for offscreen checks")


@pytest.fixture(scope="session")
def native_desktop(qapp):
    """Require a usable input desktop; unavailable is an error, never a pass/skip."""
    if sys.platform != "win32" or qapp.platformName() != "windows":
        pytest.fail("Native validation unavailable: Windows Qt platform required")
    from ctypes import wintypes
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    user32.OpenInputDesktop.restype = wintypes.HANDLE
    user32.CloseDesktop.argtypes = [wintypes.HANDLE]
    user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                               wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    desktop = user32.OpenInputDesktop(0, False, 0x0001)  # DESKTOP_READOBJECTS
    if not desktop:
        pytest.fail(f"Native validation unavailable: input desktop inaccessible ({ctypes.get_last_error()})")
    try:
        name, needed = ctypes.create_unicode_buffer(256), wintypes.DWORD()
        if not user32.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed)):
            pytest.fail("Native validation unavailable: cannot identify input desktop")
        if name.value.casefold() != "default":
            pytest.fail(f"Native validation unavailable: input desktop is {name.value!r}, not Default")
    finally:
        user32.CloseDesktop(desktop)
    return qapp


@pytest.fixture(autouse=True)
def test_environment(request):
    if request.node.get_closest_marker("windows_native"):
        request.getfixturevalue("native_desktop")


@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    app.setOrganizationName("R2CompanionTests")
    app.setApplicationName("R2CompanionTests")
    app.setQuitOnLastWindowClosed(False)
    return app


@pytest.fixture(autouse=True)
def slot_errors(monkeypatch):
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda kind, value, tb: errors.append(value))
    yield
    if QApplication.instance() is not None:
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert not errors, f"Exceção em callback Qt: {errors}"


@pytest.fixture
def clock():
    class Clock:
        now = 1000.0

        def __call__(self):
            return self.now

        def advance(self, seconds):
            self.now += seconds
    return Clock()
