from copy import deepcopy

import pytest
from PySide6.QtCore import QAbstractAnimation, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QWidget

from r2_companion.droids.themes import theme_manager
from r2_companion.ui.navigation import NAVIGATION
from test_context_v03 import pet


@pytest.fixture(autouse=True)
def native_windows_ready(pet):
    QTest.qWait(80)


def wait_transition(wheel):
    for _ in range(50):
        if not wheel.transitioning:
            return
        QTest.qWait(10)
    assert not wheel.transitioning


def click_item(pet, key):
    QTest.mouseClick(pet.radial.buttons[key], Qt.MouseButton.LeftButton)
    wait_transition(pet.radial)


@pytest.mark.parametrize("page", ["clock", "timer", "system", "tasks", "notes", "minigames", "diagnostics"])
def test_wheel_opens_each_real_page_without_projection_and_reopens_minimized(pet, page):
    pet.radial.popup_near(pet.window)
    if page not in {"minigames", "diagnostics"}:
        click_item(pet, "tools")
        assert pet.radial.level == "tools" and "radial" in pet.controller.gates
    click_item(pet, page)
    assert pet.tools.isVisible() and pet.tools.tabs.currentWidget() is pet.tools.pages[page]
    assert pet.window.hologram.isNull() and not pet.window.hologram_timer.isActive()
    assert not pet.radial.isVisible() and "radial" not in pet.controller.gates
    if page == "diagnostics":
        assert pet.tools.diagnostics_page.fields["Personagem"].text().startswith(pet.profile.name)
    pet.tools.showMinimized()
    pet.show_tools_page(page)
    assert pet.tools.isVisible() and not pet.tools.isMinimized()


def test_wheel_has_registered_levels_and_blocks_duplicates_during_real_animation(pet):
    wheel = pet.radial
    selected = QSignalSpy(wheel.action_selected)
    wheel.popup_near(pet.window)
    initial = {key: button.geometry() for key, button in wheel.buttons.items()}
    wheel.select("tools")
    assert wheel.transitioning and wheel.transition.state() == QAbstractAnimation.State.Running
    wheel.select("minigames")
    wheel.back()
    QTest.qWait(50)
    assert any(button.geometry() != initial[key] for key, button in wheel.buttons.items())
    wait_transition(wheel)
    assert wheel.level == "tools" and selected.count() == 0
    assert set(wheel.buttons) == {item.id for item in NAVIGATION["tools"]}
    QTest.mouseClick(wheel.center, Qt.MouseButton.LeftButton)
    wait_transition(wheel)
    assert wheel.level == "main" and wheel.history == []
    wheel.select("configuration")
    wait_transition(wheel)
    wheel.select("companion")
    wait_transition(wheel)
    wheel.back()
    wait_transition(wheel)
    assert wheel.level == "configuration" and wheel.history == ["main"]
    wheel.back()
    wait_transition(wheel)
    assert wheel.level == "main"


@pytest.mark.parametrize("dismiss", ["escape", "outside", "close", "timeout"])
def test_wheel_cleans_up_mid_transition_and_starts_at_root(pet, dismiss):
    wheel = pet.radial
    wheel.popup_near(pet.window)
    wheel.select("tools")
    outside = QWidget()
    if dismiss == "escape":
        QTest.keyClick(wheel, Qt.Key.Key_Escape)
    elif dismiss == "outside":
        outside.show()
        QTest.mouseClick(outside, Qt.MouseButton.LeftButton)
    elif dismiss == "close":
        wheel.close_button.click()
    else:
        wheel.dismiss_timer.timeout.emit()
    outside.close()
    assert not wheel.isVisible() and not wheel.transitioning and wheel.transition is None
    assert wheel.level == "main" and wheel.history == []
    assert not wheel.dismiss_timer.isActive() and "radial" not in pet.controller.gates
    QTest.qWait(300)
    wheel.popup_near(pet.window)
    assert wheel.level == "main" and all(button.isEnabled() for button in wheel.buttons.values())


@pytest.mark.parametrize("identifier", ["r2_default", "dark_astromech", "spherical_droid"])
def test_wheel_submenus_and_live_projections_follow_equipped_theme(pet, identifier):
    assert pet.equip_droid(identifier)
    pet.radial.popup_near(pet.window)
    click_item(pet, "project")
    assert pet.profile.theme.colors["hero"] in pet.radial.styleSheet()
    click_item(pet, "project_clock")
    assert pet.window.projection_kind == "clock"
    assert len(pet.window.projection_text.split(":")) == 3
    assert not pet.window.hologram.isNull() and pet.window.projection_timer.isActive()
    QTest.qWait(1900)
    assert not pet.window.hologram.isNull() and not pet.window.hologram_timer.isActive()
    pet.project_tool("date")
    assert "\n" in pet.window.projection_text
    pet.window.hide()
    assert not pet.window.projection_timer.isActive()
    pet.window.show()
    assert pet.window.projection_timer.isActive()
    pet.radial.popup_near(pet.window)
    click_item(pet, "project")
    click_item(pet, "project_stop")
    assert pet.window.hologram.isNull() and not pet.window.projection_timer.isActive()


