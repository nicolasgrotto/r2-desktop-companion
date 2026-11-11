import json
from copy import deepcopy
import logging
from pathlib import Path

from PySide6.QtCore import QIODevice, QLockFile, QObject, QSaveFile, QTimer, Signal

from ..core.config import FutureSchemaError, Settings

log = logging.getLogger(__name__)


class ConfigStore(QObject):
    changed = Signal(object)
    warning = Signal(str)

    def __init__(self, directory: Path):
        super().__init__()
        self.directory = directory
        self.path = directory / "config.json"
        self.backup = directory / "config.backup.json"
        self.settings = Settings()
        self.read_only = False
        self.dirty = False
        self.notices: list[str] = []
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(750)
        self.timer.timeout.connect(self.flush)
        self.lock: QLockFile | None = None
        try:
            directory.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.read_only = True
            self.notices.append("Diretório indisponível: alterações ficarão somente nesta sessão.")

    def acquire(self) -> bool:
        if self.read_only:
            return True
        self.lock = QLockFile(str(self.directory / "companion.lock"))
        if self.lock.tryLock(0):
            return True
        if self.lock.error() == QLockFile.LockError.PermissionError:
            self.read_only = True
            self.notices.append("Diretório sem permissão de gravação; alterações somente nesta sessão.")
            return True
        return False

    def _read(self, path: Path) -> Settings:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("Configuração excede 1 MiB.")
        return Settings.parse(json.loads(path.read_text(encoding="utf-8")))

    def load(self) -> None:
        for path in (self.path, self.backup):
            try:
                self.settings = self._read(path)
                if path == self.backup:
                    self.notices.append("Configuração recuperada do backup.")
                return
            except FileNotFoundError:
                continue
            except FutureSchemaError as error:
                self.read_only = True
                self.notices.append(str(error))
                return
            except (OSError, ValueError, TypeError) as error:
                log.warning("Configuração inválida (%s)", type(error).__name__)
                self.notices.append("Configuração inválida; usando backup ou valores padrão.")
                if path == self.path and not self.read_only:
                    try:
                        self.atomic_write(self.directory / "config.corrupt.json", path.read_bytes()[:1024 * 1024])
                    except OSError:
                        pass

    @staticmethod
    def atomic_write(path: Path, contents: bytes) -> None:
        output = QSaveFile(str(path))
        output.setDirectWriteFallback(False)
        if not output.open(QIODevice.OpenModeFlag.WriteOnly):
            raise OSError(output.errorString())
        if output.write(contents) != len(contents):
            output.cancelWriting()
            raise OSError(output.errorString())
        if not output.commit():
            raise OSError(output.errorString())

    def apply(self, settings: Settings, notify: bool = True) -> None:
        settings = deepcopy(settings)
        settings.capture_droid()
        checked = Settings.parse(settings.to_dict())
        if checked == self.settings:
            return
        self.settings = checked
        self.dirty = True
        self.timer.start()
        if notify:
            self.changed.emit(checked)

    def flush(self) -> bool:
        self.timer.stop()
        if not self.dirty:
            return True
        if self.read_only:
            self.warning.emit("Sem persistência nesta sessão; o arquivo original foi preservado.")
            return False
        try:
            if self.path.exists():
                try:
                    old = self._read(self.path)
                except (OSError, ValueError, TypeError):
                    old = None
                if old is not None:
                    self.atomic_write(self.backup, json.dumps(old.to_dict(), ensure_ascii=False).encode("utf-8"))
            self.atomic_write(self.path, json.dumps(self.settings.to_dict(), indent=2, ensure_ascii=False,
                                                  allow_nan=False).encode("utf-8"))
            self.dirty = False
            return True
        except OSError:
            log.exception("Não foi possível salvar a configuração")
            self.warning.emit("Não foi possível salvar. A configuração anterior foi preservada.")
            return False

    def close(self) -> None:
        self.flush()
        if self.lock is not None and self.lock.isLocked():
            self.lock.unlock()
