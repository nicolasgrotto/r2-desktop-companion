from collections.abc import Callable
from dataclasses import dataclass
import json
import logging
from pathlib import Path
import time

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImageReader, QPixmap

from .state import State

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Frame:
    pixmap: QPixmap
    milliseconds: int
    visual: object = None


@dataclass(frozen=True)
class Clip:
    frames: tuple[Frame, ...]
    loop: bool

    @property
    def duration(self) -> int:
        return sum(frame.milliseconds for frame in self.frames)


def load_clips(manifest: Path, fill_missing=True, resource_root=None) -> dict[State, Clip]:
    if manifest.stat().st_size > 1024 * 1024:
        raise ValueError("Manifesto muito grande.")
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("manifest_version") != 1 or not isinstance(data.get("clips"), dict):
        raise ValueError("Manifesto de animação inválido.")
    root = (resource_root or manifest.parent).resolve()
    images = {}
    clips = {}
    byte_count = 0
    frame_count = 0
    for state_name, spec in data["clips"].items():
        state = State(state_name)
        frames = []
        if not isinstance(spec, dict) or type(spec.get("loop")) is not bool or not isinstance(spec.get("frames"), list):
            raise ValueError("Sequência inválida.")
        if spec["loop"] and state not in {State.IDLE, State.WALK, State.SLEEP}:
            raise ValueError("Reações precisam terminar; loop permitido apenas em IDLE, WALK e SLEEP.")
        for item in spec["frames"]:
            frame_count += 1
            if frame_count > 256 or not isinstance(item, dict):
                raise ValueError("Quantidade ou formato de frames inválido.")
            if not isinstance(item.get("image"), str) or not item["image"]:
                raise ValueError("Referência de imagem inválida.")
            relative = Path(item["image"])
            path = (manifest.parent / relative).resolve()
            if relative.is_absolute() or not path.is_relative_to(root) or path.suffix.lower() != ".png":
                raise ValueError("Imagem deve ser PNG dentro do diretório do personagem.")
            if path not in images:
                reader = QImageReader(str(path))
                size = reader.size()
                if not size.isValid() or max(size.width(), size.height()) > 2048:
                    raise ValueError("Dimensões da imagem inválidas.")
                image = reader.read()
                if image.isNull():
                    raise ValueError("PNG não pôde ser decodificado.")
                byte_count += image.sizeInBytes()
                images[path] = image
            image = images[path]
            rect = item.get("rect", [0, 0, image.width(), image.height()])
            if (not isinstance(rect, list) or len(rect) != 4 or any(type(n) is not int for n in rect)):
                raise ValueError("Retângulo de atlas inválido.")
            x, y, width, height = rect
            if min(x, y) < 0 or min(width, height) <= 0 or x + width > image.width() or y + height > image.height():
                raise ValueError("Frame fora do atlas.")
            milliseconds = item["duration_ms"]
            if type(milliseconds) is not int or not 50 <= milliseconds <= 5000:
                raise ValueError("Duração de frame deve estar entre 50 e 5000 ms.")
            byte_count += width * height * 4
            if byte_count > 32 * 1024 * 1024:
                raise ValueError("Animação excede o orçamento de 32 MiB.")
            frames.append(Frame(QPixmap.fromImage(image.copy(x, y, width, height)), milliseconds))
        if not frames:
            raise ValueError("Sequência sem frames.")
        clips[state] = Clip(tuple(frames), spec["loop"])
    if State.IDLE not in clips:
        raise ValueError("O personagem precisa de IDLE.")
    canvas = clips[State.IDLE].frames[0].pixmap.size()
    if any(frame.pixmap.size() != canvas for clip in clips.values() for frame in clip.frames):
        raise ValueError("Todos os frames devem usar o mesmo canvas e âncora.")
    for state in State if fill_missing else ():
        if state not in clips:
            log.warning("Estado %s usa placeholder IDLE", state.value)
            idle = clips[State.IDLE].frames[0]
            clips[state] = Clip((Frame(idle.pixmap, 800),), state in {State.SLEEP, State.WALK})
    return clips


class AnimationManager(QObject):
    frame_changed = Signal(object)
    clip_finished = Signal(int)

    def __init__(self, clips: dict[State, Clip], clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self.clips = clips
        self.clock = clock
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.tick)
        self.clip: Clip | None = None
        self.token = 0
        self.started = 0.0
        self.last_frame = -1

    def play(self, state: State, token: int) -> None:
        self.stop()
        self.token = token
        self.clip = self.clips[state]
        self.started = self.clock()
        self.last_frame = -1
        self.tick()

    def tick(self) -> None:
        clip = self.clip
        token = self.token
        if clip is None:
            return
        elapsed = max(0, int((self.clock() - self.started) * 1000))
        if not clip.loop and elapsed >= clip.duration:
            self.stop()
            self.clip_finished.emit(token)
            return
        elapsed %= clip.duration
        boundary = 0
        for index, frame in enumerate(clip.frames):
            boundary += frame.milliseconds
            if elapsed < boundary:
                if index != self.last_frame:
                    self.last_frame = index
                    self.frame_changed.emit(frame.visual if frame.visual is not None else frame.pixmap)
                if self.clip is clip and self.token == token and not (clip.loop and len(clip.frames) == 1):
                    self.timer.start(max(1, boundary - elapsed))
                return

    def stop(self) -> None:
        self.timer.stop()
        self.clip = None
