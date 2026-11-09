"""Export original geometric development assets; never called by the application."""
from pathlib import Path
import json
import math
import struct
import wave

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[1] / "src/r2_companion/assets"
STATES = ["IDLE", "BLINK", "LOOK_AROUND", "WALK", "HAPPY", "CURIOUS", "SLEEP", "INTERACT", "NOTIFICATION"]


def frame_svg(state, index):
    def rect(x, y, w, h, color):
        return f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}"/>'
    dark, white, shade, blue, light = "#17314b", "#eef3f7", "#aebecb", "#286bc0", "#71d1ee"
    pieces = [rect(12, 24, 9, 27, dark), rect(43, 24, 9, 27, dark),
              rect(14, 26, 5, 22, white), rect(45, 26, 5, 22, shade),
              rect(18, 20, 28, 32, dark), rect(20, 22, 24, 28, white),
              rect(22, 26, 8, 5, blue), rect(32, 26, 10, 3, shade),
              rect(22, 34, 20, 3, blue), rect(22, 40, 7, 7, shade),
              rect(32, 40, 10, 7, blue)]
    lift = -2 if state == "HAPPY" and index % 2 else 0
    pieces += [rect(18, 13 + lift, 28, 9, dark), rect(22, 8 + lift, 20, 6, dark),
               rect(24, 6 + lift, 16, 3, dark), rect(20, 15 + lift, 24, 5, shade),
               rect(24, 10 + lift, 16, 5, white), rect(26, 8 + lift, 12, 3, white)]
    eye_x = 30 + ((index - 1) * 3 if state == "LOOK_AROUND" else 0)
    eye_h = 2 if state in {"BLINK", "SLEEP"} and index % 2 == 0 else 6
    pieces += [rect(eye_x - 1, 12 + lift, 8, 8, dark), rect(eye_x, 13 + lift, 6, eye_h, blue),
               rect(eye_x + 1, 13 + lift, 2, min(2, eye_h), light)]
    led = "#50c691" if state in {"HAPPY", "INTERACT"} else ("#ffcc61" if state == "NOTIFICATION" else blue)
    pieces += [rect(22, 23, 3, 2, led), rect(39, 23, 3, 2, led),
               rect(10, 50, 13, 6, dark), rect(41, 50, 13, 6, dark),
               rect(12, 50 - (index % 2 if state == "WALK" else 0), 9, 3, blue),
               rect(43, 50 + (index % 2 if state == "WALK" else 0), 9, 3, blue),
               rect(26, 52, 12, 3, dark)]
    if state == "CURIOUS":
        pieces += [rect(48, 8, 3, 8, light), rect(48, 18, 3, 3, blue)]
    if state == "SLEEP":
        pieces += [rect(46, 5, 7, 2, shade), rect(50, 7, 3, 2, shade), rect(46, 9, 7, 2, shade)]
    return '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" shape-rendering="crispEdges">' + ''.join(pieces) + '</svg>'


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    character = ROOT / "characters/default"
    character.mkdir(parents=True, exist_ok=True)
    (ROOT / "icons").mkdir(exist_ok=True)
    (ROOT / "sounds").mkdir(exist_ok=True)
    sheet = QImage(64 * 4, 64 * len(STATES), QImage.Format.Format_ARGB32)
    sheet.fill(Qt.GlobalColor.transparent)
    painter = QPainter(sheet)
    clips = {}
    for row, state in enumerate(STATES):
        count = 1 if state in {"IDLE", "SLEEP"} else 4
        frames = []
        for column in range(count):
            renderer = QSvgRenderer(QByteArray(frame_svg(state, column).encode()))
            renderer.render(painter, QRectF(column * 64, row * 64, 64, 64))
            frames.append({"image": "placeholder.png", "rect": [column * 64, row * 64, 64, 64],
                           "duration_ms": 180 if state != "BLINK" else 100})
        clips[state] = {"loop": state in {"IDLE", "SLEEP", "WALK"}, "frames": frames}
    painter.end()
    if not sheet.save(str(character / "placeholder.png")):
        raise RuntimeError("PNG export failed")
    manifest = {"manifest_version": 1, "character_id": "original-development-placeholder",
                "placeholder": True, "canvas": [64, 64], "anchor": [32, 56], "clips": clips}
    (character / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    icon = sheet.copy(0, 0, 64, 64)
    icon.save(str(ROOT / "icons/companion.png"))
    icon.save(str(ROOT / "icons/companion.ico"))
    with wave.open(str(ROOT / "sounds/completion.wav"), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(22050)
        samples = []
        for n in range(11025):
            t = n / 22050
            frequency = 660 if t < 0.25 else 880
            envelope = min(1, (t % 0.25) * 40) * max(0, 1 - (t % 0.25) / 0.25)
            samples.append(struct.pack('<h', int(5000 * envelope * math.sin(2 * math.pi * frequency * t))))
        output.writeframes(b''.join(samples))


if __name__ == "__main__":
    main()
