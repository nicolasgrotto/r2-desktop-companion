"""Focus sessions on the shared Countdown and its uptime clock."""
from dataclasses import dataclass, replace
from enum import StrEnum
from uuid import uuid4

from PySide6.QtCore import QObject, QTimer, Signal

from ..services.companion_state import CompanionStateStore
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


@dataclass(frozen=True)
class FocusRecovery:
    session_id: str
    phase: FocusPhase
    duration: float
    remaining: float
    task_id: str | None


class FocusSessionService(QObject):
    """Start returns a run ID, a conflict to confirm, or None for an expired confirmation.

    Pass the conflict's run_id as replace_run_id to authorize just that run.
    Commands on a session also take the run ID seen by their caller.
    """

    changed = Signal(object)  # FocusSession or None, only on transitions
    completed = Signal(object)  # FocusSession, once per completed run
    recovery_changed = Signal()

    def __init__(self, countdown: Countdown, productivity: ProductivityStore,
                 state_store: CompanionStateStore | None = None):
        super().__init__()
        self.countdown = countdown
        self.productivity = productivity
        self._published: FocusSession | None = None
        self.state_store = state_store
        self.recovery: FocusRecovery | None = None
        self.checkpoint_timer = QTimer(self)
        self.checkpoint_timer.setInterval(30_000)
        self.checkpoint_timer.timeout.connect(self._checkpoint)
        if state_store is not None:
            saved = state_store.data["focus"]["session"]
            if saved is not None:
                task_id = saved["task_id"] if productivity.task(saved["task_id"]) else None
                self.recovery = FocusRecovery(saved["id"], FocusPhase(saved["phase"]),
                                              saved["duration_seconds"], saved["remaining_seconds"], task_id)
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
        if self.state_store is not None:
            if current and self.recovery is not None:
                self.recovery = None
                self.recovery_changed.emit()
            if current or previous:
                self._checkpoint()
            if (current and current.state == TimerState.RUNNING and not self.state_store.read_only):
                if not self.checkpoint_timer.isActive():
                    self.checkpoint_timer.start()
            else:
                self.checkpoint_timer.stop()
        self.changed.emit(current)
        if current is None or current.state != TimerState.COMPLETED:
            return
        if previous is None or previous.run_id != current.run_id or previous.state not in ACTIVE:
            return
        # A synchronous changed listener may already have started another run.
        if self._matches(current.run_id, TimerState.COMPLETED):
            self.completed.emit(self.session)

    def _checkpoint(self):
        session = self.session
        if session is None:
            return self.state_store.save_focus_checkpoint(None)
        remaining = self.countdown.remaining
        return self.state_store.save_focus_checkpoint({
            "id": session.session_id,
            "phase": session.phase.value,
            "duration_seconds": session.duration,
            "remaining_seconds": remaining,
            "state": ("completed" if remaining == 0 else
                      "running" if session.state == TimerState.RUNNING else "paused"),
            "task_id": session.task_id,
        })

    def recover(self, *, replace_run_id: int | None = None) -> int | CountdownConflict | None:
        offer = self.recovery
        if offer is None:
            return None
        conflict = self._conflict(replace_run_id)
        if conflict is not False or self.recovery != offer:
            return conflict if conflict is not False else None
        owner = _FocusRun(offer.session_id, offer.phase, offer.task_id)
        return self.countdown.restore(offer.duration, offer.remaining, owner=owner)

    def discard_recovery(self):
        if self.recovery is not None:
            self.recovery = None
            self._checkpoint()
            self.recovery_changed.emit()

    def close(self):
        self.checkpoint_timer.stop()
        self.countdown.changed.disconnect(self._publish)
        self.productivity.tasks_changed.disconnect(self._check_task)
        if self.state_store is not None and self.session is not None:
            self._checkpoint()

    def start_focus(self, seconds: float = FOCUS_SECONDS, *, task_id: str | None = None,
                    replace_run_id: int | None = None) -> int | CountdownConflict | None:
        return self._start(seconds, _FocusRun(uuid4().hex, FocusPhase.FOCUS, task_id), replace_run_id)

    def start_timer(self, seconds: float, *, replace_run_id: int | None = None) -> int | CountdownConflict | None:
        return self._start(seconds, None, replace_run_id)

    def _start(self, seconds: float, owner: _FocusRun | None, replace_run_id: int | None) -> int | CountdownConflict | None:
        conflict = self._conflict(replace_run_id)
        if conflict is not False:
            return conflict
        if owner is not None and owner.task_id is not None and self.productivity.task(owner.task_id) is None:
            raise ValueError("A tarefa selecionada não existe.")
        return self.countdown.start(seconds, owner=owner)

    def _conflict(self, replace_run_id):
        """Return False when the caller can acquire the shared countdown."""
        timer = self.countdown
        if timer.state == TimerState.RUNNING and timer.remaining <= 0:
            timer.tick()
        if timer.state in ACTIVE:
            if replace_run_id != timer.run_id:
                session = self.session
                return CountdownConflict(timer.run_id, session.session_id if session else None)
        elif replace_run_id is not None:
            return None
        return False

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

    def dismiss(self, run_id):
        if self._matches(run_id, TimerState.COMPLETED):
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
        if self.recovery and self.recovery.task_id and self.productivity.task(self.recovery.task_id) is None:
            self.recovery = replace(self.recovery, task_id=None)
            saved = self.state_store.data["focus"]["session"]
            if saved is not None and saved["id"] == self.recovery.session_id:
                self.state_store.save_focus_checkpoint(saved | {"task_id": None})
            self.recovery_changed.emit()
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
