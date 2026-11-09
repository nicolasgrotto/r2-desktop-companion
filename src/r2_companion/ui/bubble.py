from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QFrame, QVBoxLayout

from ..pet.positioning import clamp
from .theme import label


class Bubble(QFrame):
    def __init__(self):
        super().__init__()
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowDoesNotAcceptFocus | Qt.WindowType.WindowTransparentForInput)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setObjectName("speech")
        self.setStyleSheet("""
            QFrame#speech { background: #102c48; border: 1px solid #62bfea; border-radius: 13px; }
            QLabel { background: transparent; border: none; color: #f0f8ff; font-family: 'Segoe UI'; font-size: 13px; }
            QLabel[role='eyebrow'] { color: #6bcdf5; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
        """)
        self.setFixedWidth(280)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 14)
        layout.setSpacing(7)
        layout.addWidget(label("● R2 / TRANSMISSÃO", "eyebrow"))
        self.message = label("")
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.anchor = None
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.hide)

    def present(self, message: str, pet):
        if self.anchor is not pet:
            if self.anchor is not None:
                self.anchor.geometry_changed.disconnect(self.reposition)
            self.anchor = pet
            pet.geometry_changed.connect(self.reposition)
        self.message.setText(message[:240])
        self.adjustSize()
        self.reposition(force=True)
        self.show()
        self.timer.start(4500)

    def reposition(self, force=False):
        if self.anchor is None or (not force and not self.isVisible()):
            return
        pet = self.anchor
        screen = QGuiApplication.screenAt(pet.geometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = QRectF(screen.availableGeometry())
        y = pet.y() - self.height() - 12
        if y < area.top() + 8:
            y = pet.y() + pet.height() + 12
        point = clamp(QPointF(pet.x() + (pet.width() - self.width()) / 2, y), area, QSizeF(self.size()))
        self.move(round(point.x()), round(point.y()))

    def stop(self):
        self.timer.stop()
        self.hide()
