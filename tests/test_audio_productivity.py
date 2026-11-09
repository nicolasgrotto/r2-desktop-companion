from copy import deepcopy
import json
import random
import wave

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtTest import QSignalSpy

from r2_companion.app import ASSETS
from r2_companion.core.config import AudioSettings, Settings
from r2_companion.features.productivity import ProductivityStore
from r2_companion.services.audio import AudioService
from r2_companion.ui.productivity import NotesPage, TasksPage
from r2_companion.pet.animation import load_clips
from r2_companion.pet.state import State


class Effect(QObject):
    statusChanged = Signal()

    def __init__(self, parent):
        super().__init__(parent)
        self.playing = False
        self.plays = 0
        self.ready = QSoundEffect.Status.Ready

    def setLoopCount(self, count):
        assert count == 1

    def setVolume(self, volume):
        self.volume = volume

    def setSource(self, url):
        self.url = url

    def status(self):
        return self.ready

    def play(self):
        self.playing = True
        self.plays += 1

    def stop(self):
        self.playing = False


@pytest.fixture
def audio(qapp, clock):
    service = AudioService(ASSETS / "sounds", clock, random.Random(5), Effect, lambda: True)
    service.configure(True, AudioSettings())
    yield service
    service.close()


def test_original_wavs_are_short_valid_and_varied():
    paths = list((ASSETS / "sounds").glob("*/*.wav"))
    assert len(paths) == 15
    assert len({p.read_bytes() for p in paths}) == 15
    for path in paths:
        with wave.open(str(path), "rb") as sound:
            assert sound.getnchannels() == 1 and sound.getsampwidth() == 2
            assert 0.1 <= sound.getnframes() / sound.getframerate() <= 1


def test_timer_celebration_has_visibly_different_frames(qapp):
    clip = load_clips(ASSETS / "characters/default/manifest.json")[State.NOTIFICATION]
    assert not clip.loop
    assert len({frame.pixmap.cacheKey() for frame in clip.frames}) > 1
    assert clip.frames[0].pixmap.toImage() != clip.frames[1].pixmap.toImage()


def test_audio_volume_mute_cooldowns_variants_and_single_voice(audio, clock):
    audio.configure(True, AudioSettings(volume=0.2, min_interval=2))
    assert all(e.volume == 0.2 for values in audio.effects.values() for _, e in values)
    assert audio.play("reactions", "click")
    first = audio.previous["reactions"]
    assert not audio.play("movement")
    clock.advance(4)
    assert audio.play("reactions", "click")
    assert first != audio.previous["reactions"]
    assert sum(e.playing for values in audio.effects.values() for _, e in values) == 1
    audio.configure(True, AudioSettings(muted=True))
    assert not any(e.playing for values in audio.effects.values() for _, e in values)
    clock.advance(100)
    assert not audio.play()


def test_sleep_fullscreen_disabled_categories_and_missing_device(audio, clock):
    audio.set_context(False, True)
    assert not audio.play("reactions")
    assert audio.play("sleep", "enter")
    clock.advance(100)
    audio.set_context(True, False)
    assert not audio.play("notifications")
    audio.set_context(False, False)
    audio.settings.categories["notifications"] = False
    assert not audio.play()
    audio.settings.categories["notifications"] = True
    audio.available = lambda: False
    assert not audio.play()
    audio.available = lambda: True
    for _, effect in audio.effects["notifications"]:
        effect.ready = QSoundEffect.Status.Error
    assert not audio.play()
    audio.close()
    assert not audio.play("sleep")


def test_idle_category_has_long_cooldown(audio, clock):
    assert audio.play("idle")
    clock.advance(30)
    assert not audio.play("idle")
    clock.advance(61)
    assert audio.play("idle")


@pytest.mark.parametrize("raw", [
    {"audio": {"volume": 2}}, {"audio": {"muted": 1}}, {"audio": {"min_interval": 0}},
    {"audio": {"categories": {"other": True}}}, {"audio": {"categories": {"idle": 1}}},
    {"fullscreen_mode": "never"}, {"manual_position": {"corner": "center"}},
    {"behavior": {"weights": {"HACK": 1}}}, {"behavior": {"reaction_interval": 0}},
])
def test_invalid_new_preferences_rejected(raw):
    with pytest.raises(ValueError):
        Settings.parse(raw)


