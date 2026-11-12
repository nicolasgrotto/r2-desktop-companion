from copy import deepcopy
from dataclasses import replace
import json
import math
import shutil

import pytest
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QImage, QPainter

from r2_companion.app import ASSETS, Companion
from r2_companion.core.config import Settings
from r2_companion.droids.movement import create_movement
from r2_companion.droids.profiles import DroidRegistry
from r2_companion.droids.rig import ArticulatedVisual
from r2_companion.droids.visuals import load_profile_clips, paint_visual
from r2_companion.pet.state import State
from r2_companion.pet.window import PetWindow
from r2_companion.services.storage import ConfigStore
from r2_companion.ui.droids import DroidGarage
from r2_companion.ui.updates import UpdateCenter
from test_context_v03 import pet

NEW = ("lumo", "vigia", "pico", "tranco")
LEGACY = ("r2_default", "dark_astromech", "spherical_droid")


@pytest.fixture(scope="module")
def registry(qapp):
    return DroidRegistry(ASSETS)


@pytest.fixture(scope="module")
def resources(registry):
    return {key: load_profile_clips(registry.get(key)) for key in NEW}


def render(visual, channels=None, side=96, padding=16):
    image = QImage(side + padding * 2, side + padding * 2, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    paint_visual(p, QRectF(padding, padding, side, side), visual, motion=channels)
    p.end()
    return image


def opaque(image):
    return any(bytes(image.constBits())[3::4])


def test_seven_stable_profiles_without_another_selector(registry, pet):
    assert set(registry.profiles) == set(NEW + LEGACY)
    assert not registry.errors
    assert [registry.get(key).name for key in NEW] == ["Lumo", "Vigia", "Pico", "Tranco"]
    garage = DroidGarage(pet)
    try:
        assert garage.selector.count() == 7
        assert {garage.selector.itemData(i) for i in range(7)} == set(NEW + LEGACY)
    finally:
        garage.close()


@pytest.mark.parametrize("identifier", NEW)
def test_complete_original_clips_have_independent_articulations(resources, identifier):
    clips = resources[identifier]
    assert set(clips) == set(State)
    for state, clip in clips.items():
        assert len(clip.frames) == 12
        assert clip.loop == (state in {State.IDLE, State.WALK, State.SLEEP})
        assert all(isinstance(frame.visual, ArticulatedVisual) for frame in clip.frames)
    assert clips[State.IDLE].frames[0].visual.pose != clips[State.IDLE].frames[3].visual.pose
    assert clips[State.SLEEP].frames[3].visual.pose != clips[State.WORK].frames[3].visual.pose
    visual = clips[State.LOOK_AROUND].frames[3].visual
    parts = {part.name: i for i, part in enumerate(visual.parts)}
    assert visual.pose[parts["head"]].get("angle") != visual.pose[parts["body"]].get("angle", 0)


@pytest.mark.parametrize("identifier", NEW)
def test_every_pose_renders_at_native_scale_without_cutting_silhouette(resources, identifier):
    for clip in resources[identifier].values():
        for frame in clip.frames:
            image = render(frame.visual)
            assert opaque(image.copy(16, 16, 96, 96))
            for rect in ((0, 0, 128, 16), (0, 112, 128, 16), (0, 16, 16, 96), (112, 16, 16, 96)):
                assert not opaque(image.copy(*rect)), (identifier, frame.visual.pose)


@pytest.mark.parametrize("identifier", NEW)
def test_movement_uses_distance_and_recovers_after_direction_change(qapp, clock, registry, resources, identifier):
    window = PetWindow()
    window.resize(160, 160)
    motion = create_movement(registry.get(identifier), window)
    motion.clock = clock
    motion.last_time = clock()
    try:
        visual = resources[identifier][State.IDLE].frames[0].visual
        resting = render(visual)
        clock.advance(0.033)
        motion.displaced(9, 2)
        forward = dict(motion.channels)
        assert render(visual, forward) != resting
        if identifier in {"lumo", "tranco"}:
            radius = 17 if identifier == "lumo" else 6
            assert forward["wheel"] == pytest.approx(math.degrees(9 * 96 / 160 / radius))
        if identifier == "pico":
            assert forward["left_step"] == -forward["right_step"]
            assert forward["left_knee"] != forward["right_knee"]
        clock.advance(0.033)
        motion.displaced(-9, -2, manual=True)
        assert motion.channels != forward
        if identifier == "lumo":
            assert motion.channels["lean"] < forward["lean"]
        captured = motion.capture()
        motion.stop()
        motion.restore(captured)
        assert motion.channels == captured
        motion.release()
        assert motion.timer.isActive()
        for _ in range(60):
            motion.recover()
        assert not motion.timer.isActive()
        assert not any(value for key, value in motion.channels.items() if key not in motion.retained)
    finally:
        motion.close()
        window.close()


@pytest.mark.parametrize("identifier", NEW)
def test_garage_preview_motion_equips_and_retires_its_timer(pet, registry, identifier):
    garage = DroidGarage(pet)
    try:
        before = deepcopy(pet.store.settings)
        garage.selector.setCurrentIndex(garage.selector.findData(identifier))
        assert pet.store.settings == before
        garage.category.setCurrentIndex(garage.category.findData("Locomoção"))
        garage.play()
        garage.preview.roll()
        preview_motion = garage.preview.movement
        assert preview_motion.timer.isActive() and garage.preview.articulation
        garage.custom_controls["illumination"].setCurrentIndex(1)
        garage.equip()
        assert pet.profile.id == identifier and pet.window.illumination == "#ffbf70"
        assert pet.window.visual.parts is not garage.preview.frame.parts
        garage.show()
        garage.close()
        assert not preview_motion.timer.isActive() and not garage.preview.roll_timer.isActive()
    finally:
        garage.close()


@pytest.mark.parametrize("identifier", NEW)
def test_tools_projection_sleep_and_radial_work_with_each_new_body(pet, resources, identifier):
    assert pet.equip_droid(identifier), pet.droid_error
    controller, audio, positioning = pet.controller, pet.audio, pet.positioning
    assert pet.reactions.start("diagnosis")
    assert pet.controller.state == State.WORK
    pet.controller.enter(State.IDLE)
    pet.radial.popup_near(pet.window)
    assert "radial" in pet.controller.gates
    pet.radial.hide()
    assert "radial" not in pet.controller.gates
    pet.project_tool("clock")
    pet.window.set_frame(resources[identifier][State.LOOK_AROUND].frames[3].visual)
    x, y = pet.window.projection_anchor()
    assert 0 < x < 1 and 0 < y < 1
    eye = pet.window.projection_overlay.eye + QPointF(pet.window.projection_overlay.pos())
    assert eye.x() == pytest.approx(pet.window.x() + pet.window.width() * x)
    assert eye.y() == pytest.approx(pet.window.y() + pet.window.height() * y)
    pet.countdown.start(30)
    pet.tools.project_timer.setChecked(True)
    assert pet.window.projection_kind == "timer"
    pet.controller.enter(State.SLEEP)
    assert pet.window.sleep_effect.active
    pet.controller.enter(State.WAKE)
    assert not pet.window.sleep_effect.active
    assert (pet.controller, pet.audio, pet.positioning) == (controller, audio, positioning)


@pytest.mark.parametrize("identifier", NEW)
def test_persistence_restart_and_future_13_keep_selection_preferences_and_tools(pet, qapp, monkeypatch, identifier):
    assert pet.equip_droid(identifier)
    draft = deepcopy(pet.store.settings)
    draft.audio.volume = 0.19
    draft.behavior.movement = False
    draft.timer_projection = True
    pet.store.apply(draft)
    pet.productivity.add_task("Continuidade da Garage")
    directory = pet.store.directory
    pet.shutdown()
    qapp.processEvents()
    tools = (directory / "tools.json").read_bytes()
    # A future version uses the same additive schema and stable profile IDs.
    monkeypatch.setattr("r2_companion.app.__version__", "1.3.0")
    monkeypatch.setattr("r2_companion.services.updates.__version__", "1.3.0")
    store = ConfigStore(directory)
    assert store.acquire()
    store.load()
    second = Companion(qapp, store)
    try:
        assert second.profile.id == store.settings.active_droid == identifier
        assert second.audio.settings.volume == 0.19
        assert not second.behavior.settings.movement and store.settings.timer_projection
        assert (directory / "tools.json").read_bytes() == tools
        assert Settings.parse(store.settings.to_dict()) == store.settings
    finally:
        second.shutdown()
        qapp.processEvents()


@pytest.mark.parametrize("identifier", NEW)
def test_walk_drag_gates_and_shutdown_retire_motion(pet, clock, identifier):
    assert pet.equip_droid(identifier)
    pet.positioning.clock = clock
    pet.positioning.place(QPointF(300, 300))
    motion = pet.positioning.movement
    motion.clock = clock
    motion.last_time = clock()
    assert pet.controller.request(State.WALK)
    clock.advance(0.8)
    pet.positioning.tick()
    assert motion.channels
    pet.controller.set_gate("hidden", True)
    assert not motion.timer.isActive() and not pet.animation.timer.isActive()
    pet.controller.set_gate("hidden", False)
    pet.window.dragging = True
    pet.drag_started()
    pet.positioning.drag(QPointF(380, 330), QPointF(0, 0))
    captured = motion.capture()
    pet.window.dragging = False
    pet.drag_finished()
    assert motion.channels == captured and motion.timer.isActive()
    pet.shutdown()
    assert not motion.timer.isActive() and not pet.positioning.timer.isActive()


@pytest.mark.parametrize("mutation", ["cycle", "channel", "pose", "duration", "nan", "size", "corrupt", "emitter"])
def test_invalid_rig_cannot_replace_working_character(qapp, registry, tmp_path, mutation):
    profile = registry.get("pico")
    root = tmp_path / "pico"
    shutil.copytree(profile.manifest.parent.parent, root)
    manifest = root / "animations/manifest.json"
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if mutation == "cycle":
        data["parts"][0]["parent"] = "head"
    elif mutation == "channel":
        data["parts"][0]["motion"] = {"angle": ["unknown", 1]}
    elif mutation == "pose":
        data["clips"]["IDLE"]["frames"][0]["pose"]["absent"] = {"angle": 1}
    elif mutation == "duration":
        data["clips"]["IDLE"]["frames"][0]["duration_ms"] = 0
    elif mutation == "nan":
        data["clips"]["IDLE"]["frames"][0]["pose"]["head"]["angle"] = float("nan")
    elif mutation == "emitter":
        data["emitter"]["part"] = "absent"
    elif mutation == "size":
        QImage(1, 1, QImage.Format.Format_ARGB32).save(str(root / "sprites/body.png"))
    else:
        (root / "sprites/body.png").write_bytes(b"bad PNG")
    manifest.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        load_profile_clips(replace(profile, manifest=manifest))


@pytest.mark.parametrize("identifier", NEW)
def test_update_center_displays_saved_rig_without_resetting_selection(pet, identifier):
    assert pet.equip_droid(identifier)
    before = pet.store.path.read_bytes()
    center = UpdateCenter(pet.store.directory, client=lambda repo: None)
    center.startup.stop()
    try:
        center.set_state("idle", "Prévia local", "")
        assert center.theme_watcher.last_id == identifier
        assert isinstance(center.character.frame, ArticulatedVisual)
        assert opaque(center.character.grab().toImage())
        assert pet.store.path.read_bytes() == before
    finally:
        center.close()


def test_switches_across_entire_garage_preserve_legacy_resources_and_retire_timers(pet):
    originals = {key: (pet.droids.get(key).manifest, load_profile_clips(pet.droids.get(key))) for key in LEGACY}
    for identifier in NEW + LEGACY + NEW + LEGACY:
        previous = pet.positioning.movement
        previous.displaced(12, 0)
        assert pet.equip_droid(identifier), pet.droid_error
        if hasattr(previous, "timer"):
            assert not previous.timer.isActive()
        assert pet.droids.active_id == pet.store.settings.active_droid == identifier
        if identifier in NEW:
            assert pet.window.articulation == pet.positioning.movement.channels
    for key, (manifest, clips) in originals.items():
        assert pet.droids.get(key).manifest == manifest
        restored = load_profile_clips(pet.droids.get(key))
        for state, clip in clips.items():
            assert len(clip.frames) == len(restored[state].frames)
            assert clip.frames[0].pixmap.toImage() == restored[state].frames[0].pixmap.toImage()


@pytest.mark.parametrize("identifier", NEW)
def test_failed_persistence_restores_old_model_and_closes_prepared_rig(pet, monkeypatch, identifier):
    pet.store.flush()
    before = pet.store.path.read_bytes()
    old_motion, old_clips = pet.positioning.movement, pet.animation.clips
    prepared = []
    prepare = pet.droid_controller.prepare
    def capture(key):
        result = prepare(key)
        prepared.append(result)
        return result
    monkeypatch.setattr(pet.droid_controller, "prepare", capture)
    monkeypatch.setattr(pet.store, "flush", lambda: False)
    assert not pet.equip_droid(identifier)
    assert pet.profile.id == pet.audio.profile_id == pet.store.settings.active_droid == "r2_default"
    assert pet.animation.clips is old_clips and pet.positioning.movement is old_motion
    assert pet.store.path.read_bytes() == before
    assert not prepared[0].movement.timer.isActive()
    assert pet.controller.request(State.WORK)


@pytest.mark.parametrize("identifier", NEW)
def test_locomotion_articulations_fit_canvas(resources, registry, qapp, clock, identifier):
    window = PetWindow()
    window.resize(160, 160)
    motion = create_movement(registry.get(identifier), window)
    motion.clock = clock
    motion.last_time = clock()
    try:
        for i in range(24):
            clock.advance(0.033)
            motion.displaced(4 if i < 12 else -4, 0)
            frame = resources[identifier][State.WALK].frames[i % 12]
            picture = render(frame.visual, motion.channels)
            for rect in ((0, 0, 128, 16), (0, 112, 128, 16), (0, 16, 16, 96), (112, 16, 16, 96)):
                assert not opaque(picture.copy(*rect)), (identifier, motion.channels)
    finally:
        motion.close()
        window.close()
