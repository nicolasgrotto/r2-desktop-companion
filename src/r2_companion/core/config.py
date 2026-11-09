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
    corner: str = ""


@dataclass
class BehaviorSettings:
    frequency: str = "normal"
    movement: bool = True
    sleep_seconds: int = 300
    cursor_attention: bool = True
    system_reactions: bool = True
    hourly_reaction: bool = False
    reaction_interval: int = 45
    weights: dict[str, int] = field(default_factory=lambda: {
        "IDLE": 60, "BLINK": 20, "LOOK_AROUND": 12, "CURIOUS": 6,
        "HAPPY": 2, "SURPRISED": 1, "WORK": 3})


@dataclass
class AudioSettings:
    volume: float = 0.35
    muted: bool = False
    min_interval: float = 2.0
    categories: dict[str, bool] = field(default_factory=lambda: {
        name: True for name in ("idle", "movement", "reactions", "sleep", "notifications")})


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
    audio: AudioSettings = field(default_factory=AudioSettings)
    fullscreen_mode: str = "auto"
    manual_position: WindowSettings | None = None

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
        for group in ("window", "behavior", "audio"):
            if not isinstance(data[group], dict):
                raise ValueError(f"Grupo {group} inválido.")
            data[group] = defaults[group] | data[group]
        w, b = data["window"], data["behavior"]
        if b["frequency"] not in ("off", "quiet", "normal"):
            raise ValueError("Frequência inválida.")
        def parse_window(value):
            if not isinstance(value, dict):
                raise ValueError("Posição inválida.")
            value = defaults["window"] | value
            if value["corner"] not in ("", "top_left", "top_right", "bottom_left", "bottom_right"):
                raise ValueError("Canto inválido.")
            return WindowSettings(text(value["screen"]), number(value["x"], -100000, 100000),
                                  number(value["y"], -100000, 100000), number(value["u"], 0, 1),
                                  number(value["v"], 0, 1), boolean(value["topmost"]), value["corner"])
        window = parse_window(w)
        weights = b["weights"]
        if not isinstance(weights, dict) or set(weights) - set(defaults["behavior"]["weights"]):
            raise ValueError("Probabilidades inválidas.")
        weights = {key: int(number(weights.get(key, value), 0, 100))
                   for key, value in defaults["behavior"]["weights"].items()}
        if not any(weights.values()):
            raise ValueError("Pelo menos um comportamento deve ter peso positivo.")
        behavior = BehaviorSettings(b["frequency"], boolean(b["movement"]),
                                    int(number(b["sleep_seconds"], 30, 7200)),
                                    boolean(b["cursor_attention"]), boolean(b["system_reactions"]),
                                    boolean(b["hourly_reaction"]), int(number(b["reaction_interval"], 10, 600)), weights)
        a = data["audio"]
        if not isinstance(a["categories"], dict) or set(a["categories"]) - set(defaults["audio"]["categories"]):
            raise ValueError("Categorias de áudio inválidas.")
        audio = AudioSettings(number(a["volume"], 0, 1), boolean(a["muted"]),
                              number(a["min_interval"], 0.1, 60),
                              {key: boolean(a["categories"].get(key, True)) for key in defaults["audio"]["categories"]})
        mode = data["fullscreen_mode"] if "fullscreen_mode" in raw else ("auto" if data["suppress_fullscreen"] else "quiet")
        if mode not in ("auto", "hide", "corner", "quiet"):
            raise ValueError("Modo de tela cheia inválido.")
        manual_position = None if data["manual_position"] is None else parse_window(data["manual_position"])
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
                   shortcuts=shortcuts, audio=audio, fullscreen_mode=mode, manual_position=manual_position, **collections)
