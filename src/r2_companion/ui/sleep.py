import math

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter

from ..droids.themes import color
from .steam import SteamOverlay


class SleepOverlay(SteamOverlay):
    def paintEvent(self, event):
        if not self.active or not self.elapsed.isValid():
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        seconds = self.elapsed.elapsed() / 1000
        for index in range(3):
            phase = (seconds / 2.8 + index / 3) % 1
            tint = QColor(color("hologram", self.pet))
            tint.setAlpha(round(220 * math.sin(math.pi * phase)))
            painter.setPen(tint)
            painter.setFont(QFont("Segoe UI", round(10 + phase * 12), QFont.Weight.Bold))
            x = self.width() * 0.58 + math.sin(phase * 3 + index) * 12
            y = (1 - phase) * max(1, self.height() - 28)
            painter.drawText(QRectF(x - 18, y, 38, 28), Qt.AlignmentFlag.AlignCenter, "Z")
