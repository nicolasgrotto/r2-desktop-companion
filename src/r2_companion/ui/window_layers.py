from PySide6.QtCore import QObject, Qt


class WindowLayerPolicy(QObject):
    """One stacking preference for the mascot and its desktop surfaces.

    Animation/state code controls visibility only. Register new top-level effects
    here so they cannot introduce an independent always-on-top setting.
    """

    def __init__(self, owner, enabled=True):
        super().__init__(owner)
        self.enabled = bool(enabled)
        self.windows = []

    def register(self, window):
        if window not in self.windows:
            self.windows.append(window)
            self._apply(window)

    def _apply(self, window):
        if bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != self.enabled:
            window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.enabled)

    def set_enabled(self, enabled):
        if self.enabled == bool(enabled):
            return
        self.enabled = bool(enabled)
        visible = [window for window in self.windows if window.isVisible()]
        # Changing flags hides native windows. Update every surface before any
        # showEvent can resume a currently active animation/effect.
        for window in self.windows:
            self._apply(window)
        for window in visible:
            if not window.isVisible():
                window.show()
