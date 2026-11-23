import ctypes

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton

from r2_companion.app import Companion
from r2_companion.services.hotkeys import DEFAULT_SHORTCUT, GlobalHotkey, hotkey_codes, register, unregister
from r2_companion.services.storage import ConfigStore
from r2_companion.ui.actions import ShortcutSettings
from test_context_v03 import pet


def test_registration_preserves_previous_on_conflict_and_save_failure():
    registered = {}

    def add(handle, identifier, mask, key):
        if key == ord("X"):
            return False
        registered[identifier] = mask, key
        return True

    def remove(handle, identifier):
        del registered[identifier]

    hotkey = GlobalHotkey(add, remove)
    assert hotkey.configure(True, DEFAULT_SHORTCUT)
    previous = hotkey.active
    assert registered[previous[0]] == (0x4003, ord("R"))
    with pytest.raises(ValueError, match="em uso"):
        hotkey.configure(True, "Ctrl+Alt+X")
    assert not hotkey.configure(True, "Ctrl+Alt+Y", lambda: False)
    assert not hotkey.configure(False, DEFAULT_SHORTCUT, lambda: False)
    assert hotkey.active == previous and len(registered) == 1
    assert hotkey.configure(True, "Ctrl+Alt+Y")
    assert not hotkey.matches(previous[0], ord("R") << 16 | 3)
    assert hotkey.configure(False, "Ctrl+Alt+Y")
    assert not registered and hotkey.active is None


@pytest.mark.parametrize("shortcut", ["R", "Ctrl+R, A", "Win+R", "Ctrl+F12", "Ctrl+Left", ""])
def test_invalid_combinations(shortcut):
    with pytest.raises(ValueError):
        hotkey_codes(shortcut)


def test_shortcut_editor_captures_one_combination_by_keyboard(qapp):
    calls = []
    editor = ShortcutSettings(False, DEFAULT_SHORTCUT, "Atalho desativado.",
                              lambda enabled, keys: calls.append((enabled, keys)) or "Atalho ativo.")
    editor.show()
    QTest.keyClick(editor.enabled, Qt.Key.Key_Space)
    editor.keys.setFocus()
    QTest.keyClick(editor.keys, Qt.Key.Key_K, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
    save, = editor.findChildren(QPushButton)
    QTest.keyClick(save, Qt.Key.Key_Space)
    assert calls == [(True, "Ctrl+Alt+K")]
    assert editor.status.text() == "Atalho ativo."
    editor.close()


def test_native_global_hotkey_opens_search_while_hidden_and_releases(pet, qapp):
    first = "Ctrl+Alt+Shift+F10"
    second = "Ctrl+Alt+Shift+F11"
    assert pet.hotkey.active is None
    assert "ativo" in pet.configure_hotkey(True, first)
    modifiers, key = hotkey_codes(second)
    assert register(None, 0x5334, modifiers, key)
    try:
        assert "em uso" in pet.configure_hotkey(True, second)
        assert pet.companion_state.data["actions"]["global_shortcut"] == first
    finally:
        unregister(None, 0x5334)
    assert "ativo" in pet.configure_hotkey(True, second)
    pet.hide_pet()
    assert not pet.window.isVisible()
    # Generate a real Windows keystroke. Release every key even on failure.
    key_event = ctypes.windll.user32.keybd_event
    keys = [0x11, 0x12, 0x10, key]
    try:
        for virtual in keys:
            key_event(virtual, 0, 0, 0)
    finally:
        for virtual in reversed(keys):
            key_event(virtual, 0, 2, 0)
    for _ in range(250):
        if pet.action_search.isVisible():
            break
        QTest.qWait(20)
    assert pet.action_search.isVisible() and not pet.window.isVisible()
    assert "desativado" in pet.configure_hotkey(False, second)
    assert register(None, 0x5334, modifiers, key)
    unregister(None, 0x5334)
    assert "ativo" in pet.configure_hotkey(True, second)
    pet.shutdown()
    assert register(None, 0x5334, modifiers, key)
    unregister(None, 0x5334)


def test_first_steps_and_disabled_hotkey_persist_across_restart(pet, qapp):
    assert pet.hotkey.active is None
    menu = pet.menu
    pet.presence.select_mode("focus")
    pet.controller.set_gate("menu", True)
    assert menu.status_summary.text() == "Em foco"
    pet.controller.set_gate("menu", False)
    pet.show_first_steps()
    panel = pet.first_steps.panel
    dismiss = next(button for button in panel.findChildren(QPushButton) if "Dispensar" in button.text())
    dismiss.click()
    assert panel.isHidden()
    directory = pet.store.directory
    pet.shutdown()
    store = ConfigStore(directory)
    assert store.acquire()
    store.load()
    reopened = Companion(qapp, store)
    try:
        assert reopened.hotkey.active is None
        assert reopened.first_steps.panel.isHidden()
        reopened.actions.dispatch("first_steps")
        assert reopened.first_steps.panel.isVisible()
    finally:
        reopened.shutdown()
