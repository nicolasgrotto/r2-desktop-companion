from copy import deepcopy
from dataclasses import replace
import json
import math
from pathlib import Path
import shutil

import pytest
from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtGui import QColor
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel, QPushButton

from r2_companion.app import ASSETS, Companion
from r2_companion.core.config import Settings, Target
from r2_companion.droids.movement import DroidMovementController, SphericalMovementController
from r2_companion.droids.preferences import defaults_for, preferences_for, select_droid
from r2_companion.droids.profiles import DroidProfile, DroidRegistry, DroidTheme, contrast
from r2_companion.droids.themes import color, PersistedThemeWatcher, theme_manager
from r2_companion.droids.visuals import DroidVisual, load_profile_clips, paint_visual
from r2_companion.pet.state import State
from r2_companion.pet.window import PetWindow
from r2_companion.pet.positioning import clamp, legal_bounds
from r2_companion.services.storage import ConfigStore
from r2_companion.ui.droids import AnimationGallery, AudioCenter, DroidGarage
from test_context_v03 import pet
from test_audio_productivity import audio


@pytest.fixture
def registry():
    return DroidRegistry(ASSETS)


@pytest.mark.parametrize("identifier", ["r2_default", "dark_astromech", "spherical_droid"])
def test_profiles_match_registered_resources_and_animation_catalog(qapp, registry, identifier):
    profile = registry.get(identifier)
    clips = load_profile_clips(profile)
    assert set(clips) == set(profile.animations) == set(State)
    assert clips[State.IDLE].frames
    assert all(50 <= f.milliseconds <= 5000 for c in clips.values() for f in c.frames)
    assert profile.audio.id == profile.id
    assert not registry.errors


def test_default_profile_preserves_original_atlas(registry):
    assert registry.active_id == "r2_default"
    assert registry.active.manifest == (ASSETS / "characters/default/manifest.json").resolve()
    assert registry.get("dark_astromech").manifest != registry.active.manifest
    assert defaults_for(registry.get("dark_astromech")).personality == "calm"
    assert defaults_for(registry.get("spherical_droid")).personality == "curious"


@pytest.mark.parametrize("mutation", ["id", "theme", "missing", "voice", "catalog", "movement", "customization"])
def test_invalid_profile_is_isolated_from_other_characters(tmp_path, mutation):
    root = tmp_path / "assets"
    shutil.copytree(ASSETS, root)
    path = root / "droids/dark_astromech/profile.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if mutation == "id":
        data["id"] = "../../bad"
    elif mutation == "theme":
        data["theme"]["colors"]["text"] = "#ffffff"
        data["theme"]["colors"]["background"] = "#ffffff"
    elif mutation == "missing":
        data["manifest"] = "absent.json"
    elif mutation == "voice":
        data["audio"]["phrases"]["happy"] = [["missing"]]
    elif mutation == "catalog":
        del data["animations"]["WORK"]
    elif mutation == "customization":
        data["customization"]["illumination"]["default"] = "missing"
    else:
        data["renderer"] = "missing"
    path.write_text(json.dumps(data), encoding="utf-8")
    registry = DroidRegistry(root)
    assert set(registry.profiles) == {"r2_default", "spherical_droid"}
    assert "dark_astromech" in registry.errors


@pytest.mark.parametrize("identifier", ["r2_default", "dark_astromech", "spherical_droid"])
def test_theme_contrast_and_complete_identity(registry, identifier):
    colors = registry.get(identifier).theme.colors
    for fg, bg in (("text", "background"), ("text", "panel"), ("muted", "panel"),
                   ("hero_text", "hero"), ("button_text", "primary"), ("text", "selected")):
        assert contrast(colors[fg], colors[bg]) >= 4.5
    assert len(colors) >= 19


def test_legacy_settings_migrate_without_copying_behavior_to_new_droids(registry):
    legacy = Settings(appearance="violet", personality="talkative", sound_enabled=True)
    legacy.audio.volume = 0.12
    legacy.behavior.movement = False
    legacy.applications = [Target("one", "Editor", r"C:\Editor.exe", "app")]
    legacy.quiet_enabled = True
    current = select_droid(legacy, registry.active)
    other = select_droid(current, registry.get("dark_astromech"))
    assert other.personality == "calm" and other.behavior.movement
    assert other.audio.volume == 0.35 and other.sound_enabled
    assert other.quiet_enabled and other.applications == legacy.applications
    restored = select_droid(other, registry.active)
    assert restored.appearance == "violet" and restored.personality == "talkative"
    assert restored.audio.volume == 0.12 and not restored.behavior.movement
    assert Settings.parse(restored.to_dict()) == restored


