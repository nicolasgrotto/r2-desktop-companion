import random
from copy import deepcopy

import pytest
from PySide6.QtTest import QSignalSpy

from r2_companion.pet.behavior import BehaviorManager
from r2_companion.pet.reactions import Priority
from r2_companion.pet.state import State
from test_animation_controller_ui import clips, controller
from test_context_v03 import pet


def test_same_instant_drains_in_priority_order(controller):
    c = controller
    c.set_gate("menu", True)
    c.autonomous(State.BLINK)
    c.react(State.WORRIED, spontaneous=True)
    c.notify("done", "Concluído")
    c.react(State.GREETING)
    states = []
    c.state_changed.connect(states.append)
    c.set_gate("menu", False)
    for _ in range(4):
        c.finished(c.token)
    assert [state for state in states if state != State.IDLE] == [
        State.GREETING, State.NOTIFICATION, State.WORRIED, State.BLINK,
    ]
    assert not c.reactions.pending and c.state == State.IDLE


def test_higher_priority_interrupts_active_intent_and_old_tokens_are_inert(controller):
    c = controller
    c.autonomous(State.WORK)
    autonomous = c.token
    c.react(State.CURIOUS, spontaneous=True)
    context = c.token
    assert c.state == State.CURIOUS
    c.reactions.start("task", key="id")
    completion = c.token
    c.interact()
    interaction = c.token
    assert autonomous < context < completion < interaction
    for stale in (autonomous, context, completion):
        c.finished(stale)
    assert c.state == State.INTERACT and c.reactions.scene is None
    assert not c.reactions.start("task", key="id") and c.token == interaction


def test_full_queue_preserves_fifo_and_protects_high_priorities(controller):
    c = controller
    c.set_gate("menu", True)
    c.autonomous(State.BLINK)
    for index in range(7):
        assert c.notify(str(index), f"Aviso {index}")
    assert c.react(State.CURIOUS, spontaneous=True)  # displaces spontaneous
    assert not c.reactions.offer("another", State.BLINK, Priority.SPONTANEOUS)
    assert c.react(State.GREETING)
    assert len(c.reactions.pending) == 8
    results = QSignalSpy(c.notification_presented)
    c.set_gate("menu", False)
    assert c.state == State.GREETING
    for _ in range(8):
        c.finished(c.token)
    assert [results.at(i)[0] for i in range(results.count())] == [f"Aviso {i}" for i in range(7)]
    assert c.state == State.IDLE


@pytest.mark.parametrize("elapsed,plays", [(9.99, True), (10, False), (600, False)])
def test_queued_completion_has_a_ten_second_deadline(controller, clock, elapsed, plays):
    c = controller
    c.set_gate("drag", True)
    c.notify("run", "Foco concluído")
    assert not c.notify("run", "Foco concluído")
    delivered = QSignalSpy(c.notification_presented)
    clock.advance(elapsed)
    c.set_gate("drag", False)
    assert delivered.count() == int(plays)
    assert not c.notify("run", "Foco concluído")
    assert not c.reactions.pending


def test_pausing_drops_initiative_but_allows_task_and_explicit_action(controller):
    c = controller
    c.set_gate("menu", True)
    c.react(State.WORRIED, spontaneous=True)
    c.autonomous(State.BLINK)
    c.reactions.start("task", key="task")
    c.set_paused(True)
    c.set_gate("menu", False)
    assert c.reactions.scene == "task"
    token = c.token
    c.set_paused(False)
    c.set_paused(True)
    assert c.token == token and c.reactions.scene == "task"
    assert not c.react(State.WORK, spontaneous=True)
    assert c.react(State.GREETING)
    c.finished(c.token)
    assert c.state == State.IDLE and not c.behavior.timer.isActive() and not c.reactions.pending


def test_profile_capabilities_filter_scene_or_drop_without_private_reason(controller):
    c = controller
    c.animation.clips = {key: c.animation.clips[key] for key in (State.IDLE, State.HAPPY)}
    assert c.reactions.start("task", key="private-task")
    assert c.state == State.HAPPY
    assert not c.react(State.WORRIED, source="private-source")
    assert c.reactions.last_drop_reason == "unsupported"


