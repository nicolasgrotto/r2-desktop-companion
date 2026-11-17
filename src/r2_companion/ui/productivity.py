from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QHBoxLayout, QLineEdit,
                              QListWidget, QListWidgetItem, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget)

from .theme import ActionRow, label
from ..droids.themes import styled


class NoteEditor(QPlainTextEdit):
    def insertFromMimeData(self, source):
        if source.hasText():
            remaining = 50000 - len(self.toPlainText()) + len(self.textCursor().selectedText())
            self.insertPlainText(source.text()[:max(0, remaining)])

    def keyPressEvent(self, event):
        if event.text() and len(self.toPlainText()) - len(self.textCursor().selectedText()) >= 50000:
            if event.text().isprintable() or event.text() in ("\r", "\n"):
                return
        super().keyPressEvent(event)


def style_list(widget):
    styled(widget, "QListWidget { background: white; color: #193b57; border: 1px solid #caddea; border-radius: 9px; }"
                        "QListWidget::item { padding: 11px; border-bottom: 1px solid #edf3f9; }"
                        "QListWidget::item:selected { background: #e4effa; color: #193b57; }"
                        "QListWidget:focus { border: 2px solid @focus; }")


class TasksPage(QWidget):
    def __init__(self, store):
        super().__init__()
        self.store = store
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setMaxLength(240)
        self.input.setAccessibleName("Nova tarefa")
        self.input.setPlaceholderText("Uma coisa para fazer…")
        self.input.returnPressed.connect(self.add)
        row.addWidget(self.input, 1)
        button = QPushButton("Adicionar")
        button.clicked.connect(self.add)
        row.addWidget(button)
        layout.addLayout(row)
        self.pending = QCheckBox("Mostrar somente pendentes")
        self.pending.toggled.connect(self.render)
        layout.addWidget(self.pending)
        self.list = QListWidget()
        self.list.setAccessibleName("Lista de tarefas")
        self.list.setWordWrap(True)
        style_list(self.list)
        self.list.itemChanged.connect(self.toggle)
        layout.addWidget(self.list, 1)
        button = QPushButton("Excluir selecionada")
        button.clicked.connect(self.remove)
        layout.addWidget(button)
        self.status = label("", "muted")
        layout.addWidget(self.status)
        self.render()

    def render(self, *_):
        current = self.list.currentItem()
        current_id = None if current is None else current.data(Qt.ItemDataRole.UserRole)
        current_row = self.list.currentRow()
        self.list.blockSignals(True)
        self.list.clear()
        for task in self.store.data["tasks"]:
            if self.pending.isChecked() and task["done"]:
                continue
            item = QListWidgetItem(task["text"])
            item.setData(Qt.ItemDataRole.UserRole, task["id"])
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if task["done"] else Qt.CheckState.Unchecked)
            self.list.addItem(item)
            if task["id"] == current_id:
                self.list.setCurrentItem(item)
        if self.list.currentItem() is None and current_row >= 0:
            self.list.setCurrentRow(min(current_row, self.list.count() - 1))
        self.list.blockSignals(False)
        self.update_status()

    def update_status(self):
        remaining = sum(not task["done"] for task in self.store.data["tasks"])
        self.status.setText(f"{remaining} pendentes · Marque para concluir; desmarque para reabrir.")

    def add(self):
        try:
            self.store.add_task(self.input.text())
            self.input.clear()
            self.render()
        except ValueError as error:
            self.status.setText(str(error))

    def toggle(self, item):
        self.store.set_done(item.data(Qt.ItemDataRole.UserRole), item.checkState() == Qt.CheckState.Checked)
        if self.pending.isChecked():
            self.render()
        else:
            self.update_status()

    def remove(self):
        item = self.list.currentItem()
        if item:
            self.store.remove("tasks", item.data(Qt.ItemDataRole.UserRole))
            self.render()


class NotesPage(QWidget):
    def __init__(self, store):
        super().__init__()
        self.store = store
        self.current_id = None
        layout = QVBoxLayout(self)
        self.list = QListWidget()
        self.list.setAccessibleName("Lista de notas")
        style_list(self.list)
        self.list.setMaximumHeight(145)
        self.list.currentItemChanged.connect(self.select)
        layout.addWidget(self.list)
        row = ActionRow()
        for title, callback in (("Nova", self.add), ("Excluir", self.remove), ("Copiar conteúdo", self.copy)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addWidget(row)
        self.title = QLineEdit()
        self.title.setMaxLength(120)
        self.title.setAccessibleName("Título da nota")
        self.title.setPlaceholderText("Título")
        self.body = NoteEditor()
        self.body.setAccessibleName("Conteúdo da nota")
        self.body.setTabChangesFocus(True)
        self.body.setPlaceholderText("Escreva sua anotação…")
        styled(self.body, "QPlainTextEdit { padding: 10px; }")
        self.title.textEdited.connect(self.save)
        self.body.textChanged.connect(self.save)
        layout.addWidget(self.title)
        layout.addWidget(self.body, 1)
        self.status = label("Salvamento automático local · Até 50.000 caracteres por nota.", "muted")
        store.saved.connect(lambda: self.status.setText("Salvo neste computador."))
        store.warning.connect(self.status.setText)
        layout.addWidget(self.status)
        self.render()

    def render(self, selected=None):
        self.list.blockSignals(True)
        self.list.clear()
        for note in self.store.data["notes"]:
            item = QListWidgetItem(note["title"])
            item.setData(Qt.ItemDataRole.UserRole, note["id"])
            self.list.addItem(item)
            if note["id"] == selected:
                self.list.setCurrentItem(item)
        self.list.blockSignals(False)
        self.select(self.list.currentItem())

    def select(self, item, *_):
        self.current_id = None if item is None else item.data(Qt.ItemDataRole.UserRole)
        note = next((n for n in self.store.data["notes"] if n["id"] == self.current_id), None)
        for widget, value in ((self.title, "" if note is None else note["title"]),
                              (self.body, "" if note is None else note["body"])):
            widget.blockSignals(True)
            widget.setText(value) if widget is self.title else widget.setPlainText(value)
            widget.setEnabled(note is not None)
            widget.blockSignals(False)

    def save(self, *_):
        if self.current_id is None:
            return
        try:
            body = self.body.toPlainText()
            if len(body) > 50000:
                self.body.blockSignals(True)
                self.body.setPlainText(body[:50000])
                self.body.blockSignals(False)
            self.store.edit_note(self.current_id, self.title.text(), self.body.toPlainText())
            self.list.currentItem().setText(self.title.text().strip() or "Sem título")
            self.status.setText("Salvando alterações…")
        except ValueError as error:
            self.status.setText(str(error))

    def add(self):
        try:
            self.render(self.store.add_note())
        except ValueError as error:
            self.status.setText(str(error))

    def remove(self):
        if self.current_id is not None:
            self.store.remove("notes", self.current_id)
            self.render()

    def copy(self):
        if self.current_id is not None:
            QApplication.clipboard().setText(self.body.toPlainText())
