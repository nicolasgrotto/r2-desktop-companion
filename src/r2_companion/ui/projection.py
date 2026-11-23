from PySide6.QtCore import QPointF, QRectF, QSize, QSizeF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QLinearGradient, QPainter, QPen, QPixmap, QPolygonF, QRegion
from PySide6.QtWidgets import QWidget

from ..droids.themes import theme_manager
from ..pet.positioning import clamp
from .window_layers import present_surface


def card_size(model, dip):
    body = sum(line_height(model, index) for index, _ in enumerate(model.lines))
    return QSizeF(dip(248), dip(34 + body + (14 if model.progress is not None else 0)))


def line_height(model, index):
    return 33 if index == 0 and model.kind in {"clock", "date", "timer", "focus"} else 20


def outside(region, obstacle, gap):
    edge = obstacle.adjusted(-gap, -gap, gap, gap).intersected(region)
    if edge.isEmpty():
        return [region]
    strips = [
        region.adjusted(0, 0, 0, edge.top() - region.bottom()),
        region.adjusted(0, edge.bottom() - region.top(), 0, 0),
        region.adjusted(edge.right() - region.left(), 0, 0, 0),
        region.adjusted(0, 0, edge.left() - region.right(), 0),
    ]
    return [strip for strip in strips if not strip.isEmpty()]


def place_card(area, pet, preferred, avoid=None):
    """Place a DIP-sized card outside the mascot and inside the monitor work area."""
    if area.isEmpty():
        return QRectF()
    gap = 8
    work = area.adjusted(gap, gap, -gap, -gap) if min(area.width(), area.height()) > 2 * gap else area
    regions = outside(work, pet, gap)
    if avoid is not None:
        regions = [free for region in regions for free in outside(region, avoid, gap)]
        if not regions:
            return QRectF()
    region = next((region for region in regions
                   if region.width() >= preferred.width() and region.height() >= preferred.height()), None)
    if region is None:
        region = max(regions, key=lambda r: min(r.width(), preferred.width()) * min(r.height(), preferred.height()),
                     default=work)
    size = QSizeF(min(region.width(), preferred.width()), min(region.height(), preferred.height()))
    point = clamp(pet.center() - QPointF(size.width() / 2, size.height() / 2), region, size)
    return QRectF(point, size)


def render_card(model, size, dpr, colors, dip):
    physical = QSize(max(1, round(size.width() * dpr)), max(1, round(size.height() * dpr)))
    picture = QPixmap(physical)
    picture.setDevicePixelRatio(dpr)
    picture.fill(Qt.GlobalColor.transparent)
    p = QPainter(picture)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    rect = QRectF(0, 0, size.width(), size.height())
    background = QColor(colors["hero"])
    background.setAlpha(235)
    accent = QColor(colors["hologram"])
    p.setBrush(background)
    p.setPen(QPen(accent, 1))
    p.drawRoundedRect(rect.adjusted(0.5, 0.5, -0.5, -0.5), dip(10), dip(10))
    pad = min(dip(12), rect.width() / 4)
    content = rect.adjusted(pad, dip(6), -pad, -dip(6))
    p.setClipRect(content)
    p.setPen(QColor(colors["hero_text"]))
    y = content.y()
    header_height = dip(20)
    rows = [(model.title, header_height, dip(12), "Segoe UI", QFont.Weight.DemiBold)]
    for index, line in enumerate(model.lines):
        height = line_height(model, index)
        font = ("Consolas", 25, QFont.Weight.Bold) if height == 33 else ("Segoe UI", 13, QFont.Weight.Normal)
        family, pixels, weight = font
        rows.append((line, dip(height), dip(pixels), family, weight))
    for line, height, pixels, family, weight in rows:
        if y + height > content.bottom():
            break
        font = QFont(family)
        font.setPixelSize(max(1, pixels))
        font.setWeight(weight)
        p.setFont(font)
        text = p.fontMetrics().elidedText(" ".join(line.splitlines()), Qt.TextElideMode.ElideRight,
                                          max(0, int(content.width())))
        p.drawText(QRectF(content.x(), y, content.width(), height), Qt.AlignmentFlag.AlignVCenter, text)
        y += height
    if model.progress is not None and y + dip(8) <= content.bottom():
        track = QRectF(content.x(), y + dip(4), content.width(), dip(4))
        p.fillRect(track, QColor(colors["border"]))
        track.setWidth(track.width() * min(1, max(0, model.progress)))
        p.fillRect(track, accent)
    p.end()
    return picture


