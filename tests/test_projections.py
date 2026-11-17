import pytest
from PySide6.QtCore import QPointF, QRectF, QSizeF
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QSignalSpy, QTest

from r2_companion.droids.themes import theme_manager

from r2_companion.features.projections import ProjectionController, ProjectionModel
from r2_companion.ui.projection import card_size, place_card, render_card
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
    remaining = [ProjectionModel("timer", "Temporizador", ("00:30", "Em andamento"))]
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


@pytest.mark.parametrize(("x", "y"), [(-1580, -310), (-1300, -310), (-620, 80), (-1500, 210)])
def test_cards_fit_each_edge_in_negative_monitor_coordinates(x, y):
    work = QRectF(-1600, -320, 1120, 680)
    pet_rect = QRectF(x, y, 144, 144)
    card = place_card(work, pet_rect, QSizeF(372, 160))
    assert work.contains(card) and not card.intersects(pet_rect)
    assert card.size() == QSizeF(372, 160)


def test_small_work_area_uses_side_space_and_bounds_the_card():
    work = QRectF(-520, -30, 520, 220)
    pet_rect = QRectF(-355, 10, 165, 153)
    card = place_card(work, pet_rect, QSizeF(372, 230))
    assert work.contains(card) and not card.intersects(pet_rect)
    assert card.width() < 372 and card.height() < 230


@pytest.mark.parametrize("dpr", [1.0, 1.5, 2.0])
@pytest.mark.parametrize("kind", ["clock", "date", "timer", "focus", "task", "media"])
def test_card_renders_losslessly_for_accessibility_and_uses_dip_once(qapp, dpr, kind):
    manager = theme_manager()
    prefix = "Uma informação longa " * 80
    model = ProjectionModel(kind, "Título", (prefix + "final inteiro",), 0.4)
    alternate = ProjectionModel(kind, "Título", (prefix + "outro final",), 0.4)
    dip = lambda value: round(value * 1.5)
    size = card_size(model, dip)
    colors = manager.active.colors
    picture = render_card(model, size, dpr, colors, dip)
    assert picture.devicePixelRatio() == dpr
    assert picture.width() == round(size.width() * dpr) and picture.height() == round(size.height() * dpr)
    assert picture.toImage() == render_card(alternate, size, dpr, colors, dip).toImage()
    assert model.accessible_text.endswith("final inteiro")


def test_render_cache_scale_theme_full_text_and_static_projection_on_windows(pet, qapp, monkeypatch):
    monkeypatch.setattr("r2_companion.features.projections.local_clock", lambda: "13:10:08\nquinta-feira")
    pet.show_tools_page("clock")
    assert QTest.qWaitForWindowActive(pet.tools, 2000)
    assert pet.project_tool("date")
    overlay = pet.window.projection_overlay
    original = overlay.picture.cacheKey()
    overlay.reposition()
    pet.window.refresh_projection()
    assert overlay.picture.cacheKey() == original

    active = qapp.activeWindow()
    for scale in (125, 150):
        width = overlay.card.width()
        pet.companion_state.update("accessibility", {"ui_scale": scale, "reduced_motion": True})
        assert overlay.card.width() > width and qapp.activeWindow() is active
    original = overlay.picture.cacheKey()
    assert pet.companion_state.save_theme_override(pet.profile.id, "vigia")
    assert overlay.picture.cacheKey() != original and pet.profile.id == "r2_default"

    model = ProjectionModel("media", "Música", ("Faixa muito longa " * 60, "Artista completo"))
    assert not pet.window.show_projection("media")
    pet.window.projection.providers["media"] = lambda: model
    assert pet.window.show_projection("media")
    assert pet.tools.projection_details.toPlainText() == model.accessible_text
    accessible = QAccessible.queryAccessibleInterface(pet.tools.projection_details)
    assert accessible.text(QAccessible.Text.Name) == "Conteúdo da projeção"
    assert accessible.text(QAccessible.Text.Value) == model.accessible_text
    assert accessible.state().readOnly
    assert not pet.window.projection_timer.isActive()
    pet.window.hide()
    assert pet.window.projection_kind == "media" and not overlay.isVisible()
    assert not pet.window.projection_timer.isActive() and not pet.window.hologram_timer.isActive()
