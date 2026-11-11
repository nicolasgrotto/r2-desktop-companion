import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtTest import QTest
from r2_companion.pet.awareness import escape_destination
from r2_companion.pet.state import State
from test_context_v03 import pet


def test_diagnosis_stays_scrollable_and_never_enlarges_other_tools(pet):
    pet.show_tools_page('diagnostics')
    pet.tools.resize(480, 360)
    QTest.qWait(50)
    page = pet.tools.diagnostics_page
    page.finish()
    QTest.qWait(30)
    assert pet.tools.height() <= 400
    assert max(page.verticalScrollBar().maximum(), pet.tools.scroll_area.verticalScrollBar().maximum()) > 0
    assert 'Locomoção' not in page.fields and 'Renderizador' not in page.fields
    assert 'Efeitos carregados' not in page.fields and 'CPU' in page.fields
    assert len(page.fields) <= 9
    for name in ('clock', 'timer', 'notes', 'minigames', 'diagnostics'):
        pet.show_tools_page(name)
        QTest.qWait(10)
        assert pet.tools.height() <= 400


@pytest.mark.parametrize('top', [10, 350])
def test_projection_is_outside_pet_and_follows_without_capturing_input(pet, top):
    pet.positioning.place(QPointF(400, top))
    pet.project_tool('date')
    QTest.qWait(30)
    overlay = pet.window.projection_overlay
    card = overlay.card.translated(overlay.x(), overlay.y())
    assert overlay.isVisible()
    assert not card.intersects(QRectF(pet.window.geometry()))
    if top == 10:
        assert card.top() > pet.window.geometry().bottom()
    else:
        assert card.bottom() < pet.window.y()
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    original = overlay.geometry()
    pet.positioning.place(QPointF(500, top))
    assert overlay.geometry() != original
    pet.window.hide()
    assert not overlay.isVisible()
    pet.window.show()
    assert overlay.isVisible()
    pet.window.clear_projection()
    assert not overlay.isVisible()


@pytest.mark.parametrize('obstacle', [QRectF(100, 100, 500, 400), QRectF(-400, 100, 400, 400)])
def test_escape_chooses_a_visible_destination_outside_window(obstacle):
    pet_rect = QRectF(obstacle.center().x(), 200, 100, 100)
    area = QRectF(-600, 0, 1800, 850)
    target = escape_destination(pet_rect, obstacle, area)
    assert target is not None
    assert not QRectF(target, pet_rect.size()).intersects(obstacle)
    assert area.contains(QRectF(target, pet_rect.size()))
    assert escape_destination(pet_rect, area, area) is None


def test_robot_walks_out_of_obstructed_window_using_existing_controller(pet):
    pet.positioning.place(QPointF(400, 300))
    obstacle = QRectF(300, 200, 400, 400)
    for _ in range(8):
        if not QRectF(pet.window.geometry()).intersects(obstacle):
            break
        pet.controller.enter(State.IDLE)
        assert pet.awareness.avoid_window(obstacle)
        assert pet.controller.state == State.WALK
        assert pet.positioning.timer.isActive()
        pet.positioning.started -= 10
        pet.positioning.tick()
    assert not QRectF(pet.window.geometry()).intersects(obstacle)


@pytest.mark.parametrize('blocked', ['pause', 'drag', 'sleep', 'movement', 'frequency'])
def test_avoidance_respects_user_and_lifecycle_controls(pet, blocked):
    if blocked == 'pause':
        pet.controller.set_paused(True)
    elif blocked == 'drag':
        pet.controller.set_gate('drag', True)
    elif blocked == 'sleep':
        pet.controller.enter(State.SLEEP)
    elif blocked == 'movement':
        pet.store.settings.behavior.movement = False
    else:
        pet.store.settings.behavior.frequency = 'off'
    assert not pet.awareness.avoid_window(QRectF(pet.window.geometry()))


def test_open_tools_is_detected_as_an_obstacle(pet, monkeypatch):
    pet.show_tools()
    QTest.qWait(50)
    pet.positioning.place(QPointF(pet.tools.x() + 50, pet.tools.y() + 50))
    pet.controller.enter(State.IDLE)
    calls = []
    monkeypatch.setattr(pet.awareness, 'avoid_window', lambda rect: calls.append(rect))
    pet.check_desktop()
    assert calls and calls[0] == QRectF(pet.tools.frameGeometry())


def test_native_foreground_window_uses_monitor_origin_and_dpi(monkeypatch):
    from ctypes import wintypes
    from types import SimpleNamespace
    from r2_companion.services import windows
    def get_rect(handle, pointer):
        r = pointer._obj
        r.left, r.top, r.right, r.bottom = -1800, 100, -1200, 700
        return True
    def monitor(handle, pointer):
        pointer._obj.rcMonitor = wintypes.RECT(-1920, 0, 0, 1080)
        return True
    fake = SimpleNamespace(GetForegroundWindow=lambda: 99, IsZoomed=lambda h: False,
                           GetClassNameW=lambda *a: 0, GetWindowRect=get_rect,
                           MonitorFromWindow=lambda *a: 1, GetMonitorInfoW=monitor)
    monkeypatch.setattr(windows, 'user32', fake)
    screen = SimpleNamespace(devicePixelRatio=lambda: 1.5,
        geometry=lambda: QRectF(-1280, 0, 1280, 720), availableGeometry=lambda: QRectF(-1280, 0, 1280, 680))
    rect = windows.foreground_window_rect(12, screen)
    assert rect == QRectF(-1200, 100 / 1.5, 400, 400)
    fake.IsZoomed = lambda h: True
    assert windows.foreground_window_rect(12, screen) is None
