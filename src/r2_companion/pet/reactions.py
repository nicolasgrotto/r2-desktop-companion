from collections import deque
from dataclasses import dataclass
from enum import IntEnum

from PySide6.QtCore import QPointF

from .scenes import CATALOG, MAX_SCENE_MS, bounded_clip, scene_clips
from .state import State, AUTONOMOUS, can_request

SCENES = {"task": (State.LOOK_AROUND, State.HAPPY), "game": (State.GREETING, State.HAPPY),
          "diagnosis": (State.WORK, State.LOOK_AROUND, State.HAPPY),
          "affection": (State.CURIOUS, State.HAPPY)}
EMOTIONS = {State.CURIOUS: ("curious", "idle"), State.HAPPY: ("happy", "idle"),
            State.WORK: ("curious", "idle"), State.CONFUSED: ("confused", "reactions"),
            State.SURPRISED: ("surprised", "reactions"), State.WORRIED: ("worried", "reactions"),
            State.OVERHEAT: ("worried", "reactions"), State.GREETING: ("greeting", "reactions"),
            State.WAKE: ("wake", "sleep"), State.INTERACT: ("greeting", "reactions"),
            State.NOTIFICATION: ("celebrate", "notifications")}


class Priority(IntEnum):
    SPONTANEOUS = 0
    CONTEXT = 1
    COMPLETION = 2
    EXPLICIT = 3


@dataclass(frozen=True)
class BehaviorIntent:
    source: str
    key: str
    priority: Priority
    expires_at: float
    action: State | str
    message: str | None = None
    destination: QPointF | None = None