def beam_edge(card, eye):
    if card.top() <= eye.y() <= card.bottom():
        x = card.left() if eye.x() < card.center().x() else card.right()
        inset = min(12, card.height() / 3)
        return QPointF(x, card.top() + inset), QPointF(x, card.bottom() - inset)
    y = card.top() if eye.y() < card.center().y() else card.bottom()
    inset = min(12, card.width() / 3)
    return QPointF(card.left() + inset, y), QPointF(card.right() - inset, y)


class ProjectionOverlay(QWidget):
    def __init__(self, pet):
        super().__init__(pet, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                         | Qt.WindowType.WindowDoesNotAcceptFocus
                         | Qt.WindowType.WindowTransparentForInput)
        self.pet = pet
        self.card = QRectF()
        self.eye = QPointF()
        self.model = None
        self.picture = QPixmap()
        self._rendered = None
        self.wheel = None
        self._wheel_clip = QRectF()
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        pet.window_layers.register(self)
        pet.geometry_changed.connect(self.reposition)

    def set_model(self, model):
        self.model = model
        if model is None:
            self._rendered = None
            self.picture = QPixmap()
        self.reposition()

    def reposition(self):
        pet = self.pet
        if self.model is None or not pet.isVisible():
            self.hide()
            return
        screen = QGuiApplication.screenAt(pet.geometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            self.hide()
            return
        area = QRectF(screen.availableGeometry())
        manager = theme_manager()
        avoid = QRectF(self.wheel.geometry()) if self.wheel is not None and self.wheel.isVisible() else None
        card = place_card(area, QRectF(pet.geometry()), card_size(self.model, manager.dip), avoid)
        if card.isEmpty():
            self.hide()
            return
        dpr = screen.devicePixelRatio()
        render_key = (self.model, card.size(), dpr, manager.ui_scale, manager.active)
        content_changed = render_key != self._rendered
        if content_changed:
            self.picture = render_card(self.model, card.size(), dpr, manager.active.colors, manager.dip)
            self._rendered = render_key
        anchor_x, anchor_y = pet.projection_anchor()
        eye = QPointF(pet.x() + pet.width() * anchor_x, pet.y() + pet.height() * anchor_y)
        beam = QRectF(eye.x() - 4, eye.y() - 4, 8, 8)
        bounds = card.united(beam).adjusted(-4, -4, 4, 4).intersected(area).toAlignedRect()
        card = card.translated(-bounds.x(), -bounds.y())
        eye -= QPointF(bounds.topLeft())
        wheel_clip = avoid.translated(-bounds.x(), -bounds.y()) if avoid is not None else QRectF()
        geometry_changed = (self.geometry() != bounds or self.card != card or self.eye != eye
                            or self._wheel_clip != wheel_clip)
        if geometry_changed or not self.isVisible():
            self.card, self.eye = card, eye
            self._wheel_clip = wheel_clip
            with present_surface(self):
                if self.geometry() != bounds:
                    self.setGeometry(bounds)
                if not self.isVisible():
                    self.show()
        if geometry_changed or content_changed:
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if not self._wheel_clip.isEmpty():
            p.setClipRegion(QRegion(self.rect()) - QRegion(self._wheel_clip.toAlignedRect()))
        left, right = beam_edge(self.card, self.eye)
        middle = (left + right) / 2
        tint = QColor(theme_manager().active.colors["hologram"])
        gradient = QLinearGradient(self.eye, middle)
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
        p.drawLine(self.eye, middle)
        p.drawPixmap(self.card.toRect(), self.picture)
        tint.setAlpha(25)
        p.setPen(QPen(tint, 1))
        if self.card.width() > 12:
            for y in range(round(self.card.top()) + 4, round(self.card.bottom()) - 2, 4):
                p.drawLine(QPointF(self.card.left() + 5, y), QPointF(self.card.right() - 5, y))
