import logging
from pathlib import Path
import random
import time
import tempfile

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QMediaDevices, QSoundEffect

from ..core.config import AudioSettings
from .vocalizations import compose_phrases

log = logging.getLogger(__name__)
CATEGORY_INTERVALS = {"idle": 90, "movement": 12, "reactions": 3, "sleep": 3, "notifications": 1}


class AudioService(QObject):
    def __init__(self, directory: Path, clock=time.monotonic, rng=None, factory=QSoundEffect,
                 available=None):
        super().__init__()
        self.directory = directory
        self.clock, self.rng = clock, rng or random.Random()
        self.enabled = False
        self.settings = AudioSettings()
        self.effects = {}
        self.previous = {}
        self.history = {}
        self.last_play = -1000000.0
        self.available = available or (lambda: bool(QMediaDevices.audioOutputs()))
        self.suppressed = False
        self.sleeping = False
        self.closed = False
        self.voices = {}
        self.voice_directory = None
        for category in CATEGORY_INTERVALS:
            for path in sorted(directory.glob(f"{category}/*.wav")):
                try:
                    effect = factory(self)
                    effect.setLoopCount(1)
                    effect.setVolume(self.settings.volume)
                    effect.setSource(QUrl.fromLocalFile(str(path)))
                    effect.statusChanged.connect(lambda e=effect, p=path: self.check_status(e, p))
                    self.effects.setdefault(category, []).append((path.stem, effect))
                except (OSError, RuntimeError):
                    log.warning("Não foi possível carregar efeito %s", path.name)
        source = directory.parent / "voice"
        if source.is_dir():
            try:
                self.voice_directory = tempfile.TemporaryDirectory(prefix="r2-voice-")
                for emotion, paths in compose_phrases(source, Path(self.voice_directory.name)).items():
                    self.voices[emotion] = []
                    for path in paths:
                        effect = factory(self)
                        effect.setLoopCount(1)
                        effect.setVolume(self.settings.volume)
                        effect.setSource(QUrl.fromLocalFile(str(path)))
                        self.voices[emotion].append((path.stem, effect))
            except (OSError, ValueError, RuntimeError):
                log.warning("Vocalizações indisponíveis; efeitos básicos preservados")

    def all_effects(self):
        return [effect for values in (*self.effects.values(), *self.voices.values()) for _, effect in values]

    def check_status(self, effect, path):
        if effect.status() == QSoundEffect.Status.Error:
            log.warning("Efeito de áudio indisponível: %s", path.name)

    def configure(self, enabled: bool, settings: AudioSettings):
        self.enabled, self.settings = enabled, settings
        for effect in self.all_effects():
            effect.setVolume(settings.volume)
        if not enabled or settings.muted:
            self.stop()

    def set_context(self, suppressed: bool, sleeping: bool):
        self.suppressed, self.sleeping = suppressed, sleeping
        if suppressed or sleeping:
            self.stop()

    def play(self, category="notifications", cue=None) -> bool:
        options = [(name, effect) for name, effect in self.effects.get(category, [])
                   if cue is None or name.startswith(cue)]
        return self.play_options(category, options)

    def vocalize(self, emotion, category="reactions"):
        options = self.voices.get(emotion, [])
        return self.play_options(category, options) if options else self.play(category)

    def play_options(self, category, options):
        if (self.closed or not self.enabled or self.settings.muted or self.suppressed
                or self.sleeping and category != "sleep" or not self.settings.categories.get(category, False)):
            return False
        now = self.clock()
        if (now - self.last_play < self.settings.min_interval
                or now - self.history.get(category, -1000000) < (self.settings.idle_interval if category == "idle" else CATEGORY_INTERVALS.get(category, 3))):
            return False
        options = [(name, effect) for name, effect in options if effect.status() == QSoundEffect.Status.Ready]
        options = [(n, e) for n, e in options if n != self.previous.get(category)] or options
        try:
            if not options or not self.available():
                return False
            name, effect = self.rng.choice(options)
            self.stop()
            effect.play()
            self.last_play = now
            self.history[category] = now
            self.previous[category] = name
            return True
        except (OSError, RuntimeError):
            log.warning("Dispositivo de áudio indisponível")
            return False

    def stop(self):
        for effect in self.all_effects():
            effect.stop()

    def close(self):
        self.closed = True
        self.stop()
        if self.voice_directory is not None:
            try:
                self.voice_directory.cleanup()
            except OSError:
                log.warning("Cache de voz será limpo pelo Windows")
