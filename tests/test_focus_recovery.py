import json
import time

import pytest
from PySide6.QtTest import QSignalSpy

from r2_companion.features.focus import CountdownConflict, FocusPhase, FocusSessionService
from r2_companion.features.productivity import ProductivityStore
from r2_companion.features.timer import Countdown, TimerState
from r2_companion.services.companion_state import CompanionStateStore
from r2_companion.services.storage import ConfigStore


@pytest.fixture
def launch(qapp, tmp_path, clock):
    active = []

    def open_process(*, read_only=False):
        config = ConfigStore(tmp_path)
        config.read_only = read_only
        assert config.acquire()
        state = CompanionStateStore(config)
        store = ProductivityStore(tmp_path, read_only)
        focus = FocusSessionService(Countdown(clock), store, state)
        active.append((focus, state, config))
        return focus

    def close_process(*, crash=False):
        focus, state, config = active.pop()
        if crash:
            focus.checkpoint_timer.stop()
            focus.countdown.timer.stop()
        else:
            focus.close()
            focus.countdown.close()
            state.close()
        focus.productivity.close()
        config.close()

    yield open_process, close_process
    while active:
        close_process()


def test_clean_shutdown_restores_relative_time_paused_across_reboot_and_wall_clock_change(launch, clock, monkeypatch):
    open_process, close_process = launch
    focus = open_process()
    task_id = focus.productivity.add_task("Revisar")
    focus.start_focus(90, task_id=task_id)
    session_id = focus.session.session_id
    clock.advance(17.5)
    close_process()
    clock.now = 2
    monkeypatch.setattr(time, "time", lambda: 4_000_000_000)
    focus = open_process()
    assert focus.session is None and not focus.countdown.timer.isActive()
    assert not focus.checkpoint_timer.isActive()
    assert focus.recovery.session_id == session_id and focus.recovery.remaining == 72.5
    run = focus.recover()
    assert focus.session.task_id == task_id and focus.session.state == TimerState.PAUSED
    assert focus.session.override_id is None and not focus.countdown.timer.isActive()
    clock.advance(8000)
    assert focus.countdown.remaining == 72.5
    focus.resume(run)
    assert focus.session.override_id == session_id and focus.checkpoint_timer.isActive()
    focus.cancel(run)
    close_process()
    assert open_process().recovery is None


def test_crash_keeps_last_periodic_checkpoint_and_missing_task_is_detached(launch, clock):
    open_process, close_process = launch
    focus = open_process()
    task_id = focus.productivity.add_task("Apagar")
    focus.start_focus(90, task_id=task_id)
    assert focus.checkpoint_timer.interval() == 30_000 and focus.checkpoint_timer.isActive()
    clock.advance(30)
    focus.checkpoint_timer.timeout.emit()
    snapshot = json.loads(focus.state_store.path.read_text(encoding="utf-8"))["focus"]["session"]
    assert snapshot["remaining_seconds"] == 60 and "deadline" not in snapshot and "run_id" not in snapshot
    clock.advance(8)
    close_process(crash=True)
    focus = open_process()
    focus.productivity.remove("tasks", task_id)
    assert focus.recovery.task_id is None and focus.recovery.remaining == 60
    focus.recover()
    assert focus.session.task_id is None and focus.countdown.remaining == 60


def test_completed_recovery_stays_silent_and_standalone_does_not_replace_offer(launch):
    open_process, close_process = launch
    focus = open_process()
    run = focus.start_focus()
    focus.complete(run)
    close_process()

    focus = open_process()
    timer_run = focus.start_timer(30)
    conflict = focus.recover()
    assert conflict == CountdownConflict(timer_run, None)
    events, timer_events = QSignalSpy(focus.completed), QSignalSpy(focus.countdown.completed)
    run = focus.recover(replace_run_id=conflict.run_id)
    assert focus.session.state == TimerState.COMPLETED and focus.session.next_phase == FocusPhase.BREAK
    assert events.count() == timer_events.count() == 0
    focus.start_next_phase(run)
    close_process()
    focus = open_process()
    assert focus.recovery.phase == FocusPhase.BREAK and focus.recovery.remaining == 300
    focus.discard_recovery()
    focus.start_timer(30)
    close_process()
    focus = open_process()
    assert focus.recovery is None and focus.countdown.state == TimerState.STOPPED


def test_read_only_recovery_preserves_original_checkpoint(launch):
    open_process, close_process = launch
    focus = open_process()
    focus.start_focus(100)
    path = focus.state_store.path
    close_process()
    original = path.read_bytes()
    focus = open_process(read_only=True)
    run = focus.recover()
    focus.resume(run)
    assert not focus.checkpoint_timer.isActive()
    focus.cancel(run)
    close_process()
    assert path.read_bytes() == original


def test_invalid_checkpoint_does_not_offer_recovery(launch, tmp_path):
    open_process, _ = launch
    (tmp_path / "companion_state.json").write_text(json.dumps({
        "schema_version": 1, "focus": {"session": {
            "id": "session", "phase": "focus", "duration_seconds": 1500,
            "remaining_seconds": 12, "state": "completed",
        }},
    }), encoding="utf-8")
    focus = open_process()
    assert focus.state_store.notices and focus.recovery is None
    assert focus.countdown.state == TimerState.STOPPED
