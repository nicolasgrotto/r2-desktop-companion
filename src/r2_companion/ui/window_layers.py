from contextlib import contextmanager, nullcontext

from PySide6.QtCore import QObject, Qt

from ..services.windows import preserve_window_stack


@contextmanager
def present_surface(window):
    """Guard preparation and showing: sizing a hidden tool can create its HWND."""
    policy = getattr(window, "_window_layer_policy", None)
    guard = policy.preserve_stack() if policy is not None and not window.isVisible() else nullcontext()
    with guard:
        yield


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
            window._window_layer_policy = self
            self._apply(window)

    def _apply(self, window):
        if bool(window.windowFlags() & Qt.WindowType.WindowStaysOnTopHint) != self.enabled:
            window.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.enabled)

    def set_enabled(self, enabled):
        if self.enabled == bool(enabled):
            return
        self.enabled = bool(enabled)
        with self.preserve_stack():
            visible = [window for window in self.windows if window.isVisible()]
            # Update all flags before showEvent can resume an active effect.
            for window in self.windows:
                self._apply(window)
            for window in visible:
                if not window.isVisible():
                    window.show()

    def preserve_stack(self):
        return nullcontext() if self.enabled else preserve_window_stack(self.windows)
