from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence
from PySide6.QtWidgets import (QCheckBox, QDialog, QKeySequenceEdit, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)

from .theme import ActionRow, apply_theme, card, label


class ShortcutSettings(QWidget):
    def __init__(self, enabled, shortcut, status, apply):
        super().__init__()
        body = QVBoxLayout(self)
        body.setContentsMargins(0, 0, 0, 0)
        panel, layout = card()
        body.addWidget(panel)
        self.enabled = QCheckBox("Usar atalho global para buscar ações")
        self.enabled.setChecked(enabled)
        self.keys = QKeySequenceEdit(QKeySequence.fromString(shortcut, QKeySequence.SequenceFormat.PortableText))
        self.keys.setMaximumSequenceLength(1)
        self.keys.setAccessibleName("Combinação do atalho global")
        self.keys.setAccessibleDescription("Use Ctrl ou Alt com uma letra, número ou tecla de F1 a F11.")
        self.status = label(status, "muted")
        save = QPushButton("Salvar atalho")
        save.setAutoDefault(False)
        save.clicked.connect(lambda: self.status.setText(
            apply(self.enabled.isChecked(), self.keys.keySequence().toString(QKeySequence.SequenceFormat.PortableText))))
        for widget in (self.enabled, self.keys, self.status, save):
            layout.addWidget(widget)


class FirstSteps:
    def __init__(self, tools, registry, dispatch, dismiss):
        self.panel, content = card()
        content.addWidget(label("Primeiros passos", "heading"))
        content.addWidget(label("Arraste o mascote para movê-lo. Para recuperá-lo, abra o menu da bandeja e escolha Mostrar mascote."))
        content.addWidget(label("Na Central de Áudio, use Silenciar este personagem para interromper seus sons."))
        row = ActionRow()
        for key, title in (("search_actions", "Buscar ações"), ("audio", "Central de Áudio"),
                           ("focus", "Foco"), ("media", "Música")):
            if registry.reason(key) is None:
                button = QPushButton(title)
                button.clicked.connect(lambda checked=False, key=key: dispatch(key))
                row.addWidget(button)
        content.addWidget(row)
        close = QPushButton("Dispensar primeiros passos")
        close.clicked.connect(dismiss)
        content.addWidget(close)
        self.status = label("", "muted")
        content.addWidget(self.status)
        tools.pages["clock"].widget().layout().insertWidget(0, self.panel)


class ActionSearch(QDialog):
    def __init__(self, registry, dispatch):
        super().__init__()
        self.registry, self.dispatch = registry, dispatch
        self.setWindowTitle("Buscar ações")
        self.resize(475, 405)
        apply_theme(self)
        layout = QVBoxLayout(self)
        self.query = QLineEdit()
        self.query.setAccessibleName("Buscar ações")
        self.query.setPlaceholderText("Digite o nome de uma ação")
        self.results = QListWidget()
        self.results.setAccessibleName("Ações encontradas")
        self.status = label("", "muted")
        self.run = QPushButton("Executar")
        self.run.setAutoDefault(False)
        for widget in (self.query, self.results, self.status, self.run):
            layout.addWidget(widget)
        self.query.textChanged.connect(self.render)
        self.query.returnPressed.connect(self.execute)
        self.results.itemActivated.connect(self.execute)
        self.results.currentItemChanged.connect(self.update_selection)
        self.run.clicked.connect(self.execute)

    def showEvent(self, event):
        super().showEvent(event)
        self.render()
        self.query.setFocus()
        self.query.selectAll()

    def keyPressEvent(self, event):
        if self.query.hasFocus() and event.key() in {Qt.Key.Key_Up, Qt.Key.Key_Down} and self.results.count():
            self.results.setFocus()
            event.accept()
            return
        super().keyPressEvent(event)

    def render(self):
        self.results.clear()
        for action in self.registry.search(self.query.text()):
            reason = self.registry.reason(action.id)
            text = f"{action.title}\n{action.description}"
            if reason:
                text += f"\nIndisponível · {reason}"
            item = QListWidgetItem(text, self.results)
            item.setData(Qt.ItemDataRole.UserRole, action.id)
        self.results.setCurrentRow(0)
        self.update_selection()

    def update_selection(self):
        item = self.results.currentItem()
        key = item.data(Qt.ItemDataRole.UserRole) if item else None
        reason = self.registry.reason(key) if key else "Nenhuma ação encontrada."
        self.run.setEnabled(reason is None)
        self.status.setText(reason or "")

    def execute(self):
        item = self.results.currentItem()
        if item is None or not self.isVisible():
            return
        key = item.data(Qt.ItemDataRole.UserRole)
        if self.registry.reason(key):
            self.render()
            return
        self.close()
        self.dispatch(key)
