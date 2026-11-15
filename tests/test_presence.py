from dataclasses import FrozenInstanceError, fields, replace
from itertools import product

import pytest

from r2_companion.pet.presence import (
    FullscreenAction, PresenceContext, PresenceDecision, PresenceMode, PresencePolicy,
)


def decision(**values):
    return PresencePolicy.evaluate(PresenceContext(**values))


@pytest.mark.parametrize("context,expected", [
    ({}, dict(autonomous_movement=True, initiative=True, spontaneous_audio=False,
              explicit_reactions=True, notifications=True, character_visible=True, reason="free")),
    ({"manual_mode": "focus", "quiet_hours": True, "sound_enabled": True},
     dict(autonomous_movement=False, initiative=False, spontaneous_audio=False,
          explicit_audio=False, notifications=False, explicit_reactions=True, reason="quiet_hours")),
    ({"manual_mode": "presentation", "focus_session_id": "timer-1", "sound_enabled": True},
     dict(autonomous_movement=False, initiative=False, spontaneous_audio=False,
          explicit_reactions=False, notifications=False, character_visible=False,
          passive_surfaces=False, continuous_effects=False, reason="presentation")),
    ({"media_playing": True, "sound_enabled": False},
     dict(spontaneous_audio=False, explicit_audio=False, explicit_reactions=True, notifications=True)),
    ({"media_playing": True, "sound_enabled": True},
     dict(spontaneous_audio=False, explicit_audio=True, autonomous_movement=True, notifications=True)),
    ({"hidden": True}, dict(notifications=False, explicit_reactions=False,
                            character_visible=False, passive_surfaces=False, reason="hidden")),
    ({"manual_mode": "focus", "sound_enabled": True},
     dict(autonomous_movement=False, spontaneous_audio=False, initiative=True,
          explicit_reactions=True, explicit_audio=True, notifications=True, passive_surfaces=True)),
    ({"reduced_motion": True}, dict(autonomous_movement=False, continuous_effects=False,
                                    initiative=True, explicit_reactions=True, passive_surfaces=True)),
    ({"paused": True, "sound_enabled": True},
     dict(autonomous_movement=False, initiative=False, spontaneous_audio=False,
          explicit_reactions=True, explicit_audio=True, notifications=True)),
    ({"autonomy_enabled": False, "sound_enabled": True},
     dict(autonomous_movement=False, initiative=False, spontaneous_audio=False, explicit_reactions=True)),
    ({"movement_enabled": False, "sound_enabled": True},
     dict(autonomous_movement=False, initiative=True, spontaneous_audio=True)),
    ({"muted": True, "sound_enabled": True}, dict(spontaneous_audio=False, explicit_audio=False)),
])
def test_product_combination_table(context, expected):
    actual = decision(**context)
    for name, value in expected.items():
        assert getattr(actual, name) == value, name
    assert actual.reason_text


@pytest.mark.parametrize("action,visible", [("hide", False), ("corner", True), ("stay", True)])
def test_fullscreen_preserves_resolved_visibility_but_suspends_effects(action, visible):
    result = decision(fullscreen=action, sound_enabled=True)
    assert result.character_visible == visible
    assert not any((result.autonomous_movement, result.initiative, result.spontaneous_audio,
                    result.explicit_audio, result.explicit_reactions, result.notifications,
                    result.passive_surfaces, result.continuous_effects))


@pytest.mark.parametrize("gate", ["menu", "drag", "droid_swap", "radial", "settings", "future_gate"])
def test_transient_gates_block_new_actions_without_hiding_character(gate):
    result = decision(transient_gates={gate}, sound_enabled=True)
    assert result.character_visible
    assert not any((result.autonomous_movement, result.initiative, result.spontaneous_audio,
                    result.explicit_audio, result.explicit_reactions, result.notifications,
                    result.passive_surfaces, result.continuous_effects))
    assert result.reason == "transient"


@pytest.mark.parametrize("mode", list(PresenceMode))
def test_manual_selection_revokes_focus_even_if_effective_mode_is_unchanged(mode):
    start = PresenceContext().begin_focus("session-a")
    assert start.manual_mode == PresenceMode.FREE and start.effective_mode == PresenceMode.FOCUS
    manual = start.select_mode(mode)
    assert manual.focus_session_id is None and manual.effective_mode == mode
    assert manual.end_focus("session-a") is manual


