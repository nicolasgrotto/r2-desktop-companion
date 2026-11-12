from types import SimpleNamespace

import pytest

from r2_companion.services import windows
from test_context_v03 import pet


@pytest.mark.parametrize("flags,show,logical,native,minimized,expected", [
    (1, 0, True, False, False, True),
    (1, 0, True, True, False, False),
    (1, 1, True, False, False, False),
    (0, 0, True, False, False, False),
    (1, 0, False, False, False, False),
    (1, 0, True, False, True, False),
])
def test_hidden_start_corrects_only_native_visibility_of_an_explicitly_requested_window(
        monkeypatch, flags, show, logical, native, minimized, expected):
    state = {"visible": native, "calls": []}

    def get_startup(pointer):
        pointer._obj.flags = flags
        pointer._obj.show = show

    def display(handle, command):
        state["calls"].append((handle, command))
        state["visible"] = True

    monkeypatch.setattr(windows, "IS_WINDOWS", True)
    monkeypatch.setattr(windows, "kernel32", SimpleNamespace(GetStartupInfoW=get_startup), raising=False)
    monkeypatch.setattr(windows, "user32", SimpleNamespace(IsWindowVisible=lambda handle: state["visible"],
                                                         ShowWindow=display), raising=False)
    widget = SimpleNamespace(winId=lambda: 1234, isVisible=lambda: logical, isMinimized=lambda: minimized)
    result = windows.reveal_requested_window(widget)
    assert result["native_visibility_corrected"] == expected
    assert state["calls"] == ([(1234, 4)] if expected else [])
    assert result["native_visible"] == (native or expected)


def test_failed_native_presentation_closes_preferences_and_releases_its_gate(pet, monkeypatch):
    monkeypatch.setattr("r2_companion.app.reveal_requested_window", lambda widget: {"native_visible": False})
    with pytest.raises(RuntimeError, match="exibida"):
        pet.show_settings()
    assert pet.settings_dialog is None and "settings" not in pet.controller.gates
