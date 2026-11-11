import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
import time

import psutil
from PySide6.QtCore import QCoreApplication, QEvent, QPointF, QTimer
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion import __version__
from r2_companion.app import Companion
from r2_companion.core.config import Settings
from r2_companion.pet.state import State
from r2_companion.services.storage import ConfigStore
from r2_companion.ui.updates import UpdateCenter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".runtime-multidroid-verification"))
    args = parser.parse_args()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    store = ConfigStore(args.data_dir.resolve())
    if not store.acquire():
        return 2
    settings = Settings(suppress_fullscreen=False, sound_enabled=True)
    settings.audio.volume = 0.05
    settings.behavior.cursor_attention = False
    store.apply(settings)
    companion = Companion(app, store)
    companion.idle_timer.stop()
    companion.desktop_timer.stop()
    companion.awareness.timer.stop()
    companion.greeting_timer.stop()
    updates = UpdateCenter(store.directory, client=lambda repo: None)
    updates.startup.stop()
    updates.set_state("idle", "Prévia local", "Sem consulta de rede neste ensaio.")
    process = psutil.Process()
    report = {"profiles": {}, "switches": [], "callback_errors": [], "physical_audibility_verified": False}
    sys.excepthook = lambda kind, value, tb: report["callback_errors"].append(str(value))
    steps = []

    def equip(identifier):
        started = time.perf_counter()
        accepted = companion.equip_droid(identifier)
        elapsed = time.perf_counter() - started
        if not accepted:
            raise RuntimeError(companion.droid_error)
        preferences = deepcopy(store.settings)
        preferences.audio.volume = 0.05
        store.apply(preferences)
        report["profiles"][identifier] = {"equip_ms": elapsed * 1000, "diagnostics": companion.droid_diagnostics()}
        companion.show_garage()
        garage = companion.garage_dialog
        garage.selector.setCurrentIndex(garage.selector.findData(identifier))

    def capture(identifier, name, widget):
        if not widget.grab().save(str(store.directory / f"{identifier}-{name}.png")):
            raise RuntimeError("Falha de captura")

    def garage(identifier):
        capture(identifier, "garage", companion.garage_dialog)
        companion.garage_dialog.hide()
        companion.show_audio_center()
        companion.audio_dialog.selector.setCurrentIndex(companion.audio_dialog.selector.findData(identifier))
        companion.audio.last_play = -1000000
        companion.audio.history.clear()
        report["profiles"][identifier]["audio_ready"] = sum(e.status() == QSoundEffect.Status.Ready for e in companion.audio.all_effects())
        report["profiles"][identifier]["audio_accepted"] = companion.audio.vocalize("greeting")
        report["profiles"][identifier]["audio_playing"] = any(e.isPlaying() for e in companion.audio.all_effects())

    def audio(identifier):
        capture(identifier, "audio", companion.audio_dialog)
        companion.audio_dialog.hide()
        companion.show_garage()
        gallery = companion.garage_dialog
        gallery.selector.setCurrentIndex(gallery.selector.findData(identifier))
        gallery.animations.setCurrentRow(3)
        area = companion.positioning.screen.availableGeometry()
        companion.positioning.place(QPointF(area.center().x() - companion.window.width() / 2,
                                            area.center().y() - companion.window.height() / 2))
        companion.walk_now()
        report["profiles"][identifier]["walk_started"] = {"state": companion.controller.state.value,
            "gates": sorted(companion.controller.gates), "position": companion.window.pos().toTuple(),
            "timer": companion.positioning.timer.isActive()}

    def gallery(identifier):
        capture(identifier, "gallery", companion.garage_dialog)
        capture(identifier, "desktop", companion.window)
        report["profiles"][identifier]["body_angle_during_walk"] = companion.window.body_angle
        report["profiles"][identifier]["walk_observed"] = {"state": companion.controller.state.value,
            "gates": sorted(companion.controller.gates), "position": companion.window.pos().toTuple(),
            "timer": companion.positioning.timer.isActive()}
        companion.garage_dialog.hide()
        companion.show_tools_page(4)

    def tools(identifier):
        capture(identifier, "tools", companion.tools)
        companion.tools.hide()
        companion.show_settings()

    def preferences(identifier):
        capture(identifier, "settings", companion.settings_dialog)
        companion.settings_dialog.close()
        updates.theme_watcher.refresh()
        updates.show()

    def updater(identifier):
        capture(identifier, "updates", updates)
        updates.hide()

    for identifier in companion.droids.profiles:
        for action in (equip, garage, audio, gallery, tools, preferences, updater):
            steps.append(lambda action=action, identifier=identifier: action(identifier))

    def switch(identifier):
        started = time.perf_counter()
        accepted = companion.equip_droid(identifier)
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        report["switches"].append({"id": identifier, "accepted": accepted,
                                   "milliseconds": (time.perf_counter() - started) * 1000,
                                   "rss": process.memory_info().rss,
                                   "audio_objects": len(companion.audio.findChildren(QSoundEffect))})

    for _ in range(6):
        for identifier in companion.droids.profiles:
            steps.append(lambda identifier=identifier: switch(identifier))

    def finish():
        ticker.stop()
        updates.close()
        companion.shutdown()
        report["active_timers_after_shutdown"] = sum(t.isActive() for t in companion.findChildren(QTimer))
        report["movement_timer_after_shutdown"] = bool(getattr(companion.positioning.movement, "timer", None)
                                                       and companion.positioning.movement.timer.isActive())
        report["all_switches_accepted"] = all(r["accepted"] for r in report["switches"])
        report["version"] = __version__
        (store.directory / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    def step():
        try:
            if steps:
                steps.pop(0)()
            else:
                finish()
        except Exception as error:
            report["callback_errors"].append(str(error))
            finish()

    ticker = QTimer()
    ticker.setInterval(350)
    ticker.timeout.connect(step)
    ticker.start()
    app.exec()
    return 1 if report["callback_errors"] or not report.get("all_switches_accepted") else 0


if __name__ == "__main__":
    raise SystemExit(main())
