from PySide6.QtCore import QPointF, QRectF, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QWidget

from ..droids.themes import color
from ..pet.positioning import clamp
from .window_layers import present_surface


class ProjectionOverlay(QWidget):
    def __init__(self, pet):
        super().__init__(pet, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.pet = pet
        self.card = QRectF()
        self.eye = QPointF()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        pet.window_layers.register(self)
        pet.geometry_changed.connect(self.reposition)

    @staticmethod
    def render_card(model):
        picture = QPixmap(320, 164 if len(model.lines) > 1 else 76)
        picture.fill(Qt.GlobalColor.transparent)
        painter = QPainter(picture)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        background = QColor(color("hero"))
        background.setAlpha(200)
        painter.setBrush(background)
        painter.setPen(QPen(QColor(color("hologram")), 2))
        painter.drawRoundedRect(QRectF(picture.rect()).adjusted(2, 2, -2, -2), 14, 14)
        painter.setPen(QColor(color("hologram")))
        painter.setFont(QFont("Consolas", 30, QFont.Weight.Bold))
        painter.drawText(QRectF(8, 6, 304, 62), Qt.AlignmentFlag.AlignCenter, model.lines[0])
        if len(model.lines) > 1:
            painter.setFont(QFont("Segoe UI", 18))
            painter.drawText(QRectF(12, 67, 296, 90), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                             model.lines[1])
        painter.end()
        return picture

    def reposition(self):
        pet = self.pet
        if pet.projection_suspended or not pet.projection_kind or not pet.isVisible() or pet.hologram.isNull():
            self.hide()
            return
        screen = QGuiApplication.screenAt(pet.geometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            self.hide()
            return
        area = QRectF(screen.availableGeometry())
        width = min(240, area.width() - 16)
        height = width * pet.hologram.height() / pet.hologram.width()
        above = pet.y() - height - 18
        y = above if above >= area.top() + 8 else pet.geometry().bottom() + 18
        point = clamp(QPointF(pet.geometry().center().x() - width / 2, y), area,
                      QSizeF(width, height))
        card = QRectF(point.x(), point.y(), width, height)
        anchor_x, anchor_y = pet.projection_anchor()
        eye = QPointF(pet.x() + pet.width() * anchor_x, pet.y() + pet.height() * anchor_y)
        bounds = card.united(QRectF(eye.x() - 4, eye.y() - 4, 8, 8)).adjusted(-4, -4, 4, 4).toAlignedRect()
        with present_surface(self):
            self.setGeometry(bounds)
            self.card = card.translated(-bounds.x(), -bounds.y())
            self.eye = eye - QPointF(bounds.topLeft())
            self.show()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        edge_y = self.card.bottom() if self.eye.y() > self.card.center().y() else self.card.top()
        left, right = QPointF(self.card.left() + 12, edge_y), QPointF(self.card.right() - 12, edge_y)
        tint = QColor(color('hologram'))
        gradient = QLinearGradient(self.eye, QPointF(self.card.center().x(), edge_y))
        near = QColor(tint)
        near.setAlpha(85)
        far = QColor(tint)
        far.setAlpha(6)
        gradient.setColorAt(0, near)
        gradient.setColorAt(1, far)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(gradient)
        p.drawPolygon(QPolygonF([self.eye, left, right]))
        tint.setAlpha(110)
        p.setPen(QPen(tint, 1))
        p.drawLine(self.eye, left)
        p.drawLine(self.eye, right)
        p.drawLine(self.eye, QPointF(self.card.center().x(), edge_y))
        p.drawPixmap(self.card.toRect(), self.pet.hologram)
        tint.setAlpha(25)
        p.setPen(QPen(tint, 1))
        for y in range(round(self.card.top()) + 4, round(self.card.bottom()) - 2, 4):
            p.drawLine(QPointF(self.card.left() + 5, y), QPointF(self.card.right() - 5, y))
