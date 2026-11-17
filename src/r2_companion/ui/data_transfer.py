from datetime import datetime

from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..core.config import FutureSchemaError
from ..features.data_transfer import BACKUP_LABELS
from ..services.tasks import LocalTasks
from .theme import card, label


class DataPage(QScrollArea):
    def __init__(self, transfer):
        super().__init__()
        self.transfer = transfer
        self.tasks = LocalTasks()
        self.tasks.setParent(self)
        self.available = set()
        self.restoring = False
        self.setWidgetResizable(True)
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        export = QPushButton("Exportar tarefas e notas")
        export.clicked.connect(self.export_productivity)
        layout.addWidget(export)
        self.refresh_button = QPushButton("Atualizar estado dos backups")
        self.refresh_button.clicked.connect(lambda: self.refresh(manual=True))
        layout.addWidget(self.refresh_button)
        self.refresh_status = label("", "muted")
        layout.addWidget(self.refresh_status)
        self.rows = {}
        for group, title in BACKUP_LABELS.items():
            panel, content = card()
            content.addWidget(label(title, "heading"))
            state = label("", "muted")
            content.addWidget(state)
            restore = QPushButton("Restaurar backup")
            restore.setAccessibleName(f"Restaurar backup de {title.lower()}")
            restore.setEnabled(False)
            restore.clicked.connect(lambda checked=False, key=group: self.restore(key))
            content.addWidget(restore)
            layout.addWidget(panel)
            self.rows[group] = state, restore
        self.status = label("", "muted")
        layout.addWidget(self.status)
        layout.addStretch()

    def showEvent(self, event):
        self.refresh()
        super().showEvent(event)

    def refresh(self, *, manual=False):
        if self.restoring or not self.tasks.submit(self.read_backups, lambda result: self.show_backups(result, manual)):
            return
        if manual or not self.refresh_status.text():
            self.refresh_status.setText("Consultando backups…")
        self.update_buttons()

    def read_backups(self):
        results = {}
        for group in BACKUP_LABELS:
            modified_at = None
            try:
                backup = self.transfer.inspect(group)
            except FileNotFoundError:
                message = "Backup ainda indisponível."
            except FutureSchemaError:
                message = "Backup de uma versão futura."
            except (ValueError, OSError, RuntimeError):
                message = "Backup inválido ou inacessível."
            else:
                message = "Backup válido."
                modified_at = backup.modified_at
            results[group] = message, modified_at
        return results

    def show_backups(self, results, manual):
        if isinstance(results, Exception):
            self.refresh_status.setText(f"Não foi possível consultar os backups. {results}")
            self.available.clear()
            self.update_buttons()
            return
        self.available.clear()
        for group, (message, modified_at) in results.items():
            status, _ = self.rows[group]
            writable = self.transfer.can_restore(group)
            if modified_at is not None:
                self.available.add(group)
                written = datetime.fromtimestamp(modified_at).strftime("%d/%m/%Y às %H:%M:%S")
                message = f"{message} Última gravação em {written}."
            status.setText(message if writable else f"{message} Dados em modo somente leitura.")
        if manual:
            checked = datetime.now().strftime("%d/%m/%Y às %H:%M:%S")
            self.refresh_status.setText(f"Estado dos backups atualizado em {checked}.")
        elif self.refresh_status.text() == "Consultando backups…":
            self.refresh_status.clear()
        self.update_buttons()

    def update_buttons(self):
        available = not (self.tasks.busy or self.tasks.closed or self.restoring)
        self.refresh_button.setEnabled(available)
        for group, (_, restore) in self.rows.items():
            restore.setEnabled(available and group in self.available and self.transfer.can_restore(group))

    def export_productivity(self):
        destination, _ = QFileDialog.getSaveFileName(self, "Exportar tarefas e notas", "tarefas-e-notas.json",
                                                      "Documento JSON (*.json)")
        if not destination:
            return
        try:
            self.transfer.export_tasks_and_notes(destination)
        except (OSError, ValueError, RuntimeError) as error:
            self.status.setText(f"Não foi possível exportar os dados. {error}")
        else:
            self.status.setText("Tarefas e notas exportadas.")

    def restore(self, group):
        if self.restoring or not self.transfer.can_restore(group):
            return
        if self.tasks.submit(lambda: self.transfer.inspect(group), self.confirm_restore):
            self.restoring = True
            self.status.setText("Conferindo o backup…")
            self.update_buttons()

    def confirm_restore(self, backup):
        if isinstance(backup, Exception):
            self.finish_restore(backup)
            return
        title = BACKUP_LABELS[backup.group]
        message = (f"Substituir os dados atuais de {title.lower()} pelo backup? "
                   "O Companion guardará uma cópia recuperável dos dados atuais.")
        answer = QMessageBox.question(self, "Restaurar backup", message, defaultButton=QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            self.restoring = False
            self.status.setText("Restauração cancelada.")
            self.update_buttons()
            return
        self.status.setText("Restaurando backup…")
        self.tasks.submit(lambda: self.transfer.prepare_restore(backup), self.finish_restore)

    def finish_restore(self, prepared):
        try:
            if isinstance(prepared, Exception):
                raise prepared
            recovery = self.transfer.apply_restore(prepared)
            self.status.setText(f"Backup restaurado. Cópia dos dados anteriores em {recovery}.")
        except (OSError, ValueError, RuntimeError) as error:
            self.status.setText(f"Não foi possível restaurar o backup. {error}")
        self.restoring = False
        self.refresh()
