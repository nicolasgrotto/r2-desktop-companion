from collections import deque
import time

from PySide6.QtCore import QObject, Signal

from .behavior import BehaviorManager
from .state import State, can_request


class PetController(QObject):
    state_changed = Signal(object)
    notification_presented = Signal(str)

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
        self.animation.clip_finished.connect(self.finished)
        self.positioning.movement_finished.connect(self.finished)
        self.behavior.action_requested.connect(self.autonomous)

    def start(self):
        self.enter(State.IDLE)

    def enter(self, state: State):
        if self.closed:
            return
        self.token += 1
        self.animation.stop()
        self.positioning.stop()
        self.state = state
        if not self.gates.intersection({"hidden", "session"}):
            self.animation.play(state, self.token)
        self.behavior.schedule(state == State.IDLE and not self.gates and not self.paused)
        self.state_changed.emit(state)
        if state == State.WALK:
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

    def request(self, state: State) -> bool:
        if self.closed or not can_request(self.state, state, bool(self.gates)):
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
        if self.closed or self.gates:
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
        if self.state == State.INTERACT:
            self.enter(State.HAPPY)
        elif self.state not in {State.IDLE, State.SLEEP}:
            self.enter(State.SLEEP if self.inactive and self.state == State.NOTIFICATION else State.IDLE)
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
