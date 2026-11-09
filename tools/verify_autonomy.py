"""Observe a real autonomous walk and balloon tracking in an isolated awake session."""
import argparse
import json
from pathlib import Path
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion.app import Companion
from r2_companion.core.config import Settings
from r2_companion.pet.state import State
from r2_companion.services.storage import ConfigStore


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(".runtime-autonomy-v02"))
    args = parser.parse_args()
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    store = ConfigStore(args.data_dir.resolve())
    if not store.acquire():
        return 2
    store.apply(Settings(suppress_fullscreen=False))
    companion = Companion(app, store)
    companion.idle_timer.stop()
    started = time.monotonic()
    report = {"first_walk_seconds": None, "position_changed": False,
              "balloon_followed": False, "result": "pending"}
    origin = None
    bubble_origin = None

    def changed(state):
        nonlocal origin, bubble_origin
        if state == State.WALK and origin is None:
            report["first_walk_seconds"] = time.monotonic() - started
            origin = companion.window.pos()
            companion.bubble.present("Explorando um pouco por aqui.", companion.window)
            bubble_origin = companion.bubble.pos()

    def sample():
        if origin is not None:
            delta = companion.window.pos() - origin
            report["position_changed"] |= not delta.isNull()
            if not delta.isNull() and companion.bubble.isVisible():
                report["balloon_followed"] |= companion.bubble.pos() - bubble_origin == delta
        elapsed = time.monotonic() - started
        if elapsed >= 35 or (report["position_changed"] and report["balloon_followed"] and
                             companion.controller.state != State.WALK):
            timer.stop()
            report["duration_seconds"] = elapsed
            report["result"] = "passed" if report["position_changed"] and report["balloon_followed"] else "failed"
            companion.shutdown()
            report["active_timers_after_shutdown"] = sum(t.isActive() for t in
                (companion.animation.timer, companion.behavior.timer, companion.positioning.timer,
                 companion.bubble.timer, companion.radial.dismiss_timer, companion.store.timer))
            (store.directory / "autonomy.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    companion.controller.state_changed.connect(changed)
    timer = QTimer()
    timer.setInterval(100)
    timer.timeout.connect(sample)
    timer.start()
    app.exec()
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
