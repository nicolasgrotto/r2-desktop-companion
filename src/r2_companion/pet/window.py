from PySide6.QtCore import QEvent, QPointF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


class PetWindow(QWidget):
    clicked = Signal()
    context_requested = Signal(object)
    drag_started = Signal()
    dragged = Signal(object, object)
    drag_finished = Signal()
    exit_requested = Signal()
    geometry_changed = Signal()

    def __init__(self):
        super().__init__()
        self.setWindowTitle("R2 Companion — placeholder de desenvolvimento")
        self.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint
                            | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(False)
        self.setToolTip("R2 Companion · arte provisória\nArraste para mover · botão direito para opções")
        self.frame = QPixmap()
        self.press_global: QPointF | None = None
        self.anchor = QPointF()
        self.dragging = False
        self.resizing = False

    def set_frame(self, frame: QPixmap) -> None:
        self.frame = frame
        self.update()

    def moveEvent(self, event):
        super().moveEvent(event)
        self.geometry_changed.emit()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.geometry_changed.emit()

    def set_topmost(self, enabled: bool) -> None:
        if bool(self.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != enabled:
            was_visible = self.isVisible()
            self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, enabled)
            if was_visible:
                self.show()

    def set_pass_through(self, enabled: bool) -> None:
        was_visible = self.isVisible()
        self.setWindowFlag(Qt.WindowType.WindowTransparentForInput, enabled)
        if was_visible:
            self.show()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
        painter.drawPixmap(self.rect(), self.frame)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_global = event.globalPosition()
            self.anchor = QPointF(event.position().x() / max(1, self.width()), event.position().y() / max(1, self.height()))
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.press_global is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not self.dragging and (event.globalPosition() - self.press_global).manhattanLength() >= QApplication.startDragDistance():
            self.dragging = True
            self.drag_started.emit()
        if self.dragging:
            self.dragged.emit(event.globalPosition(), self.anchor)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self.press_global is not None:
            was_dragging = self.dragging
            self.press_global = None
            self.dragging = False
            if was_dragging:
                self.drag_finished.emit()
            else:
                self.clicked.emit()
            event.accept()

    def contextMenuEvent(self, event):
        self.context_requested.emit(event.globalPos())
        event.accept()

    def event(self, event):
        if event.type() == QEvent.Type.UngrabMouse and self.dragging:
            self.press_global = None
            self.dragging = False
            self.drag_finished.emit()
        return super().event(event)

    def closeEvent(self, event):
        self.exit_requested.emit()
        event.accept()
