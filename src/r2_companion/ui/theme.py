from functools import lru_cache
import math

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QBoxLayout, QFormLayout, QFrame, QHBoxLayout, QLabel, QLayout,
                               QScrollArea, QVBoxLayout, QWidget)
from ..droids.themes import COLOR_TOKENS, color as theme_color, color, styled, theme_manager

NAVY = "#102c48"
BLUE = "#216eea"
CYAN = "#47c8f5"
MUTED = "#647b91"

STYLE = """
QDialog { background: #edf3f9; color: #14314c; }
QWidget { font-family: 'Segoe UI'; font-size: 13px; }
QLabel { color: #14314c; background: transparent; }
QLabel[role='eyebrow'] { color: #51728e; font-size: 10px; font-weight: 700; letter-spacing: 2px; }
QLabel[role='heading'] { color: @text; font-size: 25px; font-weight: 700; }
QLabel[role='muted'] { color: #647b91; }
QLabel[role='error'] { color: #b94343; }
QFrame[role='card'] { background: #ffffff; border: 1px solid #d8e5f1; border-radius: 16px; }
QFrame[role='hero'] { background: #102c48; border: 1px solid #1c486b; border-radius: 18px; }
QFrame[role='hero'] QLabel { color: #f5faff; }
QFrame[role='hero'] QLabel[role='muted'] { color: #a8c5df; }
QPushButton { background: #ffffff; color: #244b6b; border: 1px solid #ccddea;
    border-radius: 9px; padding: 10px 16px; font-weight: 600; min-height: 18px; }
QPushButton:hover { background: #e8f3ff; border-color: #70b0ee; }
QPushButton:pressed { background: #d3e8ff; }
QPushButton:disabled { color: #8ba0b3; background: #f2f5f8; border-color: #e0e7ee; }
QPushButton[role='primary'] { background: #216eea; color: white; border-color: #216eea; }
QPushButton[role='primary']:hover { background: #175dcc; }
QPushButton[role='primary']:disabled { background: #b3cced; border-color: #b3cced; }
QPushButton[role='danger'] { color: #b94343; }
QPushButton[role='preset'] { padding: 6px 10px; min-height: 14px; }
QPushButton[compact='true'] { padding: 8px 8px; }
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTimeEdit { background: white; color: #193b57; border: 1px solid #caddea;
    border-radius: 8px; padding: 9px 12px; min-height: 20px; selection-background-color: #216eea; }
QComboBox::drop-down { border: none; width: 26px; }
QComboBox QAbstractItemView { background: white; color: #193b57; selection-background-color: #e2efff; selection-color: #14314c; }
QCheckBox { color: #214763; spacing: 10px; padding: 5px 1px; border: 2px solid transparent; }
QCheckBox::indicator { width: 18px; height: 18px; border: 1px solid #afc7dc; border-radius: 5px; background: white; }
QCheckBox::indicator:checked { background: #216eea; border: 4px solid #a6d8ff; }
QCheckBox:disabled { color: #91a3b4; }
QTabWidget::pane { border: none; background: transparent; }
QTabBar::tab { background: transparent; color: #617c94; padding: 12px 18px; margin-right: 5px; border-bottom: 3px solid transparent; font-weight: 600; }
QTabBar::tab:selected { color: #216eea; border-bottom-color: #216eea; }
QTabBar::tab:hover { color: #216eea; background: #e5eef7; }
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 8px; margin: 4px 0; }
QScrollBar::handle:vertical { background: #b9cede; border-radius: 4px; min-height: 28px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
QListWidget { background: transparent; border: 2px solid transparent; }
QListWidget::item { border: none; margin: 4px 0; padding: 0; }
QProgressBar { background: #e2edf6; border: none; border-radius: 5px; height: 10px; text-align: center; }
QProgressBar::chunk { background: #3385ee; border-radius: 5px; }
QToolTip { background: #102c48; color: white; border: 1px solid #39739c; padding: 8px; }
QMenu { background: #102c48; color: #eaf5ff; border: 1px solid #37617e; border-radius: 8px; padding: 8px; }
QMenu::item { padding: 8px 32px 8px 16px; border-radius: 5px; }
QMenu::item:selected { background: @primary; color: @button_text; }
QMenu::item:disabled { color: #7796b1; }
QMenu::separator { background: #2d4b66; height: 1px; margin: 6px 10px; }
QPushButton[role='primary'] { color: @button_text; }
QPlainTextEdit, QTextEdit, QListWidget { background: @panel; color: @text; }
QPlainTextEdit, QTextEdit { border: 1px solid @border; }
QListWidget::item { padding: 9px; }
QListWidget::item:selected { background: @selected; color: @text; }
QPushButton:focus, QCheckBox:focus, QListWidget:focus, QPlainTextEdit:focus, QTextEdit:focus,
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTimeEdit:focus {
    border: 2px solid @focus;
}
QPushButton[role='primary']:focus { border: 2px solid @button_text; }
QTabBar::tab:selected:focus { border-bottom: 3px solid @focus; background: @selected; color: @text; }
QFrame#speech { background: @notification; }
QLabel[role='brand'] { background: @hero; color: @accent; border-radius: 12px; font-size: 25px; font-weight: 800; }
"""


