import time

from PySide6.QtCore import QObject, Signal

from .behavior import BehaviorManager
from .reactions import Priority, ReactionDirector
from .state import State, can_request


class PetController(QObject):
    state_changed = Signal(object)
    notification_presented = Signal(str)
    woke = Signal(float)
    context_changed = Signal()

    def __init__(self, animation, positioning, behavior: BehaviorManager, clock=time.monotonic, *, audio=None):
        super().__init__()
        self.animation = animation
        self.positioning = positioning
        self.behavior = behavior
        self.clock = clock
        self.state = State.IDLE
        self.token = 0
        self.gates: set[str] = set()
        self.reactions = ReactionDirector(self, audio)
        self.inactive = False
        self.closed = False
        self.paused = False
        self.last_click = -1000.0
        self.sleep_started = None
        self.sleep_entered = None
        self.next_destination = None
        self.presence = None
        self.action_spontaneous = False
        self.animation.clip_finished.connect(self.finished)
        self.positioning.movement_finished.connect(self.finished)
        self.behavior.action_requested.connect(self.autonomous)
        self.behavior.supports = self.supports

    @property
    def pending_click(self):
        return any(item.action == State.INTERACT for item in self.reactions.pending)

    @property
    def pending_notifications(self):
        return [item.message for item in self.reactions.pending if item.message is not None]

    @property
    def requires_wake_click(self):
        return (self.state == State.SLEEP and self.sleep_entered is not None
                and self.clock() - self.sleep_entered >= 180)

    def wake_by_click(self):
        if self.closed or self.gates or self.state != State.SLEEP:
            return False
        self.inactive = False
        self.sleep_started = None
        self.sleep_entered = None
        self.behavior.defer_walk()
        self.action_spontaneous = False
        self.enter(State.WAKE)
        return True

    def start(self):
        self.enter(State.IDLE)

    def supports(self, state):
        return not hasattr(self.animation, "clips") or state in self.animation.clips

    def enter(self, state: State, *, clip=None):
        if self.closed:
            return
        if hasattr(self.animation, "clips") and state not in self.animation.clips:
            state = State.IDLE
        previous = self.state
        if previous == State.SLEEP and state != State.SLEEP and self.requires_wake_click:
            state = State.SLEEP
        if state == State.SLEEP and self.sleep_entered is None:
            self.sleep_entered = self.clock()
        elif state != State.SLEEP:
            self.sleep_entered = None
        if state == State.WALK and self.gates:
            self.next_destination = None
            return
        if state == State.SLEEP and self.sleep_started is None:
            self.sleep_started = self.clock()
        self.token += 1
        self.animation.stop()
        self.positioning.stop()
        self.state = state
        if not self.gates.intersection({"hidden", "session"}):
            if clip is None:
                self.animation.play(state, self.token)
            else:
                self.animation.play(state, self.token, clip=clip)
        self.behavior.schedule(state == State.IDLE and not self.gates and not self.paused)
        token = self.token
        self.state_changed.emit(state)
        if token != self.token or self.closed:
            return
        self.reactions.changed(state)
        if previous == State.SLEEP and state == State.IDLE and not self.inactive:
            duration = 0 if self.sleep_started is None else self.clock() - self.sleep_started
            self.sleep_started = None
            self.woke.emit(duration)
        if state == State.WALK:
            if self.next_destination is not None:
                destination = self.next_destination
                self.next_destination = None
                escaping = self.reactions.active is not None and self.reactions.active.source == "obstacle"
                if escaping:
                    started = self.positioning.walk_toward(destination, 1.25, self.token, max_distance=None)
                else:
                    started = self.positioning.walk_toward(destination, 4, self.token)
                if started:
                    return
                self.enter(State.IDLE)
                return
            direction = self.behavior.rng.choice((-1, 1))
            distance = direction * self.behavior.rng.uniform(45, 110)
            duration = self.behavior.rng.uniform(2, 4)
            if not (self.positioning.walk(distance, duration, self.token)
                    or self.positioning.walk(-distance, duration, self.token)):
                self.enter(State.IDLE)

    def set_presence(self, decision):
        previous = self.presence
        self.presence = decision
        self.behavior.presence_initiative = decision.initiative
        self.behavior.presence_movement = decision.autonomous_movement
        if decision.mode == "presentation" and (self.reactions.active or self.reactions.pending):
            was_active = self.reactions.active is not None
            self.reactions.close()
            if was_active:
                self.enter(State.IDLE)
        if (self.state == State.WALK and self.action_spontaneous
                and not decision.autonomous_movement):
            self.enter(State.IDLE)
        if previous is None or (previous.initiative, previous.autonomous_movement) != (decision.initiative, decision.autonomous_movement):
            self.behavior.schedule(self.state == State.IDLE and not self.gates and not self.paused)

    def autonomous(self, state: State):
        if self.paused:
            return
        if state == State.IDLE:
            if self.state == State.IDLE:
                self.behavior.accepted(state)
            self.behavior.schedule(self.state == State.IDLE and not self.gates and not self.paused)
        else:
            self.reactions.offer("autonomy", state, Priority.SPONTANEOUS)

    def react(self, state: State, *, spontaneous=False, source=None, destination=None) -> bool:
        priority = Priority.CONTEXT if spontaneous else Priority.EXPLICIT
        return self.reactions.offer(source or state.value, state, priority, destination=destination)

    def request(self, state: State, *, spontaneous=False) -> bool:
        if self.presence and (not (self.presence.initiative if spontaneous else self.presence.explicit_reactions)
                              or spontaneous and state == State.WALK and not self.presence.autonomous_movement):
            self.next_destination = None
            return False
        if self.closed or self.requires_wake_click or not self.supports(state) or not can_request(self.state, state, bool(self.gates)):
            if state == State.WALK:
                self.next_destination = None
            return False
        self.action_spontaneous = spontaneous
        self.enter(state)
        return True

    def interact(self):
        now = self.clock()
        if now - self.last_click < 0.25 or self.gates or self.closed:
            return
        self.last_click = now
        self.behavior.defer_walk()
        self.inactive = False
        self.reactions.offer("click", State.INTERACT, Priority.EXPLICIT)

    def notify(self, event_id: str, message: str):
        return self.reactions.offer("notification", State.NOTIFICATION, Priority.COMPLETION, key=event_id, message=message)

    def drain(self):
        self.reactions.drain()

    def finished(self, token: int):
        if self.closed or token != self.token or self.gates - {"radial"}:
            return
        if self.state == State.WALK:
            self.enter(State.LOOK_AROUND)
        elif self.state == State.INTERACT:
            self.enter(State.HAPPY)
        elif self.state not in {State.IDLE, State.SLEEP}:
            if self.reactions.advance_scene():
                return
            self.enter(State.SLEEP if self.inactive else State.IDLE)
            self.drain()

    def set_gate(self, name: str, active: bool):
        if self.closed or (name in self.gates) == active:
            return
        if active:
            self.gates.add(name)
            self.reactions.gate_entered(name)
            self.behavior.defer_walk()
            if name == "radial" and self.state in {State.INTERACT, State.HAPPY}:
                self.behavior.schedule(False)
                self.context_changed.emit()
                return
            self.enter(State.SLEEP if self.state == State.SLEEP else State.IDLE)
            self.behavior.schedule(False)
            if name in {"hidden", "session"}:
                self.animation.stop()
        else:
            self.gates.discard(name)
            if not self.gates:
                if name != "radial" or self.state not in {State.INTERACT, State.HAPPY}:
                    self.enter(State.SLEEP if self.inactive else State.IDLE)
                self.behavior.schedule(self.state == State.IDLE and not self.paused, quiet=True)
        self.context_changed.emit()
        if not active and not self.gates:
            self.drain()

    def set_paused(self, paused: bool):
        self.paused = paused
        if paused:
            self.reactions.pause_autonomy()
        active = self.reactions.active
        if not self.gates and (active is None or active.priority <= Priority.CONTEXT):
            self.enter(State.IDLE)
        self.behavior.schedule(not paused and not self.gates and self.state == State.IDLE, quiet=True)
        self.context_changed.emit()
        self.drain()

    def update_inactivity(self, seconds: float):
        self.inactive = (seconds >= self.behavior.settings.sleep_seconds
                         and self.behavior.settings.frequency != "off" and not self.paused)
        if not self.gates and not self.closed:
            if self.inactive and self.state == State.IDLE:
                self.sleep_started = self.clock() - seconds
                self.action_spontaneous = True
                self.enter(State.SLEEP)
            elif not self.inactive and self.state == State.SLEEP:
                self.enter(State.IDLE)

    def close(self):
        self.closed = True
        self.token += 1
        self.behavior.close()
        self.animation.stop()
        self.positioning.stop()
        self.reactions.close()
