from datetime import datetime
from types import SimpleNamespace
import wave

import pytest
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QSignalSpy, QTest

from r2_companion.app import ASSETS
from r2_companion.core.config import Settings
from r2_companion.features.minigames import GAMES, Minigame, open_game
from r2_companion.features.diagnostics import collect_diagnostics
from r2_companion.pet.personality import apply_profile, quiet_now
from r2_companion.pet.state import State
from r2_companion.services.vocalizations import compose_phrases, PHRASES
from test_context_v03 import pet
from test_audio_productivity import audio


def test_vocalizations_are_original_short_varied_and_expressive(tmp_path):
    result = compose_phrases(ASSETS / "voice", tmp_path)
    assert set(result) == set(PHRASES) and len(result) == 10
    for emotion, paths in result.items():
        assert len(paths) == 3 and len({p.read_bytes() for p in paths}) == 3
        for path in paths:
            with wave.open(str(path)) as sound:
                assert 0.1 <= sound.getnframes() / sound.getframerate() <= 1.2
                assert sound.getnchannels() == 1 and sound.getsampwidth() == 2


def test_voice_respects_volume_global_cooldown_categories_sleep_and_fullscreen(audio, clock):
    assert len(audio.voices) == 10
    assert audio.vocalize("greeting")
    assert sum(effect.playing for effect in audio.all_effects()) == 1
    assert not audio.vocalize("happy")
    clock.advance(4)
    audio.settings.categories["reactions"] = False
    assert not audio.vocalize("greeting")
    audio.settings.categories["reactions"] = True
    audio.set_context(False, True)
    assert not audio.vocalize("happy")
    assert audio.vocalize("sleep", "sleep")
    audio.set_context(True, False)
    clock.advance(10)
    assert not audio.vocalize("celebrate")
    audio.set_context(False, False)
    audio.settings.muted = True
    assert not audio.vocalize("greeting")


@pytest.mark.parametrize("name", ["calm", "curious", "talkative"])
def test_personalities_preserve_user_master_audio_and_round_trip(name):
    initial = Settings()
    initial.audio.muted = True
    initial.audio.volume = 0.12
    profile = apply_profile(initial, name)
    assert not profile.sound_enabled and profile.audio.muted and profile.audio.volume == 0.12
    assert profile.personality == name and Settings.parse(profile.to_dict()) == profile
    assert initial.personality == "custom"


@pytest.mark.parametrize("start,end,hour,minute,expected", [(1320, 480, 23, 0, True),
    (1320, 480, 7, 59, True), (1320, 480, 8, 0, False), (1320, 480, 22, 0, True),
    (600, 900, 10, 0, True), (600, 900, 15, 0, False), (0, 0, 12, 0, True)])
def test_quiet_schedule_boundaries(start, end, hour, minute, expected):
    settings = Settings(quiet_enabled=True, quiet_start=start, quiet_end=end)
    assert quiet_now(settings, datetime(2026, 11, 12, hour, minute)) is expected


@pytest.mark.parametrize("raw", [{"personality": "random"}, {"appearance": "red"},
    {"quiet_start": 1440}, {"quiet_end": -1}, {"quiet_enabled": 1}, {"audio": {"idle_interval": 0}}])
def test_invalid_new_settings_rejected(raw):
    with pytest.raises(ValueError):
        Settings.parse(raw)


def test_quiet_schedule_blocks_spontaneous_motion_audio_and_notices(pet, monkeypatch):
    monkeypatch.setattr("r2_companion.app.quiet_now", lambda settings: True)
    pet.check_desktop()
    assert "quiet_hours" in pet.controller.gates and pet.audio.suppressed
    assert not pet.behavior.timer.isActive() and not pet.tray.notifications_enabled
    assert not pet.reactions.start("game")
    monkeypatch.setattr("r2_companion.app.quiet_now", lambda settings: False)
    pet.check_desktop()
    assert "quiet_hours" not in pet.controller.gates


