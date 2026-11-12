"""Export native-size rig poses and animated contact sheets for visual review."""
import argparse
from pathlib import Path
import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion.app import ASSETS
from r2_companion.droids.movement import create_movement
from r2_companion.droids.profiles import DroidRegistry
from r2_companion.droids.visuals import load_profile_clips, paint_visual
from r2_companion.pet.state import State
from r2_companion.pet.window import PetWindow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("local_docs/v12-visual"))
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    app = QApplication.instance() or QApplication([])
    registry = DroidRegistry(ASSETS)
    if registry.errors:
        raise ValueError(registry.errors)
    contact = QImage(7 * 180, 4 * 208, QImage.Format.Format_ARGB32)
    contact.fill(QColor("#e8edf0"))
    painter = QPainter(contact)
    painter.setFont(QFont("Segoe UI", 11))
    states = (State.IDLE, State.LOOK_AROUND, State.HAPPY, State.SLEEP)
    durations = {}
    for col, profile in enumerate(registry.profiles.values()):
        clips = load_profile_clips(profile)
        durations[profile.id] = {state: clip.duration for state, clip in clips.items()}
        for row, state in enumerate(states):
            f = clips[state].frames[min(3, len(clips[state].frames) - 1)]
            rect = QRectF(col * 180 + 10, row * 208 + 25, 160, 160)
            painter.setPen(QColor("#263744"))
            painter.drawText(col * 180 + 10, row * 208 + 20, profile.name + " · " + state.value)
            if f.visual:
                paint_visual(painter, rect, f.visual)
            else:
                painter.drawPixmap(rect.toRect(), f.pixmap)
        if profile.renderer != "rigged":
            continue
        window = PetWindow()
        window.resize(160, 160)
        motion = create_movement(profile, window)
        for state in State:
            sheet = QImage(160 * 12, 160, QImage.Format.Format_ARGB32)
            sheet.fill(Qt.GlobalColor.transparent)
            p = QPainter(sheet)
            for i, frame in enumerate(clips[state].frames):
                if state == State.WALK:
                    motion.displaced(4, 0)
                paint_visual(p, QRectF(i * 160, 0, 160, 160), frame.visual, motion=motion.channels if state == State.WALK else {})
            p.end()
            sheet.save(str(args.output / f"{profile.id}-{state.value}.png"))
        motion.close()
        window.close()
    painter.end()
    contact.save(str(args.output / "contact.png"))
    cards = "\n".join(f'<section><h2>{profile.name}</h2>' + "".join(
        f'<div><p>{state.value}</p><div class="sprite" style="background-image:url({profile.id}-{state.value}.png);animation-duration:{durations[profile.id][state]}ms"></div></div>'
        for state in State) + '</section>' for profile in registry.profiles.values() if profile.renderer == "rigged")
    (args.output / "animations.html").write_text('''<!doctype html><meta charset="utf-8"><title>Revisão visual 1.2</title>
<style>body{background:#e8edf0;color:#263744;font:14px system-ui}section{display:flex;flex-wrap:wrap;gap:16px}h2{width:100%}.sprite{width:160px;height:160px;image-rendering:pixelated;animation:play 1.5s steps(12) infinite}@keyframes play{to{background-position:-1920px 0}}</style>''' + cards, encoding="utf-8")


if __name__ == "__main__":
    main()
