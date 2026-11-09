from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPointF, QRectF, QSizeF
from PySide6.QtTest import QSignalSpy

from r2_companion.app import Companion
from r2_companion.pet.awareness import fullscreen_policy
from r2_companion.pet.behavior import BehaviorManager
from r2_companion.core.config import Settings, WindowSettings
from r2_companion.pet.positioning import detect_corner, fingerprint
from r2_companion.pet.state import State
from r2_companion.services.storage import ConfigStore
from r2_companion.services.system_info import SystemInfo


@pytest.fixture
def pet(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("r2_companion.app.foreground_fullscreen", lambda hwnd: False)
    store = ConfigStore(tmp_path)
    assert store.acquire()
    result = Companion(qapp, store)
    result.greeting_timer.stop()
    result.idle_timer.stop()
    result.desktop_timer.stop()
    result.controller.enter(State.IDLE)
    yield result
    result.shutdown()
    qapp.processEvents()


@pytest.mark.parametrize("point,expected", [(QPointF(-1912, 8), "top_left"),
    (QPointF(-168, 872), "bottom_right"), (QPointF(-1000, 400), "")])
def test_corner_detection_negative_monitor(point, expected):
    assert detect_corner(point, QRectF(-1920, 0, 1920, 1040), QSizeF(160, 160)) == expected


@pytest.mark.parametrize("mode,corner,screen,expected", [
    ("auto", "top_left", "same", "corner"), ("auto", "", "same", "hide"),
    ("corner", "bottom_right", "removed", "hide"), ("hide", "top_left", "same", "hide"),
    ("quiet", "", "same", "stay"), ("corner", "top_right", "same", "corner"),
])
def test_fullscreen_policy_requires_manual_corner_on_current_screen(mode, corner, screen, expected):
    manual = SimpleNamespace(corner=corner, screen="same")
    assert fullscreen_policy(mode, manual, screen) == expected


def test_fullscreen_hides_and_restores_with_no_motion_audio_or_bubble(pet, monkeypatch):
    pet.positioning.place(QPointF(400, 400))
    pet.controller.request(State.WALK)
    pet.bubble.present("Teste", pet.window)
    monkeypatch.setattr("r2_companion.app.foreground_fullscreen", lambda hwnd: True)
    pet.check_desktop()
    assert pet.fullscreen_active and not pet.window.isVisible()
    assert not pet.positioning.timer.isActive() and not pet.behavior.timer.isActive()
    assert not pet.bubble.isVisible() and pet.audio.suppressed
    assert not pet.controller.request(State.WALK)
    pet.controller.enter(State.WALK)
    assert not pet.positioning.timer.isActive()
    monkeypatch.setattr("r2_companion.app.foreground_fullscreen", lambda hwnd: False)
    pet.store.settings.behavior.cursor_attention = False
    pet.check_desktop()
    assert pet.window.isVisible() and "fullscreen" not in pet.controller.gates
    assert not pet.audio.suppressed


def test_manual_corner_survives_save_load_and_fullscreen(pet, monkeypatch):
    pet.positioning.place(QPointF(-100000, -100000))
    pet.drag_started()
    assert pet.controller.state == State.DRAG
    assert not pet.controller.request(State.WALK)
    pet.drag_finished()
    manual = pet.store.settings.manual_position
    assert manual.corner == "top_left"
    restored = ConfigStore(pet.store.directory)
    restored.load()
    assert restored.settings.manual_position == manual
    pet.positioning.place(QPointF(500, 500))
    monkeypatch.setattr("r2_companion.app.foreground_fullscreen", lambda hwnd: True)
    pet.check_desktop()
    assert pet.window.isVisible() and pet.fullscreen_action == "corner"
    assert detect_corner(QPointF(pet.window.pos()), QRectF(pet.positioning.screen.availableGeometry()), QSizeF(pet.window.size())) == "top_left"
    before = pet.window.pos()
    pet.awareness.observe(QPointF(700, 700))
    pet.behavior.decide()
    assert pet.window.pos() == before and not pet.positioning.timer.isActive()


def test_sleep_during_reaction_and_wake_after_gate_release(pet, clock):
    controller = pet.controller
    controller.clock = clock
    pet.awareness.clock = clock
    controller.enter(State.WORK)
    controller.update_inactivity(3600)
    controller.finished(controller.token)
    assert controller.state == State.SLEEP
    assert pet.audio.sleeping
    spy = QSignalSpy(controller.woke)
    controller.set_gate("menu", True)
    clock.advance(20)
    controller.update_inactivity(0)
    controller.set_gate("menu", False)
    assert spy.count() == 1 and spy.at(0)[0] >= 20
    assert controller.state == State.WAKE
    assert not pet.audio.sleeping


def test_cursor_observation_and_stationary_approach_are_limited(pet, clock):
    awareness = pet.awareness
    awareness.clock = clock
    pet.controller.clock = clock
    awareness.last_attention = clock() - 30
    awareness.last_approach = clock() - 181
    pet.positioning.place(QPointF(400, 400))
    center = QPointF(pet.window.geometry().center())
    cursor = center + QPointF(300, 0)
    awareness.observe(cursor)
    assert pet.controller.state == State.LOOK_RIGHT
    pet.controller.finished(pet.controller.token)
    assert pet.controller.state == State.IDLE
    clock.advance(16)
    awareness.observe(cursor)
    assert pet.controller.state == State.WALK
    assert pet.positioning.destination.x() > pet.positioning.origin.x()
    assert pet.positioning.destination.x() - pet.positioning.origin.x() <= 80
    pet.controller.enter(State.IDLE)
    awareness.observe(cursor)
    assert pet.controller.state != State.WALK
    pet.controller.set_gate("drag", True)
    clock.advance(500)
    awareness.observe(cursor)
    assert not pet.positioning.timer.isActive()


def test_system_battery_charging_cpu_and_cooldowns(pet, clock):
    awareness = pet.awareness
    awareness.clock = clock
    values = {"cpu": 10, "ram": 30, "battery": 12, "charging": False}
    awareness.info = SimpleNamespace(sample=lambda **kw: values.copy())
    awareness.sample_system()
    assert pet.controller.state == State.WORRIED
    pet.controller.enter(State.IDLE)
    awareness.sample_system()
    assert pet.controller.state == State.IDLE
    values["charging"] = True
    awareness.sample_system()
    assert pet.controller.state == State.HAPPY
    pet.controller.enter(State.IDLE)
    values["cpu"] = 95
    awareness.sample_system()
    assert pet.controller.state == State.OVERHEAT
    pet.controller.enter(State.IDLE)
    pet.controller.set_gate("fullscreen", True)
    clock.advance(1000)
    awareness.sample_system()
    assert pet.controller.state == State.IDLE


def test_battery_unavailable_and_failure_are_nonfatal():
    def unavailable():
        raise NotImplementedError()
    source = SimpleNamespace(cpu_percent=lambda interval: 10, virtual_memory=lambda: SimpleNamespace(percent=30),
                             sensors_battery=unavailable)
    values = SystemInfo(source).sample(battery=True, charging=True)
    assert values["battery"] is None and values["charging"] is None


def test_shutdown_stops_new_services_and_specific_task_sound(pet, monkeypatch):
    calls = []
    monkeypatch.setattr(pet.audio, "play", lambda category, cue=None: calls.append((category, cue)))
    pet.task_completed("one")
    assert calls == [("reactions", "celebrate")]
    pet.shutdown()
    assert not pet.awareness.timer.isActive()
    assert not pet.productivity.timer.isActive()
    assert not pet.greeting_timer.isActive()


def test_configured_weights_and_cooldowns_allow_single_expression(qapp, clock):
    behavior = BehaviorManager(clock)
    behavior.settings.movement = False
    behavior.settings.weights = {key: 100 if key == "WORK" else 0 for key in behavior.settings.weights}
    assert behavior.choose() == State.WORK
    behavior.accepted(State.WORK)
    assert behavior.choose() == State.IDLE
    clock.advance(151)
    assert behavior.choose() == State.WORK
    behavior.close()


def test_startup_fullscreen_restores_manual_corner_instead_of_last_walk(qapp, tmp_path, monkeypatch):
    from PySide6.QtGui import QGuiApplication
    monkeypatch.setattr("r2_companion.app.foreground_fullscreen", lambda hwnd: True)
    screen = QGuiApplication.primaryScreen()
    store = ConfigStore(tmp_path)
    assert store.acquire()
    settings = Settings()
    settings.window.u, settings.window.v = 0.6, 0.7
    settings.manual_position = WindowSettings(screen=fingerprint(screen), u=0, v=0, corner="top_left")
    store.apply(settings)
    pet = Companion(qapp, store)
    try:
        assert pet.fullscreen_action == "corner"
        assert detect_corner(QPointF(pet.window.pos()), QRectF(screen.availableGeometry()), QSizeF(pet.window.size())) == "top_left"
        assert not pet.positioning.timer.isActive()
    finally:
        pet.shutdown()
