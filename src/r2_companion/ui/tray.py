from PySide6.QtWidgets import QSystemTrayIcon


class Tray(QSystemTrayIcon):
    def __init__(self, icon):
        super().__init__(icon)
        self.setToolTip("R2 Companion · placeholder de desenvolvimento")

    def notify(self, message: str):
        self.setToolTip("R2 Companion · " + message[:100])
        if self.isSystemTrayAvailable() and self.supportsMessages():
            self.showMessage("R2 Companion", message, QSystemTrayIcon.MessageIcon.Information, 5000)
