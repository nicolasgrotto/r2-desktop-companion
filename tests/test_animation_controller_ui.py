import json
from pathlib import Path

import pytest
from PySide6.QtCore import QObject, QPoint, QPointF, Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QApplication

from r2_companion.app import ASSETS, Companion
from r2_companion.core.config import Settings
from r2_companion.pet.animation import AnimationManager, load_clips
from r2_companion.pet.behavior import BehaviorManager
from r2_companion.pet.controller import PetController
from r2_companion.pet.state import State
from r2_companion.services.storage import ConfigStore
from r2_companion.core.config import Shortcut, Target
from r2_companion.ui.context_menu import create_menu


@pytest.fixture
def clips(qapp):
    return load_clips(ASSETS / "characters/default/manifest.json")


class Motion(QObject):
    movement_finished = Signal(int)

    def __init__(self):
        super().__init__()
        self.running = False

    def walk(self, distance, duration, token):
        self.running = True
        self.token = token
        return True

    def stop(self):
        self.running = False


@pytest.fixture
def controller(qapp, clock, clips):
    animation = AnimationManager(clips, clock)
    motion = Motion()
    behavior = BehaviorManager(clock)
    result = PetController(animation, motion, behavior, clock)
    result.start()
    yield result
    result.close()


def test_animation_static_loop_does_not_poll(qapp, clips, clock):
    animation = AnimationManager(clips, clock)
    frames = QSignalSpy(animation.frame_changed)
    animation.play(State.IDLE, 1)
    assert frames.count() == 1
    assert not animation.timer.isActive()
    animation.stop()


def test_animation_skips_delayed_frames_and_completes_once(qapp, clips, clock):
    animation = AnimationManager(clips, clock)
    frames = QSignalSpy(animation.frame_changed)
    done = QSignalSpy(animation.clip_finished)
    animation.play(State.HAPPY, 12)
    clock.advance(0.4)
    animation.tick()
    assert animation.last_frame == 2
    assert frames.count() == 2
    clock.advance(100)
    animation.tick()
    animation.tick()
    assert done.count() == 1 and done.at(0)[0] == 12
    assert not animation.timer.isActive()


@pytest.mark.parametrize("change", ["traversal", "rectangle", "duration", "missing_idle", "wrong_version", "reaction_loop"])
def test_invalid_animation_manifest_rejected(qapp, tmp_path, change):
    source = ASSETS / "characters/default"
    data = json.loads((source / "manifest.json").read_text())
    (tmp_path / "placeholder.png").write_bytes((source / "placeholder.png").read_bytes())
    if change == "traversal":
        data["clips"]["IDLE"]["frames"][0]["image"] = "../escape.png"
    elif change == "rectangle":
        data["clips"]["IDLE"]["frames"][0]["rect"] = [2000, 0, 64, 64]
    elif change == "duration":
        data["clips"]["IDLE"]["frames"][0]["duration_ms"] = 0
    elif change == "missing_idle":
        del data["clips"]["IDLE"]
    elif change == "wrong_version":
        data["manifest_version"] = 99
    else:
        data["clips"]["INTERACT"]["loop"] = True
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError):
        load_clips(manifest)


def test_sequence_png_and_optional_state_fallback(qapp, tmp_path):
    source = ASSETS / "characters/default/placeholder.png"
    from PySide6.QtGui import QImage
    image = QImage(str(source)).copy(0, 0, 64, 64)
    image.save(str(tmp_path / "idle.png"))
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"manifest_version": 1, "clips": {
        "IDLE": {"loop": True, "frames": [{"image": "idle.png", "duration_ms": 1000}]}}}))
    clips = load_clips(manifest)
    assert set(clips) == set(State)
    assert not clips[State.INTERACT].loop


def test_interaction_cancels_walk_and_stale_completion(controller, clock):
    assert controller.request(State.WALK)
    old = controller.token
    assert controller.positioning.running
    controller.interact()
    assert controller.state == State.INTERACT
    assert not controller.positioning.running
    controller.finished(old)
    assert controller.state == State.INTERACT
    controller.finished(controller.token)
    assert controller.state == State.HAPPY
    controller.finished(controller.token)
    assert controller.state == State.IDLE


