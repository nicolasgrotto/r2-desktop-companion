from PySide6.QtCore import QEvent, QPointF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from ..droids.themes import theme_manager
from ..features.projections import ProjectionController


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
                            | Qt.WindowType.WindowDoesNotAcceptFocus)
        from ..ui.window_layers import WindowLayerPolicy
        self.window_layers = WindowLayerPolicy(self)
        self.window_layers.register(self)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setAutoFillBackground(False)
        self.setToolTip("R2 Companion · arte provisória\nArraste para mover · botão direito para opções")
        self.frame = QPixmap()
        self.visual = None
        self.articulation = {}
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
        self.hologram_timer.timeout.connect(self.clear_ephemeral_projection)
        self.projection = ProjectionController(self)
        self.projection.changed.connect(self.present_projection)
        theme_manager().changed.connect(self.restyle_projection)
        self.affection_timer = QTimer(self)
        self.affection_timer.setSingleShot(True)
        self.affection_timer.setInterval(650)
        self.affection_timer.timeout.connect(self.pet_head)
        from ..ui.projection import ProjectionOverlay
        self.projection_overlay = ProjectionOverlay(self)
        from ..ui.steam import SteamOverlay
        self.steam = SteamOverlay(self)
        from ..ui.sleep import SleepOverlay
        self.sleep_effect = SleepOverlay(self)

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
        if self.projection_suspended:
            return
        self.clear_projection()
        self.hologram = pixmap
        self.hologram_timer.start(1800)
        self.update()

    @property
    def projection_kind(self):
        return self.projection.selected

    @property
    def projection_suspended(self):
        return self.projection.suspended

    @property
    def projection_text(self):
        model = self.projection.model
        return "\n".join(model.lines) if model else ""

    @property
    def projection_timer(self):
        return self.projection.timer

    def show_projection(self, kind, *, automatic=False):
        selected = self.projection.select(kind, automatic=automatic)
        if selected:
            self.hologram_timer.stop()
        return selected

    def refresh_projection(self):
        self.projection.refresh()

    def restyle_projection(self, *_):
        if self.projection.model is not None:
            self.present_projection(self.projection.model)

    def present_projection(self, model):
        self.hologram = self.projection_overlay.render_card(model) if model else QPixmap()
        self.projection_overlay.reposition()
        self.update()

    def clear_projection(self):
        self.projection.end()
        self.clear_ephemeral_projection()

    def clear_ephemeral_projection(self):
        self.hologram_timer.stop()
        if self.projection_kind is None and not self.hologram.isNull():
            self.hologram = QPixmap()
            self.update()

    def set_projection_suspended(self, suspended):
        self.projection.set_blocked("presence", suspended)
        if suspended:
            self.clear_ephemeral_projection()

    def stop_effects(self, preserve_projection=False):
        self.sleep_effect.set_active(False)
        self.steam.set_active(False)
        self.affection_timer.stop()
        self.clear_ephemeral_projection()
        if not preserve_projection:
            self.clear_projection()

    def showEvent(self, event):
        self.sleep_effect.reposition()
        self.steam.reposition()
        self.projection.set_blocked("hidden", False)
        super().showEvent(event)

    def hideEvent(self, event):
        self.sleep_effect.timer.stop()
        self.sleep_effect.hide()
        self.projection.set_blocked("hidden", True)
        self.clear_ephemeral_projection()
        self.steam.timer.stop()
        self.steam.hide()
        super().hideEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_click = True
            self.interaction_event.emit("mouse_double_click_received", {
                "press_present": self.press_global is not None, "spontaneous": event.spontaneous()})
            self.double_clicked.emit()
            event.accept()

    def set_frame(self, frame: QPixmap) -> None:
        from ..droids.visuals import VISUAL_TYPES
        if isinstance(frame, VISUAL_TYPES):
            self.visual = frame
            if self.projection_kind:
                self.projection_overlay.reposition()
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

    def set_articulation(self, channels):
        self.articulation = dict(channels)
        if self.projection_kind:
            self.projection_overlay.reposition()
        self.update()

    def projection_anchor(self):
        from ..droids.rig import ArticulatedVisual
        if isinstance(self.visual, ArticulatedVisual):
            return self.visual.anchor(self.articulation)
        return 0.54, 0.24

    def configure_droid(self, profile, preferences):
        self.tinted_frames.clear()
        self.set_motion(0, 0, 0)
        self.set_articulation({})
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
        self.window_layers.set_enabled(enabled)

    def set_pass_through(self, enabled: bool) -> None:
        with self.window_layers.preserve_stack():
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
                         self.head_offset, self.illumination, self.decoration, self.articulation)
        else:
            painter.drawPixmap(self.rect(), self.frame)
        if not self.hologram.isNull() and not self.projection_kind:
            width = max(16, self.width() // 5)
            height = round(width * self.hologram.height() / self.hologram.width())
            painter.drawPixmap(self.width() - width - 4, 4, width, height, self.hologram)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_click = False
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
            event.accept()
        if event.button() == Qt.MouseButton.LeftButton:
            self.double_click = False
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
