from itertools import combinations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from r2_companion.core.actions import ActionRegistry
from r2_companion.core.config import Settings
from r2_companion.ui.actions import ActionSearch
from r2_companion.ui.context_menu import create_menu
from r2_companion.ui.navigation import NAVIGATION, navigation
from test_context_v03 import pet


def test_search_normalizes_words_and_disables_with_reason(qapp):
    calls = []
    registry = ActionRegistry({"media": lambda: calls.append("media"), "project_clock": lambda: calls.append("clock")},
                              {"project_clock": lambda: "Projeções desativadas."})
    dialog = ActionSearch(registry, registry.dispatch)
    dialog.show()
    dialog.query.setText("RELOGIO")
    assert dialog.results.count() == 1 and not dialog.run.isEnabled()
    assert "Projeções desativadas" in dialog.status.text()
    QTest.keyClick(dialog.query, Qt.Key.Key_Return)
    assert not calls
    dialog.query.setText("musica windows")
    QTest.keyClick(dialog.query, Qt.Key.Key_Return)
    assert calls == ["media"] and not dialog.isVisible()
    assert [item.id for item in navigation(music=False)["main"]][2] == "tasks"


def test_every_wheel_destination_is_dispatchable_once_from_menu_and_search(qapp):
    leaves = {item.id for items in NAVIGATION.values() for item in items if item.id not in NAVIGATION}
    calls = []
    callbacks = {key: lambda key=key: calls.append(key) for key in leaves | {
        "interact", "show", "hide", "restore", "exit", "pass_through",
    }}
    callbacks["tools"] = callbacks["tools_center"]
    registry = ActionRegistry(callbacks)
    menu = create_menu(None, {**callbacks, "paused": lambda: False, "passing": lambda: False},
                       Settings(), [], True, registry=registry, dispatch=registry.dispatch)
    dialog = ActionSearch(registry, registry.dispatch)
    for key in sorted(leaves):
        action = next(action for action in menu.action_refs if action.data() == ("tools" if key == "tools_center" else key))
        calls.clear()
        action.trigger()
        assert calls == [key]
        dialog.show()
        row = next(row for row in range(dialog.results.count())
                   if dialog.results.item(row).data(Qt.ItemDataRole.UserRole) == key)
        dialog.results.setCurrentRow(row)
        QTest.keyClick(dialog.query, Qt.Key.Key_Return)
        assert calls == [key, key] and not dialog.isVisible()
    menu.deleteLater()


@pytest.mark.parametrize("key", ["focus", "media", "minigames", "diagnostics"])
def test_wheel_menu_search_share_destination_once(pet, key, monkeypatch):
    calls = []
    original = pet.actions.callbacks[key]

    def record():
        calls.append(key)
        return original()

    monkeypatch.setitem(pet.actions.callbacks, key, record)
    pet.companion_state.update("accessibility", {"reduced_motion": True})
    pet.radial.popup_near(pet.window)
    if key in {"minigames", "diagnostics"}:
        pet.radial.select("tools")
        rects = [button.geometry() for button in pet.radial.buttons.values()]
        assert not any(a.intersects(b) for a, b in combinations(rects, 2))
    else:
        assert [item.id for item in NAVIGATION["main"]] == ["garage", "focus", "media", "tools", "project", "configuration"]
    pet.radial.select(key)
    pet.radial.select(key)
    assert calls == [key] and "radial" not in pet.controller.gates
    assert pet.tools.tabs.currentWidget() is pet.tools.pages[key]
    pet.tools.showMinimized()
    next(action for action in pet.menu.action_refs if action.data() == key).trigger()
    assert calls == [key, key] and not pet.tools.isMinimized()
    pet.tools.close()
    pet.show_action_search()
    dialog = pet.action_search
    row = next(row for row in range(dialog.results.count())
               if dialog.results.item(row).data(Qt.ItemDataRole.UserRole) == key)
    dialog.results.setCurrentRow(row)
    QTest.keyClick(dialog.query, Qt.Key.Key_Return)
    assert calls == [key] * 3 and pet.tools.tabs.currentWidget() is pet.tools.pages[key]
    assert not dialog.isVisible()
