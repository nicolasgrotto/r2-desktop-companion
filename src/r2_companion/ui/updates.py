import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from uuid import uuid4

from PySide6.QtCore import QThread, QTimer, Qt, Signal
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QProgressBar, QPushButton, QVBoxLayout

from .. import __version__
from ..pet.animation import AnimationManager
from ..pet.state import State
from ..services.update_client import check_release, download_release, validate_release, version_tuple, REPOSITORY
from ..services.updates import independent_environment, read_release
from ..services.storage import ConfigStore
from .theme import fit_dialog
from ..droids.themes import PersistedThemeWatcher, styled
from ..droids.profiles import DroidRegistry
from ..droids.visuals import load_profile_clips
from .droids import PreviewCanvas

STYLE = """
QDialog { background: #091c30; color: #e6f7ff; }
QLabel { color: #d5edfa; font: 13px 'Segoe UI'; }
QLabel#title { color: #f4fcff; font-size: 22px; font-weight: 700; }
QLabel#state { color: #62d5ff; font-size: 16px; font-weight: 600; }
QPlainTextEdit { background: #102b43; color: #d5edfa; border: 1px solid #245675; border-radius: 9px; padding: 8px; }
QProgressBar { border: 1px solid #245675; border-radius: 6px; background: #102b43; color: #d5edfa; height: 15px; text-align: center; }
QProgressBar::chunk { background: #26b5ed; border-radius: 5px; }
QPushButton { color: #e6f7ff; background: #173c58; border: 1px solid #34769c; border-radius: 8px; padding: 10px 15px; }
QPushButton:hover { background: #216a94; }
QPushButton:disabled { color: #7893a4; background: #102b43; }
"""


