from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QMouseEvent, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from ..droids.themes import color, theme_manager
from ..features.clock import local_clock


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
    interaction_event = Signal(str, object)

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
        self.visual = None
        self.body_angle = self.head_tilt = self.head_offset = 0.0
        self.illumination = None
        self.decoration = False
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
        self.projection_kind = None
        self.projection_text = ""
        self.projection_timer = QTimer(self)
        self.projection_timer.setInterval(1000)
        self.projection_timer.timeout.connect(self.refresh_projection)
        theme_manager().changed.connect(self.refresh_projection)
        self.affection_timer = QTimer(self)
        self.affection_timer.setSingleShot(True)
        self.affection_timer.setInterval(650)
        self.affection_timer.timeout.connect(self.pet_head)
        from ..ui.projection import ProjectionOverlay
        self.projection_overlay = ProjectionOverlay(self)
        from ..ui.steam import SteamOverlay
        self.steam = SteamOverlay(self)

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
        self.clear_projection()
        self.hologram = pixmap
        self.hologram_timer.start(1800)
        self.update()

    def show_projection(self, kind):
        if kind not in {"clock", "date"}:
            return False
        self.clear_projection()
        self.projection_kind = kind
        self.refresh_projection()
        if self.isVisible():
            self.projection_timer.start()
        return True

    def refresh_projection(self, *_):
        if self.projection_kind is None:
            return
        time_text, date_text = local_clock().split("\n", 1)
        self.projection_text = time_text + ("\n" + date_text if self.projection_kind == "date" else "")
        picture = QPixmap(320, 164 if self.projection_kind == "date" else 76)
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
        painter.drawText(QRectF(8, 6, 304, 62), Qt.AlignmentFlag.AlignCenter, time_text)
        if self.projection_kind == "date":
            painter.setFont(QFont("Segoe UI", 18))
            painter.drawText(QRectF(12, 67, 296, 90), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap, date_text)
        painter.end()
        self.hologram = picture
        self.projection_overlay.reposition()
        self.update()

    def clear_projection(self):
        self.hologram_timer.stop()
        self.projection_timer.stop()
        self.projection_kind = None
        self.projection_text = ""
        self.hologram = QPixmap()
        self.projection_overlay.hide()
        self.update()

    def stop_effects(self):
        self.steam.set_active(False)
        self.affection_timer.stop()
        self.hologram_timer.stop()
        self.clear_projection()

    def showEvent(self, event):
        self.steam.reposition()
        if self.projection_kind:
            self.refresh_projection()
            self.projection_timer.start()
        super().showEvent(event)

    def hideEvent(self, event):
        self.projection_timer.stop()
        self.projection_overlay.hide()
        self.steam.timer.stop()
        self.steam.hide()
        super().hideEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_click = True
            self.double_clicked.emit()
            event.accept()

    def set_frame(self, frame: QPixmap) -> None:
        from ..droids.visuals import DroidVisual
        if isinstance(frame, DroidVisual):
            self.visual = frame
            self.update()
            return
        self.visual = None
        self.original_frame = frame
        if (self.accent != "blue" or self.illumination) and not frame.isNull():
            key = (frame.cacheKey(), self.accent, self.illumination)
            if key not in self.tinted_frames:
                palette = {}
                if self.accent != "blue":
                    colors = {"teal": ("#188b87", "#7be9d4"), "violet": ("#7855b8", "#c3a3ff"),
                              "amber": ("#bc8128", "#ffdc8e")}[self.accent]
                    palette = {QColor("#286bc0").rgb(): QColor(colors[0]).rgba(), QColor("#71d1ee").rgb(): QColor(colors[1]).rgba()}
                if self.illumination:
                    palette[QColor("#edac4b").rgb()] = QColor(self.illumination).rgba()
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

    def set_motion(self, angle, tilt, offset):
        self.body_angle, self.head_tilt, self.head_offset = angle, tilt, offset
        self.update()

    def configure_droid(self, profile, preferences):
        self.tinted_frames.clear()
        self.set_motion(0, 0, 0)
        self.setWindowTitle(f"{profile.name} · R2 Companion")
        self.setToolTip(f"{profile.name}\nArraste para mover · botão direito para opções\n{profile.art_status}")
        custom = profile.customizations(preferences.customization)
        self.illumination = None
        if "illumination" in custom:
            self.illumination = profile.customization["illumination"]["options"][custom["illumination"]]["color"]
        self.decoration = custom.get("decoration") == "beacon"
        self.set_appearance(preferences.appearance if "appearance" in custom else "blue")

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
        if self.visual is not None:
            from ..droids.visuals import paint_visual
            paint_visual(painter, self.rect(), self.visual, self.body_angle, self.head_tilt,
                         self.head_offset, self.illumination, self.decoration)
        else:
            painter.drawPixmap(self.rect(), self.frame)
        if not self.hologram.isNull() and not self.projection_kind:
            width = max(16, self.width() - 8) if self.projection_kind else max(16, self.width() // 5)
            height = round(width * self.hologram.height() / self.hologram.width())
            painter.drawPixmap(self.width() - width - 4, 4, width, height, self.hologram)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.press_global = event.globalPosition()
            self.anchor = QPointF(event.position().x() / max(1, self.width()), event.position().y() / max(1, self.height()))
            self.affection = False
            if 0.28 <= self.anchor.x() <= 0.72 and 0.08 <= self.anchor.y() <= 0.36:
                self.affection_timer.start()
            event.accept()
        self.interaction_event.emit("mouse_press_received", {
            "accepted": event.isAccepted(), "spontaneous": event.spontaneous(),
            "source": event.source().name, "button": event.button().name})

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
        self.interaction_event.emit("mouse_release_received", {
            "press_present": self.press_global is not None, "dragging": self.dragging,
            "double_click": self.double_click, "affection": self.affection,
            "spontaneous": event.spontaneous(), "source": event.source().name})
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
        self.interaction_event.emit("mouse_release_delivered", {"accepted": event.isAccepted()})

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
