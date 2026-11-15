from types import SimpleNamespace

import pytest

from r2_companion.services import windows


@pytest.mark.parametrize("scenario,anchor,restored", [
    ("normal", 4, [1, 2]),
    ("closed_predecessor", 5, [1, 2]),
    ("hidden_predecessor", 5, [1, 2]),
    ("topmost_predecessor", 0, [1, 2]),
    ("hidden_effect", 4, [1]),
    ("hidden_owner", None, []),
    ("other_platform", None, []),
])
def test_native_stack_guard_preserves_visible_depth_without_focus_or_topmost(
        monkeypatch, scenario, anchor, restored):
    calls = []
    hidden, closed = {3}, set()
    if scenario == "hidden_owner":
        hidden.add(1)
    previous = {1: 2, 2: 3, 3: 4, 4: 5, 5: 6, 6: 0}
    native = SimpleNamespace(
        IsWindowVisible=lambda handle: handle not in hidden,
        IsWindow=lambda handle: handle not in closed,
        GetWindow=lambda handle, direction: previous[handle],
        SetWindowPos=lambda *args: calls.append(args) or 1,
    )
    monkeypatch.setattr(windows, "IS_WINDOWS", scenario != "other_platform")
    monkeypatch.setattr(windows, "user32", native, raising=False)
    monkeypatch.setattr(windows, "get_window_style",
                        lambda handle, index: 8 if scenario == "topmost_predecessor" and handle == 4 else 0,
                        raising=False)
    members = [SimpleNamespace(effectiveWinId=lambda: 1, isVisible=lambda: True),
               SimpleNamespace(effectiveWinId=lambda: 2, isVisible=lambda: scenario != "hidden_effect")]
    with windows.preserve_window_stack(members):
        if scenario == "closed_predecessor":
            closed.add(4)
        if scenario == "hidden_predecessor":
            hidden.add(4)
    assert calls == [(handle, anchor, 0, 0, 0, 0, 0x213) for handle in restored]
