import pytest
from PySide6.QtCore import Qt

from r2_companion.pet.scenes import CATALOG, SCENE_LABELS, scene_clips
from r2_companion.pet.state import State
from test_context_v03 import pet


@pytest.mark.parametrize("identifier", CATALOG)
def test_garage_scenes_are_independent_and_capture_each_pose(pet, identifier, clock, tmp_path):
    pet.show_garage()
    garage = pet.garage_dialog
    garage.selector.setCurrentIndex(garage.selector.findData(identifier))
    garage.repeat.setChecked(False)
    garage.animation.clock = clock
    garage.category.setCurrentIndex(garage.category.findData("scenes"))
    assert garage.animations.count() == 3 and not garage.frame_variant.isEnabled()
    desktop = (pet.profile.id, pet.controller.token, pet.countdown.run_id)
    for row, action in enumerate(SCENE_LABELS):
        garage.animations.setCurrentRow(row)
        assert garage.animations.item(row).data(Qt.ItemDataRole.UserRole) == action
        garage.play()
        scene = CATALOG[identifier][action]
        clips = tuple(scene_clips(scene, garage.clips))
        assert [state for state, _ in clips] == [state for state, _ in scene.steps]
        assert 0 < garage.animation.clip.duration <= 6000
        elapsed = 0
        for state, clip in clips:
            clock.now = garage.animation.started + (elapsed + 1) / 1000
            garage.animation.tick()
            assert garage.preview.grab().save(str(tmp_path / f"{identifier}-{action}-{state.value}.png"))
            elapsed += clip.duration
    assert desktop == (pet.profile.id, pet.controller.token, pet.countdown.run_id)
    garage.close()
    garage.animation.timer.timeout.emit()
    assert not garage.animation.timer.isActive() and garage.animation.clip is None


def test_focus_scene_uses_reduced_motion_and_is_interrupted_by_click(pet, clock, monkeypatch):
    pet.controller.clock = pet.countdown.clock = pet.animation.clock = clock
    pet.companion_state.update("accessibility", {"reduced_motion": True})
    voices = []
    monkeypatch.setattr(pet.audio, "vocalize", lambda *args: voices.append(args))
    run = pet.focus.start_focus()
    assert pet.reactions.scene == "focus_started" and pet.controller.state == State.LOOK_AROUND
    assert pet.animation.reduced_motion and not pet.positioning.timer.isActive()
    token = pet.controller.token
    pet.controller.interact()
    assert pet.controller.state == State.INTERACT and pet.reactions.scene is None
    pet.controller.finished(token)
    assert pet.controller.state == State.INTERACT
    assert voices.count(("curious", "reactions")) == 1
    pet.focus.pause(run)
    pet.focus.resume(run)
    assert pet.reactions.scene is None and pet.countdown.run_id == run


def test_late_scene_callback_skips_remaining_steps(pet, clock):
    pet.controller.clock = clock
    run = pet.focus.start_focus()
    assert pet.reactions.scene == "focus_started"
    clock.advance(7)
    pet.controller.finished(pet.controller.token)
    assert pet.reactions.scene is None and pet.controller.state == State.IDLE
    assert pet.focus.session.run_id == run
