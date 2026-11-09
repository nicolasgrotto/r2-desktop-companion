from PySide6.QtWidgets import QSystemTrayIcon
from .bubble import Bubble


class Tray(QSystemTrayIcon):
    def __init__(self, icon):
        super().__init__(icon)
        self.setToolTip("R2 Companion · placeholder de desenvolvimento")
        self.notice = Bubble()
        self.notifications_enabled = True

    def notify(self, message: str):
        self.setToolTip("R2 Companion · " + message[:100])
        if self.notifications_enabled and self.isSystemTrayAvailable():
            self.notice.present_corner(message, self.geometry())

    def hide(self):
        self.notice.stop()
        super().hide()
