"""Character scenes composed from the existing animation and voice banks."""
from dataclasses import dataclass, replace

from .animation import Clip
from .state import State

MAX_SCENE_MS = 6000
SCENE_LABELS = {
    "focus_started": "Início do foco",
    "task_completed": "Tarefa concluída",
    "media_started": "Início da música",
}


@dataclass(frozen=True)
class Scene:
    steps: tuple[tuple[State, int], ...]
    voice: str
    still_index: int = 0


CATALOG = {
    "r2_default": {
        "focus_started": Scene(((State.LOOK_AROUND, 1250), (State.WORK, 2050)), "curious"),
        "task_completed": Scene(((State.HAPPY, 1800), (State.GREETING, 1100)), "celebrate"),
        "media_started": Scene(((State.LOOK_RIGHT, 900), (State.HAPPY, 1800)), "happy"),
    },
    "dark_astromech": {
        "focus_started": Scene(((State.LOOK_LEFT, 950), (State.WORK, 2450)), "curious"),
        "task_completed": Scene(((State.HAPPY, 1350),), "celebrate"),
        "media_started": Scene(((State.LOOK_AROUND, 1750),), "greeting"),
    },
    "spherical_droid": {
        "focus_started": Scene(((State.CURIOUS, 1550), (State.WORK, 1500)), "curious"),
        "task_completed": Scene(((State.HAPPY, 1550), (State.LOOK_AROUND, 1450)), "celebrate"),
        "media_started": Scene(((State.CURIOUS, 1450), (State.HAPPY, 1450)), "happy"),
    },
    "lumo": {
        "focus_started": Scene(((State.LOOK_AROUND, 1200), (State.WORK, 1440)), "curious", still_index=3),
        "task_completed": Scene(((State.HAPPY, 1440), (State.RECOVER, 960)), "celebrate", still_index=3),
        "media_started": Scene(((State.CURIOUS, 1080), (State.HAPPY, 1440)), "happy", still_index=3),
    },
    "vigia": {
        "focus_started": Scene(((State.LOOK_LEFT, 960), (State.LOOK_RIGHT, 960), (State.WORK, 1440)),
                               "curious", still_index=3),
        "task_completed": Scene(((State.HAPPY, 1200), (State.LOOK_AROUND, 1440)), "celebrate", still_index=3),
        "media_started": Scene(((State.LOOK_AROUND, 1200), (State.CURIOUS, 1440)), "curious", still_index=3),
    },
    "pico": {
        "focus_started": Scene(((State.CURIOUS, 960), (State.WORK, 1320)), "curious", still_index=3),
        "task_completed": Scene(((State.HAPPY, 1200), (State.GREETING, 1080)), "celebrate", still_index=3),
        "media_started": Scene(((State.LOOK_RIGHT, 840), (State.CURIOUS, 1200)), "greeting", still_index=3),
    },
    "tranco": {
        "focus_started": Scene(((State.WORK, 1440),), "curious", still_index=4),
        "task_completed": Scene(((State.HAPPY, 1440), (State.GREETING, 1440)), "celebrate", still_index=4),
        "media_started": Scene(((State.GREETING, 1320), (State.HAPPY, 1440)), "greeting", still_index=4),
    },
}


def bounded_clip(clip: Clip, budget: int) -> Clip:
    frames = []
    for frame in clip.frames:
        if budget <= 0:
            break
        duration = min(frame.milliseconds, budget)
        frames.append(replace(frame, milliseconds=duration))
        budget -= duration
    return Clip(tuple(frames), False, min(clip.still_index, max(0, len(frames) - 1)))


def scene_clips(scene, clips):
    remaining = MAX_SCENE_MS
    for state, budget in scene.steps:
        if state in clips and remaining > 0:
            original = replace(clips[state], still_index=scene.still_index)
            clip = bounded_clip(original, min(budget, remaining))
            if clip.frames:
                yield state, clip
                remaining -= clip.duration
