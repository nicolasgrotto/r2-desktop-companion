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
}


def bounded_clip(clip: Clip, budget: int) -> Clip:
    frames = []
    for frame in clip.frames:
        if budget <= 0:
            break
        duration = min(frame.milliseconds, budget)
        frames.append(replace(frame, milliseconds=duration))
        budget -= duration
    return Clip(tuple(frames), False)


def scene_clips(scene, clips):
    remaining = MAX_SCENE_MS
    for state, budget in scene.steps:
        if state in clips and remaining > 0:
            clip = bounded_clip(clips[state], min(budget, remaining))
            if clip.frames:
                yield state, clip
                remaining -= clip.duration
