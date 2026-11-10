from copy import deepcopy
from datetime import datetime

PROFILES = {
    "calm": ("quiet", 90, 180, {"IDLE": 80, "BLINK": 18, "LOOK_AROUND": 6, "CURIOUS": 2, "HAPPY": 1, "SURPRISED": 0, "WORK": 2}),
    "curious": ("normal", 30, 90, {"IDLE": 45, "BLINK": 15, "LOOK_AROUND": 18, "CURIOUS": 20, "HAPPY": 3, "SURPRISED": 2, "WORK": 8}),
    "talkative": ("normal", 20, 30, {"IDLE": 35, "BLINK": 12, "LOOK_AROUND": 10, "CURIOUS": 16, "HAPPY": 15, "SURPRISED": 4, "WORK": 5})}


def apply_profile(settings, name):
    result = deepcopy(settings)
    result.personality = name
    if name == "custom":
        return result
    frequency, interval, audio_interval, weights = PROFILES[name]
    result.behavior.frequency = frequency
    result.behavior.reaction_interval = interval
    result.behavior.weights = dict(weights)
    result.audio.idle_interval = audio_interval
    return result


def quiet_now(settings, moment=None):
    if not settings.quiet_enabled:
        return False
    moment = moment or datetime.now()
    minute = moment.hour * 60 + moment.minute
    start, end = settings.quiet_start, settings.quiet_end
    return (start <= minute < end) if start < end else (minute >= start or minute < end) if start != end else True
