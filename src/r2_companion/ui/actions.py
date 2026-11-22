from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout

from .theme import apply_theme, label


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
