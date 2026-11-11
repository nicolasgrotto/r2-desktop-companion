import math

from PySide6.QtCore import QEasingCurve, QEvent, QPointF, QRect, QRectF, QSize, QSizeF, Qt, QTimer, Signal, QParallelAnimationGroup, QPropertyAnimation
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QPushButton, QWidget

from ..pet.positioning import clamp
from .theme import icon
from .navigation import LEVEL_TITLES, NAVIGATION
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
        self.level = "main"
        self.history = []
        self.transition = None
        self.transitioning = False
        self.paused = False
        self.center_text = "R2"
        self.center = QPushButton("R2", self)
        self.center.setObjectName("center")
        self.center.setGeometry(142, 142, 84, 84)
        self.center.clicked.connect(self.back)
        self.close_button = QPushButton("×", self)
        self.close_button.setGeometry(316, 12, 36, 36)
        self.close_button.setAccessibleName("Fechar acesso rápido")
        self.close_button.setToolTip("Fechar acesso rápido · Esc")
        self.close_button.clicked.connect(self.hide)
        self.render_level()
        self.escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape.activated.connect(self.hide)
        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.timeout.connect(self.hide)
        self.deactivate_timer = QTimer(self)
        self.deactivate_timer.setSingleShot(True)
        self.deactivate_timer.setInterval(80)
        self.deactivate_timer.timeout.connect(lambda: self.hide() if not self.isActiveWindow() else None)
        QApplication.instance().installEventFilter(self)

    def button_rect(self, index, count, expanded=True):
        angle = math.radians(-90 + index * 360 / count)
        radius = 118 if expanded else 60
        width, height = (114, 60) if expanded else (76, 40)
        return QRect(round(184 + math.cos(angle) * radius - width / 2),
                     round(184 + math.sin(angle) * radius - height / 2), width, height)

    def render_level(self):
        for button in self.buttons.values():
            button.hide()
            button.deleteLater()
        self.buttons = {}
        items = NAVIGATION[self.level]
        for index, item in enumerate(items):
            title = "Continuar" if item.id == "pause" and self.paused else item.title
            glyph = "play" if item.id == "pause" and self.paused else item.glyph
            button = QPushButton(title, self)
            button.setObjectName(item.id)
            button.setIcon(icon(glyph, "#a9e6ff"))
            button.setIconSize(QSize(20, 20))
            button.setGeometry(self.button_rect(index, len(items)))
            button.setToolTip(title.replace("\n", " "))
            button.setAccessibleName(title.replace("\n", " "))
            effect = QGraphicsOpacityEffect(button)
            effect.setOpacity(1)
            button.setGraphicsEffect(effect)
            button.clicked.connect(lambda checked=False, key=item.id: self.select(key))
            self.buttons[item.id] = button
            button.show()
        self.center.setText(self.center_text if self.level == "main" else "↶")
        self.center.setToolTip("Fechar acesso rápido · Esc" if self.level == "main" else "Voltar à camada anterior · Esc para fechar")
        self.center.setAccessibleName("Fechar acesso rápido" if self.level == "main" else "Voltar à camada anterior")
        self.center.raise_()
        self.close_button.raise_()
        self.update()

    def animate_items(self, entering, finished):
        group = QParallelAnimationGroup(self)
        self.transition = group
        for index, button in enumerate(self.buttons.values()):
            geometry = QPropertyAnimation(button, b"geometry", group)
            geometry.setDuration(160 if entering else 80)
            geometry.setStartValue(self.button_rect(index, len(self.buttons), not entering))
            geometry.setEndValue(self.button_rect(index, len(self.buttons), entering))
            geometry.setEasingCurve(QEasingCurve.Type.OutCubic)
            opacity = QPropertyAnimation(button.graphicsEffect(), b"opacity", group)
            opacity.setDuration(160 if entering else 80)
            opacity.setStartValue(0.0 if entering else 1.0)
            opacity.setEndValue(1.0 if entering else 0.0)
            button.setEnabled(False)
        group.finished.connect(finished)
        group.start()

    def navigate(self, level, returning=False):
        if self.transitioning or level not in NAVIGATION or not self.isVisible():
            return
        self.transitioning = True
        self.dismiss_timer.stop()
        def enter():
            self.transition.deleteLater()
            self.transition = None
            if returning:
                self.history.pop()
            else:
                self.history.append(self.level)
            self.level = level
            self.render_level()
            self.animate_items(True, self.finish_transition)
        self.animate_items(False, enter)

    def finish_transition(self):
        self.transition.deleteLater()
        self.transition = None
        self.transitioning = False
        for button in self.buttons.values():
            button.setEnabled(True)
        next(iter(self.buttons.values())).setFocus(Qt.FocusReason.PopupFocusReason)
        self.dismiss_timer.start(12000)

    def back(self):
        if self.transitioning:
            return
        if self.history:
            self.navigate(self.history[-1], returning=True)
        else:
            self.hide()

    def reset_navigation(self):
        if self.transition is not None:
            self.transition.stop()
            self.transition.deleteLater()
            self.transition = None
        self.transitioning = False
        self.history.clear()
        self.level = "main"
        self.render_level()

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
        self.paused = paused
        self.reset_navigation()
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
        if self.transitioning or not self.isVisible() or key not in self.buttons:
            return
        if key in NAVIGATION:
            self.navigate(key)
            return
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
                self.deactivate_timer.start()
            elif obj is self and event.type() == QEvent.Type.WindowActivate:
                self.deactivate_timer.stop()
        return False

    def hideEvent(self, event):
        self.dismiss_timer.stop()
        self.deactivate_timer.stop()
        self.reset_navigation()
        super().hideEvent(event)
        self.dismissed.emit()

    def enterEvent(self, event):
        self.dismiss_timer.stop()
        super().enterEvent(event)

    def leaveEvent(self, event):
        if self.isVisible() and not self.transitioning:
            self.dismiss_timer.start(6000)
        super().leaveEvent(event)

    def stop(self):
        self.dismiss_timer.stop()
        self.hide()
        QApplication.instance().removeEventFilter(self)