def test_projection_validates_availability_preserves_tools_and_refreshes_time(pet, monkeypatch):
    monkeypatch.setattr("r2_companion.pet.window.local_clock", lambda: "12:34:56\nquinta-feira, 12 de novembro")
    assert pet.project_tool("date")
    assert pet.window.projection_text == "12:34:56\nquinta-feira, 12 de novembro"
    monkeypatch.setattr("r2_companion.pet.window.local_clock", lambda: "12:34:57\nquinta-feira, 12 de novembro")
    pet.window.projection_timer.timeout.emit()
    assert pet.window.projection_text.startswith("12:34:57")
    pet.show_tools_page("minigames")
    assert pet.window.projection_kind == "date"
    assert not pet.project_tool("unsupported")
    assert pet.window.projection_kind == "date"
    pet.window.clear_projection()
    pet.store.settings.holograms = False
    assert not pet.project_tool("clock")
    assert pet.window.hologram.isNull()


@pytest.mark.parametrize("key", ["tools", "clock", "timer", "system", "tasks", "notes", "minigames", "diagnostics",
                                  "settings", "garage", "audio", "project_clock", "project_date", "project_stop"])
def test_context_menu_native_click_routes_each_action_without_accidental_projection(pet, key):
    pet.refresh_menu()
    action = next(action for action in pet.menu.action_refs if action.data() == key)
    owner = action.parent()
    owner.popup(pet.window.pos())
    QTest.qWait(20)
    QTest.mouseClick(owner, Qt.MouseButton.LeftButton, pos=owner.actionGeometry(action).center())
    QTest.qWait(30)
    if key in pet.tools.pages or key == "tools":
        assert pet.tools.isVisible()
        if key != "tools":
            assert pet.tools.tabs.currentWidget() is pet.tools.pages[key]
    elif key == "settings":
        assert pet.settings_dialog.isVisible()
        pet.settings_dialog.close()
    elif key in {"garage", "audio"}:
        assert getattr(pet, key + "_dialog").isVisible()
    else:
        assert pet.window.projection_kind == {"project_clock": "clock", "project_date": "date", "project_stop": None}[key]
    if not key.startswith("project_"):
        assert pet.window.hologram.isNull()


def test_garage_is_only_animation_entry_and_keeps_repeat_frames_and_independent_preview(pet):
    assert all("Galeria" not in action.text() for action in pet.menu.action_refs)
    assert not hasattr(pet, "gallery_dialog") and not hasattr(pet, "show_animation_gallery")
    pet.show_garage()
    garage = pet.garage_dialog
    before = deepcopy(pet.store.settings)
    active_theme = theme_manager().active
    garage.selector.setCurrentIndex(garage.selector.findData("spherical_droid"))
    garage.category.setCurrentIndex(garage.category.findData("Locomoção"))
    garage.repeat.setChecked(False)
    garage.play()
    assert not garage.animation.clip.loop
    garage.repeat.setChecked(True)
    garage.play()
    assert garage.animation.clip.loop
    previous = garage.animations.currentRow()
    garage.step(1)
    assert garage.animations.currentRow() != previous
    garage.frame_variant.setCurrentIndex(1)
    assert not garage.animation.timer.isActive() and not garage.preview.roll_timer.isActive()
    garage.close()
    pet.show_garage()
    assert garage.clips and garage.isVisible()
    assert pet.store.settings == before and theme_manager().active == active_theme


def test_every_context_action_retains_its_registered_callback_and_identifier(qapp):
    from r2_companion.core.config import Settings
    from r2_companion.ui.context_menu import create_menu
    keys = {"interact", "tools", "garage", "audio", "clock", "timer", "system", "tasks", "notes", "minigames",
            "diagnostics", "settings", "updates", "show", "hide", "pause", "restore", "pass_through", "exit",
            "project_clock", "project_date", "project_stop"}
    calls = []
    actions = {key: lambda key=key: calls.append(key) for key in keys}
    actions.update(paused=lambda: False, passing=lambda: False)
    menu = create_menu(None, actions, Settings(), [], True)
    seen = set()
    for action in menu.action_refs:
        if action in seen or action.menu() is not None or action.isSeparator():
            continue
        seen.add(action)
        calls.clear()
        action.trigger()
        assert calls == [action.data()]
    assert keys <= {action.data() for action in seen}
    menu.deleteLater()
