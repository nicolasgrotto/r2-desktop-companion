from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from .clock import local_clock
from ..core.language import tr


@dataclass(frozen=True)
class ProjectionModel:
    kind: str
    title: str
    lines: tuple[str, ...]
    progress: float | None = None

    @property
    def accessible_text(self):
        return "\n".join((self.title, *self.lines))


def clock_model(kind):
    time, _, date = local_clock().partition("\n")
    if kind == "clock":
        return ProjectionModel(kind, tr("Relógio"), (time,))
    return ProjectionModel(kind, tr("Horário e data"), (time, date))


class ProjectionController(QObject):
    changed = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.providers = {
            "clock": lambda: clock_model("clock"),
            "date": lambda: clock_model("date"),
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
        model = self.providers[self.selected]()
        if model is None:
            self.end()
            return
        self._publish(model)
        if self.selected not in {"clock", "date", "timer", "focus"}:
            self.timer.stop()
        elif not self.suspended and not self.timer.isActive():
            self.timer.start()

    def _publish(self, model):
        if model != self.model:
            self.model = model
            self.changed.emit(model)
