from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QLineEdit, QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

from ..droids.themes import theme_manager
from ..features.minigames import (GAMES, MAX_DESCRIPTION, MAX_NAME, MAX_URL, PRESET_ICONS,
                                  load_thumbnail, new_entry, personal_games, save_game, thumbnail_image)
from .theme import ActionRow, apply_theme, card, configure_form, fit_dialog, form_row, icon, label
from ..core.language import tr


def game_icon(glyph, thumbnail):
    image = thumbnail_image(thumbnail)
    if not image.isNull():
        return QIcon(QPixmap.fromImage(image))
    return icon(glyph if not thumbnail and glyph in PRESET_ICONS else "play")


class GameEditor(QDialog):
    def __init__(self, parent, store, game=None):
        super().__init__(parent)
        self.store, self.game = store, game
        self.thumbnail = game.thumbnail if game else ""
        self.setWindowTitle(tr("Editar minigame") if game else tr("Adicionar minigame"))
        layout = QVBoxLayout(self)
        form = QFormLayout()
        configure_form(form)
        self.name = QLineEdit(game.name if game else "")
        self.name.setMaxLength(MAX_NAME)
        self.url = QLineEdit(game.url if game else "")
        self.url.setMaxLength(MAX_URL)
        self.url.setPlaceholderText("https://")
        self.description = QLineEdit(game.description if game else "")
        self.description.setMaxLength(MAX_DESCRIPTION)
        for title, control in ((tr("&Nome"), self.name), (tr("&Endereço HTTPS"), self.url), (tr("&Descrição opcional"), self.description)):
            form_row(form, title, control)

        self.icons = QComboBox()
        for glyph, title in PRESET_ICONS.items():
            self.icons.addItem(tr(title), glyph)
        self.icons.setCurrentIndex(max(0, self.icons.findData(game.glyph if game else "play")))
        self.icons.activated.connect(self.use_preset)
        form_row(form, tr("&Ícone predefinido"), self.icons)
        layout.addLayout(form)
        row = ActionRow()
        self.preview = label("")
        self.preview.setAccessibleName(tr("Prévia do ícone"))
        row.addWidget(self.preview)
        image = QPushButton(tr("Escolher imagem PNG ou JPEG…"))
        image.clicked.connect(self.choose_image)
        row.addWidget(image, 1)
        preset = QPushButton(tr("Usar ícone predefinido"))
        preset.clicked.connect(self.use_preset)
        row.addWidget(preset, 1)
        layout.addWidget(row)
        self.feedback = label("", "muted")
        layout.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Save).setText(tr("Salvar"))
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancelar"))
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.buttons = buttons
        apply_theme(self)
        fit_dialog(self, parent)
        self.render_icon()
        self.name.setFocus()

    def render_icon(self):
        side = theme_manager().dip(52)
        self.preview.setPixmap(game_icon(self.icons.currentData(), self.thumbnail).pixmap(side, side))
        title = tr("Imagem própria") if not thumbnail_image(self.thumbnail).isNull() else self.icons.currentText()
        self.preview.setAccessibleDescription(title)

    def use_preset(self):
        self.thumbnail = ""
        self.render_icon()

    def choose_image(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Escolher ícone"), "", tr("Imagens PNG e JPEG (*.png *.jpg *.jpeg)"))
        if path:
            try:
                self.thumbnail = load_thumbnail(path)
            except ValueError as error:
                self.feedback.setText(str(error))
                return
            self.feedback.clear()
            self.render_icon()

    def save(self):
        try:
            entry = new_entry(self.name.text(), self.url.text(), self.description.text(),
                              self.icons.currentData(), self.thumbnail)
            if save_game(self.store, self.game, entry):
                self.accept()
                return
        except ValueError as error:
            self.feedback.setText(str(error))
            return
        self.feedback.setText(tr("Não foi possível salvar. O catálogo anterior foi preservado."))


class MinigamesPage(QScrollArea):
    game_requested = Signal(str)

    def __init__(self, games=GAMES, *, store=None):
        super().__init__()
        self.store = store
        self.builtin = games
        self.personal = ()
        self.read_only = None
        self.setProperty("characterLiteral", True)
        self.setWidgetResizable(True)
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 16, 0, 0)
        if store is not None:
            self.add_game = QPushButton(tr("Adicionar minigame"))
            self.add_game.clicked.connect(lambda: self.edit(None))
            layout.addWidget(self.add_game)
            store.changed.connect(self.refresh)
            store.warning.connect(self.show_warning)
        self.feedback = label("", "muted")
        self.feedback.hide()
        layout.addWidget(self.feedback)
        self.cards = QVBoxLayout()
        layout.addLayout(self.cards)
        layout.addWidget(label(tr("Os jogos abrem no navegador padrão."), "muted"))
        layout.addStretch()
        self.refresh(force=True)
        theme_manager().scale_changed.connect(self.rescale)

    def rescale(self, *_):
        self.refresh(force=True)

    @property
    def games(self):
        return (*self.builtin, *self.personal)

    def show_warning(self, message):
        self.feedback.setText(message)
        self.feedback.show()
        self.refresh()

    def refresh(self, document=None, *, force=False):
        personal = personal_games(document or self.store.data) if self.store is not None else ()
        read_only = self.store is not None and self.store.read_only
        if not force and (personal, read_only) == (self.personal, self.read_only):
            return
        self.personal, self.read_only = personal, read_only
        if self.store is not None:
            self.add_game.setEnabled(not read_only)
            if read_only:
                self.feedback.setText(tr("Catálogo em modo somente leitura."))
                self.feedback.show()
        while self.cards.count():
            widget = self.cards.takeAt(0).widget()
            widget.hide()
            widget.deleteLater()
        for game in self.games:
            panel, content = card()
            panel.setProperty("characterLiteral", True)
            title = label(game.name, "heading")
            side = theme_manager().dip(44)
            preview = QPushButton()
            preview.setIcon(game_icon(game.glyph, game.thumbnail))
            preview.setIconSize(QSize(side, side))
            preview.setFixedSize(side + theme_manager().dip(16), side + theme_manager().dip(16))
            preview.setAccessibleName(tr("Abrir ") + game.name)
            preview.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
            preview.clicked.connect(lambda checked=False, key=game.id: self.game_requested.emit(key))
            header = ActionRow()
            header.addWidget(preview)
            header.addWidget(title, 1)
            content.addWidget(header)
            if game.description:
                description = tr(game.description) if game in self.builtin else game.description
                content.addWidget(label(description, "muted"))
            row = ActionRow()
            play = QPushButton(tr("Jogar no navegador"))
            play.setAccessibleName(tr("Jogar ") + game.name + tr(" no navegador"))
            play.setProperty("role", "primary")
            play.clicked.connect(lambda checked=False, key=game.id: self.game_requested.emit(key))
            row.addWidget(play)
            if game in self.personal:
                edit, remove = QPushButton(tr("Editar")), QPushButton(tr("Remover"))
                edit.setAccessibleName(tr("Editar ") + game.name)
                remove.setAccessibleName(tr("Remover ") + game.name)
                edit.clicked.connect(lambda checked=False, game=game: self.edit(game))
                remove.clicked.connect(lambda checked=False, game=game: self.remove(game))
                for button in (edit, remove):
                    button.setEnabled(not read_only)
                    row.addWidget(button)
            content.addWidget(row)
            self.cards.addWidget(panel)

    def edit(self, game):
        self.feedback.hide()
        dialog = GameEditor(self, self.store, game)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.add_game.setFocus(Qt.FocusReason.OtherFocusReason)
        theme_manager().unregister_tree(dialog)
        dialog.deleteLater()

    def remove(self, game):
        self.feedback.hide()
        buttons = QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        if QMessageBox.question(self, tr("Remover minigame"), tr("Remover este minigame do catálogo pessoal?"),
                                buttons, QMessageBox.StandardButton.Cancel) == QMessageBox.StandardButton.Yes:
            try:
                if save_game(self.store, game, None):
                    self.add_game.setFocus(Qt.FocusReason.OtherFocusReason)
            except ValueError as error:
                self.show_warning(str(error))
