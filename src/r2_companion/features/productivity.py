from copy import deepcopy
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.config import FutureSchemaError
from ..services.storage import ConfigStore

log = logging.getLogger(__name__)
MAX_BYTES = 8 * 1024 * 1024
COLLECTION_LIMITS = {"tasks": (500, "tarefas"), "notes": (100, "notas")}


@dataclass(frozen=True)
class DeletedEntry:
    collection: str
    position: int
    record: dict


def validate_document(raw):
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int:
        raise ValueError("Documento inválido.")
    if raw["schema_version"] > 1:
        raise FutureSchemaError("Tarefas e notas de uma versão futura; arquivo preservado.")
    if raw["schema_version"] != 1:
        raise ValueError("Versão inválida.")
    ids = set()
    result = {"schema_version": 1, "tasks": [], "notes": []}
    for key, (maximum, name) in COLLECTION_LIMITS.items():
        entries = raw.get(key)
        if not isinstance(entries, list):
            raise ValueError("Lista inválida.")
        if len(entries) > maximum:
            raise ValueError(f"Limite de {maximum} {name} atingido.")
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("Registro inválido.")
            entry_id = item.get("id")
            if not isinstance(entry_id, str) or not entry_id or len(entry_id) > 80:
                raise ValueError("Identificador inválido.")
            if entry_id in ids:
                raise ValueError("Já existe um registro com o mesmo identificador.")
            ids.add(entry_id)
            fields = {"text": 240} if key == "tasks" else {"title": 120, "body": 50000}
            record = {"id": entry_id}
            for field, limit in fields.items():
                value = item.get(field)
                if not isinstance(value, str) or len(value) > limit or "\x00" in value:
                    raise ValueError("Texto inválido ou extenso demais.")
                if field != "body" and (not value.strip() or any(ord(c) < 32 for c in value)):
                    raise ValueError("Título inválido.")
                record[field] = value
            if key == "tasks":
                if type(item.get("done")) is not bool:
                    raise ValueError("Estado da tarefa inválido.")
                record["done"] = item["done"]
            result[key].append(record)
    return result


class ProductivityStore(QObject):
    warning = Signal(str)
    task_completed = Signal(str)
    tasks_changed = Signal()
    saved = Signal()
    undo_changed = Signal()
    entry_restored = Signal(str, str)
    restored = Signal()

    def __init__(self, directory: Path, read_only=False):
        super().__init__()
        self.path = directory / "tools.json"
        self.backup = directory / "tools.backup.json"
        self.data = {"schema_version": 1, "tasks": [], "notes": []}
        self._deleted_entry = None
        self.read_only = read_only
        self.dirty = False
        self.notices = []
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(750)
        self.timer.timeout.connect(self.flush)
        self.load()

    @staticmethod
    def read(path):
        if path.stat().st_size > MAX_BYTES:
            raise ValueError("Dados excedem 8 MiB.")
        return validate_document(json.loads(path.read_text(encoding="utf-8")))

    def load(self):
        for path in (self.path, self.backup):
            try:
                self.data = self.read(path)
                if path == self.backup:
                    self.notices.append("Tarefas e notas recuperadas do backup.")
                return
            except FileNotFoundError:
                continue
            except FutureSchemaError as error:
                self.read_only = True
                self.notices.append(str(error))
                return
            except (OSError, ValueError, TypeError):
                self.notices.append("Dados de ferramentas inválidos; usando backup ou lista vazia.")
                if path == self.path and not self.read_only:
                    try:
                        ConfigStore.atomic_write(path.with_name("tools.corrupt.json"), path.read_bytes()[:MAX_BYTES])
                    except OSError:
                        pass

    def change(self, data):
        checked = validate_document(data)
        if len(json.dumps(checked, ensure_ascii=False, indent=2).encode("utf-8")) > MAX_BYTES:
            raise ValueError("Tarefas e notas atingiram o limite total de 8 MiB.")
        if checked != self.data:
            tasks_changed = checked["tasks"] != self.data["tasks"]
            self.data = checked
            self.dirty = True
            self.timer.start()
            if tasks_changed:
                self.tasks_changed.emit()

    def task(self, entry_id):
        return next((item for item in self.data["tasks"] if item["id"] == entry_id), None)

    def add_task(self, text):
        entry = {"id": uuid4().hex, "text": text.strip(), "done": False}
        self.change(self.data | {"tasks": self.data["tasks"] + [entry]})
        return entry["id"]

    def set_done(self, entry_id, done):
        data = deepcopy(self.data)
        entry = next(item for item in data["tasks"] if item["id"] == entry_id)
        completed = done and not entry["done"]
        entry["done"] = done
        self.change(data)
        if completed:
            self.task_completed.emit(entry_id)

    def remove(self, key, entry_id):
        if key not in COLLECTION_LIMITS:
            raise ValueError("Coleção inválida.")
        entries = self.data[key]
        for position, entry in enumerate(entries):
            if entry["id"] == entry_id:
                self.change(self.data | {key: entries[:position] + entries[position + 1:]})
                self._deleted_entry = DeletedEntry(key, position, entry.copy())
                self.undo_changed.emit()
                return True
        return False

    @property
    def undo_collection(self):
        return self._deleted_entry.collection if self._deleted_entry is not None else None

    def undo_remove(self):
        deleted = self._deleted_entry
        if deleted is None:
            return None
        entries = self.data[deleted.collection].copy()
        entries.insert(deleted.position, deleted.record)
        self.change(self.data | {deleted.collection: entries})
        self._deleted_entry = None
        self.entry_restored.emit(deleted.collection, deleted.record["id"])
        self.undo_changed.emit()
        return deleted.collection

    def add_note(self):
        entry = {"id": uuid4().hex, "title": "Nova anotação", "body": ""}
        self.change(self.data | {"notes": self.data["notes"] + [entry]})
        return entry["id"]

    def edit_note(self, entry_id, title, body):
        data = deepcopy(self.data)
        entry = next(item for item in data["notes"] if item["id"] == entry_id)
        entry.update(title=title.strip() or "Sem título", body=body)
        self.change(data)

    def flush(self):
        self.timer.stop()
        if not self.dirty:
            return True
        if self.read_only:
            self.warning.emit("Tarefas e notas somente nesta sessão; arquivo original preservado.")
            return False
        try:
            if self.path.exists():
                try:
                    previous = self.read(self.path)
                except (OSError, ValueError, TypeError):
                    previous = None
                if previous is not None:
                    ConfigStore.atomic_write(self.backup, json.dumps(previous, ensure_ascii=False).encode("utf-8"))
            ConfigStore.atomic_write(self.path, json.dumps(self.data, ensure_ascii=False, indent=2).encode("utf-8"))
            self.dirty = False
            self.saved.emit()
            return True
        except OSError:
            log.exception("Falha ao gravar ferramentas")
            self.warning.emit("Não foi possível salvar tarefas e notas; dados anteriores preservados.")
            return False

    def close(self):
        self.discard_undo()
        self.flush()

    def discard_undo(self):
        if self._deleted_entry is not None:
            self._deleted_entry = None
            self.undo_changed.emit()

    def accept_restored(self, data):
        self.data = data
        self.timer.stop()
        self.dirty = False
        self.discard_undo()
        self.tasks_changed.emit()
        self.restored.emit()
