from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from .clock import local_clock


@dataclass(frozen=True)
class ProjectionModel:
    kind: str
    lines: tuple[str, ...]


class ProjectionController(QObject):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.providers = {
            "clock": lambda: (local_clock().partition("\n")[0],),
            "date": lambda: tuple(local_clock().split("\n", 1)),
        }
        self.selected = None
        self.model = None
        self.blockers = {"hidden"}
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.refresh)

    @property
    def suspended(self):
        return bool(self.blockers)

    def select(self, kind, *, automatic=False):
        if kind not in self.providers or (automatic and self.selected not in (None, kind)):
            return False
        self.selected = kind
        self.refresh()
        return True

    def end(self, kind=None):
        if kind is not None and self.selected != kind:
            return
        self.selected = None
        self.timer.stop()
        self._publish(None)

    def set_blocked(self, reason, blocked):
        if blocked == (reason in self.blockers):
            return
        if blocked:
            self.blockers.add(reason)
            self.timer.stop()
            self._publish(None)
        else:
            self.blockers.discard(reason)
            self.refresh()

    def refresh(self):
        if self.selected is None or self.suspended:
            return
        lines = self.providers[self.selected]()
        if lines is None:
            self.end()
            return
        self._publish(ProjectionModel(self.selected, lines))
        if self.selected is not None and not self.suspended and not self.timer.isActive():
            self.timer.start()

    def _publish(self, model):
        if model != self.model:
            self.model = model
            self.changed.emit(model)