@pytest.mark.parametrize("raw", [{"active_droid": "../bad"}, {"droid_preferences": []},
    {"droid_preferences": {"a": {"audio": {"volume": -1}}}},
    {"droid_preferences": {"a": {"customization": {"x": []}}}}])
def test_invalid_individual_preferences_are_rejected(raw):
    with pytest.raises(ValueError):
        Settings.parse(raw)


def test_equipping_updates_existing_services_theme_and_persistence(pet, qapp):
    controller, audio_service, positioner = pet.controller, pet.audio, pet.positioning
    pet.show_tools()
    before = pet.tools.styleSheet()
    assert pet.equip_droid("dark_astromech"), pet.droid_error
    assert pet.controller is controller and pet.audio is audio_service and pet.positioning is positioner
    assert pet.profile.id == pet.droids.active_id == pet.store.settings.active_droid == "dark_astromech"
    assert pet.audio.profile_id == "dark_astromech" and pet.behavior.settings.frequency == "quiet"
    assert pet.tools.styleSheet() != before
    assert pet.profile.theme.colors["panel"] in pet.tools.styleSheet()
    assert json.loads(pet.store.path.read_text(encoding="utf-8"))["active_droid"] == "dark_astromech"
    assert pet.equip_droid("spherical_droid"), pet.droid_error
    assert isinstance(pet.positioning.movement, SphericalMovementController)
    assert isinstance(pet.window.visual, DroidVisual)
    assert pet.profile.theme.colors["panel"] in pet.tools.styleSheet()
    assert pet.equip_droid("r2_default")
    assert isinstance(pet.positioning.movement, DroidMovementController) and pet.window.visual is None


@pytest.mark.parametrize("stage", ["prepare", "theme", "persist", "animation"])
def test_failed_swap_restores_resources_and_persistent_selection(pet, monkeypatch, stage):
    assert pet.store.flush()
    before_file = pet.store.path.read_bytes()
    before = deepcopy(pet.store.settings)
    old_motion, old_clips = pet.positioning.movement, pet.animation.clips
    def fail(*args, **kwargs):
        raise ValueError("injected failure")
    if stage == "prepare":
        monkeypatch.setattr(pet.audio, "prepare_profile", fail)
    elif stage == "persist":
        monkeypatch.setattr(pet.store, "flush", lambda: False)
    elif stage == "theme":
        manager = theme_manager()
        apply = manager.apply
        def fail_new(theme):
            if theme.name == "Oficina de bronze":
                raise ValueError("injected theme failure")
            apply(theme)
        monkeypatch.setattr(manager, "apply", fail_new)
    else:
        play = pet.animation.play
        def fail_new(state, token):
            if pet.profile.id == "dark_astromech":
                raise ValueError("injected frame failure")
            play(state, token)
        monkeypatch.setattr(pet.animation, "play", fail_new)
    assert not pet.equip_droid("dark_astromech")
    assert pet.profile.id == pet.audio.profile_id == pet.store.settings.active_droid == "r2_default"
    assert pet.store.settings == before and pet.store.path.read_bytes() == before_file
    assert pet.positioning.movement is old_motion and pet.animation.clips is old_clips
    assert "droid_swap" not in pet.controller.gates
    assert theme_manager().active == pet.profile.theme
    assert pet.controller.request(State.WORK)


def test_repeated_switches_keep_individual_preferences_and_retire_timers(pet, qapp):
    retired = []
    for i in range(9):
        identifier = ("dark_astromech", "spherical_droid", "r2_default")[i % 3]
        previous = pet.positioning.movement
        assert pet.equip_droid(identifier), pet.droid_error
        assert not getattr(previous, "timer", pet.positioning.timer).isActive()
        settings = deepcopy(pet.store.settings)
        settings.audio.volume = {"dark_astromech": 0.11, "spherical_droid": 0.22, "r2_default": 0.33}[identifier]
        settings.appearance = "violet" if identifier == "r2_default" else "blue"
        pet.store.apply(settings)
        qapp.sendPostedEvents(None, 0)
    for identifier, expected in (("dark_astromech", 0.11), ("spherical_droid", 0.22), ("r2_default", 0.33)):
        assert pet.equip_droid(identifier)
        assert pet.store.settings.audio.volume == expected
    assert pet.store.settings.appearance == "violet"


