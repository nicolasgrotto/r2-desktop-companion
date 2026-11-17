import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QSignalSpy

from r2_companion.features.focus import CountdownConflict, FocusPhase, FocusSessionService
from r2_companion.features.productivity import ProductivityStore
from r2_companion.features.timer import Countdown, TimerState
from test_context_v03 import pet


@pytest.fixture
def focus(qapp, clock, tmp_path):
    timer = Countdown(clock)
    store = ProductivityStore(tmp_path)
    yield FocusSessionService(timer, store)
    timer.close()
    store.close()


def test_focus_pause_resume_restart_and_cancel(focus, clock):
    timer = focus.countdown
    changed, completed = QSignalSpy(focus.changed), QSignalSpy(focus.completed)
    first = focus.start_focus()
    session = focus.session
    assert session.run_id == first == timer.run_id
    assert session.duration == timer.remaining == 25 * 60
    assert session.override_id == session.session_id and session.task_id is None
    clock.advance(15)
    timer.tick()
    assert changed.count() == 1
    focus.pause(first)
    assert focus.session.state == TimerState.PAUSED and focus.session.override_id is None
    clock.advance(3600)
    assert timer.remaining == 25 * 60 - 15
    focus.resume(first)
    assert focus.session.override_id == session.session_id and timer.remaining == 25 * 60 - 15
    second = focus.restart(first)
    assert second != first and focus.session.session_id == session.session_id
    assert timer.remaining == 25 * 60
    focus.cancel(first)
    assert focus.session.run_id == second
    focus.cancel(second)
    clock.advance(1800)
    timer.tick()
    assert focus.session is None and timer.state == TimerState.STOPPED
    assert not timer.timer.isActive() and completed.count() == 0


def test_focus_offers_break_then_new_cycle_only_on_request(focus, clock):
    task = focus.productivity.add_task("Revisar")
    run = focus.start_focus(task_id=task)
    timer = focus.countdown
    session_id = focus.session.session_id
    finished = []
    focus.completed.connect(finished.append)
    assert focus.start_next_phase(run) is None and focus.session.next_phase is None
    # No Qt events while suspended. The first tick after wake sees the expired uptime deadline.
    clock.advance(7200)
    timer.tick()
    timer.tick()
    assert [item.run_id for item in finished] == [run]
    assert focus.session.next_phase == FocusPhase.BREAK and focus.session.override_id is None
    assert timer.state == TimerState.COMPLETED and not timer.timer.isActive()
    assert not focus.productivity.task(task)["done"]

    rest = focus.start_next_phase(run)
    assert timer.run_id == rest and rest != run and timer.remaining == 300
    assert focus.session.phase == FocusPhase.BREAK and focus.session.session_id == session_id
    assert focus.session.task_id == task and focus.session.override_id is None
    focus.pause(rest)
    clock.advance(7200)
    timer.tick()
    assert timer.remaining == 300
    focus.resume(rest)
    assert focus.session.override_id is None
    clock.advance(300)
    timer.tick()
    assert [item.run_id for item in finished] == [run, rest]
    assert focus.session.next_phase == FocusPhase.FOCUS and not timer.timer.isActive()
    assert not focus.complete_task(rest)
    third = focus.start_next_phase(rest)
    assert focus.session.run_id == third and third != rest
    assert focus.session.session_id != session_id and focus.session.task_id == task
    assert focus.session.phase == FocusPhase.FOCUS and timer.remaining == 1500


@pytest.mark.parametrize("paused", [False, True])
def test_two_way_conflict_binds_confirmation_to_observed_run(focus, clock, paused):
    timer = focus.countdown
    standalone = timer.start(60)
    clock.advance(7)
    if paused:
        timer.pause()
    conflict = focus.start_focus()
    assert conflict == CountdownConflict(standalone, None)
    assert timer.remaining == 53 and focus.session is None
    run = focus.start_focus(replace_run_id=conflict.run_id)
    if paused:
        focus.pause(run)
    expected = CountdownConflict(run, focus.session.session_id)
    assert focus.start_timer(80) == expected
    assert focus.start_focus(replace_run_id=standalone) == expected
    assert timer.run_id == run and timer.remaining == 1500
    assert timer.state == (TimerState.PAUSED if paused else TimerState.RUNNING)
    with pytest.raises(ValueError):
        focus.start_timer(0, replace_run_id=run)
    assert focus.session.session_id == expected.session_id
    new_timer = focus.start_timer(80, replace_run_id=run)
    assert timer.run_id == new_timer and timer.remaining == 80 and focus.session is None
    focus.cancel(run)
    assert timer.state == TimerState.RUNNING


def test_expired_confirmation_leaves_completed_run_available(focus, clock):
    run = focus.start_focus(1)
    conflict = focus.start_timer(30)
    clock.advance(2)
    assert focus.start_timer(30, replace_run_id=conflict.run_id) is None
    assert focus.session.run_id == run and focus.session.next_phase == FocusPhase.BREAK


