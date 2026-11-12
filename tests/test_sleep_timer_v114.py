from copy import deepcopy
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt

from r2_companion.core.config import Settings
from r2_companion.pet.state import State
from test_context_v03 import pet


@pytest.mark.parametrize("identifier", ["r2_default", "dark_astromech", "spherical_droid"])
def test_sleep_z_effect_follows_sleep_visibility_and_shutdown(pet, identifier):
    assert pet.equip_droid(identifier)
    pet.controller.enter(State.SLEEP)
    effect = pet.window.sleep_effect
    assert effect.active and effect.isVisible() and effect.timer.isActive()
    assert effect.windowFlags() & Qt.WindowType.WindowTransparentForInput
    image = effect.grab().toImage()
    assert any(image.pixelColor(x, y).alpha() for x in range(0, image.width(), 3) for y in range(0, image.height(), 3))
    pet.window.hide()
    assert not effect.isVisible() and not effect.timer.isActive()
    pet.window.show()
    assert effect.isVisible() and effect.timer.isActive()
    pet.controller.enter(State.WAKE)
    assert not effect.active and not effect.timer.isActive()
    pet.controller.enter(State.SLEEP)
    pet.shutdown()
    assert not effect.timer.isActive()


def test_timer_projection_runs_hidden_pauses_resumes_and_finishes(pet, clock):
    pet.countdown.clock = clock
    pet.tools.project_timer.setChecked(True)
    pet.tools.set_duration(65)
    pet.tools.start()
    assert pet.window.projection_kind == "timer" and "01:05" in pet.window.projection_text
    pet.tools.close()
    clock.advance(5)
    pet.window.refresh_projection()
    assert "01:00" in pet.window.projection_text
    pet.countdown.pause()
    assert "Pausado" in pet.window.projection_text
    clock.advance(20)
    pet.window.refresh_projection()
    assert "01:00" in pet.window.projection_text
    pet.countdown.resume()
    pet.window.hide()
    clock.advance(10)
    pet.window.show()
    assert "00:50" in pet.window.projection_text
    clock.advance(50)
    pet.countdown.tick()
    assert pet.window.projection_kind is None and not pet.window.projection_timer.isActive()


def test_projection_option_is_opt_in_persistent_and_respects_manual_override(pet, clock):
    pet.countdown.clock = clock
    pet.countdown.start(30)
    assert pet.window.projection_kind is None
    pet.tools.project_timer.setChecked(True)
    assert pet.window.projection_kind == "timer" and pet.store.settings.timer_projection
    pet.project_tool("clock")
    pet.countdown.tick()
    assert pet.window.projection_kind == "clock"
    pet.countdown.restart()
    assert pet.window.projection_kind == "timer"
    pet.tools.project_timer.setChecked(False)
    assert pet.window.projection_kind is None
    assert not Settings.parse(pet.store.settings.to_dict()).timer_projection
    pet.tools.project_timer.setChecked(True)
    assert Settings.parse(pet.store.settings.to_dict()).timer_projection
    draft = deepcopy(pet.store.settings)
    draft.holograms = False
    pet.store.apply(draft)
    assert not pet.tools.project_timer.isEnabled() and pet.window.projection_kind is None


def test_old_settings_default_to_no_timer_projection():
    raw = Settings().to_dict()
    raw.pop("timer_projection")
    assert not Settings.parse(raw).timer_projection


@pytest.mark.parametrize("cpu,expected", [(88, State.IDLE), (90, State.OVERHEAT)])
def test_cpu_overheat_threshold_is_ninety_percent(pet, cpu, expected):
    pet.awareness.info = SimpleNamespace(sample=lambda **kwargs: {"cpu": cpu, "battery": None, "charging": None})
    pet.controller.enter(State.IDLE)
    pet.awareness.sample_system()
    assert pet.controller.state == expected
