"""Versioned preferences/checkpoints independent of the legacy settings files.

Use update() for partial group edits or apply() with a complete data snapshot.
The ConfigStore owner must hold its existing lock for persistent writes.
"""
from copy import deepcopy
import json
import logging
import math
from pathlib import Path
import re

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.config import FutureSchemaError
from .storage import ConfigStore

log = logging.getLogger(__name__)
MAX_BYTES = 1024 * 1024
PROFILE_ID = re.compile(r"[a-z][a-z0-9_]{0,63}")


def default_document():
    return {
        "schema_version": 1,
        "presence": {"mode": "free"},
        "accessibility": {"reduced_motion": False, "ui_scale": 100},
        "appearance": {"theme_overrides": {}},
        "media": {"enabled": False},
        "focus": {"session": None},
        "onboarding": {"dismissed": False},
        "actions": {"global_shortcut_enabled": False},
    }


def _json_value(value):
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Chave de documento inválida.")
        for child in value.values():
            _json_value(child)
    elif isinstance(value, list):
        for child in value:
            _json_value(child)
    elif value is None or type(value) in (str, bool, int):
        return
    elif type(value) is not float or not math.isfinite(value):
        raise ValueError("Valor de documento inválido.")


def _reference(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 80
            or any(ord(character) < 32 for character in value)):
        raise ValueError("Referência de sessão inválida.")


def _number(value, minimum, maximum):
    if type(value) not in (int, float) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError("Duração de sessão inválida.")


def _encode(data):
    contents = json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    if len(contents) > MAX_BYTES:
        raise ValueError("Estado complementar excede 1 MiB.")
    return contents


def validate_document(raw):
    """Validate known fields, fill defaults and retain unknown JSON fields."""
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int:
        raise ValueError("Documento complementar inválido.")
    if raw["schema_version"] > 1:
        raise FutureSchemaError("Estado complementar de uma versão futura; arquivo preservado.")
    if raw["schema_version"] != 1:
        raise ValueError("Versão do estado complementar inválida.")
    try:
        _json_value(raw)
        result = deepcopy(raw)
        for group, defaults in default_document().items():
            if group == "schema_version":
                continue
            values = result.setdefault(group, {})
            if not isinstance(values, dict):
                raise ValueError("Grupo do estado complementar inválido.")
            for key, value in defaults.items():
                values.setdefault(key, deepcopy(value))
        if result["presence"]["mode"] not in ("free", "focus", "presentation"):
            raise ValueError("Modo de presença inválido.")
        scale = result["accessibility"]["ui_scale"]
        if type(scale) is not int or scale not in (100, 125, 150):
            raise ValueError("Escala da interface inválida.")
        for group, field in (("accessibility", "reduced_motion"), ("media", "enabled"),
                             ("onboarding", "dismissed"), ("actions", "global_shortcut_enabled")):
            if type(result[group][field]) is not bool:
                raise ValueError("Preferência booleana inválida.")
        overrides = result["appearance"]["theme_overrides"]
        if not isinstance(overrides, dict) or len(overrides) > 100:
            raise ValueError("Preferências de tema inválidas.")
        for identifier, theme in overrides.items():
            if (not isinstance(identifier, str) or not PROFILE_ID.fullmatch(identifier)
                    or not isinstance(theme, str) or not PROFILE_ID.fullmatch(theme)):
                raise ValueError("Referência de tema inválida.")
        session = result["focus"]["session"]
        if session is not None:
            if not isinstance(session, dict):
                raise ValueError("Sessão de foco inválida.")
            _reference(session.get("id"))
            if session.get("phase") not in ("focus", "break"):
                raise ValueError("Fase de foco inválida.")
            duration = session.get("duration_seconds")
            _number(duration, 1, 86400)
            _number(session.get("remaining_seconds"), 0, duration)
            if session.setdefault("task_id", None) is not None:
                _reference(session["task_id"])
        _encode(result)
        return result
    except (TypeError, RecursionError, OverflowError) as error:
        raise ValueError("Documento complementar inválido.") from error


class OversizedStateError(ValueError):
    """A bounded read cannot establish whether an oversized file is future data."""


