from PySide6.QtWidgets import QFileDialog, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget

from ..core.config import FutureSchemaError
from ..features.data_transfer import BACKUP_LABELS
from .theme import card, label


class DataPage(QScrollArea):
    def __init__(self, transfer):
        super().__init__()
        self.transfer = transfer
        self.setWidgetResizable(True)
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        export = QPushButton("Exportar tarefas e notas")
        export.clicked.connect(self.export_productivity)
        layout.addWidget(export)
        refresh = QPushButton("Atualizar estado dos backups")
        refresh.clicked.connect(self.refresh)
        layout.addWidget(refresh)
        self.rows = {}
        for group, title in BACKUP_LABELS.items():
            panel, content = card()
            content.addWidget(label(title, "heading"))
            state = label("", "muted")
            content.addWidget(state)
            restore = QPushButton("Restaurar backup")
            restore.setAccessibleName(f"Restaurar backup de {title.lower()}")
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

    def refresh(self):
        for group, (status, restore) in self.rows.items():
            try:
                self.transfer.inspect(group)
            except FileNotFoundError:
                message = "Backup ainda indisponível."
            except FutureSchemaError:
                message = "Backup de uma versão futura."
            except (ValueError, OSError, RuntimeError):
                message = "Backup inválido ou inacessível."
            else:
                message = "Backup válido."
            writable = self.transfer.can_restore(group)
            restore.setEnabled(writable and message == "Backup válido.")
            status.setText(message if writable else f"{message} Dados em modo somente leitura.")

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
        try:
            backup = self.transfer.inspect(group)
            title = BACKUP_LABELS[group]
            message = (f"Substituir os dados atuais de {title.lower()} pelo backup? "
                       "O Companion guardará uma cópia recuperável dos dados atuais.")
            if QMessageBox.question(self, "Restaurar backup", message, defaultButton=QMessageBox.StandardButton.No
                                    ) != QMessageBox.StandardButton.Yes:
                self.status.setText("Restauração cancelada.")
                return
            recovery = self.transfer.restore(backup)
            self.status.setText(f"Backup restaurado. Cópia dos dados anteriores em {recovery}.")
        except (OSError, ValueError, RuntimeError) as error:
            self.status.setText(f"Não foi possível restaurar o backup. {error}")
        self.refresh()
