from collections import deque
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
        self.recent = deque(maxlen=8)
        self.supports = lambda state: True
        self.eligible = False
        self.presence_initiative = True
        self.presence_movement = True
        self.last_reaction = -1000000.0
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self.decide)

    def choose(self) -> State:
        if self.settings.frequency == "off" or not self.presence_initiative:
            return State.IDLE
        now = self.clock()
        walk_due = self.settings.movement and self.presence_movement and now >= self.next_walk_at and self.supports(State.WALK)
        weights = {State(key): value for key, value in self.settings.weights.items()}
        options = [state for state in weights if state != State.WALK and weights[state] > 0 and self.supports(state)
                   and (state in {State.IDLE, State.BLINK} or now - self.last_reaction >= self.settings.reaction_interval)
                   and now - self.history.get(state, -1000000) >= COOLDOWNS.get(state, 0)]
        if walk_due and (not options or not self.recent or self.recent[-1] != State.WALK):
            return State.WALK
        if not options:
            return State.IDLE
        alternatives = [state for state in options if state not in self.recent]
        if not alternatives and self.recent:
            alternatives = [state for state in options if state != self.recent[-1]]
        options = alternatives or options
        return self.rng.choices(options, weights=[weights[state] for state in options], k=1)[0]

    def accepted(self, state: State) -> None:
        self.recent.append(state)
        if state != State.IDLE:
            self.history[state] = self.clock()
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
        if eligible and self.presence_initiative and self.settings.frequency != "off":
            factor = 2 if self.settings.frequency == "quiet" else 1
            delay = self.rng.uniform(10 if quiet else 8, 20) * factor
            if quiet:
                self.defer_walk(delay)
            if self.settings.movement and self.presence_movement and self.supports(State.WALK):
                delay = min(delay, max(0.1, self.next_walk_at - self.clock()))
            self.timer.start(max(100, round(delay * 1000)))

    def decide(self):
        if self.eligible:
            self.action_requested.emit(self.choose())

    def close(self):
        self.eligible = False
        self.timer.stop()
