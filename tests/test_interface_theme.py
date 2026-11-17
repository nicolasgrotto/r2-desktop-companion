from copy import deepcopy
import json

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QSignalSpy, QTest

from r2_companion.app import ASSETS, Companion
from r2_companion.droids.profiles import DroidRegistry
from r2_companion.droids.themes import resolve_theme, theme_for, theme_manager
from r2_companion.services.companion_state import CompanionStateStore
from r2_companion.services.storage import ConfigStore
from test_context_v03 import pet


DROIDS = ("dark_astromech", "lumo", "pico", "r2_default", "spherical_droid", "tranco", "vigia")


@pytest.fixture(scope="module")
def registry():
    return DroidRegistry(ASSETS)


@pytest.mark.parametrize("droid_id", DROIDS)
@pytest.mark.parametrize("provider_id", DROIDS)
def test_theme_resolution_for_every_droid_and_provider(registry, droid_id, provider_id):
    profile = registry.get(droid_id)
    assert resolve_theme(registry, profile, provider_id) is registry.get(provider_id).theme
    assert resolve_theme(registry, profile, None) is profile.theme
    assert resolve_theme(registry, profile, "unavailable") is profile.theme


def test_theme_save_preserves_unknown_fields_backup_and_read_only(qapp, tmp_path, monkeypatch):
    config = ConfigStore(tmp_path)
    assert config.acquire()
    state = CompanionStateStore(config)
    try:
        state.update("appearance", {"theme_overrides": {"pico": "unavailable"}, "future_option": [3]})
        state.update("accessibility", {"ui_scale": 125})
        assert state.save_theme_override("r2_default", "vigia")
        assert not state.dirty and not state.timer.isActive()
        saved = state.path.read_bytes()
        assert state.save_theme_override("r2_default", None)
        assert state.backup.read_bytes() == saved
        assert state.data["appearance"] == {"theme_overrides": {"pico": "unavailable"}, "future_option": [3]}
        assert state.data["accessibility"]["ui_scale"] == 125

        previous = state.data
        changes = QSignalSpy(state.changed)
        writer = ConfigStore.atomic_write

        def fail_primary(path, data):
            if path == state.path:
                raise OSError("simulated failure")
            writer(path, data)

        with monkeypatch.context() as patch:
            patch.setattr(ConfigStore, "atomic_write", staticmethod(fail_primary))
            assert not state.save_theme_override("r2_default", "vigia")
        assert state.data == previous and changes.count() == 0

        with monkeypatch.context() as patch:
            patch.setattr(config, "read_only", True)
            original = state.path.read_bytes()
            assert not state.save_theme_override("r2_default", "vigia")
            assert state.path.read_bytes() == original and state.data == previous
        state.path.write_text("{broken", encoding="utf-8")
        restored = CompanionStateStore(config)
        try:
            assert restored.data == previous
        finally:
            restored.close()
    finally:
        state.close()
        config.close()


