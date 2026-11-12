from dataclasses import replace
import hashlib
import json
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from r2_companion.app import ASSETS
from r2_companion.droids.profiles import DroidRegistry
from r2_companion.droids.visuals import load_profile_clips
from r2_companion.pet.state import State
from r2_companion.ui.droids import DroidGarage
from test_context_v03 import pet
from test_garage_expansion import render

NEW = ("lumo", "vigia", "pico", "tranco")


@pytest.fixture(scope="module")
def clips(qapp):
    registry = DroidRegistry(ASSETS)
    return {key: load_profile_clips(registry.get(key)) for key in NEW}


@pytest.mark.parametrize("identifier", NEW)
@pytest.mark.parametrize("state", list(State))
def test_every_state_has_visible_animated_cue_in_an_isolated_frame(clips, identifier, state):
    frames = clips[identifier][state].frames
    for i in (0, 3, 8, 11):
        visual = frames[i].visual
        assert visual.state == state and visual.expression_style == identifier
        assert render(visual) != render(replace(visual, expression_style=""))
    # Even stationary sleep has moving indicators without a desktop overlay.
    a, b = frames[0].visual, frames[3].visual
    assert render(a) != render(replace(a, phase=b.phase))


@pytest.mark.parametrize("identifier", NEW)
def test_distinct_reactions_and_uncrushed_mechanical_blink(clips, identifier):
    signatures = []
    for state in State:
        frames = clips[identifier][state].frames
        signatures.append(tuple(tuple(tuple(sorted(p.items())) for p in f.visual.pose) for f in frames))
    assert len(set(signatures)) >= 18
    for frame in clips[identifier][State.BLINK].frames:
        assert all(p.get("scale_y", 1) == 1 for p in frame.visual.pose)
    frames = clips[identifier][State.WAKE].frames
    head = next(i for i, p in enumerate(frames[0].visual.parts) if p.name == "head")
    assert frames[0].visual.pose[head]["light"] < frames[-1].visual.pose[head]["light"]


@pytest.mark.parametrize("identifier", ("r2_default", "spherical_droid", "dark_astromech", *NEW))
@pytest.mark.parametrize("state", (State.SLEEP, State.OVERHEAT))
def test_garage_shows_effects_on_play_and_manual_frames_and_cleans_timers(pet, identifier, state):
    garage = DroidGarage(pet)
    try:
        garage.selector.setCurrentIndex(garage.selector.findData(identifier))
        for i in range(garage.animations.count()):
            if garage.animations.item(i).data(Qt.ItemDataRole.UserRole) == state:
                garage.animations.setCurrentRow(i)
                break
        assert garage.preview.state == state
        assert garage.preview.effect_timer.isActive() == (identifier not in NEW)
        with_effect = garage.preview.grab().toImage()
        garage.stop()
        garage.frame_variant.setCurrentIndex(1)
        assert garage.preview.state == state
        assert not garage.preview.effect_timer.isActive()
        if identifier not in NEW:
            garage.preview.state = None
            without_effect = garage.preview.grab().toImage()
            assert with_effect != without_effect
    finally:
        garage.close()
    assert not garage.preview.effect_timer.isActive()


def test_legacy_animation_assets_are_byte_identical_to_before_refinement():
    # Recorded from the pre-refinement tree. Works in shallow/source-only clones.
    fixture = Path(__file__).with_name("fixtures") / "legacy_assets_sha256.json"
    for name, expected in json.loads(fixture.read_text(encoding="utf-8")).items():
        path = ASSETS / name
        raw = path.read_bytes()
        if path.suffix in {".json", ".md"}:
            raw = raw.replace(b"\r\n", b"\n")
        assert hashlib.sha256(raw).hexdigest() == expected, name