def test_sphere_body_rolls_with_distance_and_head_recovers(qapp, clock):
    window = PetWindow()
    window.resize(160, 160)
    motion = SphericalMovementController(window, clock=clock)
    clock.advance(0.033)
    motion.displaced(10, 0, manual=True)
    assert motion.angle == pytest.approx(math.degrees(10 / 50))
    assert window.body_angle == motion.angle and 0 < motion.head_tilt <= 12
    assert abs(motion.head_offset) <= 2.5
    tilt = motion.head_tilt
    motion.release()
    motion.recover()
    assert 0 < motion.head_tilt < tilt
    for _ in range(40):
        motion.recover()
    assert motion.head_tilt == motion.head_offset == 0
    assert not motion.timer.isActive() and window.body_angle != 0
    motion.close()
    window.hide()


def test_sphere_acceleration_and_deceleration_are_smooth(qapp):
    motion = SphericalMovementController(PetWindow())
    assert motion.progress(0) == 0 and motion.progress(1) == 1
    assert motion.progress(0.1) < 0.1 and motion.progress(0.9) > 0.9
    first = motion.progress(0.1) - motion.progress(0)
    middle = motion.progress(0.6) - motion.progress(0.5)
    final = motion.progress(1) - motion.progress(0.9)
    assert middle > first and middle > final
    motion.close()


def test_layered_components_move_independently(qapp, registry):
    visual = load_profile_clips(registry.get("spherical_droid"))[State.IDLE].frames[0].visual
    def render(angle, tilt):
        image = QImage(64, 64, QImage.Format.Format_ARGB32)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        paint_visual(painter, QRectF(0, 0, 64, 64), visual, angle, tilt)
        painter.end()
        return image
    idle, rolling, tilted = render(0, 0), render(70, 0), render(0, 15)
    assert idle.copy(10, 0, 44, 18) == rolling.copy(10, 0, 44, 18)
    assert idle.copy(10, 23, 44, 40) != rolling.copy(10, 23, 44, 40)
    assert idle.copy(10, 25, 44, 38) == tilted.copy(10, 25, 44, 38)
    assert idle.copy(10, 0, 44, 18) != tilted.copy(10, 0, 44, 18)


def test_spherical_drag_recovery_corners_and_fullscreen(pet, monkeypatch):
    assert pet.equip_droid("spherical_droid")
    pet.window.dragging = True
    pet.drag_started()
    old_x = pet.window.x()
    pet.positioning.drag(QPointF(old_x + 40, pet.window.y()), QPointF(0, 0))
    motion = pet.positioning.movement
    assert motion.angle != 0 and motion.head_tilt != 0
    pet.window.dragging = False
    pet.drag_finished()
    assert pet.controller.state == State.RECOVER and motion.timer.isActive()
    assert pet.window.head_tilt != 0
    monkeypatch.setattr("r2_companion.app.foreground_fullscreen", lambda hwnd: True)
    pet.check_desktop()
    assert not motion.timer.isActive() and not pet.positioning.timer.isActive()
    assert not pet.controller.request(State.WALK) and pet.audio.suppressed


def test_spherical_walk_stays_in_available_area(pet, clock):
    assert pet.equip_droid("spherical_droid")
    pet.positioning.clock = clock
    pet.positioning.place(QPointF(-100000, -100000))
    area = QRectF(pet.positioning.screen.availableGeometry())
    left, right, top, bottom = legal_bounds(area, QSizeF(pet.window.size()))
    assert pet.positioning.walk(80, 2, 42)
    clock.advance(1)
    pet.positioning.tick()
    assert left <= pet.window.x() <= right and top <= pet.window.y() <= bottom
    assert pet.window.body_angle != 0
    clock.advance(2)
    pet.positioning.tick()
    assert not pet.positioning.timer.isActive()