def label(text: str, role: str = "", parent=None) -> QLabel:
    widget = QLabel(text, parent)
    widget.setTextFormat(Qt.TextFormat.PlainText)
    widget.setWordWrap(True)
    if role:
        widget.setProperty("role", role)
    return widget


def scrollable(content):
    area = QScrollArea()
    area.setWidgetResizable(True)
    area.setWidget(content)
    return area


def configure_form(form):
    form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
    form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)


def form_row(form, title, control):
    caption = label(title)
    caption.setBuddy(control)
    control.setAccessibleName(title.replace("&", ""))
    form.addRow(caption, control)


class ActionRow(QWidget):
    """Stack related controls when their preferred widths exceed the viewport."""

    def __init__(self):
        super().__init__()
        self.row = QBoxLayout(QBoxLayout.Direction.LeftToRight, self)
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)

    def addWidget(self, widget, stretch=0):
        self.row.addWidget(widget, stretch)

    def minimumSizeHint(self):
        size = super().minimumSizeHint()
        widths = [self.row.itemAt(i).minimumSize().width() for i in range(self.row.count())]
        size.setWidth(max(widths, default=0))
        return size

    def reflow(self):
        items = [self.row.itemAt(i) for i in range(self.row.count())]
        total = sum(item.minimumSize().width() for item in items if not item.isEmpty())
        total += max(0, sum(not item.isEmpty() for item in items) - 1) * self.row.spacing()
        direction = QBoxLayout.Direction.TopToBottom if total > self.width() else QBoxLayout.Direction.LeftToRight
        if self.row.direction() != direction:
            self.row.setDirection(direction)
            self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.reflow()

    def event(self, event):
        if event.type() == QEvent.Type.LayoutRequest:
            self.reflow()
        return super().event(event)


def card(role="card") -> tuple[QFrame, QVBoxLayout]:
    widget = QFrame()
    widget.setProperty("role", role)
    layout = QVBoxLayout(widget)
    layout.setContentsMargins(22, 20, 22, 20)
    layout.setSpacing(12)
    return widget, layout


def header(title: str, subtitle: str) -> QWidget:
    widget = QWidget()
    layout = QHBoxLayout(widget)
    layout.setContentsMargins(0, 0, 0, 10)
    brand = QLabel("R2")
    brand.setAlignment(Qt.AlignmentFlag.AlignCenter)
    brand.setProperty("role", "brand")
    styled(brand, "min-width: 34px; min-height: 54px; padding: 0 10px;")
    layout.addWidget(brand)
    text = QVBoxLayout()
    text.setSpacing(3)
    text.addWidget(label("COMPANION / CONTROLE LOCAL", "eyebrow"))
    text.addWidget(label(title, "heading"))
    subtitle_label = label(subtitle, "muted")
    subtitle_label.setWordWrap(True)
    text.addWidget(subtitle_label)
    layout.addLayout(text, 1)
    return widget


def apply_theme(widget):
    styled(widget, STYLE)


def fit_dialog(widget, anchor):
    screen = QGuiApplication.screenAt(anchor.geometry().center()) or QGuiApplication.primaryScreen()
    if screen is None:
        return
    area = screen.availableGeometry()
    decoration = widget.frameSize() - widget.size()
    # Before the window is shown Qt may not know the native title bar and borders.
    frame_width = max(16, decoration.width())
    frame_height = max(40, decoration.height())
    widget.resize(min(widget.width(), max(1, area.width() - frame_width - 16)),
                  min(widget.height(), max(1, area.height() - frame_height - 16)))
    x = area.x() + (area.width() - widget.width() - frame_width) // 2
    y = area.y() + (area.height() - widget.height() - frame_height) // 2
    widget.move(x, y)


ICON_SPECS = {}


def icon(name: str, color=None, *, widget=None) -> QIcon:
    original = color
    color = theme_color(COLOR_TOKENS.get(color, "primary"), widget) if color is None or color in COLOR_TOKENS else color
    result = _colored_icon(name, color)
    ICON_SPECS[result.cacheKey()] = (name, original)
    if len(ICON_SPECS) > 512:
        ICON_SPECS.pop(next(iter(ICON_SPECS)))
    return result


