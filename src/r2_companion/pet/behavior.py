from collections.abc import Callable
import random
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..core.config import BehaviorSettings
from .state import State

COOLDOWNS = {State.BLINK: 10, State.LOOK_AROUND: 45, State.CURIOUS: 60, State.WALK: 75,
             State.HAPPY: 180, State.SURPRISED: 240, State.WORK: 150}


class BehaviorManager(QObject):
    action_requested = Signal(object)

    def __init__(self, clock: Callable[[], float] = time.monotonic, rng=None):
        super().__init__()
        self.clock = clock
        self.rng = rng or random.Random()
        self.next_walk_at = self.clock() + self.rng.uniform(15, 25)
        self.settings = BehaviorSettings()
        self.history: dict[State, float] = {}
        self.last = State.IDLE
        self.eligible = False
        self.last_reaction = -1000000.0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.decide)

    def choose(self) -> State:
        if self.settings.frequency == "off":
            return State.IDLE
        now = self.clock()
        if self.settings.movement and now >= self.next_walk_at:
            return State.WALK
        weights = {State(key): value for key, value in self.settings.weights.items()}
        options = [state for state in weights if state != State.WALK
                   and (state in {State.IDLE, State.BLINK} or now - self.last_reaction >= self.settings.reaction_interval)
                   and now - self.history.get(state, -1000000) >= COOLDOWNS.get(state, 0)]
        if not options or not any(weights[state] for state in options):
            return State.IDLE
        return self.rng.choices(options, weights=[weights[state] for state in options], k=1)[0]

    def accepted(self, state: State) -> None:
        if state != State.IDLE:
            self.history[state] = self.clock()
            self.last = state
            if state not in {State.BLINK, State.WALK}:
                self.last_reaction = self.clock()
            if state == State.WALK:
                interval = (150, 240) if self.settings.frequency == "quiet" else (75, 120)
                self.next_walk_at = self.clock() + self.rng.uniform(*interval)

    def defer_walk(self, seconds: float = 12) -> None:
        self.next_walk_at = max(self.next_walk_at, self.clock() + seconds)

    def schedule(self, eligible: bool, quiet: bool = False) -> None:
        self.eligible = eligible
        self.timer.stop()
        if eligible and self.settings.frequency != "off":
            factor = 2 if self.settings.frequency == "quiet" else 1
            delay = self.rng.uniform(10 if quiet else 8, 20) * factor
            if quiet:
                self.defer_walk(delay)
            if self.settings.movement:
                delay = min(delay, max(0.1, self.next_walk_at - self.clock()))
            self.timer.start(max(100, round(delay * 1000)))

    def decide(self):
        if self.eligible:
            self.action_requested.emit(self.choose())

    def close(self):
        self.eligible = False
        self.timer.stop()
