from copy import deepcopy
import json
import logging
from pathlib import Path
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.config import FutureSchemaError
from ..services.storage import ConfigStore

log = logging.getLogger(__name__)


def validate_document(raw):
    if not isinstance(raw, dict) or type(raw.get("schema_version")) is not int:
        raise ValueError("Documento inválido.")
    if raw["schema_version"] > 1:
        raise FutureSchemaError("Tarefas e notas de uma versão futura; arquivo preservado.")
    if raw["schema_version"] != 1:
        raise ValueError("Versão inválida.")
    ids = set()
    result = {"schema_version": 1, "tasks": [], "notes": []}
    for key, maximum in (("tasks", 500), ("notes", 100)):
        entries = raw.get(key)
        if not isinstance(entries, list) or len(entries) > maximum:
            raise ValueError("Lista inválida ou extensa demais.")
        for item in entries:
            if not isinstance(item, dict):
                raise ValueError("Registro inválido.")
            entry_id = item.get("id")
            if not isinstance(entry_id, str) or not entry_id or len(entry_id) > 80 or entry_id in ids:
                raise ValueError("Identificador inválido.")
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
    saved = Signal()

    def __init__(self, directory: Path, read_only=False):
        super().__init__()
        self.path = directory / "tools.json"
        self.backup = directory / "tools.backup.json"
        self.data = {"schema_version": 1, "tasks": [], "notes": []}
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
        if path.stat().st_size > 8 * 1024 * 1024:
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
                        ConfigStore.atomic_write(path.with_name("tools.corrupt.json"), path.read_bytes()[:8 * 1024 * 1024])
                    except OSError:
                        pass

    def change(self, data):
        checked = validate_document(data)
        if len(json.dumps(checked, ensure_ascii=False, indent=2).encode("utf-8")) > 8 * 1024 * 1024:
            raise ValueError("Tarefas e notas atingiram o limite total de 8 MiB.")
        if checked != self.data:
            self.data = checked
            self.dirty = True
            self.timer.start()

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
        if key not in ("tasks", "notes"):
            raise ValueError("Coleção inválida.")
        self.change(self.data | {key: [item for item in self.data[key] if item["id"] != entry_id]})

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
        self.flush()