def refresh_icons(widget):
    from PySide6.QtWidgets import QAbstractButton, QTabWidget
    if isinstance(widget, QAbstractButton):
        spec = ICON_SPECS.get(widget.icon().cacheKey())
        if spec:
            widget.setIcon(icon(*spec, widget=widget))
    if isinstance(widget, QTabWidget):
        for i in range(widget.count()):
            spec = ICON_SPECS.get(widget.tabIcon(i).cacheKey())
            if spec:
                widget.setTabIcon(i, icon(*spec, widget=widget))
    for action in widget.actions():
        spec = ICON_SPECS.get(action.icon().cacheKey())
        if spec:
            action.setIcon(icon(*spec, widget=widget))


@lru_cache(maxsize=64)
def _colored_icon(name: str, color: str) -> QIcon:
    result = QIcon()
    for side in (20, 24, 32, 48):
        pixmap = QPixmap(side, side)
        pixmap.fill(Qt.GlobalColor.transparent)
        p = QPainter(pixmap)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(side / 32, side / 32)
        p.setPen(QPen(QColor(color), 1.9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        p.setBrush(Qt.BrushStyle.NoBrush)
        if name == "clock":
            p.drawEllipse(QRectF(5, 5, 22, 22))
            p.drawLine(QPointF(16, 9), QPointF(16, 16))
            p.drawLine(QPointF(16, 16), QPointF(21, 19))
        elif name == "apps":
            for x in (5, 18):
                for y in (5, 18):
                    p.drawRoundedRect(QRectF(x, y, 9, 9), 2, 2)
        elif name == "folder":
            path = QPainterPath(QPointF(4, 10))
            for point in ((4, 7), (13, 7), (16, 11), (28, 11), (26, 25), (5, 25), (4, 10), (28, 11)):
                path.lineTo(*point)
            p.drawPath(path)
        elif name == "settings":
            p.drawEllipse(QRectF(7, 7, 18, 18))
            p.drawEllipse(QRectF(12, 12, 8, 8))
            for n in range(8):
                a = n * math.pi / 4
                p.drawLine(QPointF(16 + 10 * math.cos(a), 16 + 10 * math.sin(a)), QPointF(16 + 13 * math.cos(a), 16 + 13 * math.sin(a)))
        elif name == "pause":
            p.drawRoundedRect(QRectF(8, 6, 5, 20), 1, 1)
            p.drawRoundedRect(QRectF(19, 6, 5, 20), 1, 1)
        elif name in {"play", "explore"}:
            path = QPainterPath(QPointF(10, 6))
            path.lineTo(25, 16)
            path.lineTo(10, 26)
            path.closeSubpath()
            p.drawPath(path)
        elif name == "duel":
            p.drawLine(QPointF(7, 5), QPointF(25, 27))
            p.drawLine(QPointF(25, 5), QPointF(7, 27))
            p.drawLine(QPointF(5, 22), QPointF(13, 27))
            p.drawLine(QPointF(19, 27), QPointF(27, 22))
            p.drawEllipse(QRectF(13, 12, 6, 6))
        elif name == "system":
            p.drawRoundedRect(QRectF(5, 4, 22, 20), 3, 3)
            p.drawLine(QPointF(16, 24), QPointF(16, 28))
            p.drawLine(QPointF(10, 28), QPointF(22, 28))
            path = QPainterPath(QPointF(8, 16))
            for xy in ((12, 16), (14, 10), (18, 20), (21, 14), (25, 14)):
                path.lineTo(*xy)
            p.drawPath(path)
        elif name == "search":
            p.drawEllipse(QRectF(5, 5, 16, 16))
            p.drawLine(QPointF(19, 19), QPointF(27, 27))
        elif name == "close":
            p.drawLine(QPointF(10, 10), QPointF(22, 22))
            p.drawLine(QPointF(22, 10), QPointF(10, 22))
        else:
            p.drawRoundedRect(QRectF(8, 4, 16, 24), 2, 2)
            p.drawLine(QPointF(12, 12), QPointF(20, 12))
            p.drawLine(QPointF(12, 17), QPointF(20, 17))
        p.end()
        result.addPixmap(pixmap)
    return result


def apply_character_name(root, name):
    import re
    from PySide6.QtWidgets import QAbstractButton
    for widget in (root, *root.findChildren(QWidget)):
        widget.character_name = name
        current = widget
        literal = False
        while current is not None:
            literal = literal or bool(current.property("characterLiteral"))
            if current is root:
                break
            current = current.parentWidget()
        if literal:
            continue
        if not isinstance(widget, (QLabel, QAbstractButton)):
            continue
        template = widget.property("characterText")
        if template is None:
            if not re.search(r"\bR2\b(?! Companion)", widget.text()):
                continue
            template = widget.text()
            widget.setProperty("characterText", template)
        widget.setText(re.sub(r"\bR2\b(?! Companion)", lambda match: name, template))
