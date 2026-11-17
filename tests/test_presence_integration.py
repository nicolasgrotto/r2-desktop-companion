from copy import deepcopy

from PySide6.QtTest import QTest

from r2_companion.pet.state import State
from r2_companion.features.timer import TimerState
from r2_companion.app import Companion
from r2_companion.services.storage import ConfigStore
from test_context_v03 import pet


def test_focus_stops_autonomous_walk_but_allows_interaction_and_timer(pet, monkeypatch):
    monkeypatch.setattr("r2_companion.pet.presence_runtime.QSystemTrayIcon.isSystemTrayAvailable", lambda: True)
    before = deepcopy(pet.store.settings.to_dict())
    services = (pet.controller, pet.positioning, pet.animation, pet.countdown)
    pet.countdown.start(120)
    run = pet.countdown.run_id
    pet.controller.autonomous(State.WALK)
    assert pet.controller.state == State.WALK
    pet.presence.select_mode("focus")
    assert pet.controller.state != State.WALK and not pet.positioning.timer.isActive()
    assert "focus" not in pet.controller.gates
    pet.controller.autonomous(State.WALK)
    assert pet.controller.state != State.WALK
    assert pet.controller.react(State.GREETING)
    assert not pet.controller.action_spontaneous
    assert pet.countdown.state == TimerState.RUNNING and pet.countdown.run_id == run
    assert services == (pet.controller, pet.positioning, pet.animation, pet.countdown)
    assert pet.store.settings.to_dict() == before
    assert pet.companion_state.data["presence"]["mode"] == "focus"


def test_presentation_preserves_timer_and_projection_and_allows_tools(pet, monkeypatch):
    monkeypatch.setattr("r2_companion.pet.presence_runtime.QSystemTrayIcon.isSystemTrayAvailable", lambda: True)
    pet.presence.refresh()
    pet.countdown.start(120)
    assert pet.window.show_projection("clock")
    pet.presence.select_mode("presentation")
    assert not pet.window.isVisible() and not pet.window.projection_overlay.isVisible()
    assert pet.window.projection_kind == "clock" and not pet.window.projection_timer.isActive()
    assert not pet.animation.timer.isActive() and not pet.behavior.timer.isActive()
    assert pet.countdown.state == TimerState.RUNNING
    pet.timer_completed(pet.countdown.run_id)
    assert not pet.tray.notice.isVisible() and not pet.bubble.isVisible()
    pet.show_tools_page("timer")
    assert pet.tools.isVisible()
    pet.tools.hide()
    pet.presence.select_mode("free")
    assert pet.window.isVisible() and pet.window.projection_kind == "clock"
    assert pet.window.projection_timer.isActive()


def test_presentation_recovers_when_tray_disappears(pet, monkeypatch):
    available = [True]
    monkeypatch.setattr("r2_companion.pet.presence_runtime.QSystemTrayIcon.isSystemTrayAvailable", lambda: available[0])
    pet.presence.select_mode("presentation")
    assert not pet.window.isVisible()
    available[0] = False
    pet.check_desktop()
    assert pet.window.isVisible() and not pet.animation.timer.isActive()
    assert not pet.positioning.timer.isActive() and not pet.behavior.timer.isActive()
    assert pet.presence.decision.reason == "presentation_recovery"
    assert "bandeja" in pet.window.toolTip()
    pet.refresh_menu()
    pet.menu.presence_actions["free"].trigger()
    assert pet.presence.context.manual_mode == "free" and pet.window.isVisible()
    pet.show_tools()
    assert pet.tools.isVisible()


def test_menu_and_settings_share_manual_mode_without_rewriting_droid_preferences(pet, monkeypatch):
    monkeypatch.setattr("r2_companion.pet.presence_runtime.QSystemTrayIcon.isSystemTrayAvailable", lambda: True)
    before = deepcopy(pet.store.settings.droid_preferences)
    pet.refresh_menu()
    pet.menu.presence_actions["focus"].trigger()
    assert pet.menu.presence_actions["focus"].isChecked()
    pet.show_settings()
    dialog = pet.settings_dialog
    assert dialog.presence_mode.currentData() == "focus"
    assert dialog.grab().save(str(pet.store.directory / "presence-settings.png"))
    dialog.presence_mode.setCurrentIndex(dialog.presence_mode.findData("presentation"))
    dialog.apply(False)
    assert pet.presence.context.manual_mode == "presentation"
    assert pet.companion_state.flush()
    assert pet.store.settings.droid_preferences == before
    dialog.reject()
    QTest.qWait(20)