def test_minigames_open_only_the_registered_https_url_with_qurl(qapp):
    calls = []
    assert open_game("duel-of-fates", lambda url: calls.append(url) or True)
    assert calls[0].toString() == "https://nicolasgrotto.github.io/duel-of-fates/"
    assert calls[0].scheme() == "https"
    with pytest.raises(ValueError):
        open_game("unknown", lambda url: pytest.fail("unknown game launched"))
    with pytest.raises(ValueError):
        open_game("bad", games=(Minigame("bad", "Bad", "Bad", "file:///C:/bad.exe"),))
    assert not open_game("duel-of-fates", lambda url: False)


def test_catalog_button_launches_once_and_fullscreen_suppresses_reaction(pet, monkeypatch):
    calls = []
    monkeypatch.setattr("r2_companion.app.open_game", lambda key: calls.append(key) or True)
    pet.show_tools_page(pet.tools.tabs.indexOf(pet.tools.minigames_page))
    from PySide6.QtWidgets import QPushButton
    button = next(b for b in pet.tools.minigames_page.findChildren(QPushButton) if "Jogar" in b.text())
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    assert calls == [GAMES[0].id] and pet.reactions.scene == "game"
    pet.controller.set_gate("fullscreen", True)
    assert pet.reactions.scene is None
    assert pet.launch_minigame(GAMES[0].id)
    assert len(calls) == 2 and pet.reactions.scene is None


def test_pet_head_holds_react_but_do_not_open_radial_or_drag(pet):
    window = pet.window
    clicked = QSignalSpy(window.clicked)
    petted = QSignalSpy(window.petted)
    QTest.mousePress(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 35))
    window.affection_timer.timeout.emit()
    QTest.mouseRelease(window, Qt.MouseButton.LeftButton, pos=QPoint(80, 35))
    assert petted.count() == 1 and clicked.count() == 0
    assert pet.reactions.scene == "affection" and not pet.radial.isVisible()


def test_scene_chains_sound_on_peak_and_restores_previous_state(pet, monkeypatch):
    calls = []
    monkeypatch.setattr(pet.audio, "vocalize", lambda emotion, category: calls.append((emotion, category)))
    pet.controller.enter(State.WORK)
    calls.clear()
    assert pet.reactions.start("task")
    assert pet.controller.state == State.LOOK_AROUND and not calls
    pet.controller.finished(pet.controller.token)
    assert pet.controller.state == State.HAPPY and calls == [("celebrate", "reactions")]
    pet.controller.finished(pet.controller.token)
    assert pet.controller.state == State.WORK and pet.reactions.scene is None
    pet.reactions.start("affection")
    pet.drag_started()
    assert pet.reactions.scene is None


def test_visual_variants_keep_transparency_and_cached_frames(pet):
    window = pet.window
    original = window.original_frame
    window.set_appearance("teal")
    first = window.frame
    assert first.toImage() != original.toImage()
    assert first.toImage().pixelColor(0, 0).alpha() == 0
    window.set_frame(original)
    assert window.frame.cacheKey() == first.cacheKey()
    window.set_appearance("blue")
    assert window.frame.cacheKey() == original.cacheKey()


def test_diagnostics_handles_missing_battery_and_runs_only_on_request(pet):
    page = pet.tools.diagnostics_page
    assert not page.timer.isActive()
    page.start()
    assert page.timer.isActive() and pet.reactions.scene == "diagnosis"
    page.timer.timeout.emit()
    assert page.fields["Versão"].text()
    system = SimpleNamespace(sample=lambda **kw: {"cpu": 10, "ram": 20, "battery": None, "charging": None})
    audio = SimpleNamespace(available=lambda: False, all_effects=lambda: [], enabled=False, settings=SimpleNamespace(muted=True))
    report = collect_diagnostics(system, audio)
    assert report["Bateria"] == "Indisponível" and report["Som do R2"] == "Silencioso"
