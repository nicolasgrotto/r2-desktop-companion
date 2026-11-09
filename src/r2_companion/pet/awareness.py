from collections import deque
import time

from PySide6.QtCore import QObject, QPointF, QRectF, QSizeF, QTimer
from PySide6.QtGui import QCursor

from ..services.system_info import SystemInfo
from .positioning import fingerprint, from_normalized
from .state import State


def fullscreen_policy(mode, manual_position, screen_name):
    pinned = (manual_position is not None and manual_position.corner
              and manual_position.screen == screen_name)
    if mode == "quiet":
        return "stay"
    if mode in {"auto", "corner"} and pinned:
        return "corner"
    return "hide"


class ContextReactions(QObject):
    def __init__(self, controller, positioning, store, audio, clock=time.monotonic):
        super().__init__()
        self.controller, self.positioning, self.store, self.audio = controller, positioning, store, audio
        self.clock = clock
        self.cursor = None
        self.cursor_since = self.clock()
        self.last_attention = -1000000
        self.last_approach = -1000000
        self.last_home = self.clock()
        self.active_since = self.clock()
        self.clicks = deque(maxlen=8)
        self.history = {}
        self.charging = None
        self.info = SystemInfo()
        self.timer = QTimer(self)
        self.timer.setInterval(15000)
        self.timer.timeout.connect(self.sample_system)
        self.timer.start()
        self.controller.woke.connect(self.wake)

    def available(self):
        return (not self.controller.closed and not self.controller.gates and not self.controller.paused
                and not self.controller.inactive and self.controller.state == State.IDLE)

    def limited_reaction(self, key, state, cooldown=300):
        if self.available() and self.clock() - self.history.get(key, -1000000) >= cooldown:
            if self.controller.react(state):
                self.history[key] = self.clock()
                return True
        return False

    def greet(self):
        self.limited_reaction("greeting", self.controller.behavior.rng.choice(
            (State.GREETING, State.HAPPY, State.SURPRISED)), 60)

    def wake(self, duration):
        self.active_since = self.clock()
        if duration >= 7200:
            self.greet()
        else:
            self.controller.react(State.WAKE)

    def click(self):
        now = self.clock()
        self.clicks.append(now)
        return len([t for t in self.clicks if now - t <= 3]) >= 4

    def observe(self, cursor=None):
        now = self.clock()
        cursor = QPointF(QCursor.pos()) if cursor is None else QPointF(cursor)
        if self.cursor is None or (cursor - self.cursor).manhattanLength() > 4:
            self.cursor_since = now
            self.cursor = cursor
        if not self.available():
            if self.controller.inactive:
                self.active_since = now
            return
        settings = self.store.settings.behavior
        if settings.frequency == "off":
            return
        window = self.positioning.window
        center = QPointF(window.geometry().center())
        delta = cursor - center
        distance = (delta.x() ** 2 + delta.y() ** 2) ** 0.5
        if settings.hourly_reaction and now - self.active_since >= 3600:
            if self.limited_reaction("hour", State.HAPPY, 3600):
                self.active_since = now
                return
        if settings.cursor_attention and now - self.last_attention >= 25 and distance < 450:
            self.last_attention = now
            self.controller.react(State.CURIOUS if distance < 160 else State.LOOK_LEFT if delta.x() < 0 else State.LOOK_RIGHT)
            return
        if (settings.cursor_attention and settings.movement and now - self.cursor_since >= 15
                and now - self.last_approach >= 180 and 200 < distance < 500
                and self.positioning.screen is not None
                and self.positioning.screen.availableGeometry().contains(cursor.toPoint())):
            self.last_approach = now
            destination = QPointF(window.pos()) + delta * (min(80, distance - 180) / distance)
            self.controller.next_destination = destination
            if self.controller.request(State.WALK):
                self.controller.behavior.accepted(State.WALK)
            return
        home = self.store.settings.manual_position
        if (settings.movement and home is not None and now - self.last_home >= 300
                and self.positioning.screen is not None and home.screen == fingerprint(self.positioning.screen)):
            self.last_home = now
            destination = from_normalized(home.u, home.v,
                QRectF(self.positioning.screen.availableGeometry()), QSizeF(window.size()))
            if (destination - QPointF(window.pos())).manhattanLength() < 5:
                return
            self.controller.next_destination = destination
            if self.controller.request(State.WALK):
                self.controller.behavior.accepted(State.WALK)

    def sample_system(self):
        if (not self.store.settings.behavior.system_reactions
                or self.store.settings.behavior.frequency == "off" or not self.available()):
            return
        values = self.info.sample(battery=True, charging=True)
        plugged = values.get("charging")
        if plugged is True and self.charging is False:
            self.limited_reaction("charging", State.HAPPY)
        elif values["battery"] is not None and values["battery"] <= 20 and plugged is not True:
            self.limited_reaction("battery", State.WORRIED, 600)
        elif values["cpu"] is not None and values["cpu"] >= 90:
            self.limited_reaction("cpu", State.OVERHEAT)
        self.charging = plugged

    def close(self):
        self.timer.stop()
