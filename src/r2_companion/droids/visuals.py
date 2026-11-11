from dataclasses import dataclass
import json

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QImageReader, QPixmap

from ..core.config import number
from ..pet.animation import Clip, Frame, load_clips
from ..pet.state import State
from .profiles import resource


@dataclass(frozen=True)
class DroidVisual:
    body: QPixmap
    head: QPixmap
    head_x: float = 0
    head_y: float = 0
    head_tilt: float = 0
    body_angle: float = 0
    lift: float = 0


def paint_visual(painter, rect, visual, angle=0, tilt=0, offset=0, illumination=None, decoration=False):
    painter.save()
    painter.translate(rect.x(), rect.y())
    painter.scale(rect.width() / 64, rect.height() / 64)
    painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform, False)
    painter.save()
    painter.translate(32, 39 + visual.lift)
    painter.rotate(angle + visual.body_angle)
    painter.drawPixmap(QPointF(-20, -20), visual.body)
    painter.restore()
    painter.save()
    painter.translate(32 + visual.head_x + offset, 19 + visual.head_y + visual.lift)
    painter.rotate(visual.head_tilt + tilt)
    painter.drawPixmap(QPointF(-15, -16), visual.head)
    painter.fillRect(QRectF(7, -7, 2, 2), QColor(illumination or "#ffc46b"))
    painter.restore()
    if decoration:
        painter.fillRect(QRectF(47, 5, 2, 5), QColor(illumination or "#ffc46b"))
        painter.fillRect(QRectF(45, 7, 6, 1), QColor(illumination or "#ffc46b"))
    painter.restore()


def load_profile_clips(profile):
    if profile.renderer == "atlas":
        return load_clips(profile.manifest, fill_missing=False, resource_root=profile.manifest.parent.parent)
    data = json.loads(profile.manifest.read_text(encoding="utf-8"))
    root = profile.manifest.parent
    images = []
    for key, expected in (("body", QSize(40, 40)), ("head", QSize(30, 18))):
        path = resource(root.parent, str(root.relative_to(root.parent) / data[key]), ".png")
        reader = QImageReader(str(path))
        if reader.size() != expected:
            raise ValueError(f"Dimensão inválida do componente {key}.")
        picture = reader.read()
        if picture.isNull():
            raise ValueError("Componente não decodificável.")
        images.append(QPixmap.fromImage(picture))
    canvas = QPixmap(64, 64)
    canvas.fill(Qt.GlobalColor.transparent)
    clips = {}
    count = 0
    for name, spec in data["clips"].items():
        state = State(name)
        if type(spec.get("loop")) is not bool or spec["loop"] and state not in {State.IDLE, State.SLEEP, State.WALK}:
            raise ValueError("Loop de componente inválido.")
        frames = []
        for item in spec["frames"]:
            count += 1
            if count > 256:
                raise ValueError("Muitos frames de componentes.")
            visual = DroidVisual(*images, number(item.get("head_x", 0), -6, 6),
                                 number(item.get("head_y", 0), -4, 4), number(item.get("head_tilt", 0), -25, 25),
                                 number(item.get("body_angle", 0), -360, 360), number(item.get("lift", 0), -3, 3))
            frames.append(Frame(canvas, int(number(item["duration_ms"], 50, 5000)), visual))
        if not frames:
            raise ValueError("Animação vazia.")
        clips[state] = Clip(tuple(frames), spec["loop"])
    if State.IDLE not in clips:
        raise ValueError("IDLE ausente.")
    return clips
