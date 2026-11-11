import math

from PySide6.QtCore import QElapsedTimer, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QGuiApplication, QPainter, QRadialGradient
from PySide6.QtWidgets import QWidget


class SteamOverlay(QWidget):
    def __init__(self, pet):
        super().__init__(pet, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.pet = pet
        self.active = False
        self.elapsed = QElapsedTimer()
        self.timer = QTimer(self)
        self.timer.setInterval(50)
        self.timer.timeout.connect(self.update)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        pet.geometry_changed.connect(self.reposition)

    def set_active(self, active):
        if active and not self.active:
            self.elapsed.start()
        self.active = active
        self.reposition()

    def reposition(self):
        if not self.active or not self.pet.isVisible():
            self.timer.stop()
            self.hide()
            return
        pet = self.pet
        screen = QGuiApplication.screenAt(pet.geometry().center()) or QGuiApplication.primaryScreen()
        top = pet.y() - 70
        if screen is not None:
            top = max(top, screen.availableGeometry().top())
        self.setGeometry(pet.x(), top, pet.width(), pet.y() + round(pet.height() * 0.28) - top)
        self.timer.start()
        self.show()
        self.update()

    def paintEvent(self, event):
        if not self.active or not self.elapsed.isValid():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        seconds = self.elapsed.elapsed() / 1000
        for index in range(9):
            phase = (seconds / 1.8 + index / 9) % 1
            radius = 6 + phase * 16
            x = self.width() * (0.38 if index % 2 else 0.62) + math.sin(phase * 5 + index) * 13
            y = self.height() - 8 - phase * (self.height() - 12)
            center = QPointF(x, y)
            gradient = QRadialGradient(center, radius)
            gradient.setColorAt(0, QColor(205, 215, 224, round(155 * (1 - phase))))
            gradient.setColorAt(1, QColor(170, 185, 199, 0))
            painter.setBrush(gradient)
            painter.drawEllipse(QRectF(x - radius, y - radius, radius * 2, radius * 2))
