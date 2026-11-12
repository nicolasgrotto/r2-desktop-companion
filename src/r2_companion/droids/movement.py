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

    def capture(self):
        return None

    def restore(self, captured):
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

    def capture(self):
        return self.angle, self.head_tilt, self.head_offset

    def restore(self, captured):
        self.angle, self.head_tilt, self.head_offset = captured
        self.window.set_motion(*captured)

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


class ArticulatedMovementController(DroidMovementController):
    """Distance drives joints; the short recovery timer only settles motion."""
    retained = {"wheel"}

    def __init__(self, window, speed=1, clock=time.monotonic):
        super().__init__(window, speed, clock)
        self.channels = {}
        self.velocity = 0
        self.distance = 0
        self.last_time = clock()
        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self.recover)

    def progress(self, value):
        return value * value * (3 - 2 * value)

    def displaced(self, dx, dy, manual=False):
        elapsed = max(1 / 120, min(0.2, self.clock() - self.last_time))
        self.last_time = self.clock()
        # Convert DIP displacement into the 96-unit artwork coordinate system.
        scale = 96 / max(1, self.window.width())
        dx, dy = dx * scale, dy * scale
        velocity = dx / elapsed
        acceleration = (velocity - self.velocity) / elapsed
        self.velocity = velocity
        self.distance += math.hypot(dx, dy) * (-1 if dx < 0 else 1)
        self.drive(dx, dy, velocity, acceleration, manual)
        self.window.set_articulation(self.channels)
        self.timer.start()

    def drive(self, dx, dy, velocity, acceleration, manual):
        raise NotImplementedError

    def capture(self):
        return dict(self.channels)

    def restore(self, captured):
        self.channels = dict(captured)
        self.window.set_articulation(self.channels)

    def release(self):
        self.last_time = self.clock()
        self.timer.start()

    def recover(self):
        for key in self.channels.keys() - self.retained:
            self.channels[key] *= 0.76
            if abs(self.channels[key]) < 0.04:
                self.channels[key] = 0
        if not any(value for key, value in self.channels.items() if key not in self.retained):
            self.timer.stop()
            self.velocity = 0
        self.window.set_articulation(self.channels)

    def stop(self):
        self.timer.stop()
        self.velocity = 0
        self.last_time = self.clock()
        self.channels = {key: value for key, value in self.channels.items() if key in self.retained}
        self.window.set_articulation(self.channels)

    def close(self):
        # A retired controller must not overwrite the newly equipped rig.
        self.timer.stop()


class MonocycleMovementController(ArticulatedMovementController):
    def drive(self, dx, dy, velocity, acceleration, manual):
        self.channels["wheel"] = (self.channels.get("wheel", 0) + math.degrees(dx / 17)) % 360
        target = max(-15, min(15, velocity * 0.12 + acceleration * 0.002))
        self.channels["lean"] = self.channels.get("lean", 0) * 0.45 + target * 0.55
        self.channels["head"] = -self.channels["lean"] * 0.65


class HoverMovementController(ArticulatedMovementController):
    def progress(self, value):
        return (1 - math.cos(math.pi * value)) / 2

    def drive(self, dx, dy, velocity, acceleration, manual):
        self.channels["bank"] = max(-7, min(7, velocity * 0.065))
        self.channels["head"] = -self.channels["bank"] * 0.7
        self.channels["lift"] = max(-2, min(2, dy * 0.1))


class BipedMovementController(ArticulatedMovementController):
    def drive(self, dx, dy, velocity, acceleration, manual):
        phase = self.distance / 8
        stride = math.sin(phase)
        self.channels.update(left_step=stride * 22, right_step=-stride * 22,
                             left_knee=max(0, stride) * 30, right_knee=max(0, -stride) * 30,
                             left_foot=-stride * 12, right_foot=stride * 12,
                             lift=-abs(math.cos(phase)) * 1.5,
                             lean=max(-6, min(6, velocity * 0.04)))
        self.channels["head"] = -self.channels["lean"] * 0.8


class TractionMovementController(ArticulatedMovementController):
    def progress(self, value):
        # A short, assertive launch with a smooth stop.
        return 1 - (1 - value) ** 3

    def drive(self, dx, dy, velocity, acceleration, manual):
        self.channels["wheel"] = (self.channels.get("wheel", 0) + math.degrees(dx / 6)) % 360
        self.channels["lean"] = max(-8, min(8, velocity * 0.045 + acceleration * 0.001))
        self.channels["head"] = -self.channels["lean"] * 0.3
        self.channels["lift"] = math.sin(self.distance * 0.7) * min(0.7, abs(velocity) / 50)


MOVEMENT_CONTROLLERS = {"astromech": DroidMovementController, "spherical": SphericalMovementController,
                        "monocycle": MonocycleMovementController, "hover": HoverMovementController,
                        "biped": BipedMovementController, "traction": TractionMovementController}


def create_movement(profile, window):
    factory = MOVEMENT_CONTROLLERS.get(profile.movement)
    if factory is None:
        raise ValueError(f"Locomoção indisponível: {profile.movement}")
    return factory(window, profile.speed)
