import pytest
from PySide6.QtCore import QPointF
from PySide6.QtTest import QSignalSpy

from r2_companion.features.projections import ProjectionController
from test_context_v03 import pet


def test_projection_selection_survives_combined_suspension_without_updates(qapp, monkeypatch):
    values = []
    time = ["12:34:56"]

    def read_clock():
        values.append(time[0])
        return f"{time[0]}\nquinta-feira"

    monkeypatch.setattr("r2_companion.features.projections.local_clock", read_clock)
    controller = ProjectionController()
    changes = QSignalSpy(controller.changed)
    assert controller.select("date") and not controller.timer.isActive()
    assert not values
    controller.set_blocked("hidden", False)
    assert controller.model.lines == ("12:34:56", "quinta-feira")
    controller.refresh()
    assert changes.count() == 1
    controller.set_blocked("presence", True)
    controller.set_blocked("disabled", True)
    controller.set_blocked("presence", False)
    assert controller.selected == "date" and controller.model is None and not controller.timer.isActive()
    count = len(values)
    controller.refresh()
    assert len(values) == count
    time[0] = "12:35:00"
    controller.set_blocked("disabled", False)
    assert controller.model.lines[0] == "12:35:00" and controller.timer.isActive()
    controller.end()
    assert controller.selected is None and controller.model is None and not controller.timer.isActive()


def test_automatic_timer_does_not_replace_an_existing_selection(qapp):
    controller = ProjectionController()
    remaining = [("00:30", "Em andamento")]
    controller.providers["timer"] = lambda: remaining[0]
    controller.set_blocked("hidden", False)
    assert controller.select("clock")
    assert not controller.select("timer", automatic=True)
    assert not controller.select("media")
    controller.end("timer")
    assert controller.selected == "clock"
    controller.end()
    assert controller.select("timer", automatic=True)
    assert controller.model.lines == ("00:30", "Em andamento")
    remaining[0] = None
    controller.refresh()
    assert controller.selected is None and not controller.timer.isActive()


def test_projection_swap_reanchors_without_replacing_view_or_taking_focus(pet, qapp):
    pet.show_tools_page("timer")
    active = qapp.activeWindow()
    assert pet.project_tool("date")
    overlay = pet.window.projection_overlay
    initial_anchor = pet.window.projection_anchor()
    assert pet.equip_droid("pico"), pet.droid_error
    assert pet.window.projection_overlay is overlay and overlay.isVisible()
    assert pet.window.projection_kind == "date"
    assert qapp.activeWindow() is active
    x, y = pet.window.projection_anchor()
    assert (x, y) != initial_anchor
    eye = overlay.eye + QPointF(overlay.pos())
    assert eye.x() == pytest.approx(pet.window.x() + pet.window.width() * x)
    assert eye.y() == pytest.approx(pet.window.y() + pet.window.height() * y)
