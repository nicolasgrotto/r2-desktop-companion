from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLineEdit, QListWidget, QListWidgetItem,
                              QPushButton, QStyle, QStyledItemDelegate, QVBoxLayout)

from .theme import apply_theme, header, icon, label
from ..droids.themes import color, styled

KINDS = {"app": ("Aplicativo", "apps"), "folder": ("Pasta", "folder"),
         "file": ("Arquivo", "file"), "alias": ("Atalho", "apps")}


class TargetDelegate(QStyledItemDelegate):
    def sizeHint(self, option, index):
        return QSize(240, 78)

    def paint(self, painter: QPainter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        rect = option.rect.adjusted(1, 2, -1, -3)
        painter.setBrush(QColor(color("selected" if selected else "panel")))
        painter.setPen(QColor(color("focus" if selected else "border")))
        painter.drawRoundedRect(rect, 11, 11)
        details = index.data(Qt.ItemDataRole.UserRole + 1) or {}
        kind, glyph = KINDS.get(details.get("kind"), ("Destino", "file"))
        avatar = QRect(rect.x() + 13, rect.y() + 15, 40, 40)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(color("selected")))
        painter.drawRoundedRect(avatar, 10, 10)
        icon(glyph).paint(painter, avatar.adjusted(8, 8, -8, -8))
        x, width = rect.x() + 66, max(20, rect.width() - 84)
        font = QFont("Segoe UI")
        font.setPixelSize(14)
        font.setWeight(QFont.Weight.DemiBold)
        painter.setFont(font)
        painter.setPen(QColor(color("text")))
        title = details.get("label", index.data(Qt.ItemDataRole.DisplayRole) or "")
        painter.drawText(QRect(x, rect.y() + 12, width, 24), Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(title, Qt.TextElideMode.ElideRight, width))
        font.setPixelSize(11)
        font.setWeight(QFont.Weight.Normal)
        painter.setFont(font)
        painter.setPen(QColor(color("muted")))
        description = kind + " · " + details.get("path", "")
        painter.drawText(QRect(x, rect.y() + 37, width, 22), Qt.AlignmentFlag.AlignVCenter,
                         painter.fontMetrics().elidedText(description, Qt.TextElideMode.ElideMiddle, width))
        painter.restore()


def target_item(target, *, label_override=None, alias=False):
    title = label_override or target.label
    item = QListWidgetItem(title + "\n" + target.path)
    item.setData(Qt.ItemDataRole.UserRole, target.id)
    item.setData(Qt.ItemDataRole.UserRole + 1, {"label": title, "kind": "alias" if alias else target.kind,
                                             "path": target.path})
    item.setToolTip(title + "\n" + target.path)
    return item


def filter_targets(widget, query: str) -> int:
    query = query.casefold().strip()
    visible = 0
    for row in range(widget.count()):
        item = widget.item(row)
        match = query in item.text().casefold()
        item.setHidden(not match)
        visible += match
    return visible


class LaunchpadDialog(QDialog):
    target_requested = Signal(object)
    configure_requested = Signal()

    def __init__(self, mode: str):
        super().__init__()
        self.mode = mode
        self.entries = {}
        self.resize(620, 570)
        self.setWindowTitle(("Aplicativos" if mode == "apps" else "Meus locais") + " · R2 Companion")
        apply_theme(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 22)
        layout.setSpacing(16)
        layout.addWidget(header("Seus aplicativos" if mode == "apps" else "Seus lugares favoritos",
                                "Um clique para abrir o que faz parte do seu dia."))
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar por nome ou caminho…")
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.filter)
        layout.addWidget(self.search)
        self.list = QListWidget()
        self.list.setItemDelegate(TargetDelegate(self.list))
        self.list.itemActivated.connect(lambda item: self.open_selected())
        self.list.itemSelectionChanged.connect(self.update_selection)
        layout.addWidget(self.list, 1)
        self.empty = label("")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        styled(self.empty, "color: #718ba1; padding: 28px; font-size: 15px;")
        layout.addWidget(self.empty, 1)
        row = QHBoxLayout()
        add = QPushButton("Gerenciar favoritos")
        add.setIcon(icon("settings"))
        add.clicked.connect(self.configure)
        row.addWidget(add)
        row.addStretch()
        self.open_button = QPushButton("Abrir selecionado")
        self.open_button.setProperty("role", "primary")
        self.open_button.clicked.connect(self.open_selected)
        row.addWidget(self.open_button)
        layout.addLayout(row)

    def set_settings(self, settings):
        self.list.clear()
        targets = settings.applications if self.mode == "apps" else settings.locations
        self.entries = {target.id: target for target in targets}
        for target in targets:
            self.list.addItem(target_item(target))
        if self.mode == "locations":
            all_targets = {target.id: target for target in settings.applications + settings.locations}
            for alias in settings.shortcuts:
                target = all_targets.get(alias.target_id)
                if target is not None:
                    self.entries[alias.id] = target
                    item = target_item(target, label_override=alias.label, alias=True)
                    item.setData(Qt.ItemDataRole.UserRole, alias.id)
                    self.list.addItem(item)
        self.filter()
        self.update_selection()

    def filter(self, *_):
        count = filter_targets(self.list, self.search.text())
        self.empty.setVisible(count == 0)
        self.list.setVisible(count != 0)
        if self.list.count() == 0:
            self.empty.setText("Seu painel está pronto para receber favoritos.\nUse Gerenciar favoritos para adicionar o primeiro.")
        else:
            self.empty.setText("Nenhum resultado para essa busca.\nTente outro nome ou parte do caminho.")
        current = self.list.currentItem()
        if current is not None and current.isHidden():
            self.list.setCurrentItem(None)
        self.update_selection()

    def update_selection(self):
        if hasattr(self, "open_button"):
            item = self.list.currentItem()
            self.open_button.setEnabled(item is not None and not item.isHidden())

    def open_selected(self):
        item = self.list.currentItem()
        if item is not None and not item.isHidden():
            target = self.entries.get(item.data(Qt.ItemDataRole.UserRole))
            if target is not None:
                self.target_requested.emit(target)

    def configure(self):
        self.hide()
        self.configure_requested.emit()
