from PySide6.QtCore import QSize, Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QVBoxLayout, QWidget

from ..features.minigames import GAMES
from .theme import card, icon, label


class MinigamesPage(QWidget):
    game_requested = Signal(str)

    def __init__(self, games=GAMES):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.addWidget(label("Escolha sua próxima aventura", "eyebrow"))
        for game in games:
            panel, content = card()
            row = QHBoxLayout()
            art = QPushButton()
            art.setIcon(icon(game.glyph))
            art.setIconSize(QSize(42, 42))
            art.setFixedSize(70, 70)
            art.setAccessibleName("Abrir " + game.name)
            art.clicked.connect(lambda checked=False, key=game.id: self.game_requested.emit(key))
            row.addWidget(art)
            text = QVBoxLayout()
            text.addWidget(label(game.name, "heading"))
            description = label(game.description, "muted")
            description.setWordWrap(True)
            text.addWidget(description)
            row.addLayout(text, 1)
            content.addLayout(row)
            button = QPushButton("Jogar no navegador  ↗")
            button.setProperty("role", "primary")
            button.clicked.connect(lambda checked=False, key=game.id: self.game_requested.emit(key))
            content.addWidget(button)
            layout.addWidget(panel)
        note = label("Os jogos abrem no navegador padrão. É necessária conexão com a internet.", "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