def test_last_eight_accepted_choices_and_weighted_fallback(qapp, clock):
    behavior = BehaviorManager(clock, random.Random(9))
    behavior.settings.movement = False
    behavior.settings.weights = {"IDLE": 0, "BLINK": 1, "WORK": 100}
    for _ in range(12):
        behavior.accepted(State.WORK)
        clock.advance(301)
    assert list(behavior.recent) == [State.WORK] * 8
    assert {behavior.choose() for _ in range(50)} == {State.BLINK}
    behavior.accepted(State.BLINK)
    assert behavior.choose() == State.WORK
    behavior.settings.weights["BLINK"] = 0
    behavior.accepted(State.WORK)
    assert behavior.choose() == State.IDLE
    clock.advance(301)
    assert behavior.choose() == State.WORK
    behavior.supports = lambda state: state != State.WORK
    assert behavior.choose() == State.IDLE
    behavior.close()


def test_context_does_not_restart_an_active_reaction_on_duplicate(controller):
    assert controller.react(State.WORRIED, spontaneous=True, source="battery")
    token = controller.token
    assert not controller.react(State.WORRIED, spontaneous=True, source="battery")
    assert controller.token == token and not controller.reactions.pending


def test_weighted_choice_uses_configured_weights_of_eligible_alternatives(controller, monkeypatch):
    behavior = controller.behavior
    behavior.settings.movement = False
    behavior.settings.weights = {"CURIOUS": 70, "BLINK": 3, "WORK": 17}
    controller.react(State.CURIOUS, spontaneous=True)
    observed = []

    def choose(options, weights, k):
        observed.extend(zip(options, weights))
        return [options[0]]

    monkeypatch.setattr(behavior.rng, "choices", choose)
    assert behavior.choose() == State.BLINK
    assert observed == [(State.BLINK, 3), (State.WORK, 17)]


def test_focus_completion_is_presented_and_voiced_once(pet, clock, monkeypatch):
    pet.countdown.clock = clock
    voices, tray = [], []
    monkeypatch.setattr(pet.audio, "vocalize", lambda *args: voices.append(args))
    monkeypatch.setattr(pet.tray, "notify", tray.append)
    notices = QSignalSpy(pet.controller.notification_presented)
    pet.focus.start_focus(1)
    voices.clear()
    clock.advance(1)
    pet.countdown.tick()
    pet.focus_completed(pet.focus.session)
    assert voices == [("celebrate", "notifications")]
    assert len(tray) == notices.count() == 1


def test_focus_completion_in_presentation_remains_in_tools_without_replay(pet, clock, monkeypatch):
    monkeypatch.setattr("r2_companion.pet.presence_runtime.QSystemTrayIcon.isSystemTrayAvailable", lambda: True)
    pet.countdown.clock = clock
    run = pet.focus.start_focus(5)
    pet.presence.select_mode("presentation")
    clock.advance(6)
    pet.countdown.tick()
    assert pet.focus.session.run_id == run and pet.focus.session.next_phase is not None
    assert not pet.tools.focus_page.next_button.isHidden() and not pet.reactions.pending
    pet.presence.select_mode("free")
    assert pet.controller.state == State.IDLE and pet.reactions.active is None


def test_droid_swap_invalidates_active_and_pending_completion_then_accepts_new_event(pet, monkeypatch):
    voices = []
    monkeypatch.setattr(pet.audio, "vocalize", lambda *args: voices.append(args))
    task = pet.productivity.add_task("Primeira")
    queued = pet.productivity.add_task("Segunda")
    backup = deepcopy(pet.productivity.data)
    pet.productivity.set_done(task, True)
    old_token = pet.controller.token
    pet.productivity.set_done(queued, True)
    assert pet.reactions.scene == "task_completed" and len(pet.reactions.pending) == 1
    assert voices == [("celebrate", "reactions")]
    voices.clear()
    assert pet.equip_droid("spherical_droid")
    new_token = pet.controller.token
    after_swap = tuple(voices)
    pet.controller.finished(old_token)
    assert pet.reactions.scene is None and not pet.reactions.pending
    assert ("celebrate", "reactions") not in after_swap
    assert pet.productivity.task(queued)["done"]
    pet.task_completed(queued)
    assert pet.controller.token == new_token and tuple(voices) == after_swap
    pet.productivity.set_done(queued, False)
    pet.productivity.set_done(queued, True)
    pet.controller.finished(pet.controller.token)
    assert voices[len(after_swap):] == [("celebrate", "reactions")]
    pet.controller.finished(pet.controller.token)
    pet.productivity.accept_restored(backup)
    pet.productivity.set_done(queued, True)
    assert pet.reactions.scene == "task_completed"
