import pytest
from PySide6.QtGui import QPixmap

from test_context_v03 import pet


@pytest.mark.parametrize("context", ["fullscreen", "presentation_without_tray"])
def test_suspending_passive_surfaces_discards_ephemeral_hologram(pet, monkeypatch, context):
    image = QPixmap(32, 32)
    image.fill("white")
    pet.window.project(image)
    assert not pet.window.hologram.isNull() and pet.window.hologram_timer.isActive()
    if context == "fullscreen":
        pet.store.settings.fullscreen_mode = "quiet"
        monkeypatch.setattr("r2_companion.app.foreground_fullscreen", lambda hwnd: True)
        pet.check_desktop()
    else:
        monkeypatch.setattr("r2_companion.pet.presence_runtime.QSystemTrayIcon.isSystemTrayAvailable", lambda: False)
        pet.presence.select_mode("presentation")
    assert pet.window.isVisible()
    assert pet.window.hologram.isNull() and not pet.window.hologram_timer.isActive()
    assert not pet.window.projection_overlay.isVisible()
