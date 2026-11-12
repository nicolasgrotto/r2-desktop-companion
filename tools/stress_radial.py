import argparse
import ctypes
from ctypes import wintypes
from copy import deepcopy
import json
from pathlib import Path
import random
import sys
import time

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from r2_companion.app import Companion
from r2_companion.pet.state import State
from r2_companion.services.storage import ConfigStore
from r2_companion.ui.navigation import NAVIGATION


def wait_until(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise TimeoutError("Estado esperado não foi alcançado")
        QTest.qWait(5)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--cycles", type=int, default=100)
    parser.add_argument("--seed", type=int, default=112)
    args = parser.parse_args()
    output = args.data_dir.resolve()
    if output.exists() or not output.is_relative_to(root) or not 1 <= args.cycles <= 5000:
        parser.error("Use uma pasta nova no repositório e 1 a 5000 sequências")
    output.mkdir(parents=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    store = ConfigStore(output / "data")
    assert store.acquire()
    pet = Companion(app, store)
    pet.greeting_timer.stop()
    pet.idle_timer.stop()
    pet.desktop_timer.stop()
    pet.awareness.timer.stop()
    pet.controller.enter(State.IDLE)
    pet.navigation_trace.verbose = True
    randomizer = random.Random(args.seed)
    outside = QWidget()
    outside.setWindowTitle("Radial stress test")
    outside.resize(120, 80)
    records, errors = [], []
    original_hook = sys.excepthook
    sys.excepthook = lambda kind, error, tb: errors.append(type(error).__name__)
    preferences = deepcopy(store.settings.droid_preferences)
    pet.productivity.add_task("Stress fixture")
    expected_tools = deepcopy(pet.productivity.data)
    actions = [(level, item.id) for level, items in NAVIGATION.items()
               for item in items if item.id not in NAVIGATION and item.id != "updates"]
    operations = ["normal", "stop_exit", "stop_enter", "pause", "destroy", "early_selection",
                  "hide_reopen", "focus", "minimize", "secondary", "recreate", "rapid_back", "pet_input", "pet_toggle"]
    user32 = ctypes.WinDLL("user32")
    user32.GetForegroundWindow.restype = wintypes.HWND
    foreground = user32.GetForegroundWindow()
    try:
        for index in range(args.cycles):
            operation = operations[index % len(operations)]
            level, key = actions[index % len(actions)]
            record = {"index": index, "operation": operation, "action": key,
                      "started_ns": time.monotonic_ns(), "passed": False}
            error_count = len(errors)
            try:
                wheel = pet.radial
                if operation == "secondary":
                    pet.show_garage()
                    pet.show_audio_center()
                    pet.show_settings()
                    pet.show_tools()
                elif operation == "recreate":
                    pet.show_settings()
                    pet.settings_dialog.close()
                    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
                    pet.show_settings()
                    pet.settings_dialog.close()
                elif operation == "minimize":
                    pet.window.showMinimized()
                    pet.window.showNormal()
                wheel.popup_near(pet.window)
                if operation in {"pet_input", "pet_toggle"}:
                    if operation == "pet_toggle":
                        QTest.mouseClick(pet.window, Qt.MouseButton.LeftButton, pos=QPoint(80, 110))
                        assert not wheel.isVisible()
                    else:
                        wheel.hide()
                    QTest.mouseClick(pet.window, Qt.MouseButton.LeftButton, pos=QPoint(80, 110))
                    assert wheel.isVisible()
                elif operation in {"stop_exit", "stop_enter", "pause", "destroy", "early_selection"}:
                    wheel.select("tools")
                    if operation in {"stop_enter", "early_selection"}:
                        wheel.transition.setCurrentTime(wheel.transition.duration())
                    if operation == "destroy":
                        group = wheel.transition
                        group.deleteLater()
                        QCoreApplication.sendPostedEvents(group, QEvent.Type.DeferredDelete)
                    elif operation == "pause":
                        wheel.transition.pause()
                    elif operation != "early_selection":
                        wheel.transition.stop()
                    if operation == "early_selection":
                        QTest.mouseClick(wheel.buttons["notes"], Qt.MouseButton.LeftButton)
                        assert pet.tools.isVisible() and pet.tools.tabs.currentWidget() is pet.tools.pages["notes"]
                        pet.tools.close()
                    else:
                        assert not wheel.transitioning and all(b.isEnabled() for b in wheel.buttons.values())
                    wheel.hide()
                    wheel.popup_near(pet.window)
                elif operation == "hide_reopen":
                    wheel.select("tools")
                    QTest.qWait(randomizer.choice([0, 1, 16, 50, 100]))
                    wheel.hide()
                    wheel.popup_near(pet.window)
                elif operation == "focus":
                    outside.show()
                    app.setActiveWindow(outside)
                    wait_until(lambda: not wheel.isVisible())
                    outside.hide()
                    wheel.popup_near(pet.window)
                elif operation == "rapid_back":
                    wheel.select("configuration")
                    wheel.transition.setCurrentTime(wheel.transition.duration())
                    wheel.back()
                    wait_until(lambda: not wheel.transitioning)
                    assert wheel.level == "main"
                if level != "main":
                    if level == "companion":
                        QTest.mouseClick(wheel.buttons["configuration"], Qt.MouseButton.LeftButton)
                        wait_until(lambda: not wheel.transitioning)
                    QTest.mouseClick(wheel.buttons[level], Qt.MouseButton.LeftButton)
                    wait_until(lambda: not wheel.transitioning)
                    assert wheel.level == level
                QTest.mouseClick(wheel.buttons[key], Qt.MouseButton.LeftButton)
                assert not wheel.isVisible() and not wheel.transitioning and "radial" not in pet.controller.gates
                destination = pet.navigation_destination(key)
                if destination is not None:
                    assert destination.isVisible() and not destination.isMinimized()
                    if key in pet.tools.pages:
                        assert pet.tools.tabs.currentWidget() is pet.tools.pages[key]
                elif key.startswith("project_"):
                    assert pet.window.projection_kind == {"project_clock": "clock", "project_date": "date", "project_stop": None}[key]
                assert store.settings.droid_preferences == preferences
                assert pet.productivity.data == expected_tools
                assert len(errors) == error_count
                record["passed"] = True
                record["attempt"] = pet.navigation_trace.attempt
            except Exception as error:
                record["error"] = type(error).__name__ + ": " + str(error)
                pet.radial.grab().save(str(output / f"failure-{index}.png"))
            finally:
                pet.radial.hide()
                outside.hide()
                for widget in (pet.tools, pet.garage_dialog, pet.audio_dialog, pet.settings_dialog):
                    if widget is not None:
                        widget.close()
                if pet.controller.paused:
                    pet.toggle_pause()
                records.append(record)
                with (output / "attempts.jsonl").open("a", encoding="utf-8") as target:
                    target.write(json.dumps(record) + "\n")
                if (index + 1) % 10 == 0:
                    print(json.dumps({"completed": index + 1, "failed": sum(not r["passed"] for r in records)}), flush=True)
    finally:
        exit_action = next(action for action in pet.menu.action_refs if action.data() == "exit")
        exit_action.trigger()
        menu_exit = pet.closed
        pet.shutdown()
        outside.close()
        sys.excepthook = original_hook
    report = {"seed": args.seed, "cycles": args.cycles, "passed": all(r["passed"] for r in records) and not errors,
              "successes": sum(r["passed"] for r in records), "failures": sum(not r["passed"] for r in records),
              "callback_errors": errors, "foreground_available": bool(foreground),
              "classification": "automated Qt widget stress; not a manual physical-input approval",
              "preferences_preserved": store.settings.droid_preferences == preferences,
              "tools_preserved": pet.productivity.data == expected_tools, "trace_stopped": not pet.navigation_trace.worker.is_alive()}
    report["menu_exit"] = menu_exit
    report["passed"] = report["passed"] and menu_exit and report["trace_stopped"]
    (output / "stress.json").write_text(json.dumps(report, indent=2))
    print(json.dumps(report), flush=True)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