def test_notification_waits_for_drag_and_returns_to_sleep(controller):
    controller.update_inactivity(10000)
    assert controller.state == State.SLEEP
    controller.set_gate("drag", True)
    controller.notify("one", "Concluído")
    controller.notify("one", "Duplicado")
    assert len(controller.pending_notifications) == 1
    controller.set_gate("drag", False)
    assert controller.state == State.NOTIFICATION
    controller.finished(controller.token)
    assert controller.state == State.SLEEP
    controller.update_inactivity(0)
    assert controller.state == State.IDLE


def test_many_clicks_coalesce_and_pause_still_allows_interaction(controller, clock):
    controller.set_paused(True)
    assert not controller.behavior.timer.isActive()
    controller.interact()
    assert controller.state == State.INTERACT
    for _ in range(10):
        clock.advance(0.3)
        controller.interact()
    assert controller.pending_click
    controller.finished(controller.token)
    controller.finished(controller.token)
    assert controller.state == State.INTERACT
    assert not controller.pending_click
    controller.autonomous(State.WALK)
    assert controller.state == State.INTERACT


def test_hidden_and_shutdown_stop_work(controller):
    controller.set_gate("hidden", True)
    controller.notify("one", "done")
    assert not controller.animation.timer.isActive()
    assert not controller.behavior.timer.isActive()
    controller.set_gate("menu", True)
    assert not controller.animation.timer.isActive()
    controller.close()
    controller.finished(controller.token)
    assert controller.closed and not controller.pending_notifications


@pytest.fixture
def companion(qapp, tmp_path):
    store = ConfigStore(tmp_path)
    assert store.acquire()
    store.load()
    result = Companion(qapp, store)
    QTest.qWait(50)
    yield result
    result.shutdown()
    qapp.processEvents()


def test_application_window_and_shutdown(companion):
    assert companion.window.isVisible()
    assert companion.window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert companion.window.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert companion.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    image = companion.window.grab().toImage()
    assert image.pixelColor(0, 0).alpha() == 0
    assert image.pixelColor(80, 60).alpha() > 0
    companion.show_tools()
    companion.countdown.start(60)
    companion.controller.request(State.HAPPY)
    assert companion.countdown.timer.isActive()
    companion.shutdown()
    companion.shutdown()
    timers = [companion.animation.timer, companion.behavior.timer, companion.positioning.timer,
              companion.countdown.timer, companion.monitor.timer, companion.idle_timer,
              companion.desktop_timer, companion.tools.clock_timer, companion.bubble.timer,
              companion.store.timer]
    assert not any(timer.isActive() for timer in timers)
    second = ConfigStore(companion.store.directory)
    assert second.acquire()
    second.close()


def test_click_and_drag_are_distinct(companion, qapp):
    clicked = QSignalSpy(companion.window.clicked)
    finished = QSignalSpy(companion.window.drag_finished)
    QTest.mouseClick(companion.window, Qt.MouseButton.LeftButton, pos=QPoint(80, 80))
    assert clicked.count() == 1
    assert companion.controller.state == State.INTERACT
    window = companion.window
    origin = QPointF(window.mapToGlobal(QPoint(80, 80)))
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 80))
    movement = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(110, 80), origin + QPointF(30, 0),
                           Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(window, movement)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 80))
    assert clicked.count() == 1 and finished.count() == 1
    assert "drag" not in companion.controller.gates


def test_tools_settings_menu_and_persistence(companion, qapp):
    menu_text = [action.text() for action in companion.menu.actions()]
    assert all(any(name in label for label in menu_text) for name in
               ("Interagir", "Aplicativos", "Atalhos", "Ferramentas", "Configurações", "Sair"))
    companion.show_tools()
    assert companion.monitor.timer.isActive() and companion.tools.clock_timer.isActive()
    companion.tools.hide()
    assert not companion.monitor.timer.isActive() and not companion.tools.clock_timer.isActive()
    companion.show_settings()
    dialog = companion.settings_dialog
    assert "settings" in companion.controller.gates
    assert not dialog.startup.isEnabled()
    dialog.scale.setValue(128)
    dialog.apply(False)
    assert not dialog.error.text()
    assert companion.window.width() == 128
    assert companion.store.settings.visual_scale == 128
    dialog.reject()
    assert companion.settings_dialog is None
    assert "settings" not in companion.controller.gates
    saved = json.loads(companion.store.path.read_text(encoding="utf-8"))
    assert saved["visual_scale"] == 128


