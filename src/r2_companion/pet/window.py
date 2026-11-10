from PySide6.QtCore import QEvent, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget


class PetWindow(QWidget):
    clicked = Signal()
    double_clicked = Signal()
    petted = Signal()
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
        self.double_click = False
        self.affection = False
        self.accent = "blue"
        self.original_frame = QPixmap()
        self.tinted_frames = {}
        self.hologram = QPixmap()
        self.hologram_timer = QTimer(self)
        self.hologram_timer.setSingleShot(True)
        self.hologram_timer.timeout.connect(self.clear_projection)
        self.affection_timer = QTimer(self)
        self.affection_timer.setSingleShot(True)
        self.affection_timer.setInterval(650)
        self.affection_timer.timeout.connect(self.pet_head)

    def pet_head(self):
        if self.press_global is not None and not self.dragging:
            self.affection = True
            self.petted.emit()

    def set_appearance(self, accent):
        if accent != self.accent:
            self.accent = accent
            self.tinted_frames.clear()
            self.set_frame(self.original_frame)

    def project(self, pixmap):
        self.hologram = pixmap
        self.hologram_timer.start(1800)
        self.update()

    def clear_projection(self):
        self.hologram = QPixmap()
        self.update()

    def stop_effects(self):
        self.affection_timer.stop()
        self.hologram_timer.stop()
        self.clear_projection()

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_click = True
            self.double_clicked.emit()
            event.accept()

    def set_frame(self, frame: QPixmap) -> None:
        self.original_frame = frame
        if self.accent != "blue" and not frame.isNull():
            key = (frame.cacheKey(), self.accent)
            if key not in self.tinted_frames:
                colors = {"teal": ("#188b87", "#7be9d4"), "violet": ("#7855b8", "#c3a3ff"),
                          "amber": ("#bc8128", "#ffdc8e")}[self.accent]
                palette = {QColor("#286bc0").rgb(): QColor(colors[0]).rgba(), QColor("#71d1ee").rgb(): QColor(colors[1]).rgba()}
                picture = frame.toImage()
                for y in range(picture.height()):
                    for x in range(picture.width()):
                        pixel = picture.pixel(x, y)
                        if pixel in palette:
                            picture.setPixel(x, y, palette[pixel])
                self.tinted_frames[key] = QPixmap.fromImage(picture)
            frame = self.tinted_frames[key]
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
        if not self.hologram.isNull():
            side = max(16, self.width() // 5)
            painter.drawPixmap(self.width() - side - 4, 4, side, side, self.hologram)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_global = event.globalPosition()
            self.anchor = QPointF(event.position().x() / max(1, self.width()), event.position().y() / max(1, self.height()))
            self.affection = False
            if 0.28 <= self.anchor.x() <= 0.72 and 0.08 <= self.anchor.y() <= 0.36:
                self.affection_timer.start()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.press_global is None or not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if not self.dragging and (event.globalPosition() - self.press_global).manhattanLength() >= QApplication.startDragDistance():
            self.affection_timer.stop()
            self.dragging = True
            self.drag_started.emit()
        if self.dragging:
            self.dragged.emit(event.globalPosition(), self.anchor)
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton and self.press_global is not None:
            self.affection_timer.stop()
            was_dragging = self.dragging
            self.press_global = None
            self.dragging = False
            if was_dragging:
                self.drag_finished.emit()
            elif not self.double_click and not self.affection:
                self.clicked.emit()
            self.double_click = False
            event.accept()

    def contextMenuEvent(self, event):
        self.context_requested.emit(event.globalPos())
        event.accept()

    def event(self, event):
        if event.type() == QEvent.Type.UngrabMouse:
            self.affection_timer.stop()
        if event.type() == QEvent.Type.UngrabMouse and self.dragging:
            self.press_global = None
            self.dragging = False
            self.drag_finished.emit()
        return super().event(event)

    def closeEvent(self, event):
        self.exit_requested.emit()
        event.accept()
