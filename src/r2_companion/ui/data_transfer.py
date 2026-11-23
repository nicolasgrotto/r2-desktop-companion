from datetime import datetime

from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..core.config import FutureSchemaError
from ..features.data_transfer import BACKUP_LABELS
from ..services.tasks import LocalTasks
from .theme import card, label
from ..core.language import tr


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
        export = QPushButton(tr("Exportar tarefas e notas"))
        export.clicked.connect(self.export_productivity)
        layout.addWidget(export)
        self.refresh_button = QPushButton(tr("Atualizar estado dos backups"))
        self.refresh_button.clicked.connect(lambda: self.refresh(manual=True))
        layout.addWidget(self.refresh_button)
        self.refresh_status = label("", "muted")
        layout.addWidget(self.refresh_status)
        self.rows = {}
        for group, title in BACKUP_LABELS.items():
            title = tr(title)
            panel, content = card()
            content.addWidget(label(title, "heading"))
            state = label("", "muted")
            content.addWidget(state)
            restore = QPushButton(tr("Restaurar backup"))
            restore.setAccessibleName(tr("Restaurar backup de {0}", title.lower()))
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
            self.refresh_status.setText(tr("Consultando backups…"))
        self.update_buttons()

    def read_backups(self):
        results = {}
        for group in BACKUP_LABELS:
            modified_at = None
            try:
                backup = self.transfer.inspect(group)
            except FileNotFoundError:
                message = tr("Backup ainda indisponível.")
            except FutureSchemaError:
                message = tr("Backup de uma versão futura.")
            except (ValueError, OSError, RuntimeError):
                message = tr("Backup inválido ou inacessível.")
            else:
                message = tr("Backup válido.")
                modified_at = backup.modified_at
            results[group] = message, modified_at
        return results

    def show_backups(self, results, manual):
        if isinstance(results, Exception):
            self.refresh_status.setText(tr("Não foi possível consultar os backups. {0}", results))
            self.available.clear()
            self.update_buttons()
            return
        self.available.clear()
        for group, (message, modified_at) in results.items():
            status, _ = self.rows[group]
            writable = self.transfer.can_restore(group)
            if modified_at is not None:
                self.available.add(group)
                written = datetime.fromtimestamp(modified_at).strftime(tr("%d/%m/%Y às %H:%M:%S"))
                message = tr("{0} Última gravação em {1}.", message, written)
            status.setText(message if writable else tr("{0} Dados em modo somente leitura.", message))
        if manual:
            checked = datetime.now().strftime(tr("%d/%m/%Y às %H:%M:%S"))
            self.refresh_status.setText(tr("Estado dos backups atualizado em {0}.", checked))
        elif self.refresh_status.text() == tr("Consultando backups…"):
            self.refresh_status.clear()
        self.update_buttons()

    def update_buttons(self):
        available = not (self.tasks.busy or self.tasks.closed or self.restoring)
        self.refresh_button.setEnabled(available)
        for group, (_, restore) in self.rows.items():
            restore.setEnabled(available and group in self.available and self.transfer.can_restore(group))

    def export_productivity(self):
        destination, _ = QFileDialog.getSaveFileName(self, tr("Exportar tarefas e notas"), "tarefas-e-notas.json",
                                                      tr("Documento JSON (*.json)"))
        if not destination:
            return
        try:
            self.transfer.export_tasks_and_notes(destination)
        except (OSError, ValueError, RuntimeError) as error:
            self.status.setText(tr("Não foi possível exportar os dados. {0}", error))
        else:
            self.status.setText(tr("Tarefas e notas exportadas."))

    def restore(self, group):
        if self.restoring or not self.transfer.can_restore(group):
            return
        if self.tasks.submit(lambda: self.transfer.inspect(group), self.confirm_restore):
            self.restoring = True
            self.status.setText(tr("Conferindo o backup…"))
            self.update_buttons()

    def confirm_restore(self, backup):
        if isinstance(backup, Exception):
            self.finish_restore(backup)
            return
        title = tr(BACKUP_LABELS[backup.group])
        message = (tr("Substituir os dados atuais de {0} pelo backup? O Companion guardará uma cópia recuperável dos dados atuais.", title.lower()))
        answer = QMessageBox.question(self, tr("Restaurar backup"), message, defaultButton=QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            self.restoring = False
            self.status.setText(tr("Restauração cancelada."))
            self.update_buttons()
            return
        self.status.setText(tr("Restaurando backup…"))
        self.tasks.submit(lambda: self.transfer.prepare_restore(backup), self.finish_restore)

    def finish_restore(self, prepared):
        try:
            if isinstance(prepared, Exception):
                raise prepared
            recovery = self.transfer.apply_restore(prepared)
            self.status.setText(tr("Backup restaurado. Cópia dos dados anteriores em {0}.", recovery))
        except (OSError, ValueError, RuntimeError) as error:
            self.status.setText(tr("Não foi possível restaurar o backup. {0}", error))
        self.restoring = False
        self.refresh()
