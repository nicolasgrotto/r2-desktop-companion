import argparse
import json
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QMediaDevices, QSoundEffect
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion.app import Companion
from r2_companion.core.config import Settings
from r2_companion.services.storage import ConfigStore


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".runtime-features-v03"))
    args = parser.parse_args()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    store = ConfigStore(args.data_dir.resolve())
    if not store.acquire():
        return 2
    settings = Settings(suppress_fullscreen=False)
    settings.sound_enabled = True
    settings.audio.volume = 0.05
    settings.behavior.cursor_attention = False
    store.apply(settings)
    pet = Companion(app, store)
    pet.idle_timer.stop()
    pet.awareness.timer.stop()
    report = {"audio_outputs": len(QMediaDevices.audioOutputs())}
    pet.productivity.add_task("Conferir montagem do robô")
    pet.productivity.add_task("Organizar os cabos da bancada")
    note = pet.productivity.add_note()
    pet.productivity.edit_note(note, "Próxima montagem", "Conferir as medidas da base.\nSeparar os conectores e testar a iluminação.")
    pet.tools.tasks_page.render()
    pet.tools.notes_page.render(note)

    def capture_tasks():
        pet.show_tools_page(3)
        QTimer.singleShot(200, lambda: pet.tools.grab().save(str(store.directory / "tasks.png")))

    def capture_notes():
        pet.show_tools_page(4)
        QTimer.singleShot(200, lambda: pet.tools.grab().save(str(store.directory / "notes.png")))

    def capture_audio():
        pet.tools.hide()
        pet.show_settings()
        pet.settings_dialog.tabs.setCurrentIndex(2)
        QTimer.singleShot(200, lambda: pet.settings_dialog.grab().save(str(store.directory / "audio.png")))

    def play_sound():
        pet.settings_dialog.reject()
        pet.audio.last_play = -1000000
        pet.audio.history.clear()
        report["loaded_sounds"] = sum(effect.status() == QSoundEffect.Status.Ready
            for effects in pet.audio.effects.values() for _, effect in effects)
        report["playback_accepted"] = pet.audio.play("notifications", "timer")
        report["effect_playing"] = any(effect.isPlaying() for effects in pet.audio.effects.values() for _, effect in effects)

    def finish():
        report["tasks"] = len(pet.productivity.data["tasks"])
        report["notes"] = len(pet.productivity.data["notes"])
        pet.shutdown()
        report["active_timers_after_shutdown"] = sum(timer.isActive() for timer in
            (pet.animation.timer, pet.behavior.timer, pet.positioning.timer, pet.countdown.timer,
             pet.monitor.timer, pet.awareness.timer, pet.productivity.timer, pet.greeting_timer,
             pet.idle_timer, pet.desktop_timer, pet.radial.dismiss_timer, pet.tools.clock_timer, store.timer))
        (store.directory / "features.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    QTimer.singleShot(1000, capture_tasks)
    QTimer.singleShot(2000, capture_notes)
    QTimer.singleShot(3000, capture_audio)
    QTimer.singleShot(4000, play_sound)
    QTimer.singleShot(5000, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