def test_legacy_preferences_and_new_groups_round_trip():
    legacy = Settings.parse({"sound_enabled": True, "suppress_fullscreen": False})
    assert legacy.fullscreen_mode == "quiet" and legacy.sound_enabled
    assert Settings.parse(legacy.to_dict()) == legacy
    partial = Settings.parse({"audio": {"categories": {"idle": False}}})
    assert not partial.audio.categories["idle"] and partial.audio.categories["notifications"]


def test_tasks_notes_persist_completion_once_and_reopen(qapp, tmp_path):
    store = ProductivityStore(tmp_path)
    spy = QSignalSpy(store.task_completed)
    task = store.add_task("Finalizar montagem")
    note = store.add_note()
    store.edit_note(note, "Medidas", "Linha 1\nLinha 2 — 中文")
    store.set_done(task, True)
    store.set_done(task, True)
    assert spy.count() == 1
    store.set_done(task, False)
    assert not store.data["tasks"][0]["done"]
    assert store.flush()
    restored = ProductivityStore(tmp_path)
    assert restored.data == store.data
    restored.remove("tasks", task)
    restored.remove("notes", note)
    restored.close()
    assert ProductivityStore(tmp_path).data == {"schema_version": 1, "tasks": [], "notes": []}
    store.close()


def test_corrupt_tools_backup_future_schema_and_atomic_failure(qapp, tmp_path, monkeypatch):
    store = ProductivityStore(tmp_path)
    store.add_task("Primeira")
    assert store.flush()
    store.add_task("Segunda")
    assert store.flush()
    store.path.write_text("{broken", encoding="utf-8")
    recovered = ProductivityStore(tmp_path)
    assert len(recovered.data["tasks"]) == 1
    assert recovered.path.with_name("tools.corrupt.json").read_text() == "{broken"
    assert recovered.notices
    recovered.add_task("Recuperada")
    assert recovered.flush()
    original = recovered.path.read_bytes()
    monkeypatch.setattr("r2_companion.features.productivity.ConfigStore.atomic_write", lambda *a: (_ for _ in ()).throw(OSError("full")))
    recovered.add_task("Sem espaço")
    assert not recovered.flush() and recovered.path.read_bytes() == original
    recovered.path.write_text('{"schema_version":99}', encoding="utf-8")
    future = ProductivityStore(tmp_path)
    future.add_task("Sessão")
    assert future.read_only and not future.flush()
    assert json.loads(future.path.read_text())["schema_version"] == 99


def test_invalid_tool_records_do_not_replace_current_data(qapp, tmp_path):
    store = ProductivityStore(tmp_path)
    store.add_task("Válida")
    previous = deepcopy(store.data)
    for text in ("", "x" * 241, "ruim\x00", "quebra\nlinha"):
        with pytest.raises(ValueError):
            store.add_task(text)
        assert store.data == previous
    note = store.add_note()
    with pytest.raises(ValueError):
        store.edit_note(note, "Título", "x" * 50001)
    assert store.data["notes"][0]["body"] == ""
    store.close()


def test_tasks_and_notes_widgets_copy_edit_filter_and_autosave(qapp, tmp_path):
    store = ProductivityStore(tmp_path)
    tasks = TasksPage(store)
    tasks.input.setText("Organizar bancada")
    tasks.add()
    from PySide6.QtCore import Qt
    tasks.list.item(0).setCheckState(Qt.CheckState.Checked)
    assert store.data["tasks"][0]["done"]
    tasks.pending.setChecked(True)
    assert tasks.list.count() == 0
    tasks.pending.setChecked(False)
    tasks.list.item(0).setCheckState(Qt.CheckState.Unchecked)
    assert not store.data["tasks"][0]["done"]
    notes = NotesPage(store)
    notes.add()
    notes.title.setText("Projeto")
    notes.body.setPlainText("Anotação local")
    notes.copy()
    assert qapp.clipboard().text() == "Anotação local"
    assert "Salvando" in notes.status.text()
    store.timer.timeout.emit()
    assert "Salvo" in notes.status.text()
    assert ProductivityStore(tmp_path).data["notes"][0]["title"] == "Projeto"
    notes.body.setPlainText("x" * 50001)
    assert len(store.data["notes"][0]["body"]) == 50000
    notes.remove()
    assert not store.data["notes"]
    store.close()
