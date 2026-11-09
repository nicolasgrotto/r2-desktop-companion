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
        self.visible = False
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.tick)

    @property
    def remaining(self) -> float:
        if self.state == TimerState.RUNNING:
            return max(0.0, self.deadline - self.clock())
        return self.remaining_at_pause

    def start(self, seconds: float) -> None:
        if not math.isfinite(seconds) or not 1 <= seconds <= 86400:
            raise ValueError("Escolha uma duração entre 1 segundo e 24 horas.")
        self.run_id += 1
        self.duration = seconds
        self.deadline = self.clock() + seconds
        self.state = TimerState.RUNNING
        self.tick()

    def pause(self) -> None:
        if self.state == TimerState.RUNNING:
            self.tick()
            if self.state == TimerState.RUNNING:
                self.remaining_at_pause = self.remaining
                self.state = TimerState.PAUSED
                self.timer.stop()
                self.changed.emit()

    def resume(self) -> None:
        if self.state == TimerState.PAUSED:
            self.deadline = self.clock() + self.remaining_at_pause
            self.state = TimerState.RUNNING
            self.tick()

    def restart(self) -> None:
        self.start(self.duration)

    def tick(self) -> None:
        if self.state == TimerState.RUNNING:
            if self.remaining <= 0:
                self.state = TimerState.COMPLETED
                self.remaining_at_pause = 0
                self.timer.stop()
                self.completed.emit(self.run_id)
            else:
                delay = min(self.remaining, 0.5 if self.visible else 30)
                self.timer.start(max(1, math.ceil(delay * 1000)))
        self.changed.emit()

    def set_visible(self, visible: bool) -> None:
        self.visible = visible
        self.tick()

    def close(self) -> None:
        self.timer.stop()
        self.state = TimerState.STOPPED
