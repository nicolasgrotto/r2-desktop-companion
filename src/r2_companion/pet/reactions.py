from collections import deque

from .state import State, AUTONOMOUS

SCENES = {"task": (State.LOOK_AROUND, State.HAPPY), "game": (State.GREETING, State.HAPPY),
          "diagnosis": (State.WORK, State.LOOK_AROUND, State.HAPPY),
          "affection": (State.CURIOUS, State.HAPPY)}
EMOTIONS = {State.CURIOUS: ("curious", "idle"), State.HAPPY: ("happy", "idle"),
            State.WORK: ("curious", "idle"), State.CONFUSED: ("confused", "reactions"),
            State.SURPRISED: ("surprised", "reactions"), State.WORRIED: ("worried", "reactions"),
            State.OVERHEAT: ("worried", "reactions"), State.GREETING: ("greeting", "reactions"),
            State.WAKE: ("wake", "sleep"), State.INTERACT: ("greeting", "reactions"),
            State.NOTIFICATION: ("celebrate", "notifications")}


class ReactionDirector:
    def __init__(self, controller, audio):
        self.controller, self.audio = controller, audio
        self.queue = deque()
        self.scene = None
        self.previous = State.IDLE
        self.controller.state_changed.connect(self.changed)

    def start(self, scene):
        if scene not in SCENES or self.controller.gates or self.controller.inactive or self.controller.closed:
            return False
        self.previous = self.controller.state if self.controller.state in AUTONOMOUS - {State.WALK} else State.IDLE
        self.scene = scene
        self.queue = deque(state for state in SCENES[scene] if self.controller.supports(state))
        if not self.queue:
            self.scene = None
            return False
        self.controller.react(self.queue.popleft())
        return True

    def changed(self, state):
        if self.controller.gates or state in {State.DRAG, State.SLEEP, State.INTERACT}:
            self.queue.clear()
            self.scene = None
        if state == State.IDLE and self.scene:
            if self.queue and not self.controller.inactive and not self.controller.pending_notifications:
                self.controller.react(self.queue.popleft())
                return
            previous = self.previous
            self.queue.clear()
            self.scene = None
            if previous != State.IDLE and not self.controller.inactive and not self.controller.gates:
                self.controller.react(previous)
                return
        if self.scene:
            if state == State.HAPPY:
                self.audio.vocalize("affection" if self.scene == "affection" else "celebrate", "reactions")
        elif state == State.SLEEP:
            self.audio.vocalize("sleep", "sleep")
        elif state == State.WALK:
            self.audio.play("movement", "servo")
        elif state in EMOTIONS:
            self.audio.vocalize(*EMOTIONS[state])

    def close(self):
        self.queue.clear()
        self.scene = None
