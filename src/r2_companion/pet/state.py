from enum import Enum


class State(str, Enum):
    IDLE = "IDLE"
    BLINK = "BLINK"
    LOOK_AROUND = "LOOK_AROUND"
    WALK = "WALK"
    HAPPY = "HAPPY"
    CURIOUS = "CURIOUS"
    SLEEP = "SLEEP"
    INTERACT = "INTERACT"
    NOTIFICATION = "NOTIFICATION"
    SURPRISED = "SURPRISED"
    WORK = "WORK"
    CONFUSED = "CONFUSED"
    DRAG = "DRAG"
    RECOVER = "RECOVER"
    WAKE = "WAKE"
    GREETING = "GREETING"
    WORRIED = "WORRIED"
    OVERHEAT = "OVERHEAT"
    LOOK_LEFT = "LOOK_LEFT"
    LOOK_RIGHT = "LOOK_RIGHT"


AUTONOMOUS = {State.BLINK, State.LOOK_AROUND, State.WALK, State.CURIOUS, State.HAPPY,
              State.SURPRISED, State.WORK, State.LOOK_LEFT, State.LOOK_RIGHT}


def can_request(current: State, requested: State, blocked: bool = False) -> bool:
    if blocked:
        return False
    if requested == State.INTERACT:
        return current != State.INTERACT
    if requested == State.NOTIFICATION:
        return current not in {State.INTERACT, State.HAPPY, State.NOTIFICATION}
    return current == State.IDLE and requested in AUTONOMOUS | {State.SLEEP}
