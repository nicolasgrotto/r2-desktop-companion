import argparse
import json
from pathlib import Path
import sys

from PySide6.QtCore import QTimer
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion.app import Companion
from r2_companion.core.config import Settings
from r2_companion.services.storage import ConfigStore
from r2_companion.services.update_client import ASSET, REPOSITORY, validate_release
from r2_companion.ui.updates import UpdateCenter


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".runtime-v11-preview"))
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
    pet = Companion(app, store)
    pet.idle_timer.stop()
    pet.awareness.timer.stop()
    report = {"update_source": "local fixture", "test_volume": 0.05}
    raw = {"tag_name": "v1.2.0", "draft": False, "prerelease": False,
           "body": "Novidades de uma release de teste\n\nMelhorias de personalidade e novas interações.",
           "assets": [{"name": name, "size": 100, "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/v1.2.0/{name}"}
                      for name in (ASSET, ASSET + ".sha256")]}
    updates = UpdateCenter(store.directory, client=lambda repository: validate_release(raw, repository))
    updates.startup.stop()

    def minigames():
        pet.show_tools_page(pet.tools.tabs.indexOf(pet.tools.minigames_page))
        QTimer.singleShot(150, lambda: pet.tools.grab().save(str(store.directory / "minigames.png")))

    def diagnose():
        pet.show_tools_page(pet.tools.tabs.indexOf(pet.tools.diagnostics_page))
        pet.tools.diagnostics_page.start()
        QTimer.singleShot(800, lambda: pet.tools.grab().save(str(store.directory / "diagnostics.png")))

    def update_preview():
        pet.tools.hide()
        updates.show()
        updates.check()
        QTimer.singleShot(300, lambda: updates.grab().save(str(store.directory / "updates.png")))

    def appearance():
        pet.window.set_appearance("violet")
        pet.show_settings()
        QTimer.singleShot(150, lambda: pet.settings_dialog.grab().save(str(store.directory / "settings.png")))
        QTimer.singleShot(200, lambda: pet.window.grab().save(str(store.directory / "violet.png")))

    def audio():
        pet.settings_dialog.reject()
        report["voices_ready"] = sum(effect.status() == QSoundEffect.Status.Ready for values in pet.audio.voices.values() for _, effect in values)
        pet.audio.last_play = -1000000
        pet.audio.history.clear()
        report["voice_accepted"] = pet.audio.vocalize("greeting")
        report["voice_playing"] = any(effect.isPlaying() for values in pet.audio.voices.values() for _, effect in values)

    def finish():
        report["update_state"] = updates.state
        updates.close()
        pet.shutdown()
        report["active_timers_after_shutdown"] = sum(timer.isActive() for timer in
            (pet.animation.timer, pet.behavior.timer, pet.positioning.timer, pet.awareness.timer,
             pet.window.affection_timer, pet.window.hologram_timer, pet.tools.diagnostics_page.timer,
             pet.store.timer, pet.productivity.timer, pet.greeting_timer, pet.tray.notice.timer,
             updates.poll, updates.animation.timer, updates.startup))
        (store.directory / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    QTimer.singleShot(700, minigames)
    QTimer.singleShot(1500, diagnose)
    QTimer.singleShot(2600, update_preview)
    QTimer.singleShot(3500, appearance)
    QTimer.singleShot(4400, audio)
    QTimer.singleShot(5500, finish)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
