from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QPixmap
from PySide6.QtTest import QSignalSpy
import pytest

from r2_companion.pet.animation import AnimationManager, Clip, Frame
from r2_companion.pet.state import State
from r2_companion.ui.updates import UpdateCenter
from test_context_v03 import pet


def set_motion(pet, enabled):
    pet.companion_state.update("accessibility", {"reduced_motion": enabled})


def test_static_action_preserves_elapsed_time_and_token(qapp, clock):
    clip = Clip(tuple(Frame(QPixmap(2, 2), 500) for _ in range(3)), False)
    manager = AnimationManager({State.WORK: clip}, clock)
    frames = QSignalSpy(manager.frame_changed)
    done = QSignalSpy(manager.clip_finished)
    manager.play(State.WORK, 17)
    clock.advance(0.55)
    manager.tick()
    manager.set_reduced_motion(True)
    assert manager.last_frame == 1 and manager.timer.interval() in range(949, 952)
    clock.advance(1)
    manager.tick()
    manager.tick()
    assert frames.count() == 2 and done.count() == 1 and done.at(0) == [17]
    assert not manager.timer.isActive()


def test_motion_preference_in_settings_and_update_center(pet):
    pet.show_settings()
    dialog = pet.settings_dialog
    assert not dialog.reduced_motion.isChecked()
    dialog.reduced_motion.setChecked(True)
    dialog.apply(True)
    assert pet.presence.context.reduced_motion and pet.companion_state.flush()
    center = UpdateCenter(pet.store.directory)
    center.startup.stop()
    try:
        center.set_state("checking", "Verificando", "")
        assert not center.animation.timer.isActive() and center.progress.isHidden()
        refreshed = QSignalSpy(center.theme_watcher.timer.timeout)
        set_motion(pet, False)
        assert pet.companion_state.flush()
        assert refreshed.count() or refreshed.wait(3000)
        assert not center.animation.reduced_motion and not center.progress.isHidden()
    finally:
        center.set_state("idle", "", "")
        center.close()


def test_toggle_during_autonomous_walk_sleep_and_smoke(pet):
    pet.controller.autonomous(State.WALK)
    assert pet.positioning.timer.isActive()
    set_motion(pet, True)
    assert pet.controller.state == State.IDLE
    assert not pet.positioning.timer.isActive() and not pet.animation.timer.isActive()
    for state, effect in [(State.SLEEP, pet.window.sleep_effect), (State.OVERHEAT, pet.window.steam)]:
        set_motion(pet, False)
        pet.controller.enter(state)
        assert effect.timer.isActive()
        token = pet.controller.token
        set_motion(pet, True)
        assert pet.controller.token == token and not effect.timer.isActive()
        set_motion(pet, False)
        assert effect.timer.isActive()
        pet.controller.enter(State.IDLE)


@pytest.mark.parametrize("entering", [False, True])
def test_radial_toggle_finishes_current_navigation_once(pet, entering):
    wheel = pet.radial
    ready = QSignalSpy(wheel.page_ready)
    actions = QSignalSpy(wheel.action_selected)
    wheel.popup_near(pet.window)
    wheel.select("tools")
    if entering:
        wheel.transition.setCurrentTime(wheel.transition.totalDuration())
    assert wheel.phase == ("entering" if entering else "exiting")
    set_motion(pet, True)
    assert wheel.level == "tools" and wheel.transition is None and not wheel.transitioning
    assert ready.count() == 1
    wheel.back()
    wheel.select("tools")
    wheel.select("tasks")
    assert ready.count() == 3 and actions.count() == 1 and actions.at(0) == ["tasks"]
    assert "radial" not in pet.controller.gates and pet.tools.isVisible()


def test_global_motion_follows_all_droids_and_live_garage_preview(pet):
    set_motion(pet, True)
    for identifier in pet.droids.profiles:
        assert pet.equip_droid(identifier)
        pet.controller.enter(State.IDLE)
        assert pet.animation.clip and not pet.animation.timer.isActive()
        pet.controller.autonomous(State.WALK)
        assert not pet.positioning.timer.isActive()
    pet.show_garage()
    garage = pet.garage_dialog
    garage.selector.setCurrentIndex(garage.selector.findData("spherical_droid"))
    row = next(i for i in range(garage.animations.count())
               if garage.animations.item(i).data(Qt.ItemDataRole.UserRole) == State.WALK)
    garage.animations.setCurrentRow(row)
    assert not garage.animation.timer.isActive() and not garage.preview.roll_timer.isActive()
    set_motion(pet, False)
    assert garage.preview.roll_timer.isActive()
    set_motion(pet, True)
    assert not garage.preview.roll_timer.isActive()
    garage.close()
    assert pet.equip_droid("spherical_droid")
    pet.drag_started()
    before = pet.window.pos()
    target = pet.positioning.screen.availableGeometry().center()
    pet.positioning.drag(QPointF(target), QPointF(0.3, 0.5))
    pet.drag_finished()
    assert pet.window.pos() != before and not pet.positioning.movement.timer.isActive()
    assert "drag" not in pet.controller.gates