def test_saved_position_survives_application_initialization(qapp, tmp_path):
    store = ConfigStore(tmp_path)
    assert store.acquire()
    settings = Settings()
    settings.window.u = 0.25
    settings.window.v = 0.35
    store.apply(settings)
    store.flush()
    result = Companion(qapp, store)
    try:
        assert result.store.settings.window.u == pytest.approx(0.25, abs=0.002)
        assert result.store.settings.window.v == pytest.approx(0.35, abs=0.002)
    finally:
        result.shutdown()


def test_menu_callbacks_keep_their_target_and_monitor(qapp):
    settings = Settings()
    application = Target("app", "Editor", r"C:\Tools\editor.exe", "app")
    location = Target("dir", "Pasta", r"C:\Users", "folder")
    settings.applications = [application]
    settings.locations = [location]
    settings.shortcuts = [Shortcut("alias", "Alias", "app")]
    from types import SimpleNamespace
    screen = SimpleNamespace(name=lambda: "Test monitor")
    targets, monitors = [], []
    actions = {name: lambda: None for name in ("interact", "settings", "tools", "show", "hide",
                                               "pause", "restore", "exit", "pass_through")}
    actions.update(target=targets.append, screen=monitors.append, paused=lambda: False, passing=lambda: False)
    menu = create_menu(None, actions, settings, [screen], True)
    applications = next(action.menu() for action in menu.actions() if action.text() == "Aplicativos")
    shortcuts = next(action.menu() for action in menu.actions() if action.text() == "Atalhos")
    monitors_menu = next(action.menu() for action in menu.actions() if action.text() == "Mover para monitor")
    applications.actions()[0].trigger()
    shortcuts.actions()[0].trigger()
    shortcuts.actions()[1].trigger()
    monitors_menu.actions()[0].trigger()
    assert targets == [application, location, application]
    assert monitors == [screen]
    menu.deleteLater()


def test_balloon_follows_drag_without_restarting_its_lifetime(companion, qapp):
    companion.positioning.place(QPointF(400, 400))
    companion.interact()
    qapp.processEvents()
    assert companion.bubble.isVisible()
    pet_before, bubble_before = companion.window.pos(), companion.bubble.pos()
    remaining = companion.bubble.timer.remainingTime()
    companion.controller.set_gate("drag", True)
    companion.positioning.drag(QPointF(560, 500), QPointF(0.5, 0.5))
    qapp.processEvents()
    delta = companion.window.pos() - pet_before
    assert delta != QPoint()
    assert companion.bubble.pos() - bubble_before == delta
    assert companion.bubble.isVisible()
    assert 0 < companion.bubble.timer.remainingTime() <= remaining
    companion.drag_finished()


def test_balloon_reanchors_below_pet_near_top_edge(companion, qapp):
    companion.positioning.place(QPointF(400, 0))
    companion.bubble.present("Teste de posição", companion.window)
    qapp.processEvents()
    assert companion.bubble.y() >= companion.window.y() + companion.window.height()
    screen = companion.positioning.screen
    assert screen.availableGeometry().contains(companion.bubble.geometry())


def test_left_click_opens_wheel_and_still_plays_the_interaction(companion):
    companion.left_click()
    assert companion.radial.isVisible()
    assert "radial" in companion.controller.gates
    assert companion.controller.state == State.INTERACT
    assert companion.bubble.isVisible()
    companion.controller.finished(companion.controller.token)
    assert companion.controller.state == State.HAPPY
    companion.controller.finished(companion.controller.token)
    assert companion.controller.state == State.IDLE
    assert not companion.behavior.timer.isActive()
    companion.radial.hide()
    assert "radial" not in companion.controller.gates
    assert companion.behavior.timer.isActive()


def test_radial_button_opens_tools_and_escape_releases_gate(companion):
    companion.left_click()
    QTest.mouseClick(companion.radial.buttons["tools"], Qt.MouseButton.LeftButton)
    assert companion.tools.isVisible()
    assert not companion.radial.isVisible()
    assert "radial" not in companion.controller.gates
    companion.tools.hide()
    companion.radial.popup_near(companion.window)
    QTest.keyClick(companion.radial, Qt.Key.Key_Escape)
    assert not companion.radial.isVisible()
    assert "radial" not in companion.controller.gates


