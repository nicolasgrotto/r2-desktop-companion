from copy import deepcopy

from PySide6.QtTest import QTest

from r2_companion.app import Companion
from r2_companion.services.storage import ConfigStore
from test_context_v03 import pet


def test_state_survives_droid_switch_shutdown_and_native_restart(pet, qapp, monkeypatch):
    state = pet.companion_state
    lock = pet.store.lock
    legacy_audio = deepcopy(pet.store.settings.audio)
    state.update("appearance", {"theme_overrides": {"r2_default": "vigia"}})
    state.update("accessibility", {"ui_scale": 125})
    expected = state.data
    assert pet.equip_droid("vigia")
    assert pet.companion_state is state and pet.store.lock is lock and lock.isLocked()
    assert state.data == expected and not state.data["media"]["enabled"]
    pet.shutdown()
    assert not state.timer.isActive() and not lock.isLocked() and not state.dirty
    owner = ConfigStore(pet.store.directory)
    assert owner.acquire()
    owner.load()
    monkeypatch.setattr("r2_companion.app.foreground_fullscreen", lambda hwnd: False)
    replacement = Companion(qapp, owner)
    try:
        replacement.greeting_timer.stop()
        assert replacement.companion_state.data == expected
        assert replacement.companion_state.config_store is owner
        assert replacement.equip_droid("r2_default")
        assert replacement.store.settings.audio == legacy_audio
    finally:
        replacement.shutdown()
    QTest.qWait(30)
    assert not replacement.companion_state.timer.isActive() and not owner.lock.isLocked()


def test_companion_state_warning_uses_existing_notification_path(pet, monkeypatch):
    notices = []
    monkeypatch.setattr(pet.tray, "notify", lambda message: notices.append(message))
    pet.companion_state.warning.emit("Falha de persistência complementar de teste")
    assert notices == ["Falha de persistência complementar de teste"]
