import math
from shiboken6 import isValid

from PySide6.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QPointF, QRect, QRectF, QSize, QSizeF, Qt, QTimer, Signal, QParallelAnimationGroup, QPropertyAnimation
from PySide6.QtGui import QColor, QFont, QGuiApplication, QKeySequence, QPainter, QPen, QShortcut
from PySide6.QtWidgets import QApplication, QGraphicsOpacityEffect, QPushButton, QWidget

from ..pet.positioning import clamp
from .theme import icon
from .navigation import LEVEL_TITLES, NAVIGATION
from ..droids.themes import color, styled


class RadialButton(QPushButton):
    def event(self, event):
        result = super().event(event)
        if event.type() in {QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.KeyPress,
                            QEvent.Type.KeyRelease}:
            self.parentWidget().record("qt_event_delivered", detail=True, qt_event=event.type().name,
                                       widget=self.objectName(), accepted=event.isAccepted(), handled=result)
        return result


class RadialMenu(QWidget):
    action_selected = Signal(str)
    opened = Signal()
    dismissed = Signal()
    page_ready = Signal(str)

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
        self.trace = None
        self.begin_attempt = None
        self.trigger_widget = None
        self.dismissed_by_trigger_press = False
        self.level = "main"
        self.history = []
        self.transition = None
        self.transitioning = False
        self.phase = "idle"
        self.paused = False
        self.center_text = "R2"
        self.center = RadialButton("R2", self)
        self.center.setObjectName("center")
        self.center.setGeometry(142, 142, 84, 84)
        self.center.clicked.connect(self.back)
        self.close_button = RadialButton("×", self)
        self.close_button.setGeometry(316, 12, 36, 36)
        self.close_button.setAccessibleName("Fechar acesso rápido")
        self.close_button.setToolTip("Fechar acesso rápido · Esc")
        self.close_button.clicked.connect(lambda: self.dismiss("close_button"))
        self.render_level()
        self.escape = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.escape.activated.connect(lambda: self.dismiss("escape"))
        self.dismiss_timer = QTimer(self)
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.timeout.connect(lambda: self.dismiss("inactivity_timeout"))
        self.deactivate_timer = QTimer(self)
        self.deactivate_timer.setSingleShot(True)
        self.deactivate_timer.setInterval(80)
        self.deactivate_timer.timeout.connect(self.check_deactivation)
        QApplication.instance().installEventFilter(self)

    def record(self, event, **fields):
        if self.trace is None:
            return
        app = QApplication.instance()
        focus, active = app.focusWidget(), app.activeWindow()
        self.trace(event, level=self.level, history=list(self.history), phase=self.phase,
                   transitioning=self.transitioning, visible=self.isVisible(), minimized=self.isMinimized(),
                   active=self.isActiveWindow(), focus=type(focus).__name__ if focus else None,
                   active_window=type(active).__name__ if active else None, **fields)

    def check_deactivation(self):
        self.record("deactivation_checked")
        if not self.isActiveWindow():
            self.record("dismiss_requested", reason="deactivated")
            self.hide()

    def dismiss(self, reason):
        self.record("dismiss_requested", reason=reason)
        self.hide()

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
            button = RadialButton(title, self)
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
            button.setEnabled(entering)
        self.phase = "entering" if entering else "exiting"
        group.finished.connect(lambda: self.animation_finished(group, finished))
        group.stateChanged.connect(lambda state, previous: self.animation_state_changed(group, state))
        group.destroyed.connect(lambda: self.animation_destroyed(group))
        self.record("animation_started", duration_ms=group.duration())
        group.start()

    def animation_finished(self, group, finished):
        if self.transition is not group:
            return
        self.transition = None
        group.deleteLater()
        self.record("animation_finished")
        try:
            finished()
        except Exception as error:
            self.record("animation_callback_failed", error=error)
            self.cancel_transition("callback_failed")
            raise

    def animation_state_changed(self, group, state):
        if self.transition is not group:
            return
        if not isValid(group):
            self.animation_destroyed(group)
            return
        if state == QAbstractAnimation.State.Paused:
            self.cancel_transition("animation_paused")
        elif state == QAbstractAnimation.State.Stopped and group.currentTime() < group.totalDuration():
            self.cancel_transition("animation_stopped")

    def animation_destroyed(self, group):
        if self.transition is group:
            self.transition = None
            self.cancel_transition("animation_destroyed")

    def cancel_transition(self, reason):
        group, self.transition = self.transition, None
        if group is not None:
            group.stop()
            group.deleteLater()
        self.transitioning = False
        self.phase = "idle"
        for index, button in enumerate(self.buttons.values()):
            button.setGeometry(self.button_rect(index, len(self.buttons)))
            button.graphicsEffect().setOpacity(1)
            button.setEnabled(True)
        if self.isVisible():
            self.dismiss_timer.start(12000)
        self.record("transition_cancelled", reason=reason)

    def navigate(self, level, returning=False):
        if self.transitioning or level not in NAVIGATION or not self.isVisible():
            self.record("navigation_rejected", target=level)
            return
        self.transitioning = True
        self.dismiss_timer.stop()
        def enter():
            if returning:
                self.history.pop()
            else:
                self.history.append(self.level)
            self.level = level
            self.render_level()
            self.record("page_entered")
            self.animate_items(True, self.finish_transition)
        self.animate_items(False, enter)

    def finish_transition(self):
        self.transitioning = False
        self.phase = "idle"
        for button in self.buttons.values():
            button.setEnabled(True)
        if self.isActiveWindow():
            next(iter(self.buttons.values())).setFocus(Qt.FocusReason.PopupFocusReason)
        self.dismiss_timer.start(12000)
        self.record("page_ready")
        self.page_ready.emit(self.level)

    def back(self):
        if self.phase == "entering":
            self.cancel_transition("back_during_entry")
        if self.transitioning:
            self.record("navigation_rejected", target="back")
            return
        if self.history:
            self.navigate(self.history[-1], returning=True)
        else:
            self.hide()

    def reset_navigation(self):
        if self.transition is not None:
            self.cancel_transition("reset")
        self.transitioning = False
        self.phase = "idle"
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

    def popup_near(self, pet, paused=False, new_attempt=True):
        if new_attempt and self.begin_attempt is not None:
            self.begin_attempt()
        self.record("open_requested")
        self.paused = paused
        self.reset_navigation()
        screen = QGuiApplication.screenAt(pet.geometry().center()) or QGuiApplication.primaryScreen()
        if screen is None:
            self.record("open_rejected", reason="no_screen")
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
        self.record("wheel_shown")

    def select(self, key):
        self.record("selection_received", action=key)
        if self.phase == "entering" and key in self.buttons and self.isVisible():
            self.cancel_transition("selection_during_entry")
        if self.transitioning or not self.isVisible() or key not in self.buttons:
            self.record("selection_rejected", action=key)
            return
        self.record("item_selected", action=key)
        if key in NAVIGATION:
            self.navigate(key)
            return
        self.hide()
        self.record("callback_emitted", action=key)
        self.action_selected.emit(key)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()
            event.accept()
        else:
            super().keyPressEvent(event)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.Type.MouseButtonPress and obj is self.trigger_widget:
            self.dismissed_by_trigger_press = self.isVisible()
        if isinstance(obj, QWidget) and (obj is self or self.isAncestorOf(obj)):
            if kind in {QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.KeyPress,
                        QEvent.Type.FocusIn, QEvent.Type.FocusOut, QEvent.Type.WindowActivate,
                        QEvent.Type.WindowDeactivate, QEvent.Type.Show, QEvent.Type.Hide}:
                self.record("qt_event_received", detail=True, qt_event=kind.name, widget=obj.objectName(),
                            accepted_before=event.isAccepted(), spontaneous=event.spontaneous(),
                            enabled=obj.isEnabled())
        if self.isVisible():
            if event.type() == QEvent.Type.MouseButtonPress:
                if isinstance(obj, QWidget) and obj is not self and not self.isAncestorOf(obj):
                    self.record("dismiss_requested", reason="trigger_press" if obj is self.trigger_widget else "outside_press")
                    self.hide()
            elif obj is self and event.type() == QEvent.Type.WindowDeactivate:
                self.record("window_deactivated")
                self.deactivate_timer.start()
            elif obj is self and event.type() == QEvent.Type.WindowActivate:
                self.record("window_activated")
                self.deactivate_timer.stop()
        return False

    def hideEvent(self, event):
        self.record("wheel_hidden")
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
        self.record("wheel_stopped")
        self.dismiss_timer.stop()
        self.hide()
        QApplication.instance().removeEventFilter(self)
