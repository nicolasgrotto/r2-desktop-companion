import random

import pytest
from PySide6.QtTest import QSignalSpy

from r2_companion.core.config import BehaviorSettings
from r2_companion.features.timer import Countdown, TimerState
from r2_companion.pet.behavior import BehaviorManager
from r2_companion.pet.state import State, can_request


def test_countdown_pause_resume_restart_and_exactly_once(qapp, clock):
    timer = Countdown(clock)
    spy = QSignalSpy(timer.completed)
    timer.start(10)
    clock.advance(4)
    timer.pause()
    assert timer.remaining == pytest.approx(6)
    clock.advance(100)
    assert timer.remaining == pytest.approx(6)
    timer.resume()
    clock.advance(7)
    timer.tick()
    timer.tick()
    assert timer.state == TimerState.COMPLETED and spy.count() == 1
    timer.restart()
    assert timer.run_id == 2 and timer.remaining == 10
    clock.advance(10000)
    timer.tick()
    assert spy.count() == 2
    timer.close()
    assert not timer.timer.isActive()


def test_pause_at_deadline_completes_without_resurrection(qapp, clock):
    timer = Countdown(clock)
    timer.start(1)
    clock.advance(2)
    timer.pause()
    timer.resume()
    assert timer.state == TimerState.COMPLETED


@pytest.mark.parametrize("value", [0, -1, 86401, float("nan"), float("inf")])
def test_timer_rejects_invalid_duration(qapp, clock, value):
    with pytest.raises(ValueError):
        Countdown(clock).start(value)


def test_behavior_cooldown_no_immediate_repeat_and_off(qapp, clock):
    behavior = BehaviorManager(clock, random.Random(7))
    behavior.accepted(State.WALK)
    assert all(behavior.choose() != State.WALK for _ in range(300))
    clock.advance(181)
    behavior.accepted(State.BLINK)
    options = {behavior.choose() for _ in range(1000)}
    assert State.WALK in options and State.BLINK not in options
    behavior.settings.movement = False
    assert all(behavior.choose() != State.WALK for _ in range(500))
    behavior.settings.frequency = "off"
    behavior.schedule(True)
    assert not behavior.timer.isActive()
    assert behavior.choose() == State.IDLE


def test_seeded_behavior_is_repeatable(qapp, clock):
    first, second = BehaviorManager(clock, random.Random(1)), BehaviorManager(clock, random.Random(1))
    assert [first.choose() for _ in range(100)] == [second.choose() for _ in range(100)]


def test_first_walk_has_a_deadline_and_cannot_be_starved_by_idle_choices(qapp, clock):
    behavior = BehaviorManager(clock, random.Random(10))
    deadline = behavior.next_walk_at
    assert clock() + 15 <= deadline <= clock() + 25
    for _ in range(10):
        behavior.schedule(True)
        assert behavior.next_walk_at == deadline
    clock.now = deadline + 0.1
    assert behavior.choose() == State.WALK
    behavior.accepted(State.WALK)
    assert clock() + 75 <= behavior.next_walk_at <= clock() + 120
    assert behavior.choose() != State.WALK
    behavior.close()


def test_walk_deadline_respects_disable_and_interaction_quiet_time(qapp, clock):
    behavior = BehaviorManager(clock, random.Random(10))
    clock.advance(30)
    behavior.settings.movement = False
    assert behavior.choose() != State.WALK
    behavior.settings.movement = True
    behavior.defer_walk(12)
    assert behavior.choose() != State.WALK
    clock.advance(13)
    assert behavior.choose() == State.WALK
    behavior.settings.frequency = "off"
    assert behavior.choose() == State.IDLE
    behavior.close()


@pytest.mark.parametrize("current", list(State))
def test_drag_gate_rejects_every_requested_state(current):
    assert all(not can_request(current, requested, blocked=True) for requested in State)