class CompanionStateStore(QObject):
    changed = Signal(object)
    saved = Signal()
    warning = Signal(str)

    def __init__(self, config_store: ConfigStore):
        super().__init__()
        self.config_store = config_store
        self.path = config_store.directory / "companion_state.json"
        self.backup = config_store.directory / "companion_state.backup.json"
        self._data = default_document()
        self._protected = False
        self._closed = False
        self.dirty = False
        self.notices = []
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(750)
        self.timer.timeout.connect(self.flush)
        self._load()

    @property
    def data(self):
        return deepcopy(self._data)

    def theme_override_for(self, droid_id):
        return self._data["appearance"]["theme_overrides"].get(droid_id)

    @property
    def read_only(self):
        owner = self.config_store
        return (self._protected or owner.read_only or owner.lock is None or not owner.lock.isLocked())

    @staticmethod
    def _read(path: Path):
        with path.open("rb") as handle:
            contents = handle.read(MAX_BYTES + 1)
        if len(contents) > MAX_BYTES:
            raise OversizedStateError("Estado complementar excede o limite de leitura.")
        return validate_document(json.loads(contents.decode("utf-8"))), contents

    @classmethod
    def read_document_file(cls, path: Path) -> dict:
        """Read one validated state file without acquiring the writer's lock."""
        return cls._read(path)[0]

    def _load(self):
        for path in (self.path, self.backup):
            try:
                self._data, _ = self._read(path)
                if path == self.backup:
                    self.notices.append("Estado complementar recuperado do backup.")
                    self.dirty = True
                break
            except FileNotFoundError:
                continue
            except FutureSchemaError:
                self._protected = True
                self.notices.append("Estado complementar de versão futura; usando padrões nesta sessão, sem sobrescrever o arquivo.")
                return
            except (OversizedStateError, OSError):
                # Do not overwrite data whose schema could not be safely read.
                self._protected = True
                self.notices.append("Estado complementar inacessível ou extenso demais; arquivo preservado em somente leitura.")
            except (ValueError, RecursionError):
                self.notices.append("Estado complementar inválido; tentando backup ou valores padrão.")
        else:
            self.dirty = True  # Persist defaults on first writable startup.
        if self.dirty and not self.read_only:
            self.timer.start()

    def apply(self, data, *, immediate=False):
        if self._closed:
            raise RuntimeError("Armazenamento complementar encerrado.")
        checked = validate_document(data)
        if checked != self._data:
            self._data = checked
            self.dirty = True
            self.timer.start()
            self.changed.emit(self.data)
        return self.flush() if immediate else True

    def update(self, group, values, *, immediate=False):
        if group not in default_document() or group == "schema_version" or not isinstance(values, dict):
            raise ValueError("Grupo de preferências inválido.")
        data = self.data
        data[group].update(deepcopy(values))
        return self.apply(data, immediate=immediate)

    def save_theme_override(self, droid_id, provider_id):
        candidate = self.data
        overrides = candidate["appearance"]["theme_overrides"]
        if provider_id is None:
            overrides.pop(droid_id, None)
        else:
            overrides[droid_id] = provider_id
        if candidate == self._data:
            return True
        candidate = validate_document(candidate)
        if not self._write(candidate):
            return False
        self._data = candidate
        self.timer.stop()
        self.dirty = False
        self.changed.emit(self.data)
        self.saved.emit()
        return True

    def flush(self):
        self.timer.stop()
        if not self.dirty:
            return True
        if not self._write(self._data):
            return False
        self.dirty = False
        self.saved.emit()
        return True

    def _write(self, data):
        if self._closed or self.read_only:
            self.warning.emit("Estado complementar somente nesta sessão; arquivos originais preservados.")
            return False
        try:
            previous = None
            # Recheck both files before touching either: a future backup must
            # not be overwritten just because the primary schema is current.
            for path in (self.path, self.backup):
                try:
                    _, contents = self._read(path)
                    if path == self.path:
                        previous = contents
                except FileNotFoundError:
                    continue
                except (FutureSchemaError, OversizedStateError):
                    self._protected = True
                    self.warning.emit("Estado complementar incompatível; arquivos preservados em somente leitura.")
                    return False
                except (ValueError, RecursionError):
                    continue  # Keep a valid recovery backup instead of rotating corrupt data.
            contents = _encode(data)
            if previous is not None:
                ConfigStore.atomic_write(self.backup, previous)
            ConfigStore.atomic_write(self.path, contents)
            return True
        except (OSError, ValueError) as error:
            log.warning("Falha ao salvar estado complementar (%s)", type(error).__name__)
            self.warning.emit("Não foi possível salvar o estado complementar; dados anteriores preservados.")
            return False

    def close(self):
        result = self.flush()
        self._closed = True
        return result