def test_companion_session_resume_reconciles_the_shared_deadline(pet, clock):
    pet.countdown.clock = clock
    focus = FocusSessionService(pet.countdown, pet.productivity)
    completed = QSignalSpy(focus.completed)
    run = focus.start_focus(60)
    pet.session_events.signals.suspended.emit(True)
    clock.advance(45)
    pet.session_events.signals.suspended.emit(False)
    assert focus.session.run_id == run and pet.countdown.remaining == 15
    assert completed.count() == 0
    pet.session_events.signals.suspended.emit(True)
    clock.advance(90)
    pet.session_events.signals.suspended.emit(False)
    assert completed.count() == 1 and focus.session.state == TimerState.COMPLETED
    assert focus.session.next_phase == FocusPhase.BREAK and not pet.countdown.timer.isActive()


@pytest.mark.parametrize("cancel_first", [False, True])
def test_cancel_and_expiration_at_same_deadline(focus, clock, cancel_first):
    finished = QSignalSpy(focus.completed)
    run = focus.start_focus(2)
    clock.advance(2)
    if cancel_first:
        focus.cancel(run)
    focus.pause(run)  # An expired deadline completes instead of pausing at zero.
    focus.countdown.tick()
    focus.cancel(run)
    focus.complete(run)
    assert finished.count() == (0 if cancel_first else 1)
    if cancel_first:
        assert focus.session is None
    else:
        assert focus.session.state == TimerState.COMPLETED
    assert not focus.countdown.timer.isActive()


def test_late_events_and_commands_cannot_affect_replacements(focus, clock, qapp):
    timer = focus.countdown
    completions = QSignalSpy(focus.completed)
    standalone = focus.start_timer(2)
    queued_runs = []

    def delayed_completion(run_id):
        queued_runs.append(run_id)
        focus.complete(run_id)

    timer.completed.connect(delayed_completion, Qt.ConnectionType.QueuedConnection)
    timer.completed.emit(standalone)  # Queued before the caller confirms replacement.
    first = focus.start_focus(5, replace_run_id=standalone)
    qapp.processEvents()
    assert queued_runs == [standalone] and focus.session.state == TimerState.RUNNING
    clock.advance(5)
    timer.tick()
    assert completions.count() == 1
    second = focus.start_focus(10)
    second_session = focus.session
    QTimer.singleShot(0, lambda: focus.cancel(first))
    qapp.processEvents()
    assert queued_runs == [standalone, first]
    assert focus.session == second_session and timer.remaining == 10
    assert focus.restart(first) is None and focus.start_next_phase(first) is None
    focus.complete(second)
    timer.completed.emit(second)
    timer.tick()
    qapp.processEvents()
    assert completions.count() == 2 and focus.session.state == TimerState.COMPLETED


def test_closing_shared_timer_releases_running_focus(focus):
    run = focus.start_focus()
    changes = []
    focus.changed.connect(changes.append)
    focus.countdown.close()
    focus.complete(run)
    assert changes == [None] and focus.session is None and not focus.countdown.timer.isActive()


@pytest.mark.parametrize("removed_by", ["delete", "restore"])
def test_missing_task_unlinks_without_interrupting_timer_or_relinking_on_undo(focus, clock, removed_by):
    store = focus.productivity
    task = store.add_task("Vinculada")
    other = store.add_task("Outra")
    run = focus.start_focus(45, task_id=task)
    session_id = focus.session.session_id
    store.remove("tasks", other)
    assert focus.session.task_id == task
    clock.advance(8)
    if removed_by == "delete":
        store.remove("tasks", task)
        assert store.undo_remove() == "tasks"
    else:
        store.accept_restored(store.data | {"tasks": []})
    assert focus.session.task_id is None and focus.session.override_id == session_id
    assert focus.countdown.run_id == run and focus.countdown.remaining == 37
    focus.complete(run)
    assert not focus.complete_task(run)
    with pytest.raises(ValueError):
        focus.start_focus(task_id=other)
    assert focus.session.run_id == run


@pytest.mark.parametrize("already_done", [False, True])
def test_linked_task_completion_is_explicit_and_idempotent(focus, already_done):
    store = focus.productivity
    task = store.add_task("Conferir")
    done = QSignalSpy(store.task_completed)
    run = focus.start_focus(task_id=task)
    if already_done:
        store.set_done(task, True)
    assert not focus.complete_task(run)
    focus.pause(run)
    focus.complete(run)
    assert store.task(task)["done"] == already_done and done.count() == int(already_done)
    assert focus.complete_task(run) == (not already_done)
    assert not focus.complete_task(run)
    assert done.count() == 1 and done.at(0) == [task]
