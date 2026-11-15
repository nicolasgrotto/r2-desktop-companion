from copy import deepcopy
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from r2_companion.app import Companion
from r2_companion.pet.state import State
from r2_companion.services.storage import ConfigStore
from r2_companion.ui.steam import SteamOverlay
from test_context_v03 import pet


def set_overlay(pet, enabled):
    settings = deepcopy(pet.store.settings)
    settings.window.topmost = enabled
    pet.store.apply(settings)


def desktop_surfaces(pet):
    # Keep the expected surfaces independent of the policy's registry, so a
    # forgotten registration cannot silently disappear from these checks.
    return (pet.window, pet.window.sleep_effect, pet.window.steam,
            pet.window.projection_overlay, pet.bubble, pet.tray.notice, pet.radial)


def assert_layers(pet, enabled):
    for window in desktop_surfaces(pet):
        assert bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == enabled
    assert pet.store.settings.window.topmost == enabled


@pytest.mark.parametrize("enabled", [False, True])
def test_every_animation_and_new_surface_inherits_the_current_policy(pet, enabled):
    set_overlay(pet, enabled)
    for state in State:
        pet.controller.enter(state)
        assert_layers(pet, enabled)
    # A surface created after preferences were loaded must inherit the policy.
    extra = SteamOverlay(pet.window)
    try:
        assert bool(extra.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) == enabled
        pet.window.set_topmost(not enabled)
        assert bool(extra.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != enabled
    finally:
        extra.set_active(False)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("state", [State.IDLE, State.SLEEP, State.OVERHEAT])
def test_all_surfaces_follow_preference_in_every_state(pet, enabled, state):
    set_overlay(pet, enabled)
    pet.controller.enter(state)
    pet.window.show_projection("clock")
    pet.bubble.present("Teste de sobreposição", pet.window)
    pet.tray.notice.present_corner("Aviso", pet.window.geometry())
    assert_layers(pet, enabled)
    assert pet.window.sleep_effect.isVisible() == (state == State.SLEEP)
    assert pet.window.steam.isVisible() == (state == State.OVERHEAT)
    assert pet.window.projection_overlay.isVisible() and pet.bubble.isVisible()
    for effect in (pet.window.sleep_effect, pet.window.steam, pet.window.projection_overlay, pet.bubble):
        assert effect.windowFlags() & Qt.WindowType.WindowTransparentForInput
        assert effect.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus
    for next_state in (State.WAKE, State.INTERACT, State.IDLE):
        pet.controller.enter(next_state)
        assert_layers(pet, enabled)
    pet.positioning.settle()
    assert_layers(pet, enabled)
    assert pet.store.settings.to_dict()["window"]["topmost"] == enabled
    pet.radial.popup_near(pet.window)
    assert pet.radial.isVisible() and "radial" in pet.controller.gates
    assert_layers(pet, enabled)
    pet.radial.hide()
    assert "radial" not in pet.controller.gates


@pytest.mark.parametrize("state", [State.IDLE, State.SLEEP, State.OVERHEAT])
def test_live_toggle_preserves_effects_visibility_timers_and_input_flags(pet, state):
    pet.controller.enter(state)
    pet.window.show_projection("date")
    pet.bubble.present("Mensagem", pet.window)
    pet.tray.notice.present_corner("Aviso", pet.window.geometry())
    visible = {window: window.isVisible() for window in desktop_surfaces(pet)}
    for enabled in (False, True, False):
        # Apply the policy directly to avoid the independent preferences workflow
        # resetting inactivity; the state must survive a stacking change itself.
        pet.store.settings.window.topmost = enabled
        pet.window.set_topmost(enabled)
        assert pet.controller.state == state
        assert_layers(pet, enabled)
        assert {window: window.isVisible() for window in visible} == visible
        assert pet.window.sleep_effect.timer.isActive() == (state == State.SLEEP)
        assert pet.window.steam.timer.isActive() == (state == State.OVERHEAT)
        assert pet.window.projection_timer.isActive()
        assert pet.bubble.timer.isActive() and pet.tray.notice.timer.isActive()
        pet.window.set_pass_through(True)
        pet.window.set_pass_through(False)
        assert_layers(pet, enabled)
        pet.window.hide()
        assert not pet.window.sleep_effect.isVisible() and not pet.window.steam.isVisible()
        pet.window.show()
        assert_layers(pet, enabled)


@pytest.mark.parametrize("enabled", [False, True])
def test_automatic_sleep_wake_droid_switch_and_restart_keep_saved_preference(pet, enabled, qapp):
    set_overlay(pet, enabled)
    pet.controller.update_inactivity(pet.behavior.settings.sleep_seconds + 1)
    assert pet.controller.state == State.SLEEP
    assert_layers(pet, enabled)
    for identifier in pet.droids.profiles:
        assert pet.equip_droid(identifier)
        assert pet.controller.state == State.SLEEP
        assert_layers(pet, enabled)
    pet.controller.update_inactivity(0)
    assert pet.controller.state == State.WAKE
    assert_layers(pet, enabled)
    directory = pet.store.directory
    pet.shutdown()
    store = ConfigStore(directory)
    assert store.acquire()
    store.load()
    restarted = None
    try:
        restarted = Companion(qapp, store)
        assert_layers(restarted, enabled)
    finally:
        if restarted:
            restarted.shutdown()
        else:
            store.close()


@pytest.fixture
def native_underlay(tmp_path):
    if os.name != "nt":
        pytest.skip("Requires a real Windows desktop")
    ready = tmp_path / "underlay.json"
    helper = Path(__file__).parent / "helpers/native_underlay.py"
    child = subprocess.Popen([sys.executable, str(helper), str(ready)],
                             creationflags=subprocess.CREATE_NO_WINDOW,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        for _ in range(100):
            if ready.exists():
                break
            QTest.qWait(50)
        assert ready.exists(), "Underlay did not start"
        yield json.loads(ready.read_text())["hwnd"]
    finally:
        child.terminate()
        child.wait(timeout=5)


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("state", [State.IDLE, State.SLEEP, State.OVERHEAT])
@pytest.mark.parametrize("raise_owner", [False, True])
def test_native_style_z_order_and_focus_with_external_window(pet, native_underlay, enabled, state,
                                                            raise_owner, monkeypatch):
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    get_style = user32.GetWindowLongPtrW if ctypes.sizeof(ctypes.c_void_p) == 8 else user32.GetWindowLongW
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = ctypes.c_ssize_t
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                   ctypes.c_int, ctypes.c_int, wintypes.UINT]
    if raise_owner:
        # Reproduce the native owner-raising behavior independently of the
        # Windows version/desktop used by the test runner.
        for surface in (pet.window.sleep_effect, pet.window.steam,
                        pet.window.projection_overlay, pet.bubble):
            for method in ("show", "setGeometry", "adjustSize"):
                def call_and_raise(*args, original=getattr(surface, method), window=surface):
                    if not window.isVisible():
                        assert user32.SetWindowPos(int(pet.window.winId()), 0, 0, 0, 0, 0, 0x213)
                    return original(*args)
                monkeypatch.setattr(surface, method, call_and_raise)

    def above(first, second):
        handle = user32.GetWindow(second, 3)  # GW_HWNDPREV
        while handle:
            if handle == first:
                return True
            handle = user32.GetWindow(handle, 3)
        return False

    set_overlay(pet, enabled)
    # Establish the mascot's depth below a separate process without relying on
    # foreground permission to raise a foreign HWND from this test process.
    if not enabled:
        assert user32.SetWindowPos(int(pet.window.winId()), native_underlay, 0, 0, 0, 0, 0x213)
    assert above(int(pet.window.winId()), native_underlay) == enabled, "Initial native stacking"
    before = user32.GetForegroundWindow()
    pet.controller.enter(state)
    pet.window.show_projection("clock")
    pet.bubble.present("Mensagem", pet.window)
    QTest.qWait(80)
    for window in desktop_surfaces(pet):
        handle = int(window.winId())
        assert bool(get_style(handle, -20) & 8) == enabled, window
        if window.isVisible():
            assert above(handle, native_underlay) == enabled, window
    assert user32.GetForegroundWindow() == before, "Effects stole foreground activation"
    for setting in (not enabled, enabled):
        pet.window.set_topmost(setting)
        for window in desktop_surfaces(pet):
            assert bool(get_style(int(window.winId()), -20) & 8) == setting, window
    pet.window.set_pass_through(True)
    pet.window.set_pass_through(False)
    assert bool(get_style(int(pet.window.winId()), -20) & 8) == enabled
    # Reestablish normal stacking after deliberately changing the stacking band.
    if not enabled:
        assert user32.SetWindowPos(int(pet.window.winId()), native_underlay, 0, 0, 0, 0, 0x213)
    pet.controller.enter(State.WAKE)
    pet.controller.enter(State.IDLE)
    assert above(int(pet.window.winId()), native_underlay) == enabled
    assert user32.GetForegroundWindow() == before
