"""In-memory focus sessions on the shared Countdown and its uptime clock."""
from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from PySide6.QtCore import QObject, Signal

from .productivity import ProductivityStore
from .timer import Countdown, TimerState


FOCUS_SECONDS = 25 * 60
BREAK_SECONDS = 5 * 60
ACTIVE = (TimerState.RUNNING, TimerState.PAUSED)


class FocusPhase(StrEnum):
    FOCUS = "focus"
    BREAK = "break"


@dataclass
class _FocusRun:
    session_id: str
    phase: FocusPhase
    task_id: str | None


@dataclass(frozen=True)
class FocusSession:
    session_id: str
    run_id: int
    phase: FocusPhase
    duration: float
    state: TimerState
    task_id: str | None

    @property
    def override_id(self) -> str | None:
        """Presence consumers acquire or release ownership only when this ID changes."""
        if self.phase == FocusPhase.FOCUS and self.state == TimerState.RUNNING:
            return self.session_id
        return None

    @property
    def next_phase(self) -> FocusPhase | None:
        if self.state != TimerState.COMPLETED:
            return None
        return FocusPhase.BREAK if self.phase == FocusPhase.FOCUS else FocusPhase.FOCUS


@dataclass(frozen=True)
class CountdownConflict:
    run_id: int
    session_id: str | None  # None identifies a standalone timer.


class FocusSessionService(QObject):
    """Start returns a run ID, a conflict to confirm, or None for an expired confirmation.

    Pass the conflict's run_id as replace_run_id to authorize just that run.
    Commands on a session also take the run ID seen by their caller.
    """

    changed = Signal(object)  # FocusSession or None, only on transitions
    completed = Signal(object)  # FocusSession, once per completed run

    def __init__(self, countdown: Countdown, productivity: ProductivityStore):
        super().__init__()
        self.countdown = countdown
        self.productivity = productivity
        self._published: FocusSession | None = None
        countdown.changed.connect(self._publish)
        productivity.tasks_changed.connect(self._check_task)

    @property
    def session(self) -> FocusSession | None:
        timer = self.countdown
        owner = timer.owner
        if not isinstance(owner, _FocusRun):
            return None
        return FocusSession(owner.session_id, timer.run_id, owner.phase, timer.duration, timer.state, owner.task_id)

    def _publish(self):
        current = self.session
        previous = self._published
        if current == previous:
            return
        self._published = current
        self.changed.emit(current)
        if current is None or current.state != TimerState.COMPLETED:
            return
        if previous and previous.run_id == current.run_id and previous.state == TimerState.COMPLETED:
            return
        # A synchronous changed listener may already have started another run.
        if self._matches(current.run_id, TimerState.COMPLETED):
            self.completed.emit(self.session)

    def start_focus(self, seconds: float = FOCUS_SECONDS, *, task_id: str | None = None,
                    replace_run_id: int | None = None) -> int | CountdownConflict | None:
        return self._start(seconds, _FocusRun(uuid4().hex, FocusPhase.FOCUS, task_id), replace_run_id)

    def start_timer(self, seconds: float, *, replace_run_id: int | None = None) -> int | CountdownConflict | None:
        return self._start(seconds, None, replace_run_id)

    def _start(self, seconds: float, owner: _FocusRun | None, replace_run_id: int | None) -> int | CountdownConflict | None:
        timer = self.countdown
        if timer.state == TimerState.RUNNING and timer.remaining <= 0:
            timer.tick()
        if timer.state in ACTIVE:
            if replace_run_id != timer.run_id:
                session = self.session
                return CountdownConflict(timer.run_id, session.session_id if session else None)
        elif replace_run_id is not None:
            return None
        if owner is not None and owner.task_id is not None and self.productivity.task(owner.task_id) is None:
            raise ValueError("A tarefa selecionada não existe.")
        return timer.start(seconds, owner=owner)

    def _matches(self, run_id, *states):
        session = self.session
        return session is not None and session.run_id == run_id and session.state in states

    def pause(self, run_id):
        if self._matches(run_id, TimerState.RUNNING):
            self.countdown.pause()

    def resume(self, run_id):
        if self._matches(run_id, TimerState.PAUSED):
            self.countdown.resume()

    def cancel(self, run_id):
        if self._matches(run_id, *ACTIVE):
            self.countdown.stop()

    def complete(self, run_id):
        if self._matches(run_id, *ACTIVE):
            self.countdown.complete()

    def restart(self, run_id: int) -> int | None:
        if self._matches(run_id, *ACTIVE, TimerState.COMPLETED):
            return self.countdown.restart()
        return None

    def start_next_phase(self, run_id: int) -> int | None:
        if not self._matches(run_id, TimerState.COMPLETED):
            return None
        session = self.session
        if session.next_phase == FocusPhase.BREAK:
            owner = _FocusRun(session.session_id, FocusPhase.BREAK, session.task_id)
            return self.countdown.start(BREAK_SECONDS, owner=owner)
        owner = _FocusRun(uuid4().hex, FocusPhase.FOCUS, session.task_id)
        return self.countdown.start(FOCUS_SECONDS, owner=owner)

    def _check_task(self):
        owner = self.countdown.owner
        if isinstance(owner, _FocusRun) and owner.task_id is not None and self.productivity.task(owner.task_id) is None:
            owner.task_id = None
            self._publish()

    def complete_task(self, run_id) -> bool:
        if not self._matches(run_id, TimerState.COMPLETED) or self.session.phase != FocusPhase.FOCUS:
            return False
        task = self.productivity.task(self.session.task_id)
        if task is None or task["done"]:
            return False
        self.productivity.set_done(task["id"], True)
        return True