def test_garage_theme_only_updates_open_surfaces_and_persists_on_restart(pet, qapp):
    manager = theme_manager()
    r2 = pet.profile
    vigia_theme = pet.droids.get("vigia").theme
    pet.show_tools_page("timer")
    pet.show_audio_center()
    pet.show_garage()
    garage = pet.garage_dialog
    icon = pet.tools.start_button.icon().cacheKey()
    original_styles = {widget: widget.styleSheet() for widget in (pet.tools, pet.audio_dialog, pet.radial, pet.menu)}
    original = deepcopy(pet.store.settings)
    identity = (pet.profile, pet.audio.profile_id, pet.animation.clips, pet.positioning.movement,
                pet.window.visual, pet.window.accent)
    changes = QSignalSpy(manager.changed)

    garage.theme_choice.setCurrentIndex(garage.theme_choice.findData("vigia"))
    assert theme_for(garage) == vigia_theme and manager.active == r2.theme
    assert changes.count() == 0
    garage.close()
    pet.show_garage()
    assert garage.theme_choice.currentData() is None

    garage.theme_choice.setCurrentIndex(garage.theme_choice.findData("vigia"))
    assert pet.project_tool("clock")
    projection = pet.window.hologram.cacheKey()
    garage.save_theme_button.click()
    assert manager.active == vigia_theme and changes.count() == 1
    assert pet.droid_diagnostics()["Tema"] == vigia_theme.name
    assert pet.droid_diagnostics()["Tema original"] == r2.theme.name
    assert pet.tools.start_button.icon().cacheKey() != icon
    assert all(widget.styleSheet() != style for widget, style in original_styles.items())
    assert pet.window.projection_kind == "clock" and pet.window.hologram.cacheKey() != projection
    assert pet.store.settings == original
    assert (pet.profile, pet.audio.profile_id, pet.animation.clips, pet.positioning.movement,
            pet.window.visual, pet.window.accent) == identity
    assert json.loads(pet.companion_state.path.read_text())["appearance"]["theme_overrides"] == {"r2_default": "vigia"}
    assert pet.equip_droid("pico") and manager.active == pet.profile.theme
    assert pet.equip_droid("r2_default") and manager.active == vigia_theme

    directory = pet.store.directory
    pet.shutdown()
    reopened = ConfigStore(directory)
    assert reopened.acquire()
    reopened.load()
    companion = Companion(qapp, reopened)
    try:
        assert companion.profile.id == companion.audio.profile_id == "r2_default"
        assert manager.active == vigia_theme
        companion.show_garage()
        editor = companion.garage_dialog
        assert editor.theme_choice.currentData() == "vigia"
        editor.theme_choice.setCurrentIndex(0)
        editor.save_theme_button.click()
        assert manager.active == companion.profile.theme
        assert not companion.companion_state.data["appearance"]["theme_overrides"]
    finally:
        companion.shutdown()


def test_theme_selector_keyboard_and_fallback_at_all_scales(pet, monkeypatch):
    pet.companion_state.update("appearance", {"theme_overrides": {"r2_default": "unavailable", "pico": "lumo"}})
    pet.show_garage()
    garage = pet.garage_dialog
    select = garage.theme_choice
    try:
        assert select.currentData() == "unavailable"
        assert not select.model().item(select.currentIndex()).isEnabled()
        assert "indisponível" in garage.theme_status.text()
        assert theme_manager().active == pet.profile.theme
        assert pet.companion_state.theme_override_for("r2_default") == "unavailable"
        assert QAccessible.queryAccessibleInterface(select).text(QAccessible.Text.Name) == "Tema da interface"
        garage.activateWindow()
        assert QTest.qWaitForWindowActive(garage, 2000)
        for scale in (100, 125, 150):
            pet.companion_state.update("accessibility", {"ui_scale": scale})
            garage.resize(360, 420)
            QTest.qWait(30)
            select.setFocus()
            assert select.hasFocus()
            QTest.keyClick(select, Qt.Key.Key_Home)
            assert select.currentIndex() == 0
            assert garage.save_theme_button.isEnabled()
            QTest.keyClick(select, Qt.Key.Key_Tab)
            assert garage.save_theme_button.hasFocus()
            assert garage.scroll_area.horizontalScrollBar().maximum() == 0
            QTest.keyClick(garage.save_theme_button, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
            assert select.hasFocus()
        QTest.keyClick(select, Qt.Key.Key_Tab)
        QTest.keyClick(garage.save_theme_button, Qt.Key.Key_Space)
        assert pet.companion_state.theme_override_for("r2_default") is None
        assert pet.companion_state.theme_override_for("pico") == "lumo"
        with monkeypatch.context() as patch:
            patch.setattr(pet.store, "read_only", True)
            garage.close()
            pet.show_garage()
            assert not select.isEnabled() and not garage.save_theme_button.isEnabled()
            assert "somente leitura" in garage.theme_status.text()
    finally:
        theme_manager().set_ui_scale(100)
