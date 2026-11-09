import logging
from pathlib import Path
import random
import time

from PySide6.QtCore import QObject, QUrl
from PySide6.QtMultimedia import QMediaDevices, QSoundEffect

from ..core.config import AudioSettings

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

    def check_status(self, effect, path):
        if effect.status() == QSoundEffect.Status.Error:
            log.warning("Efeito de áudio indisponível: %s", path.name)

    def configure(self, enabled: bool, settings: AudioSettings):
        self.enabled, self.settings = enabled, settings
        for effects in self.effects.values():
            for _, effect in effects:
                effect.setVolume(settings.volume)
        if not enabled or settings.muted:
            self.stop()

    def set_context(self, suppressed: bool, sleeping: bool):
        self.suppressed, self.sleeping = suppressed, sleeping
        if suppressed or sleeping:
            self.stop()

    def play(self, category="notifications", cue=None) -> bool:
        if (self.closed or not self.enabled or self.settings.muted or self.suppressed
                or self.sleeping and category != "sleep" or not self.settings.categories.get(category, False)):
            return False
        now = self.clock()
        if (now - self.last_play < self.settings.min_interval
                or now - self.history.get(category, -1000000) < CATEGORY_INTERVALS.get(category, 3)):
            return False
        options = [(name, effect) for name, effect in self.effects.get(category, [])
                   if (cue is None or name.startswith(cue)) and effect.status() == QSoundEffect.Status.Ready]
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
        for effects in self.effects.values():
            for _, effect in effects:
                effect.stop()

    def close(self):
        self.closed = True
        self.stop()