def test_focus_ownership_prevents_stale_completion_from_releasing_new_session():
    start = PresenceContext().begin_focus("old")
    newer = start.begin_focus("new")
    assert newer.end_focus("old") is newer
    ended = newer.end_focus("new")
    assert ended.effective_mode == PresenceMode.FREE and ended.focus_session_id is None
    manual_focus = PresenceContext(manual_mode="focus").begin_focus("timer")
    assert manual_focus.end_focus("timer").effective_mode == PresenceMode.FOCUS
    presentation = PresenceContext(manual_mode="presentation").begin_focus("timer")
    assert presentation.effective_mode == PresenceMode.PRESENTATION
    assert presentation.end_focus("timer").effective_mode == PresenceMode.PRESENTATION


@pytest.mark.parametrize("value", ["", "x" * 81, "bad\nreference", 123])
def test_invalid_session_references_are_rejected(value):
    with pytest.raises(ValueError):
        PresenceContext(focus_session_id=value)
    with pytest.raises(ValueError):
        PresenceContext().begin_focus(value)


def test_context_is_immutable_and_does_not_alias_mutable_gates():
    gates = {"menu"}
    context = PresenceContext(transient_gates=gates)
    gates.clear()
    assert context.transient_gates == frozenset({"menu"})
    with pytest.raises(FrozenInstanceError):
        context.hidden = True
    with pytest.raises(ValueError):
        PresenceContext(manual_mode="invalid")
    with pytest.raises(ValueError):
        PresenceContext(fullscreen="auto")  # Resolve using existing geometry policy first.


def test_updates_distinguish_context_changes_from_effect_changes(monkeypatch):
    policy = PresencePolicy()
    context = PresenceContext(hidden=True)
    initial = policy.update(context)
    assert initial.context_changed and initial.decision_changed
    evaluate = policy.evaluate
    calls = []
    monkeypatch.setattr(policy, "evaluate", lambda value: (calls.append(value), evaluate(value))[1])
    same = policy.update(replace(context))
    assert not same.context_changed and not same.decision_changed and not calls
    assert same.decision is initial.decision
    changed = policy.update(replace(context, media_playing=True))
    assert changed.context_changed and not changed.decision_changed and len(calls) == 1
    visible = policy.update(PresenceContext())
    assert visible.context_changed and visible.decision_changed and len(calls) == 2
    assert PresencePolicy().update(PresenceContext()).decision == visible.decision


def test_combined_restrictions_never_reenable_a_permission():
    permissions = [field.name for field in fields(PresenceDecision)
                   if field.name not in {"mode", "reason", "reason_text"}]
    restrictions = ["quiet_hours", "hidden", "suspended", "reduced_motion", "media_playing", "paused", "muted"]
    for mode, fullscreen, flags in product(PresenceMode, FullscreenAction, product((False, True), repeat=7)):
        context = PresenceContext(manual_mode=mode, fullscreen=fullscreen, sound_enabled=True,
                                  **dict(zip(restrictions, flags)))
        before = PresencePolicy.evaluate(context)
        for restriction, active in zip(restrictions, flags):
            if not active:
                after = PresencePolicy.evaluate(replace(context, **{restriction: True}))
                assert all(not getattr(after, name) or getattr(before, name) for name in permissions), (context, restriction)
        if context.suspended:
            assert not any(getattr(before, name) for name in permissions)
            assert before.reason == "suspended"


@pytest.mark.parametrize("fullscreen", list(FullscreenAction))
def test_presentation_without_tray_keeps_static_recovery_surface(fullscreen):
    context = PresenceContext(manual_mode="presentation", tray_available=False, fullscreen=fullscreen)
    result = PresencePolicy.evaluate(context)
    assert result.character_visible and result.reason == "presentation_recovery"
    assert not any((result.initiative, result.autonomous_movement, result.spontaneous_audio,
                    result.explicit_audio, result.explicit_reactions, result.passive_surfaces,
                    result.notifications, result.continuous_effects))
    assert not PresencePolicy.evaluate(replace(context, suspended=True)).character_visible
