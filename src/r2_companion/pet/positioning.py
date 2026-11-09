from collections.abc import Callable
import time

from PySide6.QtCore import QObject, QPointF, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication

from ..core.config import WindowSettings


def legal_bounds(area: QRectF, size: QSizeF, margin: float = 8) -> tuple[float, float, float, float]:
    mx = min(margin, max(0, (area.width() - size.width()) / 2))
    my = min(margin, max(0, (area.height() - size.height()) / 2))
    return (area.x() + mx, max(area.x() + mx, area.x() + area.width() - size.width() - mx),
            area.y() + my, max(area.y() + my, area.y() + area.height() - size.height() - my))


def clamp(point: QPointF, area: QRectF, size: QSizeF) -> QPointF:
    left, right, top, bottom = legal_bounds(area, size)
    return QPointF(min(right, max(left, point.x())), min(bottom, max(top, point.y())))


def normalized(point: QPointF, area: QRectF, size: QSizeF) -> tuple[float, float]:
    left, right, top, bottom = legal_bounds(area, size)
    return (min(1, max(0, (point.x() - left) / (right - left))) if right > left else 0.5,
            min(1, max(0, (point.y() - top) / (bottom - top))) if bottom > top else 0.5)


def from_normalized(u: float, v: float, area: QRectF, size: QSizeF) -> QPointF:
    left, right, top, bottom = legal_bounds(area, size)
    return clamp(QPointF(left + u * (right - left), top + v * (bottom - top)), area, size)


def nearest_index(point: QPointF, areas: list[QRectF]) -> int:
    if not areas:
        raise ValueError("Nenhum monitor disponível.")
    def distance(rect):
        dx = max(rect.x() - point.x(), 0, point.x() - (rect.x() + rect.width()))
        dy = max(rect.y() - point.y(), 0, point.y() - (rect.y() + rect.height()))
        return dx * dx + dy * dy
    return min(range(len(areas)), key=lambda i: distance(areas[i]))


def fingerprint(screen) -> str:
    return "|".join((screen.manufacturer(), screen.model(), screen.serialNumber(), screen.name()))


class Positioner(QObject):
    settled = Signal(object)
    movement_finished = Signal(int)
    screens_changed = Signal()

    def __init__(self, window, clock: Callable[[], float] = time.monotonic):
        super().__init__()
        self.window = window
        self.clock = clock
        self.display_size = 160
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.tick)
        self.token = 0
        self.screen = None
        app = QGuiApplication.instance()
        app.screenAdded.connect(self.add_screen)
        app.screenRemoved.connect(self.reconcile)
        for screen in app.screens():
            self.add_screen(screen, reconcile=False)

    def add_screen(self, screen, reconcile=True):
        screen.availableGeometryChanged.connect(self.reconcile)
        screen.logicalDotsPerInchChanged.connect(self.reconcile)
        if reconcile:
            self.reconcile()

    def fit(self, screen) -> None:
        area = screen.availableGeometry()
        side = max(1, min(self.display_size, area.width(), area.height()))
        if self.window.size().width() != side or self.window.size().height() != side:
            self.window.setFixedSize(side, side)

    def place(self, point: QPointF, screen=None) -> None:
        screens = QGuiApplication.screens()
        if not screens:
            return
        screen = screen or screens[nearest_index(point, [QRectF(s.availableGeometry()) for s in screens])]
        self.screen = screen
        self.fit(screen)
        point = clamp(point, QRectF(screen.availableGeometry()), QSizeF(self.window.size()))
        self.window.move(round(point.x()), round(point.y()))

    def drag(self, pointer: QPointF, anchor: QPointF) -> None:
        screens = QGuiApplication.screens()
        if not screens:
            return
        screen = screens[nearest_index(pointer, [QRectF(s.availableGeometry()) for s in screens])]
        self.fit(screen)
        self.place(pointer - QPointF(anchor.x() * self.window.width(), anchor.y() * self.window.height()), screen)

    def restore(self, saved: WindowSettings) -> None:
        screens = QGuiApplication.screens()
        if not screens:
            return
        matches = [s for s in screens if saved.screen and fingerprint(s) == saved.screen]
        screen = matches[0] if matches else QGuiApplication.primaryScreen()
        self.fit(screen)
        self.place(from_normalized(saved.u, saved.v, QRectF(screen.availableGeometry()), QSizeF(self.window.size())), screen)

    def snapshot(self) -> WindowSettings | None:
        if self.screen not in QGuiApplication.screens():
            return None
        point = QPointF(self.window.pos())
        u, v = normalized(point, QRectF(self.screen.availableGeometry()), QSizeF(self.window.size()))
        return WindowSettings(fingerprint(self.screen), point.x(), point.y(), u, v,
                              bool(self.window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint))

    def settle(self) -> None:
        saved = self.snapshot()
        if saved:
            self.settled.emit(saved)

    def reconcile(self, *_):
        self.stop()
        if not QGuiApplication.screens():
            self.screens_changed.emit()
            return
        self.place(QPointF(self.window.pos()))
        self.settle()
        self.screens_changed.emit()

    def walk(self, distance: float, duration: float, token: int) -> bool:
        self.stop()
        if self.screen not in QGuiApplication.screens():
            return False
        self.origin = QPointF(self.window.pos())
        self.destination = clamp(self.origin + QPointF(distance, 0), QRectF(self.screen.availableGeometry()), QSizeF(self.window.size()))
        if abs(self.destination.x() - self.origin.x()) < 4:
            return False
        self.token = token
        self.duration = duration
        self.started = self.clock()
        self.timer.start()
        return True

    def tick(self):
        progress = min(1.0, max(0.0, (self.clock() - self.started) / self.duration))
        self.place(self.origin + (self.destination - self.origin) * progress, self.screen)
        if progress >= 1:
            self.timer.stop()
            self.settle()
            self.movement_finished.emit(self.token)

    def stop(self):
        self.timer.stop()
