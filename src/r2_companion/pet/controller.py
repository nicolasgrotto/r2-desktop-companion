from collections import deque
import time

from PySide6.QtCore import QObject, Signal

from .behavior import BehaviorManager
from .state import State, can_request


class PetController(QObject):
    state_changed = Signal(object)
    notification_presented = Signal(str)
    woke = Signal(float)

    def __init__(self, animation, positioning, behavior: BehaviorManager, clock=time.monotonic):
        super().__init__()
        self.animation = animation
        self.positioning = positioning
        self.behavior = behavior
        self.clock = clock
        self.state = State.IDLE
        self.token = 0
        self.gates: set[str] = set()
        self.pending_click = False
        self.pending_notifications = deque(maxlen=5)
        self.seen_notifications = deque(maxlen=100)
        self.inactive = False
        self.closed = False
        self.paused = False
        self.last_click = -1000.0
        self.sleep_started = None
        self.sleep_entered = None
        self.next_destination = None
        self.animation.clip_finished.connect(self.finished)
        self.positioning.movement_finished.connect(self.finished)
        self.behavior.action_requested.connect(self.autonomous)

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
        self.pending_click = False
        self.behavior.defer_walk()
        self.enter(State.WAKE)
        return True

    def start(self):
        self.enter(State.IDLE)

    def supports(self, state):
        return not hasattr(self.animation, "clips") or state in self.animation.clips

    def enter(self, state: State):
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
            self.animation.play(state, self.token)
        self.behavior.schedule(state == State.IDLE and not self.gates and not self.paused)
        self.state_changed.emit(state)
        if previous == State.SLEEP and state == State.IDLE and not self.inactive:
            duration = 0 if self.sleep_started is None else self.clock() - self.sleep_started
            self.sleep_started = None
            self.woke.emit(duration)
        if state == State.WALK:
            if self.next_destination is not None:
                destination = self.next_destination
                self.next_destination = None
                if self.positioning.walk_toward(destination, 4, self.token):
                    return
                self.enter(State.IDLE)
                return
            direction = self.behavior.rng.choice((-1, 1))
            distance = direction * self.behavior.rng.uniform(45, 110)
            duration = self.behavior.rng.uniform(2, 4)
            if not (self.positioning.walk(distance, duration, self.token)
                    or self.positioning.walk(-distance, duration, self.token)):
                self.enter(State.IDLE)

    def autonomous(self, state: State):
        if self.paused:
            return
        if state == State.IDLE:
            self.behavior.schedule(self.state == State.IDLE and not self.gates and not self.paused)
        elif self.request(state):
            self.behavior.accepted(state)

    def react(self, state: State) -> bool:
        if self.closed or self.gates or self.inactive or self.state == State.SLEEP or not self.supports(state):
            return False
        self.behavior.defer_walk()
        self.enter(state)
        return True

    def request(self, state: State) -> bool:
        if self.closed or self.requires_wake_click or not self.supports(state) or not can_request(self.state, state, bool(self.gates)):
            if state == State.WALK:
                self.next_destination = None
            return False
        self.enter(state)
        return True

    def interact(self):
        now = self.clock()
        if now - self.last_click < 0.25 or self.gates or self.closed:
            return
        self.last_click = now
        self.behavior.defer_walk()
        self.inactive = False
        if self.state in {State.INTERACT, State.HAPPY}:
            self.pending_click = True
        else:
            self.request(State.INTERACT)

    def notify(self, event_id: str, message: str):
        if event_id in self.seen_notifications or self.closed:
            return
        self.seen_notifications.append(event_id)
        self.pending_notifications.append(message)
        self.drain()

    def drain(self):
        if self.closed or self.gates or self.requires_wake_click:
            return
        if self.pending_click and self.state in {State.IDLE, State.SLEEP}:
            self.pending_click = False
            self.enter(State.INTERACT)
        elif self.pending_notifications and can_request(self.state, State.NOTIFICATION):
            message = self.pending_notifications.popleft()
            self.enter(State.NOTIFICATION)
            self.notification_presented.emit(message)

    def finished(self, token: int):
        if self.closed or token != self.token or self.gates - {"radial"}:
            return
        if self.state == State.WALK:
            self.enter(State.LOOK_AROUND)
        elif self.state == State.INTERACT:
            self.enter(State.HAPPY)
        elif self.state not in {State.IDLE, State.SLEEP}:
            self.enter(State.SLEEP if self.inactive else State.IDLE)
            self.drain()

    def set_gate(self, name: str, active: bool):
        if self.closed or (name in self.gates) == active:
            return
        if active:
            self.gates.add(name)
            self.behavior.defer_walk()
            if name == "radial" and self.state in {State.INTERACT, State.HAPPY}:
                self.behavior.schedule(False)
                return
            self.pending_click = False
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
                self.drain()

    def set_paused(self, paused: bool):
        self.paused = paused
        if not self.gates:
            self.enter(State.IDLE)
        self.behavior.schedule(not paused and not self.gates and self.state == State.IDLE, quiet=True)

    def update_inactivity(self, seconds: float):
        self.inactive = (seconds >= self.behavior.settings.sleep_seconds
                         and self.behavior.settings.frequency != "off" and not self.paused)
        if not self.gates and not self.closed:
            if self.inactive and self.state == State.IDLE:
                self.sleep_started = self.clock() - seconds
                self.enter(State.SLEEP)
            elif not self.inactive and self.state == State.SLEEP:
                self.enter(State.IDLE)

    def close(self):
        self.closed = True
        self.token += 1
        self.behavior.close()
        self.animation.stop()
        self.positioning.stop()
        self.pending_notifications.clear()
