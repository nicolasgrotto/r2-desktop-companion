from PySide6.QtCore import QObject, QTimer, Signal


class SystemMonitor(QObject):
    updated = Signal(object)

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.count = 0
        self.timer = QTimer(self)
        self.timer.setInterval(3000)
        self.timer.timeout.connect(self.sample)

    def set_visible(self, visible: bool) -> None:
        if visible:
            self.service.primed = False
            self.count = 0
            self.sample()
            self.timer.start()
        else:
            self.timer.stop()

    def sample(self) -> None:
        self.updated.emit(self.service.sample(battery=self.count % 10 == 0))
        self.count += 1

    def close(self) -> None:
        self.timer.stop()
