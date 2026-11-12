import json
import sys

import pytest
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QWidget

from r2_companion.ui.navigation import NAVIGATION
from test_context_v03 import pet
from test_navigation_v111 import wait_transition


def enter(wheel, level):
    wheel.select(level)
    wait_transition(wheel)
    assert wheel.level == level and wheel.isVisible()


def test_mouse_press_and_release_on_pet_close_the_same_wheel_once(pet):
    wheel = pet.radial
    wheel.popup_near(pet.window)
    opened, dismissed = QSignalSpy(wheel.opened), QSignalSpy(wheel.dismissed)
    QTest.mouseClick(pet.window, Qt.MouseButton.LeftButton, pos=QPoint(80, 110))
    assert not wheel.isVisible()
    assert opened.count() == 0 and dismissed.count() == 1
    assert "radial" not in pet.controller.gates


def test_repeated_pet_clicks_preserve_personality_without_vetoing_navigation(pet, monkeypatch):
    monkeypatch.setattr(pet.awareness, "clock", lambda: 1000)
    for _ in range(8):
        QTest.mouseClick(pet.window, Qt.MouseButton.LeftButton, pos=QPoint(80, 110))
        assert pet.radial.isVisible()
        QTest.mouseClick(pet.radial.buttons["minigames"], Qt.MouseButton.LeftButton)
        assert pet.tools.isVisible() and pet.tools.tabs.currentWidget() is pet.tools.pages["minigames"]
        assert "radial" not in pet.controller.gates
        pet.tools.close()
    assert any(entry for entry in pet.awareness.clicks)
    assert pet.controller.state.name == "CONFUSED"


@pytest.mark.parametrize("deliver_release", [True, False])
def test_single_click_after_double_click_is_not_discarded_by_the_previous_gesture(pet, deliver_release):
    point = QPoint(80, 110)
    QTest.mouseClick(pet.window, Qt.MouseButton.LeftButton, pos=point)
    assert pet.radial.isVisible()
    QTest.mouseDClick(pet.window, Qt.MouseButton.LeftButton, pos=point)
    assert pet.window.double_click and not pet.radial.isVisible()
    if deliver_release:
        QTest.mouseRelease(pet.window, Qt.MouseButton.LeftButton, pos=point)
        assert not pet.window.double_click
    QTest.mouseClick(pet.window, Qt.MouseButton.LeftButton, pos=point)
    assert pet.radial.isVisible() and not pet.window.double_click
    QTest.mouseClick(pet.radial.buttons["minigames"], Qt.MouseButton.LeftButton)
    assert pet.tools.isVisible() and pet.tools.tabs.currentWidget() is pet.tools.pages["minigames"]


@pytest.mark.parametrize("phase", ["exiting", "entering"])
@pytest.mark.parametrize("interrupt", ["stop", "pause", "destroy"])
def test_interrupted_animation_restores_rendered_page_and_allows_real_action(pet, phase, interrupt):
    wheel = pet.radial
    wheel.popup_near(pet.window)
    wheel.select("tools")
    if phase == "entering":
        wheel.transition.setCurrentTime(wheel.transition.duration())
    assert wheel.phase == phase
    group = wheel.transition
    if interrupt == "destroy":
        group.deleteLater()
        QCoreApplication.sendPostedEvents(group, QEvent.Type.DeferredDelete)
    else:
        getattr(group, interrupt)()
    assert not wheel.transitioning and wheel.transition is None
    assert wheel.level == ("tools" if phase == "entering" else "main")
    assert all(button.isEnabled() and button.geometry() == wheel.button_rect(index, len(wheel.buttons))
               and button.graphicsEffect().opacity() == 1 for index, button in enumerate(wheel.buttons.values()))
    if wheel.level == "main":
        enter(wheel, "tools")
    QTest.mouseClick(wheel.buttons["clock"], Qt.MouseButton.LeftButton)
    assert pet.tools.isVisible() and pet.tools.tabs.currentWidget() is pet.tools.pages["clock"]
    assert not wheel.isVisible() and "radial" not in pet.controller.gates


def test_click_on_a_rendered_incoming_item_executes_without_waiting_for_animation(pet):
    wheel = pet.radial
    wheel.popup_near(pet.window)
    wheel.select("tools")
    wheel.transition.setCurrentTime(wheel.transition.duration())
    assert wheel.level == "tools" and wheel.phase == "entering"
    QTest.mouseClick(wheel.buttons["notes"], Qt.MouseButton.LeftButton)
    assert pet.tools.isVisible() and pet.tools.tabs.currentWidget() is pet.tools.pages["notes"]
    assert not wheel.transitioning and "radial" not in pet.controller.gates


@pytest.mark.parametrize("phase", ["exiting", "entering"])
def test_closing_and_reopening_rejects_callbacks_from_retired_animation(pet, phase):
    wheel = pet.radial
    wheel.popup_near(pet.window)
    wheel.select("tools")
    if phase == "entering":
        wheel.transition.setCurrentTime(wheel.transition.duration())
    old = wheel.transition
    wheel.hide()
    wheel.popup_near(pet.window)
    old.finished.emit()
    assert wheel.level == "main" and not wheel.transitioning and wheel.history == []
    assert all(button.isEnabled() for button in wheel.buttons.values())
    wheel.buttons["diagnostics"].click()
    assert pet.tools.isVisible()


