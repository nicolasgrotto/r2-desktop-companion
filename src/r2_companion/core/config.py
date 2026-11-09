from dataclasses import asdict, dataclass, field
import math
from typing import Any


class FutureSchemaError(ValueError):
    pass


def number(value: Any, low: float, high: float) -> float:
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError(f"Número fora do intervalo {low}–{high}.")
    return float(value)


def boolean(value: Any) -> bool:
    if type(value) is not bool:
        raise ValueError("Preferência booleana inválida.")
    return value


def text(value: Any, maximum: int = 512) -> str:
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise ValueError("Texto de configuração inválido.")
    return value


@dataclass
class Target:
    id: str
    label: str
    path: str
    kind: str


@dataclass
class Shortcut:
    id: str
    label: str
    target_id: str


@dataclass
class WindowSettings:
    screen: str = ""
    x: float = 0
    y: float = 0
    u: float = 0.85
    v: float = 0.9
    topmost: bool = True


@dataclass
class BehaviorSettings:
    frequency: str = "normal"
    movement: bool = True
    sleep_seconds: int = 300


@dataclass
class Settings:
    schema_version: int = 1
    window: WindowSettings = field(default_factory=WindowSettings)
    behavior: BehaviorSettings = field(default_factory=BehaviorSettings)
    visual_scale: int = 160
    sound_enabled: bool = False
    bubbles: bool = True
    suppress_fullscreen: bool = True
    timer_seconds: int = 300
    startup: bool = False
    applications: list[Target] = field(default_factory=list)
    locations: list[Target] = field(default_factory=list)
    shortcuts: list[Shortcut] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def parse(cls, raw: dict) -> "Settings":
        if not isinstance(raw, dict):
            raise ValueError("Configuração deve ser um objeto JSON.")
        version = raw.get("schema_version", 1)
        if type(version) is not int or version < 1:
            raise ValueError("Versão inválida.")
        if version > 1:
            raise FutureSchemaError("Configuração de uma versão mais recente; arquivo preservado.")
        defaults = cls().to_dict()
        data = defaults | raw
        for group in ("window", "behavior"):
            if not isinstance(data[group], dict):
                raise ValueError(f"Grupo {group} inválido.")
            data[group] = defaults[group] | data[group]
        w, b = data["window"], data["behavior"]
        if b["frequency"] not in ("off", "quiet", "normal"):
            raise ValueError("Frequência inválida.")
        window = WindowSettings(text(w["screen"]), number(w["x"], -100000, 100000),
                                number(w["y"], -100000, 100000), number(w["u"], 0, 1),
                                number(w["v"], 0, 1), boolean(w["topmost"]))
        behavior = BehaviorSettings(b["frequency"], boolean(b["movement"]),
                                    int(number(b["sleep_seconds"], 30, 7200)))
        collections = {}
        used_ids: set[str] = set()
        for key, kinds in (("applications", {"app"}), ("locations", {"folder", "file"})):
            entries = data[key]
            if not isinstance(entries, list) or len(entries) > 100:
                raise ValueError("Lista de atalhos inválida ou muito extensa.")
            targets = []
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("Atalho inválido.")
                target = Target(text(entry.get("id"), 80), text(entry.get("label"), 80),
                                text(entry.get("path")), text(entry.get("kind"), 10))
                if not target.id or not target.label.strip() or target.id in used_ids or target.kind not in kinds:
                    raise ValueError("Identificador, nome ou tipo do atalho inválido.")
                used_ids.add(target.id)
                targets.append(target)
            collections[key] = targets
        aliases = data["shortcuts"]
        if not isinstance(aliases, list) or len(aliases) > 100:
            raise ValueError("Lista de aliases inválida.")
        shortcuts = []
        target_ids = used_ids.copy()
        for alias in aliases:
            if not isinstance(alias, dict):
                raise ValueError("Alias inválido.")
            item = Shortcut(text(alias.get("id"), 80), text(alias.get("label"), 80),
                            text(alias.get("target_id"), 80))
            if not item.id or not item.label.strip() or item.id in used_ids or item.target_id not in target_ids:
                raise ValueError("Alias não referencia um destino válido.")
            used_ids.add(item.id)
            shortcuts.append(item)
        return cls(window=window, behavior=behavior, visual_scale=int(number(data["visual_scale"], 64, 256)),
                   sound_enabled=boolean(data["sound_enabled"]), bubbles=boolean(data["bubbles"]),
                   suppress_fullscreen=boolean(data["suppress_fullscreen"]),
                   timer_seconds=int(number(data["timer_seconds"], 1, 86400)), startup=boolean(data["startup"]),
                   shortcuts=shortcuts, **collections)
