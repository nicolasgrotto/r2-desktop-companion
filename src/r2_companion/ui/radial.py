import math

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QApplication, QPushButton, QWidget

from ..pet.positioning import clamp
from .theme import icon
from ..droids.themes import color, styled


class RadialMenu(QWidget):
    action_selected = Signal(str)
    opened = Signal()
    dismissed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Acesso rápido · R2 Companion")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(368, 368)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        styled(self, """
            QPushButton { color: #eaf7ff; background: #153751; border: 1px solid #38647f;
              border-radius: 15px; font: 600 11px 'Segoe UI'; padding: 7px; }
            QPushButton:hover, QPushButton:focus { background: #216eea; border: 2px solid #67d8ff; }
            QPushButton:pressed { background: #1652b4; }
            QPushButton#center { color: #71d6fb; background: #0b2138; border: 1px solid #398cb8;
              border-radius: 42px; font: 700 24px 'Segoe UI'; }
        """)
        self.buttons = {}
        definitions = (("tools", "Ferramentas", "clock"), ("apps", "Aplicativos", "apps"),
                       ("locations", "Meus locais", "folder"), ("settings", "Configurar", "settings"),
                       ("explore", "Explorar", "explore"), ("pause", "Pausar", "pause"))
        for index, (key, title, glyph) in enumerate(definitions):
            angle = math.radians(-90 + index * 60)
            center = QPointF(184 + math.cos(angle) * 118, 184 + math.sin(angle) * 118)
            button = QPushButton(title, self)
            button.setIcon(icon(glyph, "#a9e6ff"))
            button.setIconSize(QSize(21, 21))
            button.setGeometry(round(center.x() - 54), round(center.y() - 30), 108, 60)
            button.setToolTip(title)
            button.setAccessibleName(title)
            button.clicked.connect(lambda checked=False, action=key: self.select(action))
            self.buttons[key] = button
        self.center = QPushButton("R2", self)
        self.center.setObjectName("center")
        self.center.setGeometry(142, 142, 84, 84)
        self.center.setToolTip("Fechar acesso rápido · Esc")
        self.center.setAccessibleName("Fechar acesso rápido")
        self.center.clicked.connect(self.hide)
        self.escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape.activated.connect(self.hide)
        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.timeout.connect(self.hide)
        QApplication.instance().installEventFilter(self)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setBrush(QColor(color("hero", self)))
        p.setPen(QPen(QColor(color("border", self)), 1))
        p.drawEllipse(QRectF(8, 8, 352, 352))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(color("decoration", self)), 1))
        p.drawEllipse(QRectF(24, 24, 320, 320))
        p.drawEllipse(QRectF(117, 117, 134, 134))
        for n in range(48):
            angle = math.radians(n * 7.5)
            inner = 157 if n % 4 else 152
            p.setPen(QPen(QColor(color("accent" if n % 4 == 0 else "decoration", self)), 1))
            p.drawLine(QPointF(184 + inner * math.cos(angle), 184 + inner * math.sin(angle)),
                       QPointF(184 + 164 * math.cos(angle), 184 + 164 * math.sin(angle)))
        p.setPen(QColor(color("hero_text", self)))
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.DemiBold))
        p.drawText(QRectF(122, 229, 124, 22), Qt.AlignmentFlag.AlignCenter, "ACESSO RÁPIDO")
        p.setPen(QColor(color("hero_muted", self)))
        p.drawText(QRectF(122, 248, 124, 18), Qt.AlignmentFlag.AlignCenter, "ESC · FECHAR")

    def popup_near(self, pet, paused=False):
        self.buttons["pause"].setText("Continuar" if paused else "Pausar")
        self.buttons["pause"].setIcon(icon("play" if paused else "pause", "#a9e6ff"))
        screen = QGuiApplication.screenAt(pet.geometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            return
        area = QRectF(screen.availableGeometry())
        x = pet.x() - self.width() - 16
        if x < area.left():
            x = pet.x() + pet.width() + 16
        point = clamp(QPointF(x, pet.y() + pet.height() / 2 - self.height() / 2), area, QSizeF(self.size()))
        self.move(round(point.x()), round(point.y()))
        self.opened.emit()
        self.show()
        self.raise_()
        self.activateWindow()
        self.buttons["tools"].setFocus(Qt.FocusReason.PopupFocusReason)
        self.dismiss_timer.start(12000)

    def select(self, key):
        self.hide()
        self.action_selected.emit(key)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        if self.isVisible():
            if event.type() == QEvent.Type.MouseButtonPress:
                if isinstance(obj, QWidget) and obj is not self and not self.isAncestorOf(obj):
                    self.hide()
            elif obj is self and event.type() == QEvent.Type.WindowDeactivate:
                self.hide()
        return False

    def hideEvent(self, event):
        self.dismiss_timer.stop()
        super().hideEvent(event)
        self.dismissed.emit()

    def enterEvent(self, event):
        self.dismiss_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isVisible():
            self.dismiss_timer.start(6000)
        super().leaveEvent(event)

    def stop(self):
        self.dismiss_timer.stop()
        self.hide()
        QApplication.instance().removeEventFilter(self)
