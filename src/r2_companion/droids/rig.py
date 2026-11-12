"""Validated hierarchical PNG rigs shared by desktop and Garage rendering."""
from dataclasses import dataclass
import json
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImageReader, QPixmap, QTransform

from ..pet.animation import Clip, Frame
from ..pet.state import State
from .profiles import resource
from .expressions import STYLES, paint_expression


CHANNELS = {"wheel", "lean", "head", "bank", "lift", "left_step", "right_step",
            "left_knee", "right_knee", "left_foot", "right_foot"}
PROPERTIES = {"angle", "x", "y", "scale_y", "opacity", "light"}


def bounded(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError("Valor de articulação fora dos limites.")
    return float(value)


def point(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("Coordenada de articulação inválida.")
    return tuple(bounded(v, -256, 256) for v in value)


@dataclass(frozen=True)
class RigPart:
    name: str
    parent: int
    image: QPixmap
    position: tuple
    pivot: tuple
    z: float
    motion: tuple
    lamp: tuple | None


@dataclass(frozen=True)
class ArticulatedVisual:
    parts: tuple[RigPart, ...]
    pose: tuple[dict, ...]
    canvas: tuple[int, int]
    emitter: tuple
    expression_style: str = ""
    state: State | None = None
    phase: float = 0

    def transforms(self, motion=None):
        motion = motion or {}
        transforms = []
        for part, pose in zip(self.parts, self.pose):
            values = dict(pose)
            for prop, channel, factor in part.motion:
                values[prop] = values.get(prop, 0) + motion.get(channel, 0) * factor
            transform = QTransform(transforms[part.parent]) if part.parent >= 0 else QTransform()
            transform.translate(part.position[0] + values.get("x", 0), part.position[1] + values.get("y", 0))
            transform.rotate(values.get("angle", 0))
            transform.scale(1, values.get("scale_y", 1))
            transforms.append(transform)
        return transforms

    def anchor(self, motion=None):
        index, x, y = self.emitter
        p = self.transforms(motion)[index].map(QPointF(x, y))
        return p.x() / self.canvas[0], p.y() / self.canvas[1]

    def paint(self, painter, rect, illumination=None, motion=None):
        painter.save()
        painter.translate(rect.x(), rect.y())
        painter.scale(rect.width() / self.canvas[0], rect.height() / self.canvas[1])
        painter.setRenderHint(painter.RenderHint.SmoothPixmapTransform, False)
        transforms = self.transforms(motion)
        for index in sorted(range(len(self.parts)), key=lambda i: self.parts[i].z):
            part = self.parts[index]
            painter.save()
            painter.setTransform(transforms[index], True)
            painter.setOpacity(self.pose[index].get("opacity", 1))
            painter.drawPixmap(QPointF(-part.pivot[0], -part.pivot[1]), part.image)
            if part.lamp:
                x, y, width, height = part.lamp
                lamp_color = QColor(illumination or "#8fe9d2").darker(
                    round(100 + 250*(1-self.pose[index].get("light", 1))))
                painter.fillRect(QRectF(x, y, width, height), lamp_color)
            painter.restore()
        if self.expression_style:
            paint_expression(painter, self.state, self.phase, self.expression_style)
        painter.restore()


def load_rig_clips(profile):
    if profile.manifest.stat().st_size > 1024 * 1024:
        raise ValueError("Manifesto articulado muito grande.")
    data = json.loads(profile.manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("manifest_version") != 3 or data.get("canvas") != list(profile.canvas):
        raise ValueError("Canvas articulado incompatível com o perfil.")
    specs = data.get("parts")
    style = data.get("expression_style", "")
    if style and style not in STYLES:
        raise ValueError("Estilo de expressão desconhecido.")
    if not isinstance(specs, list) or not 2 <= len(specs) <= 32:
        raise ValueError("Quantidade de peças inválida.")
    parts, indices = [], {}
    root = profile.manifest.parent.parent
    for spec in specs:
        if not isinstance(spec, dict):
            raise ValueError("Peça articulada inválida.")
        name, parent = spec.get("name"), spec.get("parent")
        if not isinstance(name, str) or not name.isidentifier() or name in indices:
            raise ValueError("Nome de peça inválido ou duplicado.")
        if parent is not None and (not isinstance(parent, str) or parent not in indices):
            raise ValueError("Pai ausente ou ciclo no rig.")
        path = resource(root, str(profile.manifest.parent.relative_to(root) / spec["image"]), ".png")
        reader = QImageReader(str(path))
        if reader.size().width() != profile.canvas[0] or reader.size().height() != profile.canvas[1]:
            raise ValueError("Dimensão inválida da peça.")
        picture = reader.read()
        if picture.isNull():
            raise ValueError("Peça PNG não decodificável.")
        bindings = []
        if not isinstance(spec.get("motion", {}), dict):
            raise ValueError("Canais de movimento inválidos.")
        for prop, binding in spec.get("motion", {}).items():
            if prop not in {"angle", "x", "y"} or not isinstance(binding, list) or len(binding) != 2 or binding[0] not in CHANNELS:
                raise ValueError("Canal de movimento inválido.")
            bindings.append((prop, binding[0], bounded(binding[1], -4, 4)))
        lamp = spec.get("lamp")
        if lamp is not None:
            if not isinstance(lamp, list) or len(lamp) != 4:
                raise ValueError("Iluminação de peça inválida.")
            lamp = tuple(bounded(v, -256, 256) for v in lamp)
            if lamp[2] <= 0 or lamp[3] <= 0:
                raise ValueError("Dimensão de iluminação inválida.")
        parts.append(RigPart(name, indices[parent] if parent is not None else -1,
                             QPixmap.fromImage(picture), point(spec["position"]), point(spec["pivot"]),
                             bounded(spec.get("z", len(parts)), -32, 32), tuple(bindings), lamp))
        indices[name] = len(parts) - 1
    emitter = data.get("emitter", {})
    if not isinstance(emitter, dict) or not isinstance(emitter.get("part"), str) or emitter["part"] not in indices:
        raise ValueError("Sensor de projeção ausente.")
    emitter = (indices[emitter["part"]], *point(emitter.get("point")))
    canvas = QPixmap(*profile.canvas)
    canvas.fill(Qt.GlobalColor.transparent)
    clips, count = {}, 0
    if not isinstance(data.get("clips"), dict):
        raise ValueError("Catálogo articulado inválido.")
    for name, spec in data["clips"].items():
        state = State(name)
        if not isinstance(spec, dict) or not isinstance(spec.get("frames"), list):
            raise ValueError("Sequência articulada inválida.")
        if type(spec.get("loop")) is not bool or spec["loop"] and state not in {State.IDLE, State.SLEEP, State.WALK}:
            raise ValueError("Loop articulado inválido.")
        frames = []
        for item in spec["frames"]:
            count += 1
            if count > 256 or not isinstance(item, dict):
                raise ValueError("Quantidade ou formato de frames inválido.")
            duration = item["duration_ms"]
            if type(duration) is not int or not 50 <= duration <= 5000:
                raise ValueError("Duração de frame inválida.")
            pose = item.get("pose", {})
            if not isinstance(pose, dict) or set(pose) - indices.keys():
                raise ValueError("Pose referencia peça desconhecida.")
            values = []
            for part in parts:
                props = pose.get(part.name, {})
                if not isinstance(props, dict) or set(props) - PROPERTIES:
                    raise ValueError("Propriedade de pose inválida.")
                limits = {"angle": (-180, 180), "x": (-24, 24), "y": (-24, 24),
                          "scale_y": (0.05, 2), "opacity": (0, 1), "light": (0, 1)}
                values.append({key: bounded(value, *limits[key]) for key, value in props.items()})
            phase = (len(frames) + 0.5) / len(spec["frames"])
            frames.append(Frame(canvas, duration, ArticulatedVisual(tuple(parts), tuple(values), profile.canvas, emitter,
                                                                  style, state, phase)))
        if not frames:
            raise ValueError("Animação articulada vazia.")
        clips[state] = Clip(tuple(frames), spec["loop"])
    if State.IDLE not in clips:
        raise ValueError("IDLE ausente.")
    return clips