def test_garage_preview_changes_neither_active_character_nor_preferences(pet, qapp):
    garage = DroidGarage(pet)
    before = deepcopy(pet.store.settings)
    active_theme = theme_manager().active
    garage.selector.setCurrentIndex(garage.selector.findData("spherical_droid"))
    assert garage.profile.id == "spherical_droid" and pet.profile.id == "r2_default"
    assert pet.store.settings == before and theme_manager().active == active_theme
    assert garage.profile.theme.colors["panel"] in garage.styleSheet()
    garage.custom_controls["illumination"].setCurrentIndex(1)
    assert garage.preview.illumination == "#ff6654"
    assert pet.store.settings == before
    garage.equip()
    assert pet.profile.id == "spherical_droid"
    assert pet.window.illumination == "#ff6654"
    garage.close()


def test_gallery_filters_actual_clips_can_play_stop_and_show_frames(pet):
    gallery = AnimationGallery(pet)
    gallery.selector.setCurrentIndex(gallery.selector.findData("spherical_droid"))
    assert gallery.animations.count() == len(gallery.profile.animations)
    gallery.category.setCurrentIndex(gallery.category.findData("Locomoção"))
    assert gallery.animations.count() == 3
    gallery.play()
    assert gallery.preview.roll_timer.isActive()
    gallery.stop()
    assert not gallery.animation.timer.isActive() and not gallery.preview.roll_timer.isActive()
    gallery.frame_variant.setCurrentIndex(2)
    assert isinstance(gallery.preview.frame, DroidVisual)
    assert pet.controller.animation is pet.animation and pet.profile.id == "r2_default"
    gallery.close()


def test_audio_profiles_preview_volume_and_cleanup(audio, registry, clock):
    profile = registry.get("dark_astromech")
    assert audio.vocalize("greeting")
    clock.advance(4)
    settings = deepcopy(audio.settings)
    settings.volume = 0.14
    assert audio.preview(profile.audio, "voice", "greeting", 1, settings)
    assert audio.profile_id == "r2_default" and audio.settings.volume == 0.35
    playing = [e for e in audio.all_effects() if e.playing]
    assert len(playing) == 1 and playing[0].volume == 0.14
    path = Path(audio.preview_bank["directory"].name)
    bank = audio.prepare_profile(registry.get("spherical_droid").audio)
    previous = audio.activate_profile(bank)
    assert not any(e.playing for e in audio.all_effects())
    assert audio.preview_bank is None and not path.exists()
    assert audio.profile_id == "spherical_droid"
    audio.release_bank(previous)
    assert not audio.vocalize("greeting")
    clock.advance(4)
    assert audio.vocalize("greeting")


def test_audio_center_saves_other_droid_without_equipping_or_overwriting_current(pet):
    center = AudioCenter(pet)
    original = deepcopy(pet.store.settings.audio)
    center.selector.setCurrentIndex(center.selector.findData("dark_astromech"))
    assert center.catalog.count() == 25
    center.volume.setValue(17)
    center.categories["movement"].setChecked(False)
    center.save()
    assert pet.profile.id == "r2_default" and pet.store.settings.audio == original
    assert pet.store.settings.droid_preferences["dark_astromech"].audio.volume == 0.17
    assert pet.equip_droid("dark_astromech")
    assert pet.audio.settings.volume == 0.17 and not pet.audio.settings.categories["movement"]
    center.close()


def test_all_existing_interfaces_follow_global_theme(pet):
    pet.show_settings()
    pet.show_audio_center()
    for identifier in ("dark_astromech", "spherical_droid", "r2_default"):
        assert pet.equip_droid(identifier)
        colors = pet.profile.theme.colors
        assert colors["panel"] in pet.tools.styleSheet()
        assert colors["text"] in pet.audio_dialog.styleSheet()
        assert colors["notification"] in pet.bubble.styleSheet()
        assert colors["panel"] in pet.tools.notes_page.body.styleSheet()
        assert colors["primary"] in pet.menu.styleSheet()
        assert colors["hero"] in pet.radial.styleSheet()
        pet.show_settings()
        assert colors["background"] in pet.settings_dialog.styleSheet()