class ReactionDirector:
    capacity = 8
    lifetime = 10
    passive_gates = {"hidden", "session", "fullscreen", "quiet_hours", "droid_swap"}

    def __init__(self, controller, audio=None):
        self.controller, self.audio = controller, audio
        self.pending: list[BehaviorIntent] = []
        self.active: BehaviorIntent | None = None
        self.seen_completions = deque(maxlen=100)
        self.steps = deque()
        self.previous = State.IDLE
        self.last_drop_reason = None
        self.profile_id = None
        self.scene_deadline = None
        self.scene_voice = None

    @property
    def scene(self):
        if self.active and (self.active.action in SCENES or self.scene_deadline is not None):
            return self.active.action
        return None

    def already_notified(self, event_id):
        return ("notification", event_id) in self.seen_completions

    def start(self, scene, *, key=None):
        priority = Priority.COMPLETION if scene == "task" else Priority.EXPLICIT
        return self.offer(scene, scene, priority, key=key)

    def start_scene(self, action, *, key=None):
        if action == "task_completed":
            if action not in CATALOG.get(self.profile_id, {}):
                return self.start("task", key=key)
            return self.offer("task", action, Priority.COMPLETION, key=key)
        priority = Priority.EXPLICIT if action == "focus_started" else Priority.CONTEXT
        return self.offer(action, action, priority, key=key)

    def retain_focus(self, run_id):
        self.pending = [intent for intent in self.pending
                        if intent.action != "focus_started" or intent.key == run_id]
        if self.scene == "focus_started" and self.active.key != run_id:
            self.reset_active()
            self.controller.enter(State.IDLE)
            self.drain()

    def _drop(self, reason):
        self.last_drop_reason = reason
        return False

    def _expire(self):
        now = self.controller.clock()
        fresh = [intent for intent in self.pending if now < intent.expires_at]
        if len(fresh) != len(self.pending):
            self.pending = fresh
            self._drop("expired")

    def offer(self, source, action, priority, *, key=None, message=None, destination=None):
        c = self.controller
        self._expire()
        intent = BehaviorIntent(source, key or source, priority, c.clock() + self.lifetime,
                                action, message, destination)
        identity = (source, intent.key)
        if priority == Priority.COMPLETION and key is not None:
            if identity in self.seen_completions:
                return self._drop("duplicate")
            self.seen_completions.append(identity)
        if c.closed or self.passive_gates.intersection(c.gates) or (c.presence and c.presence.mode == "presentation"):
            return self._drop("unavailable")
        if not any(c.supports(step) for step in self._states(intent)):
            return self._drop("unsupported")
        if any((other.source, other.key) == identity for other in self.pending):
            return self._drop("duplicate")
        if (self.active and (self.active.source, self.active.key) == identity and self.active.action == action
                and action != State.INTERACT and priority != Priority.COMPLETION):
            return self._drop("duplicate")
        if priority <= Priority.CONTEXT and (c.paused or c.behavior.settings.frequency == "off"):
            return self._drop("autonomy_disabled")
        if len(self.pending) == self.capacity:
            # Stable priority order keeps earlier requests at equal priority.
            if self.pending[-1].priority >= priority:
                return self._drop("queue_full")
            self.pending.pop()
            self._drop("displaced")
        self.pending.append(intent)
        self.pending.sort(key=lambda item: item.priority, reverse=True)
        self.drain()
        return self.active is intent or intent in self.pending

    def _states(self, intent):
        if isinstance(intent.action, State):
            return (intent.action,)
        scene = CATALOG.get(self.profile_id, {}).get(intent.action)
        return tuple(state for state, _ in scene.steps) if scene else SCENES.get(intent.action, ())

    def _eligible(self, intent):
        c = self.controller
        if c.closed or c.gates or c.requires_wake_click:
            return False
        if self.active and (self.active.priority > intent.priority
                            or self.active.priority == intent.priority and intent.priority != Priority.EXPLICIT):
            return False
        if intent.action == State.NOTIFICATION:
            return (c.state != State.WAKE and (not c.presence or c.presence.notifications)
                    and (can_request(c.state, State.NOTIFICATION)
                         or self.active is not None and self.active.priority < Priority.COMPLETION))
        if c.state in {State.SLEEP, State.DRAG, State.WAKE} or c.inactive:
            return False
        if intent.action == State.INTERACT and (c.state == State.INTERACT or
                c.state == State.HAPPY and self.active and self.active.action == State.INTERACT):
            return False
        if intent.priority <= Priority.CONTEXT:
            return (not c.paused and c.behavior.settings.frequency != "off"
                    and (not c.presence or c.presence.initiative)
                    and (intent.action != State.WALK or c.behavior.settings.movement
                         and (not c.presence or c.presence.autonomous_movement)))
        return not c.presence or c.presence.explicit_reactions

    def drain(self):
        self._expire()
        for intent in self.pending:
            if self._eligible(intent):
                self.pending.remove(intent)
                self._begin(intent)
                return

    def _begin(self, intent):
        c = self.controller
        scene = CATALOG.get(self.profile_id, {}).get(intent.action)
        if scene:
            steps = deque(scene_clips(scene, c.animation.clips))
        else:
            steps = deque((state, None) for state in self._states(intent) if c.supports(state))
        if not steps:
            self._drop("unsupported")
            return
        # Never restore a step of an interrupted scene.
        self.previous = c.state if not self.active and c.state in AUTONOMOUS - {State.WALK} else State.IDLE
        self.active = intent
        self.steps = steps
        self.scene_deadline = c.clock() + MAX_SCENE_MS / 1000 if scene else None
        self.scene_voice = scene.voice if scene else None
        state, clip = steps.popleft()
        c.action_spontaneous = intent.priority <= Priority.CONTEXT
        if state != State.WALK and intent.priority != Priority.SPONTANEOUS:
            c.behavior.defer_walk()
        c.next_destination = intent.destination
        c.enter(state, clip=clip)
        if intent.priority == Priority.SPONTANEOUS or state == State.WALK:
            c.behavior.accepted(state)
        else:
            c.behavior.recent.append(state)
        if intent.message is not None and self.active is intent:
            c.notification_presented.emit(intent.message)

    def advance_scene(self):
        if not self.scene or self.controller.inactive or self.controller.gates:
            return False
        remaining = (int((self.scene_deadline - self.controller.clock()) * 1000)
                     if self.scene_deadline is not None else MAX_SCENE_MS)
        if self.steps and remaining > 0:
            state, clip = self.steps.popleft()
            self.controller.enter(state, clip=bounded_clip(clip, remaining) if clip else None)
            return True
        previous = self.previous
        self.reset_active()
        self._expire()
        if previous != State.IDLE and not self.pending and self.controller.supports(previous):
            self.controller.enter(previous)
            return True
        return False

    def reset_active(self):
        self.active = None
        self.steps.clear()
        self.scene_deadline = self.scene_voice = None

    def gate_entered(self, name):
        if name in self.passive_gates:
            self.pending.clear()
        else:
            self.pending = [item for item in self.pending if item.action != State.INTERACT]

    def pause_autonomy(self):
        self.pending = [item for item in self.pending if item.priority > Priority.CONTEXT]

    def changed(self, state):
        if state in {State.IDLE, State.SLEEP, State.DRAG}:
            self.reset_active()
        if self.audio is None:
            return
        if self.scene_deadline is not None:
            if self.scene_voice is not None:
                voice, self.scene_voice = self.scene_voice, None
                self.audio.vocalize(voice, "reactions")
        elif self.scene:
            if state == State.HAPPY:
                self.audio.vocalize("affection" if self.scene == "affection" else "celebrate", "reactions")
        elif state == State.SLEEP:
            self.audio.vocalize("sleep", "sleep")
        elif state == State.WALK:
            self.audio.play("movement", "servo")
        elif state in EMOTIONS:
            self.audio.vocalize(*EMOTIONS[state])

    def close(self):
        self.reset_active()
        self.pending.clear()

    def forget_task_completion(self, task_id):
        identity = ("task", task_id)
        if identity in self.seen_completions:
            self.seen_completions.remove(identity)
        self.pending = [item for item in self.pending if (item.source, item.key) != identity]

    def tasks_restored(self):
        self.seen_completions = deque((key for key in self.seen_completions if key[0] != "task"),
                                      maxlen=self.seen_completions.maxlen)
        self.pending = [item for item in self.pending if item.source != "task"]