@pytest.mark.parametrize("action", [item.id for items in NAVIGATION.values() for item in items if item.id not in NAVIGATION])
def test_every_leaf_uses_the_live_controller_and_preserves_all_droid_data(pet, action, monkeypatch):
    before = pet.store.settings.to_dict()["droid_preferences"]
    updates = []
    monkeypatch.setattr(pet.updates, "launch_center", lambda: updates.append(True))
    wheel = pet.radial
    wheel.popup_near(pet.window)
    parent = next(level for level, items in NAVIGATION.items() if any(item.id == action for item in items))
    if parent != "main":
        if parent == "companion":
            enter(wheel, "configuration")
        enter(wheel, parent)
    QTest.mouseClick(wheel.buttons[action], Qt.MouseButton.LeftButton)
    assert not wheel.isVisible() and "radial" not in pet.controller.gates
    destination = pet.navigation_destination(action)
    if destination is not None:
        assert destination.isVisible() and not destination.isMinimized()
    elif action == "updates":
        assert updates == [True]
    elif action.startswith("project_"):
        assert pet.window.projection_kind == {"project_clock": "clock", "project_date": "date", "project_stop": None}[action]
    elif action == "pause":
        assert pet.controller.paused
    elif action == "explore":
        assert pet.controller.state.name == "WALK"
    assert pet.store.settings.to_dict()["droid_preferences"] == before
    if pet.settings_dialog is not None:
        pet.settings_dialog.close()


@pytest.mark.parametrize("component", ["tools", "garage", "audio", "settings"])
def test_navigation_survives_secondary_windows_minimization_and_recreation(pet, component):
    action = {"tools": pet.show_tools, "garage": pet.show_garage,
              "audio": pet.show_audio_center, "settings": pet.show_settings}[component]
    action()
    widget = pet.navigation_destination(component)
    widget.showMinimized()
    action()
    assert widget.isVisible() and not widget.isMinimized()
    widget.close()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    action()
    assert pet.navigation_destination(component).isVisible()
    pet.window.showMinimized()
    pet.window.showNormal()
    pet.radial.popup_near(pet.window)
    pet.radial.buttons["minigames"].click()
    assert pet.tools.isVisible() and pet.tools.tabs.currentWidget() is pet.tools.pages["minigames"]
    if pet.settings_dialog is not None:
        pet.settings_dialog.close()


def test_lost_and_recovered_activation_cancels_pending_dismissal(pet, qapp):
    wheel = pet.radial
    wheel.popup_near(pet.window)
    qapp.sendEvent(wheel, QEvent(QEvent.Type.WindowDeactivate))
    assert wheel.deactivate_timer.isActive()
    qapp.sendEvent(wheel, QEvent(QEvent.Type.WindowActivate))
    assert not wheel.deactivate_timer.isActive()
    enter(wheel, "tools")
    wheel.buttons["timer"].click()
    assert pet.tools.tabs.currentWidget() is pet.tools.pages["timer"] and pet.tools.isVisible()


def test_callback_exception_is_correlated_and_never_keeps_the_radial_gate(pet, monkeypatch):
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda kind, value, tb: errors.append(value))

    def fail():
        raise RuntimeError("callback failed")

    monkeypatch.setattr(pet, "navigation_actions", lambda: {"diagnostics": fail})
    pet.radial.popup_near(pet.window)
    pet.radial.buttons["diagnostics"].click()
    assert len(errors) == 1 and isinstance(errors[0], RuntimeError)
    assert not pet.radial.isVisible() and "radial" not in pet.controller.gates
    pet.navigation_trace.close()
    records = [json.loads(line) for line in (pet.store.directory / "navigation.jsonl").read_text().splitlines()]
    failure = next(record for record in records if record["event"] == "callback_failed")
    assert failure["exception"] == "RuntimeError" and failure["action"] == "diagnostics"
    assert any(record["event"] == "item_selected" and record["attempt"] == failure["attempt"] for record in records)
    assert not any(record["event"] == "callback_completed" for record in records)


def test_invalid_callback_reports_an_error_and_cannot_announce_success(pet, monkeypatch):
    monkeypatch.setattr(pet, "navigation_actions", lambda: {"diagnostics": None})
    with pytest.raises(ValueError, match="callback"):
        pet.radial_action("diagnostics")


@pytest.mark.parametrize("phase", ["exiting", "entering"])
def test_shutdown_during_transition_releases_all_animation_and_trace_resources(pet, phase):
    pet.radial.popup_near(pet.window)
    pet.radial.select("tools")
    if phase == "entering":
        pet.radial.transition.setCurrentTime(pet.radial.transition.duration())
    pet.shutdown()
    assert not pet.radial.transitioning and pet.radial.transition is None
    assert not pet.radial.isVisible() and not pet.navigation_trace.worker.is_alive()