def test_update_center_watcher_tracks_persisted_theme_without_taking_lock(pet):
    watcher = PersistedThemeWatcher(pet.store.directory, ASSETS)
    assert pet.equip_droid("dark_astromech")
    theme_manager().apply(pet.droids.get("r2_default").theme)
    watcher.refresh()
    assert watcher.last_id == "dark_astromech" and theme_manager().active == pet.profile.theme
    watcher.timer.stop()


def test_restart_and_corrupt_configuration_preserve_profiles_and_tools(pet, qapp):
    assert pet.equip_droid("spherical_droid")
    settings = deepcopy(pet.store.settings)
    settings.audio.volume = 0.16
    pet.store.apply(settings)
    assert pet.store.flush()
    pet.productivity.add_task("Preservar tarefa")
    pet.productivity.flush()
    tools_bytes = pet.productivity.path.read_bytes()
    directory = pet.store.directory
    pet.shutdown()
    qapp.processEvents()
    store = ConfigStore(directory)
    assert store.acquire()
    store.load()
    second = Companion(qapp, store)
    assert second.profile.id == "spherical_droid" and second.audio.settings.volume == 0.16
    assert second.productivity.path.read_bytes() == tools_bytes
    second.shutdown()
    qapp.processEvents()
    (directory / "config.json").write_text("{broken", encoding="utf-8")
    recovered = ConfigStore(directory)
    recovered.load()
    assert recovered.settings.active_droid == "spherical_droid"
    assert "r2_default" in recovered.settings.droid_preferences


def test_reaction_diagnostics_hologram_and_quiet_hours_use_active_profile(pet, monkeypatch):
    assert pet.equip_droid("spherical_droid")
    assert pet.reactions.start("diagnosis") and pet.controller.state == State.WORK
    report = pet.droid_diagnostics()
    assert report["Renderizador"] == "layered" and report["Locomoção"] == "SphericalMovementController"
    assert report["Perfil vocal"] == "spherical_droid"
    pet.project_tool("clock")
    assert not pet.window.hologram.isNull()
    monkeypatch.setattr("r2_companion.app.quiet_now", lambda settings: True)
    pet.check_desktop()
    assert pet.audio.suppressed and not pet.reactions.start("game")
    assert pet.equip_droid("dark_astromech")
    assert "quiet_hours" in pet.controller.gates and not pet.controller.request(State.WALK)


def test_missing_optional_animation_is_not_requested_or_shown(pet):
    pet.animation.clips = {State.IDLE: pet.animation.clips[State.IDLE]}
    assert not pet.controller.react(State.WORK)
    assert not pet.controller.request(State.WALK)
    assert not pet.reactions.start("diagnosis")
    assert pet.controller.state == State.IDLE


@pytest.mark.parametrize("restriction", ["master", "mute", "preview_mute", "category", "fullscreen", "sleep"])
def test_preview_respects_existing_audio_policies(audio, registry, restriction):
    settings = deepcopy(audio.settings)
    if restriction == "master":
        audio.enabled = False
    elif restriction == "mute":
        audio.settings.muted = True
    elif restriction == "preview_mute":
        settings.muted = True
    elif restriction == "category":
        settings.categories["reactions"] = False
    elif restriction == "fullscreen":
        audio.set_context(True, False)
    else:
        audio.set_context(False, True)
    assert not audio.preview(registry.get("dark_astromech").audio, "voice", "greeting", 0, settings)
    assert not any(effect.playing for effect in audio.all_effects())


def test_heading_has_readable_text_token_on_dark_background(pet):
    assert pet.equip_droid("dark_astromech")
    sheet = pet.tools.styleSheet()
    assert f"QLabel[role='heading'] {{ color: {pet.profile.theme.colors['text']}" in sheet


def test_corrupt_image_prevents_swap_without_touching_active_droid(pet, tmp_path):
    root = tmp_path / "assets"
    shutil.copytree(ASSETS, root)
    (root / "droids/dark_astromech/sprites/vesper.png").write_bytes(b"broken PNG")
    registry = DroidRegistry(root)
    pet.droid_controller.registry = registry
    assert not pet.equip_droid("dark_astromech")
    assert pet.profile.id == "r2_default" and pet.audio.profile_id == "r2_default"


