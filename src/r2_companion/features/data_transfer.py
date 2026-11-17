"""Explicit exports and local backup recovery under the existing data lock."""
from dataclasses import dataclass
import json
import os
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
    data: object
    encoded: bytes
    modified_at: float


@dataclass(frozen=True)
class PreparedRestore:
    backup: Backup
    backup_version: tuple | None
    current_version: tuple | None


class OversizedDocumentError(ValueError):
    pass


def encode_document(group, data):
    _, validate = VALIDATORS[group]
    checked = validate(data.to_dict() if isinstance(data, Settings) else data)
    return encode_checked(group, checked)


def encode_checked(group, checked):
    values = checked.to_dict() if isinstance(checked, Settings) else checked
    contents = json.dumps(values, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
    if len(contents) > VALIDATORS[group][0]:
        raise ValueError("O documento excede o limite de armazenamento.")
    return contents


def file_version(stat):
    return stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns


def current_version(path):
    try:
        return file_version(path.stat())
    except FileNotFoundError:
        return None


def read_contents(group, path):
    maximum = VALIDATORS[group][0]
    with path.open("rb") as handle:
        before = os.fstat(handle.fileno())
        contents = handle.read(maximum + 1)
        stat = os.fstat(handle.fileno())
    if file_version(before) != file_version(stat):
        raise OSError("O arquivo mudou durante a leitura. Consulte novamente.")
    if len(contents) > maximum:
        raise OversizedDocumentError("O documento excede o limite de leitura.")
    return contents, stat


def read_document(group, path):
    contents, stat = read_contents(group, path)
    _, validate = VALIDATORS[group]
    try:
        data = validate(json.loads(contents.decode("utf-8")))
        encoded = encode_checked(group, data)
    except (TypeError, RecursionError, OverflowError) as error:
        raise ValueError("O documento está inválido.") from error
    return Backup(group, contents, data, encoded, stat.st_mtime)


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
        return read_document(group, self.stores[group].backup)

    def can_restore(self, group):
        lock = self.config.lock
        return bool(lock and lock.isLocked() and not self.config.read_only and not self.stores[group].read_only)

    def restore(self, backup):
        if not self.can_restore(backup.group):
            raise OSError("Os dados estão em modo somente leitura.")
        return self.apply_restore(self.prepare_restore(backup))

    def prepare_restore(self, backup):
        group = backup.group
        store = self.stores[group]
        backup_version = current_version(store.backup)
        contents, _ = read_contents(group, store.backup)
        if contents != backup.contents:
            raise ValueError("O backup mudou. Consulte novamente antes de restaurar.")
        version = current_version(store.path)
        try:
            read_document(group, store.path)
        except (FutureSchemaError, OversizedDocumentError):
            raise
        except FileNotFoundError:
            pass
        except ValueError:
            # An invalid current file can be repaired using the validated live snapshot.
            pass
        return PreparedRestore(backup, backup_version, version)

    def apply_restore(self, prepared):
        backup = prepared.backup
        group = backup.group
        store = self.stores[group]
        if not self.can_restore(group):
            raise OSError("Os dados estão em modo somente leitura.")
        if current_version(store.backup) != prepared.backup_version:
            raise ValueError("O backup mudou. Consulte novamente antes de restaurar.")
        if current_version(store.path) != prepared.current_version:
            raise ValueError("Os dados atuais mudaram. Consulte novamente antes de restaurar.")
        recovery = self.recovery_path(store)
        previous = store.settings if group == "config" else store.data
        previous_contents = encode_document(group, previous)

        def write(restored_contents):
            ConfigStore.atomic_write(recovery, previous_contents)
            ConfigStore.atomic_write(store.path, restored_contents)

        if group == "config":
            self.restore_configuration(backup.data, lambda data: write(encode_document(group, data)))
        else:
            write(backup.encoded)
            store.accept_restored(backup.data)
        return recovery
