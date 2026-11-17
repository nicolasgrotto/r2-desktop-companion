from collections.abc import Callable
from enum import Enum
import math

from PySide6.QtCore import QObject, QTimer, Signal


class TimerState(str, Enum):
    STOPPED = "Parado"
    RUNNING = "Em andamento"
    PAUSED = "Pausado"
    COMPLETED = "Concluído"


class Countdown(QObject):
    changed = Signal()
    completed = Signal(int)

    def __init__(self, clock: Callable[[], float]):
        super().__init__()
        self.clock = clock
        self.state = TimerState.STOPPED
        self.duration = 300.0
        self.remaining_at_pause = 0.0
        self.deadline = 0.0
        self.run_id = 0
        self.owner = None
        self.visible = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.tick)

    @property
    def remaining(self) -> float:
        if self.state == TimerState.RUNNING:
            return max(0.0, self.deadline - self.clock())
        return self.remaining_at_pause

    def start(self, seconds: float, *, owner: object | None = None) -> int:
        """Attach optional run metadata before notifying synchronous listeners."""
        if not math.isfinite(seconds) or not 1 <= seconds <= 86400:
            raise ValueError("Escolha uma duração entre 1 segundo e 24 horas.")
        self.run_id += 1
        run_id = self.run_id
        self.owner = owner
        self.duration = seconds
        self.deadline = self.clock() + seconds
        self.state = TimerState.RUNNING
        self.tick()
        return run_id

    def pause(self) -> None:
        if self.state == TimerState.RUNNING:
            remaining = self.remaining
            if remaining <= 0:
                self.complete()
            else:
                self.remaining_at_pause = remaining
                self.state = TimerState.PAUSED
                self.timer.stop()
                self.changed.emit()

    def restore(self, duration: float, remaining: float, *, owner: object) -> int:
        """Install a validated relative checkpoint without arming the timer."""
        self.timer.stop()
        self.run_id += 1
        run_id = self.run_id
        self.owner = owner
        self.duration = duration
        self.remaining_at_pause = remaining
        self.deadline = 0.0
        self.state = TimerState.PAUSED if remaining else TimerState.COMPLETED
        self.changed.emit()
        return run_id

    def resume(self) -> None:
        if self.state == TimerState.PAUSED:
            self.deadline = self.clock() + self.remaining_at_pause
            self.state = TimerState.RUNNING
            self.tick()

    def restart(self) -> int:
        return self.start(self.duration, owner=self.owner)

    def stop(self) -> None:
        """Cancel the current run without emitting a completion notification."""
        self.timer.stop()
        self.state = TimerState.STOPPED
        self.owner = None
        self.deadline = 0.0
        self.remaining_at_pause = 0.0
        self.changed.emit()

    def complete(self) -> None:
        if self.state not in (TimerState.RUNNING, TimerState.PAUSED):
            return
        self.state = TimerState.COMPLETED
        self.remaining_at_pause = 0.0
        self.timer.stop()
        self.completed.emit(self.run_id)
        self.changed.emit()

    def tick(self) -> None:
        if self.state == TimerState.RUNNING:
            remaining = self.remaining
            if remaining <= 0:
                self.complete()
                return
            delay = min(remaining, 0.5 if self.visible else 30)
            self.timer.start(max(1, math.ceil(delay * 1000)))
        self.changed.emit()

    def set_visible(self, visible: bool) -> None:
        self.visible = visible
        self.tick()

    def close(self) -> None:
        self.stop()
