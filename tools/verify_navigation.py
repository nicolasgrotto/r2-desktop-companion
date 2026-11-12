import argparse
import json
from pathlib import Path
import sys

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion import __version__
from r2_companion.app import Companion
from r2_companion.core.config import Settings
from r2_companion.services.storage import ConfigStore
from r2_companion.ui.updates import UpdateCenter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".runtime-navigation-v111"))
    args = parser.parse_args()
    directory = args.data_dir.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    store = ConfigStore(directory)
    if not store.acquire():
        return 2
    settings = Settings(suppress_fullscreen=False)
    settings.behavior.cursor_attention = False
    settings.behavior.movement = False
    store.apply(settings)
    pet = Companion(app, store)
    pet.greeting_timer.stop()
    pet.desktop_timer.stop()
    pet.idle_timer.stop()
    pet.awareness.timer.stop()
    updates = UpdateCenter(directory)
    updates.startup.stop()
    report = {"version": __version__, "profiles": {}, "callback_errors": [], "physical_validation": False}
    sys.excepthook = lambda kind, value, trace: report["callback_errors"].append(str(value))
    def capture(name, widget):
        assert widget.isVisible()
        assert widget.grab().save(str(directory / f"{identifier}-{name}.png"))
    def click(key):
        QTest.mouseClick(pet.radial.buttons[key], Qt.MouseButton.LeftButton)
        QTest.qWait(300)
    try:
        QTest.qWait(150)
        for identifier in pet.droids.profiles:
            assert pet.equip_droid(identifier)
            profile = {}
            report["profiles"][identifier] = profile
            pet.radial.popup_near(pet.window)
            QTest.qWait(100)
            capture("wheel-main", pet.radial)
            QTest.mouseClick(pet.radial.buttons["tools"], Qt.MouseButton.LeftButton)
            QTest.qWait(110)
            capture("wheel-transition", pet.radial)
            QTest.qWait(190)
            assert pet.radial.level == "tools"
            capture("wheel-tools", pet.radial)
            click("tools_center")
            assert pet.tools.isVisible() and pet.window.hologram.isNull()
            capture("tools", pet.tools)
            pet.tools.close()
            for key in ("minigames", "diagnostics"):
                pet.refresh_menu()
                action = next(a for a in pet.menu.action_refs if a.data() == key)
                menu = action.parent()
                menu.popup(pet.window.pos())
                QTest.qWait(40)
                QTest.mouseClick(menu, Qt.MouseButton.LeftButton, pos=menu.actionGeometry(action).center())
                QTest.qWait(100)
                assert pet.tools.isVisible() and pet.tools.tabs.currentWidget() is pet.tools.pages[key]
                assert pet.window.hologram.isNull()
                capture(key, pet.tools)
                profile[key] = True
                pet.tools.close()
            pet.radial.popup_near(pet.window)
            click("project")
            capture("wheel-project", pet.radial)
            click("project_date")
            assert pet.window.projection_kind == "date"
            QTest.qWait(2100)
            assert not pet.window.hologram.isNull()
            profile["projection_text"] = pet.window.projection_text
            capture("projection", pet.window.projection_overlay)
            pet.window.clear_projection()
            pet.show_garage()
            garage = pet.garage_dialog
            garage.selector.setCurrentIndex(garage.selector.findData(identifier))
            garage.animations.setCurrentRow(3)
            QTest.qWait(100)
            capture("garage", garage)
            profile["animations"] = garage.animations.count()
            garage.close()
            updates.theme_watcher.refresh()
            updates.show()
            for state, title in (("checking", "Verificando atualização"), ("download", "Baixando atualização"),
                                 ("integrity", "Validando pacote"), ("preparing", "Preparando instalação"),
                                 ("restarting", "Reiniciando o Companion"), ("done", "Atualização concluída")):
                updates.set_state(state, title, "Prévia visual local; nenhuma operação de rede ou instalação é executada aqui.")
                if state == "download":
                    updates.download_progress(1200000, 3000000)
                QTest.qWait(60)
                capture("updates-" + state, updates)
            updates.hide()
            profile["theme"] = pet.profile.theme.name
    except Exception as error:
        report["callback_errors"].append(str(error))
    finally:
        updates.closing = True
        updates.close()
        pet.shutdown()
    report["passed"] = not report["callback_errors"] and set(report["profiles"]) == set(pet.droids.profiles)
    (directory / "validation.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
