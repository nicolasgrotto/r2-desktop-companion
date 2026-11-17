"""Explicit exports and local backup recovery under the existing data lock."""
from dataclasses import dataclass
import json
from pathlib import Path

from ..core.config import FutureSchemaError, Settings
from ..services.companion_state import MAX_BYTES as STATE_LIMIT, validate_document as validate_state
from ..services.storage import ConfigStore
from .productivity import MAX_BYTES as PRODUCTIVITY_LIMIT, validate_document as validate_productivity


BACKUP_LABELS = {
    "config": "Configuração",
    "tools": "Tarefas e notas",
    "companion_state": "Estado complementar",
}
VALIDATORS = {
    "config": (1024 * 1024, Settings.parse),
    "tools": (PRODUCTIVITY_LIMIT, validate_productivity),
    "companion_state": (STATE_LIMIT, validate_state),
}


@dataclass(frozen=True)
class Backup:
    group: str
    contents: bytes


class OversizedDocumentError(ValueError):
    pass


def encode_document(group, data):
    maximum, validate = VALIDATORS[group]
    checked = validate(data.to_dict() if isinstance(data, Settings) else data)
    values = checked.to_dict() if isinstance(checked, Settings) else checked
    contents = json.dumps(values, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    if len(contents) > maximum:
        raise ValueError("O documento excede o limite de armazenamento.")
    return contents


def read_document(group, path):
    maximum, validate = VALIDATORS[group]
    with path.open("rb") as handle:
        contents = handle.read(maximum + 1)
    if len(contents) > maximum:
        raise OversizedDocumentError("O documento excede o limite de leitura.")
    try:
        data = validate(json.loads(contents.decode("utf-8")))
        encode_document(group, data)
    except (TypeError, RecursionError, OverflowError) as error:
        raise ValueError("O documento está inválido.") from error
    return contents, data


class DataTransfer:
    def __init__(self, config, productivity, state, restore_configuration):
        self.config = config
        self.productivity = productivity
        self.stores = {"config": config, "tools": productivity, "companion_state": state}
        self.restore_configuration = restore_configuration

    def export_tasks_and_notes(self, destination):
        self.export(destination, encode_document("tools", self.productivity.data))

    def export_note(self, entry_id, destination):
        data = validate_productivity(self.productivity.data)
        note = next((entry for entry in data["notes"] if entry["id"] == entry_id), None)
        if note is None:
            raise ValueError("Selecione uma nota para exportar.")
        self.export(destination, note["body"].encode("utf-8"))

    def export(self, destination, contents):
        destination = Path(destination).resolve()
        reserved = (path for store in self.stores.values()
                    for path in (store.path, store.backup, self.recovery_path(store)))
        if destination == (self.config.directory / "companion.lock").resolve() or any(
            destination == path.resolve() for path in reserved
        ):
            raise ValueError("Escolha um arquivo de destino diferente dos arquivos internos do Companion.")
        ConfigStore.atomic_write(destination, contents)

    @staticmethod
    def recovery_path(store):
        return store.path.with_suffix(".before-restore.json")

    def inspect(self, group):
        contents, _ = read_document(group, self.stores[group].backup)
        return Backup(group, contents)

    def can_restore(self, group):
        lock = self.config.lock
        return bool(lock and lock.isLocked() and not self.config.read_only and not self.stores[group].read_only)

    def restore(self, backup):
        group = backup.group
        store = self.stores[group]
        if not self.can_restore(group):
            raise OSError("Os dados estão em modo somente leitura.")
        contents, candidate = read_document(group, store.backup)
        if contents != backup.contents:
            raise ValueError("O backup mudou. Consulte novamente antes de restaurar.")
        try:
            read_document(group, store.path)
        except (FutureSchemaError, OversizedDocumentError):
            raise
        except FileNotFoundError:
            pass
        except ValueError:
            # An invalid current file can be repaired using the validated live snapshot.
            pass

        recovery = self.recovery_path(store)
        previous = store.settings if group == "config" else store.data
        previous_contents = encode_document(group, previous)

        def persist(data):
            restored_contents = encode_document(group, data)
            ConfigStore.atomic_write(recovery, previous_contents)
            ConfigStore.atomic_write(store.path, restored_contents)

        if group == "config":
            self.restore_configuration(candidate, persist)
        else:
            persist(candidate)
            store.accept_restored(candidate)
        return recovery