def test_unsupported_saved_character_falls_back_and_preserves_its_preferences(pet, qapp):
    directory = pet.store.directory
    settings = deepcopy(pet.store.settings)
    settings.capture_droid()
    settings.active_droid = "uninstalled_droid"
    settings.audio.volume = 0.13
    pet.store.apply(settings, notify=False)
    pet.store.flush()
    pet.shutdown()
    qapp.processEvents()
    store = ConfigStore(directory)
    assert store.acquire()
    store.load()
    replacement = Companion(qapp, store)
    try:
        assert replacement.profile.id == "r2_default"
        assert store.settings.droid_preferences["uninstalled_droid"].audio.volume == 0.13
    finally:
        replacement.shutdown()
        qapp.processEvents()


@pytest.mark.parametrize("component", ["voice", "effect"])
def test_corrupt_pcm_is_rejected_and_prepared_resources_are_released(audio, registry, tmp_path, component):
    source = tmp_path / "assets"
    shutil.copytree(ASSETS, source)
    path = source / ("droids/dark_astromech/audio/voice/soft.wav" if component == "voice" else "sounds/idle/happy.wav")
    path.write_bytes(b"invalid PCM")
    profile = DroidRegistry(source).get("dark_astromech")
    previous = audio.profile_id
    with pytest.raises(ValueError, match="PCM"):
        audio.prepare_profile(profile.audio)
    assert audio.profile_id == previous
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    assert len(audio.findChildren(type(audio.all_effects()[0]))) == 45


def test_shutdown_releases_audio_objects_monitor_hooks_and_theme_subscriptions(pet, qapp):
    audio = pet.audio
    pet.shutdown()
    assert not audio.all_effects() and not pet.positioning.tracked_screens
    assert pet.tools not in theme_manager().widgets
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    from PySide6.QtMultimedia import QSoundEffect
    assert not audio.findChildren(QSoundEffect)


@pytest.mark.parametrize("factory", [DroidGarage, AnimationGallery, AudioCenter])
def test_new_dialogs_fit_small_work_areas_without_clipping_controls(pet, qapp, factory):
    dialog = factory(pet)
    dialog.resize(480, 360)
    dialog.show()
    qapp.processEvents()
    assert dialog.width() == 480 and dialog.height() == 360
    assert dialog.scroll_area.verticalScrollBar().maximum() > 0
    dialog.close()


def test_invalid_default_profile_does_not_block_other_characters(tmp_path):
    root = tmp_path / "assets"
    shutil.copytree(ASSETS, root)
    (root / "droids/r2_default/profile.json").write_text("{broken", encoding="utf-8")
    registry = DroidRegistry(root)
    assert registry.default_id == "dark_astromech"
    assert registry.active.id == "dark_astromech" and "r2_default" in registry.errors


def test_startup_recovers_when_active_voice_resources_are_corrupt(pet, qapp, tmp_path, monkeypatch):
    root = tmp_path / "assets"
    shutil.copytree(ASSETS, root)
    (root / "droids/dark_astromech/audio/voice/soft.wav").write_bytes(b"invalid")
    directory = pet.store.directory
    assert pet.equip_droid("dark_astromech")
    pet.shutdown()
    qapp.processEvents()
    monkeypatch.setattr("r2_companion.app.ASSETS", root)
    store = ConfigStore(directory)
    assert store.acquire()
    store.load()
    recovered = Companion(qapp, store)
    try:
        assert recovered.profile.id == "r2_default"
        assert "dark_astromech" in store.settings.droid_preferences
    finally:
        recovered.shutdown()
        qapp.processEvents()


def test_custom_illumination_follows_head_frames_instead_of_screen_coordinates(pet):
    profile = pet.droids.get("dark_astromech")
    preferences = defaults_for(profile)
    preferences.customization["illumination"] = "red"
    assert pet.equip_droid(profile.id, preferences)
    for frame in pet.animation.clips[State.DRAG].frames:
        pet.window.set_frame(frame.pixmap)
        original, tinted = frame.pixmap.toImage(), pet.window.frame.toImage()
        for y in range(64):
            for x in range(64):
                if original.pixelColor(x, y) == QColor("#edac4b"):
                    assert tinted.pixelColor(x, y) == QColor("#ff6654")
