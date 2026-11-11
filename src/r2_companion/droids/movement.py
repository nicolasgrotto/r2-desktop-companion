import math
import time

from PySide6.QtCore import QObject, QTimer


class DroidMovementController(QObject):
    def __init__(self, window, speed=1, clock=time.monotonic):
        super().__init__()
        self.window, self.speed, self.clock = window, speed, clock

    def progress(self, value):
        return value

    def displaced(self, dx, dy, manual=False):
        pass

    def release(self):
        pass

    def stop(self):
        pass

    def close(self):
        self.stop()


class SphericalMovementController(DroidMovementController):
    def __init__(self, window, speed=1, clock=time.monotonic):
        super().__init__(window, speed, clock)
        self.angle = 0.0
        self.head_tilt = 0.0
        self.head_offset = 0.0
        self.last_time = clock()
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.recover)

    def progress(self, value):
        return value * value * (3 - 2 * value)

    def displaced(self, dx, dy, manual=False):
        if dx == 0 and dy == 0:
            return
        elapsed = max(1 / 120, min(0.2, self.clock() - self.last_time))
        self.last_time = self.clock()
        radius = max(1, self.window.width() * 20 / 64)
        self.angle = (self.angle + math.degrees(dx / radius)) % 360
        target = max(-12, min(12, dx / elapsed * (0.055 if manual else 0.035)))
        self.head_tilt += (target - self.head_tilt) * 0.45
        self.head_offset = max(-2.5, min(2.5, self.head_tilt * 0.18))
        self.window.set_motion(self.angle, self.head_tilt, self.head_offset)
        self.timer.start()

    def release(self):
        self.timer.start()

    def recover(self):
        self.head_tilt *= 0.76
        self.head_offset *= 0.72
        if abs(self.head_tilt) < 0.08 and abs(self.head_offset) < 0.03:
            self.head_tilt = self.head_offset = 0.0
            self.timer.stop()
        self.window.set_motion(self.angle, self.head_tilt, self.head_offset)

    def stop(self):
        self.timer.stop()
        self.head_tilt = self.head_offset = 0.0
        self.window.set_motion(self.angle, 0, 0)


MOVEMENT_CONTROLLERS = {"astromech": DroidMovementController, "spherical": SphericalMovementController}


def create_movement(profile, window):
    factory = MOVEMENT_CONTROLLERS.get(profile.movement)
    if factory is None:
        raise ValueError(f"Locomoção indisponível: {profile.movement}")
    return factory(window, profile.speed)
