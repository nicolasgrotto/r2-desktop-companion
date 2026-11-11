from dataclasses import dataclass
import json
from pathlib import Path
import re

from ..core.config import number, text
from ..pet.personality import PROFILES
from ..pet.state import State
from ..services.vocalizations import PHRASES


def resource(root, value, suffix=None):
    relative = Path(text(value))
    path = (root / relative).resolve()
    if relative.is_absolute() or not path.is_relative_to(root.resolve()) or not path.is_file():
        raise ValueError(f"Recurso ausente ou fora de assets: {value}")
    if suffix and path.suffix.lower() != suffix:
        raise ValueError(f"Formato de recurso inválido: {value}")
    return path


def contrast(first, second):
    def luminance(color):
        values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        values = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
        return sum(v * w for v, w in zip(values, (0.2126, 0.7152, 0.0722)))
    a, b = sorted((luminance(first), luminance(second)))
    return (b + 0.05) / (a + 0.05)


@dataclass(frozen=True)
class DroidTheme:
    name: str
    colors: dict[str, str]
    radius: int

    @classmethod
    def parse(cls, data):
        keys = {"primary", "secondary", "accent", "background", "panel", "border", "text", "muted",
                "hero", "hero_text", "hero_muted", "selected", "focus", "button_text", "error", "disabled",
                "notification", "hologram", "decoration"}
        if not isinstance(data, dict) or not isinstance(data.get("colors"), dict) or set(data["colors"]) != keys:
            raise ValueError("Tokens de tema incompletos.")
        colors = dict(data["colors"])
        if any(not isinstance(c, str) or not re.fullmatch(r"#[0-9a-fA-F]{6}", c) for c in colors.values()):
            raise ValueError("Cor de tema inválida.")
        for fg, bg in (("text", "background"), ("text", "panel"), ("muted", "panel"),
                       ("hero_text", "hero"), ("hero_muted", "hero"), ("button_text", "primary"),
                       ("text", "selected"), ("hero_text", "notification")):
            if contrast(colors[fg], colors[bg]) < 4.5:
                raise ValueError(f"Contraste insuficiente: {fg}/{bg}.")
        return cls(text(data.get("name"), 80), colors, int(number(data.get("radius", 12), 4, 24)))


@dataclass(frozen=True)
class DroidAudioProfile:
    id: str
    voice: Path
    sounds: Path
    phrases: dict


@dataclass(frozen=True)
class DroidProfile:
    id: str
    name: str
    description: str
    manifest: Path
    renderer: str
    animations: dict[State, str]
    audio: DroidAudioProfile
    personality: str
    movement: str
    canvas: tuple[int, int]
    speed: float
    theme: DroidTheme
    customization: dict
    art_status: str

    @classmethod
    def load(cls, path, assets):
        if path.stat().st_size > 131072:
            raise ValueError("Perfil excede 128 KiB.")
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("profile_version") != 1:
            raise ValueError("Versão de perfil inválida.")
        identifier = data.get("id", "")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,63}", identifier):
            raise ValueError("ID de droide inválido.")
        manifest = resource(assets, data["manifest"], ".json")
        animation_data = json.loads(manifest.read_text(encoding="utf-8"))
        renderer = data["renderer"]
        if renderer not in ("atlas", "layered"):
            raise ValueError("Renderizador desconhecido.")
        if animation_data.get("manifest_version") != (1 if renderer == "atlas" else 2):
            raise ValueError("Manifesto incompatível com renderizador.")
        animations = {State(k): text(v, 80) for k, v in data["animations"].items()}
        if State.IDLE not in animations or set(animations) != {State(k) for k in animation_data["clips"]}:
            raise ValueError("O catálogo precisa corresponder às animações registradas.")
        for spec in animation_data["clips"].values():
            for frame in spec["frames"]:
                if renderer == "atlas":
                    resource(assets, str(manifest.parent.relative_to(assets) / frame["image"]), ".png")
        if renderer == "layered":
            for component in ("body", "head"):
                resource(assets, str(manifest.parent.relative_to(assets) / animation_data[component]), ".png")
        if data["personality"] not in PROFILES.keys() | {"custom"}:
            raise ValueError("Personalidade desconhecida.")
        from .movement import MOVEMENT_CONTROLLERS
        if data["movement"] not in MOVEMENT_CONTROLLERS:
            raise ValueError("Controlador de locomoção não registrado.")
        canvas = data["canvas"]
        if not isinstance(canvas, list) or len(canvas) != 2:
            raise ValueError("Canvas inválido.")
        canvas = tuple(int(number(n, 32, 256)) for n in canvas)
        audio = data["audio"]
        voice = resource(assets, audio["voice"] + "/soft.wav", ".wav").parent
        sounds = resource(assets, audio["sounds"] + "/notifications/timer.wav", ".wav").parent.parent
        phrases = audio.get("phrases", PHRASES)
        if not isinstance(phrases, dict) or set(phrases) != set(PHRASES):
            raise ValueError("Mapeamento vocal incompleto.")
        for variants in phrases.values():
            if not isinstance(variants, (list, tuple)) or not 1 <= len(variants) <= 5:
                raise ValueError("Variantes vocais inválidas.")
            for phrase in variants:
                if not isinstance(phrase, (list, tuple)) or not 1 <= len(phrase) <= 6:
                    raise ValueError("Frase vocal inválida.")
                for syllable in phrase:
                    resource(voice, syllable + ".wav", ".wav")
        customization = data.get("customization", {})
        if not isinstance(customization, dict) or len(customization) > 8:
            raise ValueError("Personalizações inválidas.")
        for key, spec in customization.items():
            if key not in {"appearance", "illumination", "decoration"} or not isinstance(spec, dict):
                raise ValueError("Personalização não suportada pelo renderizador.")
            options = spec.get("options", {})
            if not isinstance(options, dict) or not options or spec.get("default") not in options:
                raise ValueError("Opções de personalização inválidas.")
            for value in options.values():
                if not isinstance(value, dict) or not isinstance(value.get("label"), str):
                    raise ValueError("Opção sem apresentação.")
                if key == "illumination" and not re.fullmatch(r"#[0-9a-fA-F]{6}", value.get("color", "")):
                    raise ValueError("Iluminação inválida.")
        return cls(identifier, text(data["name"], 80), text(data["description"], 1000), manifest,
                   renderer, animations, DroidAudioProfile(identifier, voice, sounds, phrases), data["personality"],
                   text(data["movement"], 64), canvas, number(data.get("speed", 1), 0.3, 2),
                   DroidTheme.parse(data["theme"]), customization, text(data["art_status"], 200))

    def customizations(self, values):
        return {key: values.get(key) if values.get(key) in spec["options"] else spec["default"]
                for key, spec in self.customization.items()}


class DroidRegistry:
    def __init__(self, assets):
        self.assets = assets.resolve()
        self.profiles = {}
        self.errors = {}
        self.sources = {}
        self.active_id = "r2_default"
        for path in sorted((self.assets / "droids").glob("*/profile.json")):
            try:
                profile = DroidProfile.load(path, self.assets)
                if profile.id in self.profiles:
                    raise ValueError("ID duplicado.")
                self.profiles[profile.id] = profile
                self.sources[profile.id] = path
            except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
                self.errors[path.parent.name] = str(error)
        if "r2_default" not in self.profiles:
            raise ValueError("O perfil padrão não está disponível.")

    def get(self, identifier):
        if identifier not in self.profiles:
            raise ValueError("Droide indisponível.")
        return self.profiles[identifier]

    @property
    def active(self):
        return self.get(self.active_id)