def test_drag_closes_radial_and_preserves_the_balloon(companion, qapp):
    companion.positioning.place(QPointF(400, 400))
    companion.left_click()
    assert companion.radial.isVisible()
    window = companion.window
    origin = QPointF(window.mapToGlobal(QPoint(80, 80)))
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 80))
    assert not companion.radial.isVisible()
    event = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(110, 80), origin + QPointF(30, 0),
                        Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    QApplication.sendEvent(window, event)
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 80))
    assert companion.bubble.isVisible()
    assert not companion.controller.gates


def test_autonomous_deadline_starts_real_window_motion(companion):
    companion.controller.enter(State.IDLE)
    companion.behavior.next_walk_at = companion.behavior.clock() - 1
    before = companion.window.pos()
    companion.behavior.timer.timeout.emit()
    assert companion.controller.state == State.WALK
    assert companion.positioning.timer.isActive()
    QTest.qWait(250)
    assert companion.window.pos() != before


def test_walking_at_edge_tries_the_opposite_direction(companion, monkeypatch):
    companion.positioning.place(QPointF(100000, 400))
    origin = companion.window.pos()
    monkeypatch.setattr(companion.behavior.rng, "choice", lambda choices: 1)
    companion.controller.request(State.WALK)
    assert companion.controller.state == State.WALK
    assert companion.positioning.destination.x() < origin.x()


def test_launchpad_search_and_alias_selection_deliver_once(companion):
    settings = Settings()
    app = Target("app", "Editor", r"C:\Tools\editor.exe", "app")
    folder = Target("dir", "Projetos", r"C:\dev", "folder")
    settings.applications = [app]
    settings.locations = [folder]
    settings.shortcuts = [Shortcut("alias", "Meu editor", "app")]
    panel = companion.locations_panel
    panel.set_settings(settings)
    spy = QSignalSpy(panel.target_requested)
    panel.search.setText("editor")
    assert panel.list.item(0).isHidden()
    assert not panel.list.item(1).isHidden()
    panel.list.setCurrentRow(1)
    assert panel.open_button.isEnabled()
    panel.list.itemActivated.emit(panel.list.item(1))
    assert spy.count() == 1 and spy.at(0)[0] == app
    panel.search.setText("nada encontrado")
    assert not panel.open_button.isEnabled()
    panel.open_selected()
    assert spy.count() == 1


def test_timer_minutes_presets_and_pause_resume_are_consistent(companion):
    tools = companion.tools
    tools.set_duration(65)
    assert tools.minutes.value() == 1 and tools.seconds.value() == 5
    tools.start()
    assert companion.countdown.duration == 65
    assert not tools.start_button.isEnabled()
    assert not tools.minutes.isEnabled()
    tools.toggle_pause()
    assert tools.pause_button.text() == "Continuar"
    tools.toggle_pause()
    assert tools.pause_button.text() == "Pausar"
    companion.countdown.close()
    tools.set_duration(0)
    tools.start()
    assert "1 segundo" in tools.completion.text()


def test_settings_sleep_minutes_round_trip_without_schema_change(companion):
    companion.show_settings()
    dialog = companion.settings_dialog
    dialog.sleep.setValue(0.5)
    dialog.apply(False)
    assert companion.store.settings.behavior.sleep_seconds == 30
    assert companion.store.settings.schema_version == 1
    dialog.reject()


def test_radial_timeout_and_shutdown_cannot_leave_autonomy_blocked(companion):
    companion.left_click()
    assert companion.radial.dismiss_timer.isActive()
    companion.radial.dismiss_timer.timeout.emit()
    assert not companion.radial.isVisible()
    assert "radial" not in companion.controller.gates
    companion.controller.finished(companion.controller.token)
    companion.controller.finished(companion.controller.token)
    assert companion.behavior.timer.isActive()
    companion.radial.popup_near(companion.window)
    companion.shutdown()
    assert not companion.radial.dismiss_timer.isActive()
    assert not companion.radial.isVisible()
    assert not companion.apps_panel.isVisible()
    assert not companion.locations_panel.isVisible()