class UpdateWorker(QThread):
    result = Signal(object)
    error = Signal(str)
    progress = Signal(int, int)
    stage = Signal(str, str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            value = self.operation(self)
            if not self.isInterruptionRequested():
                self.result.emit(value)
        except Exception as error:
            if not self.isInterruptionRequested():
                self.error.emit(str(error))


BUSY_STATES = {"checking", "download", "integrity", "preparing", "handoff", "installing", "restarting"}


class UpdateCenter(QDialog):
    def __init__(self, directory, install=None, owner_pid=0, owner_started=0, resume=None, client=check_release, ready_file=None):
        super().__init__()
        self.setWindowTitle("Central de atualizações · R2 Companion")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.presented = False
        styled(self, STYLE)
        self.resize(440, 340)
        self.directory = Path(directory).resolve()
        self.theme_watcher = PersistedThemeWatcher(self.directory, Path(__file__).resolve().parents[1] / "assets", self)
        self.install = None if install is None else Path(install).resolve()
        self.owner_pid, self.owner_started = owner_pid, owner_started
        self.metadata = read_release(self.install / "release.json") if self.install else {"version": __version__, "repository": REPOSITORY}
        self.client = client
        self.worker = None
        self.child = None
        self.successor = None
        self.ready_file = Path(ready_file) if ready_file else None
        self.handoff_file = None
        self.handoff_started = 0
        self.prepared = None
        self.pending_operation = None
        self.release = None
        self.state = "idle"
        self.closing = False
        self.status_path = None
        self.status_message = ""
        self.installer_state = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        heading = QHBoxLayout()
        self.character = PreviewCanvas()
        self.character.setFixedSize(72, 72)
        heading.addWidget(self.character)
        labels = QVBoxLayout()
        title = QLabel("Central de atualizações")
        title.setObjectName("title")
        labels.addWidget(title)
        self.installed_label = QLabel(f"R2 Companion · v{self.metadata['version']}")
        labels.addWidget(self.installed_label)
        heading.addLayout(labels, 1)
        layout.addLayout(heading)
        self.status = QLabel("Pronto para verificar")
        self.status.setObjectName("state")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.detail = QLabel("A consulta é manual e não altera a instalação.")
        self.detail.setWordWrap(True)
        layout.addWidget(self.detail)
        self.package_label = QLabel("")
        self.package_label.setWordWrap(True)
        layout.addWidget(self.package_label)
        self.progress = QProgressBar()
        self.progress.hide()
        layout.addWidget(self.progress)
        self.notes = QPlainTextEdit()
        self.notes.setReadOnly(True)
        self.notes.setMaximumHeight(150)
        self.notes.hide()
        layout.addWidget(self.notes)
        buttons = QHBoxLayout()
        self.action = QPushButton("Verificar novamente")
        self.action.clicked.connect(self.act)
        buttons.addWidget(self.action)
        self.later = QPushButton("Depois")
        self.later.clicked.connect(self.close)
        buttons.addWidget(self.later)
        layout.addLayout(buttons)
        assets = Path(__file__).resolve().parents[1] / "assets"
        registry = DroidRegistry(assets)
        profile = registry.profiles.get(self.theme_watcher.last_id, registry.active)
        self.animation = AnimationManager(load_profile_clips(profile))
        self.animation.frame_changed.connect(self.character.set_frame)
        self.theme_watcher.profile_changed.connect(self.use_profile)
        self.animation.clip_finished.connect(lambda token: self.animation.play(State.WORK, 1) if self.state in BUSY_STATES else None)
        self.poll = QTimer(self)
        self.poll.setInterval(500)
        self.poll.timeout.connect(self.poll_install)
        self.handoff_timer = QTimer(self)
        self.handoff_timer.setInterval(100)
        self.handoff_timer.timeout.connect(self.poll_handoff)
        self.startup = QTimer(self)
        self.startup.setSingleShot(True)
        self.startup.timeout.connect(lambda: self.resume_install(Path(resume)) if resume else self.check())
        self.startup.start(0)

    def use_profile(self, profile):
        try:
            clips = load_profile_clips(profile)
        except (OSError, ValueError, KeyError, TypeError):
            return
        self.animation.stop()
        self.animation.clips = clips
        self.animation.play(State.WORK if self.state in BUSY_STATES else State.IDLE, 1)

    def operation_active(self):
        return (self.state in BUSY_STATES
                or self.worker is not None and self.worker.isRunning()
                or self.child is not None and self.child.poll() is None
                or self.handoff_timer.isActive())

    def set_state(self, state, text, detail):
        self.state = state
        self.status.setText(text)
        self.detail.setText(detail)
        busy = state in BUSY_STATES
        self.action.setEnabled(not busy and not (self.worker is not None and self.worker.isRunning())
                               and not (self.child is not None and self.child.poll() is None))
        self.later.setText("Aguarde a conclusão" if busy else "Fechar")
        self.later.setEnabled(not busy)
        self.progress.setVisible(busy)
        self.progress.setRange(0, 0)
        self.animation.play(State.WORK if busy else State.HAPPY if state in {"current", "done"} else State.IDLE, 1)
        self.action.setText("Atualizar agora" if state == "available" else "Tentar novamente" if state == "error" else "Verificar novamente")

    def start_worker(self, operation, callback):
        if self.worker is not None and self.worker.isRunning():
            return
        worker = UpdateWorker(operation, self)
        self.worker = worker
        worker.result.connect(callback)
        worker.error.connect(self.fail)
        worker.progress.connect(self.download_progress)
        worker.stage.connect(lambda state, text: self.set_state(state, text, "A instalação atual continua disponível."))
        worker.finished.connect(self.worker_finished)
        worker.start()

    def worker_finished(self):
        worker = self.sender()
        if self.worker is worker:
            self.worker = None
        worker.deleteLater()
        if self.closing:
            self.close()
        elif self.pending_operation is not None:
            operation, self.pending_operation = self.pending_operation, None
            operation()
        else:
            self.action.setEnabled(not self.operation_active())

    def act(self):
        if self.operation_active():
            return
        if self.state == "available":
            self.download()
        else:
            self.check()

    def check(self):
        if self.operation_active():
            return
        self.package_label.clear()
        self.notes.hide()
        self.set_state("checking", "Verificando atualizações…", "Consultando a última release estável no GitHub.")
        self.start_worker(lambda worker: self.client(self.metadata["repository"]), self.checked)

    def checked(self, release):
        self.release = release
        self.notes.setPlainText(release["notes"])
        self.notes.show()
        if version_tuple(release["version"]) <= version_tuple(self.metadata["version"]):
            self.set_state("current", "Você está utilizando a versão mais recente!", f"Versão instalada: {self.metadata['version']}.")
        else:
            self.set_state("available", f"Versão {release['version']} disponível", f"Instalada: {self.metadata['version']}. Confira as novidades e escolha quando atualizar.")

    def download_progress(self, received, total):
        if total > 0:
            self.progress.setRange(0, total)
            self.progress.setValue(received)
            self.progress.setFormat("%p%")
            self.detail.setText(f"{received / 1048576:.2f} de {total / 1048576:.2f} MiB baixados")
        else:
            self.progress.setRange(0, 0)
            self.detail.setText(f"{received / 1048576:.2f} MiB baixados · tamanho total indisponível")

    def download(self):
        if self.operation_active():
            return
        if self.release is None:
            self.fail("Verifique a versão disponível antes de baixar.")
            return
        if self.install is None:
            self.fail("A instalação automática está disponível no executável. Gere ou instale o pacote Windows para atualizar.")
            return
        if self.directory == self.install or self.install in self.directory.parents:
            self.fail("O diretório de dados precisa ficar fora da instalação.")
            return
        destination = self.directory / "updates" / ("download-" + uuid4().hex)
        self.package_label.setText(f"Pacote Windows · v{self.release['version']}")
        self.set_state("download", "Baixando atualização…", "O R2 será encerrado apenas depois da validação.")
        self.start_worker(lambda worker: download_release(self.release, destination, worker.progress.emit, worker.stage.emit,
                                                         worker.isInterruptionRequested), self.downloaded)

    def downloaded(self, prepared):
        self.set_state("preparing", "Preparando instalação…", "Criando uma central independente para acompanhar o reinício.")
        self.prepared = Path(prepared)
        if self.worker is not None:
            self.pending_operation = self.prepare_center
        else:
            self.prepare_center()

    def prepare_center(self):
        destination = self.directory / "updates" / ("center-" + uuid4().hex) / "R2Companion"
        def copy(worker):
            for path in self.install.rglob("*"):
                if path.is_symlink() or path.is_junction():
                    raise ValueError("A instalação contém links e não pode ser atualizada automaticamente.")
            def copy_file(source, target):
                if worker.isInterruptionRequested():
                    raise InterruptedError("Preparação cancelada.")
                return shutil.copy2(source, target)
            shutil.copytree(self.install, destination, copy_function=copy_file)
            return destination
        self.start_worker(copy, self.spawn_center)

    def spawn_center(self, destination):
        try:
            self.handoff_file = self.prepared / ("center-ready-" + uuid4().hex + ".json")
            self.successor = subprocess.Popen([str(Path(destination) / "R2Companion.exe"), "--update-center", "--install-dir", str(self.install),
                              "--data-dir", str(self.directory), "--owner-pid", str(self.owner_pid),
                              "--owner-start", str(self.owner_started), "--resume-update", str(self.prepared),
                              "--update-ready-file", str(self.handoff_file)],
                             cwd=str(destination), env=independent_environment(), creationflags=subprocess.CREATE_NO_WINDOW)
            self.handoff_started = time.monotonic()
            self.set_state("handoff", "Abrindo acompanhamento da instalação…",
                           "Esta janela permanece aberta até a central independente estar visível.")
            self.handoff_timer.start()
        except OSError as error:
            self.fail(str(error))

    def poll_handoff(self):
        try:
            if self.handoff_file.is_file():
                ready = json.loads(self.handoff_file.read_text(encoding="utf-8"))
                if ready.get("pid") == self.successor.pid and ready.get("visible") is True and self.successor.poll() is None:
                    ConfigStore.atomic_write(self.handoff_file.with_suffix(".ack"), b"ready")
                    self.handoff_timer.stop()
                    self.closing = True
                    self.close()
                    return
        except (OSError, ValueError, AttributeError):
            pass
        if self.successor.poll() is not None or time.monotonic() - self.handoff_started > 45:
            self.handoff_timer.stop()
            self.fail("A central independente não confirmou sua abertura. A instalação atual foi preservada. Tente novamente.")

    def announce_ready(self):
        if (not self.isVisible() or not self.presented or self.windowHandle() is None
                or not self.windowHandle().isExposed() or self.ready_file is None):
            return
        try:
            ConfigStore.atomic_write(self.ready_file, json.dumps({"pid": os.getpid(), "visible": True}).encode("utf-8"))
        except OSError as error:
            self.fail(f"Não foi possível confirmar a abertura da central: {error}")

    def resume_install(self, prepared):
        if self.ready_file is not None:
            if not self.ready_file.with_suffix(".ack").is_file():
                if not self.handoff_started:
                    self.handoff_started = time.monotonic()
                    self.set_state("handoff", "Central de instalação pronta", "Aguardando a confirmação da janela anterior.")
                self.announce_ready()
                if time.monotonic() - self.handoff_started > 50:
                    self.fail("A janela anterior não confirmou a transferência. Feche esta central e tente novamente.")
                else:
                    self.startup.start(100)
                return
        self.install_prepared(prepared)

    def install_prepared(self, prepared):
        try:
            if self.install is None:
                raise ValueError("Instalação ausente.")
            self.release = validate_release(json.loads((prepared / "candidate.json").read_text(encoding="utf-8")), self.metadata["repository"])
            self.package_label.setText(f"Pacote Windows · v{self.release['version']}")
            bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
            script = bundle / "scripts/update-r2-companion.ps1"
            self.status_path = prepared / "status.json"
            powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            log = (prepared / "installer.log").open("ab")
            try:
                self.child = subprocess.Popen([str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script),
                    "-InstallDirectory", str(self.install), "-DataDirectory", str(self.directory), "-Yes", "-Console",
                    "-ExpectedProcessId", str(self.owner_pid), "-ProcessStarted", str(self.owner_started),
                    "-PreparedDirectory", str(prepared), "-PreparedVersion", self.release["version"],
                    "-StatusPath", str(self.status_path)], stdout=log, stderr=log,
                    cwd=str(prepared), env=independent_environment(), creationflags=subprocess.CREATE_NO_WINDOW)
            finally:
                log.close()
            self.set_state("installing", "Instalando atualização…", "Encerrando o R2, criando backup e preparando o reinício.")
            self.later.setEnabled(False)
            self.poll.start()
        except (OSError, ValueError) as error:
            self.fail(str(error))

    def poll_install(self):
        try:
            if self.status_path.is_file():
                status = json.loads(self.status_path.read_text(encoding="utf-8-sig"))
                self.status_message = status.get("message", "")
                state = status.get("state")
                self.installer_state = state
                titles = {"checking": "Conferindo atualização…", "integrity": "Verificando integridade…",
                          "installing": "Instalando atualização…", "restarting": "Reiniciando o Companion…"}
                if state in titles and state != self.state:
                    self.set_state(state, titles[state], self.status_message)
                self.detail.setText(self.status_message)
        except (OSError, ValueError):
            pass
        if self.child.poll() is not None:
            self.poll.stop()
            self.later.setEnabled(True)
            if self.child.returncode == 0:
                try:
                    self.metadata = read_release(self.install / "release.json")
                    self.installed_label.setText(f"R2 Companion · v{self.metadata['version']}")
                except (OSError, ValueError):
                    self.fail("A instalação terminou, mas não foi possível ler sua versão. Consulte o log.")
                    return
                restart_required = self.installer_state == "restart_required"
                if self.installer_state != "current" and self.release is not None and self.metadata["version"] != self.release["version"]:
                    self.fail("A versão instalada não corresponde ao pacote solicitado. Consulte o log e tente novamente.")
                    return
                if self.installer_state not in {"current", "done", "restart_required"}:
                    self.fail("O instalador encerrou sem confirmar a conclusão. Consulte o log de atualização.")
                    return
                self.set_state("restart_required" if restart_required else "done",
                               "Reinicie para utilizar a nova versão" if restart_required else "Atualização concluída",
                               self.status_message or "A instalação terminou. Abra o Companion para conferir a nova versão.")
            else:
                self.fail(self.status_message or "Não foi possível atualizar. Consulte o log em updates e tente novamente.")

    def fail(self, message):
        self.set_state("error", "Não foi possível atualizar", message)

    def paintEvent(self, event):
        super().paintEvent(event)
        self.presented = True

    def reject(self):
        self.close()

    def closeEvent(self, event):
        if not self.closing and self.operation_active():
            event.ignore()
            return
        if self.worker is not None and self.worker.isRunning():
            event.ignore()
            return
        self.startup.stop()
        self.theme_watcher.close()
        self.poll.stop()
        self.handoff_timer.stop()
        self.animation.stop()
        event.accept()


def run_update_center(directory, install=None, owner_pid=0, owner_started=0, resume=None, ready_file=None):
    app = QApplication.instance() or QApplication([sys.argv[0]])
    app.setQuitOnLastWindowClosed(True)
    dialog = UpdateCenter(directory, install, owner_pid, owner_started, resume, ready_file=ready_file)
    fit_dialog(dialog, dialog)
    dialog.show()
    dialog.raise_()
    dialog.activateWindow()
    return app.exec()
