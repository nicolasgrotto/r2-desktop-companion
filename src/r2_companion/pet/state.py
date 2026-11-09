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


AUTONOMOUS = {State.BLINK, State.LOOK_AROUND, State.WALK, State.CURIOUS, State.HAPPY}


def can_request(current: State, requested: State, blocked: bool = False) -> bool:
    if blocked:
        return False
    if requested == State.INTERACT:
        return current != State.INTERACT
    if requested == State.NOTIFICATION:
        return current not in {State.INTERACT, State.HAPPY, State.NOTIFICATION}
    return current == State.IDLE and requested in AUTONOMOUS | {State.SLEEP}