def test_focus_silence_and_suspend_remain_stronger_than_mode_selection(pet, monkeypatch):
    monkeypatch.setattr("r2_companion.pet.presence_runtime.QSystemTrayIcon.isSystemTrayAvailable", lambda: True)
    monkeypatch.setattr("r2_companion.app.quiet_now", lambda settings: True)
    pet.presence.select_mode("focus")
    pet.check_desktop()
    assert not pet.presence.decision.notifications and not pet.presence.decision.spontaneous_audio
    assert pet.presence.decision.reason == "quiet_hours"
    pet.presence.select_mode("free")
    assert not pet.presence.decision.initiative
    pet.set_suspended(True)
    pet.presence.select_mode("focus")
    assert not pet.window.isVisible() and not pet.animation.timer.isActive()
    assert pet.presence.decision.reason == "suspended"


def test_manual_mode_survives_droid_swap_and_restart(pet, qapp, monkeypatch):
    monkeypatch.setattr("r2_companion.pet.presence_runtime.QSystemTrayIcon.isSystemTrayAvailable", lambda: True)
    pet.presence.select_mode("focus")
    assert pet.equip_droid("vigia")
    assert pet.presence.context.manual_mode == "focus"
    assert not pet.behavior.presence_movement
    assert pet.behavior.settings.movement == pet.store.settings.behavior.movement
    pet.shutdown()
    owner = ConfigStore(pet.store.directory)
    assert owner.acquire()
    owner.load()
    replacement = Companion(qapp, owner)
    try:
        assert replacement.presence.context.manual_mode == "focus"
        assert not replacement.behavior.presence_movement
        assert replacement.profile.id == "vigia"
    finally:
        replacement.shutdown()


def test_projection_stays_suspended_during_geometry_updates_in_fullscreen(pet, monkeypatch):
    pet.store.settings.fullscreen_mode = "quiet"
    assert pet.window.show_projection("clock")
    monkeypatch.setattr("r2_companion.app.foreground_fullscreen", lambda hwnd: True)
    pet.check_desktop()
    assert pet.window.isVisible() and pet.window.projection_kind == "clock"
    pet.window.projection_overlay.reposition()
    assert not pet.window.projection_overlay.isVisible()
    assert not pet.window.projection_timer.isActive()
    monkeypatch.setattr("r2_companion.app.foreground_fullscreen", lambda hwnd: False)
    pet.check_desktop()
    assert pet.window.projection_kind == "clock" and pet.window.projection_timer.isActive()


def test_future_state_remains_untouched_when_manual_mode_changes(pet):
    future = b'{"schema_version":99,"extension":"preserved"}'
    pet.companion_state.path.write_bytes(future)
    pet.presence.select_mode("focus")
    assert pet.presence.context.manual_mode == "focus"
    assert not pet.companion_state.flush()
    assert pet.companion_state.path.read_bytes() == future


def test_visibility_and_audio_restore_immediately_without_desktop_poll(pet, monkeypatch):
    monkeypatch.setattr("r2_companion.pet.presence_runtime.QSystemTrayIcon.isSystemTrayAvailable", lambda: True)
    topmost = pet.store.settings.window.topmost
    pet.hide_pet()
    assert not pet.window.isVisible() and pet.audio.suppressed
    pet.show_pet()
    assert pet.window.isVisible() and not pet.audio.suppressed
    pet.presence.select_mode("presentation")
    pet.show_pet()
    assert pet.presence.context.manual_mode == "free"
    assert pet.window.isVisible() and not pet.audio.suppressed
    assert pet.store.settings.window.topmost == topmost
