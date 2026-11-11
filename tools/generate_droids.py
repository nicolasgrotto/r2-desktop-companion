import json
import math
from pathlib import Path
import random
import struct
import sys
import wave

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPolygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion.pet.state import State
from r2_companion.services.vocalizations import PHRASES
from generate_voice import SYLLABLES

ROOT = Path(__file__).resolve().parents[1] / "src/r2_companion/assets"
CATEGORIES = {s.value: "Expressões" for s in State}
CATEGORIES.update(IDLE="Repouso", SLEEP="Repouso", WAKE="Repouso", WALK="Locomoção", DRAG="Locomoção",
                  RECOVER="Locomoção", OVERHEAT="Inspeção", WORK="Inspeção", WORRIED="Inspeção",
                  GREETING="Interações", INTERACT="Interações", NOTIFICATION="Interações")


def save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def image(width, height):
    picture = QImage(width, height, QImage.Format.Format_ARGB32)
    picture.fill(Qt.GlobalColor.transparent)
    return picture


def dark_frame(state, index):
    picture = image(64, 64)
    p = QPainter(picture)
    p.setPen(Qt.PenStyle.NoPen)
    def box(x, y, w, h, color):
        p.fillRect(x, y, w, h, QColor(color))
    def polygon(points, color):
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygon([QPoint(x, y) for x, y in points]))
    ink, black, steel, edge, bronze, gold = "#10151c", "#202730", "#313c47", "#536170", "#9d7045", "#d4aa6b"
    phase = math.sin(index * math.pi / 3)
    bob = round(phase) if state in {"WALK", "HAPPY", "GREETING", "INTERACT"} else 0
    eye = -3 if state == "LOOK_LEFT" else 3 if state == "LOOK_RIGHT" else round(phase * 3) if state in {"LOOK_AROUND", "CURIOUS", "WORK", "CONFUSED"} else 0
    lift = -2 if state in {"SURPRISED", "WAKE", "DRAG"} and index in {1, 2, 3} else 0
    polygon([(12, 51), (14, 29), (20, 27), (22, 53)], ink)
    polygon([(44, 27), (50, 29), (52, 51), (42, 53)], ink)
    box(14, 31, 4, 18, bronze)
    box(46, 31, 3, 18, bronze)
    box(15, 33, 1, 13, gold)
    box(47, 33, 1, 13, black)
    polygon([(20, 22 + bob), (44, 22 + bob), (46, 49 + bob), (40, 54 + bob), (24, 54 + bob), (18, 49 + bob)], ink)
    polygon([(22, 25 + bob), (42, 25 + bob), (43, 48 + bob), (38, 51 + bob), (25, 51 + bob), (21, 47 + bob)], black)
    box(22, 26 + bob, 2, 20, edge)
    box(40, 26 + bob, 2, 21, steel)
    box(25, 26 + bob, 14, 3, bronze)
    box(26, 26 + bob, 12, 1, gold)
    box(25, 32 + bob, 14, 7, ink)
    for y in (33, 35, 37):
        box(26, y + bob, 11, 1, edge)
        box(38, y + bob, 1, 1, bronze)
    box(25, 42 + bob, 5, 7, steel)
    box(26, 43 + bob, 3, 3, bronze)
    box(33, 42 + bob, 6, 7, ink)
    for y in (43, 45, 47):
        box(34, y + bob, 4, 1, bronze)
    hy = bob + lift
    polygon([(19, 22 + hy), (19, 15 + hy), (24, 9 + hy), (39, 9 + hy), (45, 15 + hy), (45, 22 + hy)], ink)
    polygon([(21, 16 + hy), (25, 11 + hy), (38, 11 + hy), (43, 16 + hy), (43, 21 + hy), (21, 21 + hy)], steel)
    box(23, 16 + hy, 18, 5, black)
    box(25, 11 + hy, 12, 1, edge)
    box(26, 12 + hy, 3, 3, bronze)
    box(35, 12 + hy, 3, 3, bronze)
    box(20, 22 + hy, 24, 2, bronze)
    box(21, 22 + hy, 21, 1, gold)
    box(28 + eye, 14 + hy, 9, 7, ink)
    eye_height = 1 if state == "SLEEP" or state == "BLINK" and index in {2, 3} else 3
    box(30 + eye, 16 + hy, 5, eye_height, "#c45442")
    box(31 + eye, 16 + hy, 2, 1, "#ffd18a")
    box(39, 17 + hy, 2, 2, "#edac4b")
    if state in {"WORRIED", "OVERHEAT", "CONFUSED"}:
        box(39, 17 + hy, 2, 2, "#f26550" if index % 2 else "#ffd18a")
    for x in (10, 41):
        offset = round(phase) if state == "WALK" and x == 10 else -round(phase) if state == "WALK" else 0
        polygon([(x, 51 + offset), (x + 11, 50 + offset), (x + 13, 54 + offset), (x + 13, 57 + offset), (x, 57 + offset)], ink)
        box(x + 1, 52 + offset, 9, 2, bronze)
        box(x + 2, 55 + offset, 9, 1, steel)
    box(26, 54 + bob, 12, 3, ink)
    box(28, 54 + bob, 8, 1, bronze)
    if state in {"WORK", "OVERHEAT", "DRAG", "RECOVER"}:
        box(7 + index, 29 - index, 2, 2, gold)
        box(54 - index, 28 + index, 1, 3, edge)
    if state in {"GREETING", "SURPRISED", "NOTIFICATION"}:
        box(49, 9 + index % 3, 1, 5, gold)
        box(52, 13 + index % 3, 3, 1, bronze)
    if state == "SLEEP":
        box(47, 8, 5, 1, edge)
        box(50, 9, 1, 2, edge)
        box(47, 11, 5, 1, edge)
    p.end()
    return picture


def sphere_components(directory):
    body = image(40, 40)
    p = QPainter(body)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#263744"))
    p.drawEllipse(0, 0, 39, 39)
    p.setBrush(QColor("#b7c5cb"))
    p.drawEllipse(2, 2, 35, 35)
    p.setBrush(QColor("#e8efef"))
    p.drawEllipse(3, 2, 32, 32)
    p.setBrush(QColor("#fafcf6"))
    p.drawEllipse(5, 3, 27, 25)
    p.setBrush(QColor("#c86625"))
    p.drawEllipse(7, 7, 24, 24)
    p.setBrush(QColor("#f5a34d"))
    p.drawEllipse(8, 7, 21, 21)
    p.setBrush(QColor("#3e4f59"))
    p.drawEllipse(12, 12, 14, 14)
    p.setBrush(QColor("#d5e1e2"))
    p.drawEllipse(14, 14, 10, 10)
    p.fillRect(17, 16, 4, 6, QColor("#566a73"))
    p.fillRect(18, 17, 2, 2, QColor("#a5c6ca"))
    for x, y, w, h in ((3, 15, 4, 9), (30, 8, 4, 6), (25, 32, 5, 3)):
        p.fillRect(x, y, w, h, QColor("#d27b32"))
    for x, y in ((10, 10), (26, 11), (10, 26), (26, 26)):
        p.fillRect(x, y, 2, 2, QColor("#825b3c"))
    p.fillRect(8, 5, 10, 1, QColor("#ffffff"))
    p.fillRect(28, 27, 3, 2, QColor("#a9b9bf"))
    p.end()
    body.save(str(directory / "sprites/body.png"))
    head = image(30, 18)
    p = QPainter(head)
    p.setPen(Qt.PenStyle.NoPen)
    def poly(points, color):
        p.setBrush(QColor(color))
        p.drawPolygon(QPolygon([QPoint(x, y) for x, y in points]))
    poly([(1, 12), (3, 6), (8, 2), (21, 2), (26, 6), (29, 12), (27, 16), (3, 16)], "#263744")
    poly([(3, 11), (5, 6), (9, 4), (20, 4), (24, 7), (26, 12), (25, 14), (4, 14)], "#f3f5ec")
    p.fillRect(7, 5, 4, 2, QColor("#f2a34d"))
    p.fillRect(19, 5, 4, 2, QColor("#db8034"))
    p.fillRect(3, 13, 24, 2, QColor("#cc742d"))
    p.fillRect(5, 15, 21, 1, QColor("#aebfc3"))
    p.fillRect(11, 6, 8, 7, QColor("#263744"))
    p.fillRect(12, 7, 5, 4, QColor("#455f6c"))
    p.fillRect(13, 7, 2, 2, QColor("#b7e1dc"))
    p.fillRect(22, 9, 2, 2, QColor("#ffc46b"))
    p.fillRect(6, 9, 3, 2, QColor("#9bb0b7"))
    p.fillRect(7, 1, 1, 4, QColor("#617a85"))
    p.fillRect(6, 0, 3, 1, QColor("#e6a058"))
    p.end()
    head.save(str(directory / "sprites/head.png"))


def voice(directory, pitch, pace, harmonic):
    directory.mkdir(parents=True, exist_ok=True)
    rng = random.Random(103 if pitch < 1 else 211)
    rate = 22050
    for name, (start, end, duration) in SYLLABLES.items():
        duration *= pace
        phase = 0
        samples = bytearray()
        for i in range(round(rate * duration)):
            t = i / rate
            frequency = (start + (end - start) * t / duration) * pitch
            frequency *= 1 + 0.08 * math.sin(t * 2 * math.pi * (19 if pitch < 1 else 37))
            phase += 2 * math.pi * frequency / rate
            envelope = min(1, t / 0.012) * min(1, (duration - t) / 0.035)
            value = math.sin(phase) + harmonic * math.sin(phase * 2) + 0.025 * rng.uniform(-1, 1)
            samples.extend(struct.pack("<h", round(4500 * envelope * value)))
        with wave.open(str(directory / f"{name}.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(samples)


def theme(name, dark=False, orange=False):
    colors = dict(primary="#2162cc", secondary="#183f68", accent="#5ed4ff", background="#edf3f9",
                  panel="#ffffff", border="#b6c9db", text="#14314c", muted="#4e657a", hero="#102c48",
                  hero_text="#f5faff", hero_muted="#b5d0e7", selected="#dceaff", focus="#2162cc",
                  button_text="#ffffff", error="#b03131", disabled="#637588", notification="#102c48",
                  hologram="#73dcff", decoration="#386685")
    if dark:
        colors.update(primary="#bd824c", secondary="#513928", accent="#ff6957", background="#11151b",
                      panel="#1e252d", border="#896d52", text="#f3e8db", muted="#bdaf9f", hero="#15191f",
                      hero_text="#fff1dc", hero_muted="#d7bc98", selected="#513928", focus="#f0b16e",
                      button_text="#17120f", error="#ff9383", disabled="#aca297", notification="#231c18",
                      hologram="#ffb65e", decoration="#9e7350")
    if orange:
        colors.update(primary="#a84813", secondary="#7b4226", accent="#f6923e", background="#fbf5ec",
                      panel="#fffdf8", border="#c5af98", text="#40352c", muted="#74604b", hero="#56351f",
                      hero_text="#fff7e7", hero_muted="#edcdb1", selected="#fce2c5", focus="#a84813",
                      button_text="#ffffff", error="#b03131", disabled="#827465", notification="#56351f",
                      hologram="#ffb866", decoration="#a66d43")
    return {"name": name, "radius": 8 if dark else 20 if orange else 12, "colors": colors}


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    for identifier, name, description, personality, movement, visual_theme in (
        ("r2_default", "R2 · Original", "Seu companheiro branco e azul, com o atlas e as preferências anteriores preservados.", "custom", "astromech", theme("Estação azul")),
        ("dark_astromech", "Vesper", "Sentinela de manutenção em grafite e bronze. Observa em silêncio e responde com pulsos graves.", "calm", "astromech", theme("Oficina de bronze", dark=True)),
        ("spherical_droid", "Orbita", "Explorador de cerâmica clara e cobre laranja. Rola com energia e mantém a cabeça em equilíbrio.", "curious", "spherical", theme("Hangar solar", orange=True))):
        directory = ROOT / "droids" / identifier
        (directory / "sprites").mkdir(parents=True, exist_ok=True)
        (directory / "animations").mkdir(exist_ok=True)
        manifest = "characters/default/manifest.json" if identifier == "r2_default" else f"droids/{identifier}/animations/manifest.json"
        custom = {"appearance": {"label": "Cor dos painéis", "default": "blue", "options": {
            k: {"label": title} for k, title in (("blue", "Azul original"), ("teal", "Verde oceano"), ("violet", "Violeta"), ("amber", "Âmbar"))}}} if identifier == "r2_default" else {
                "illumination": {"label": "Iluminação", "default": "amber", "options": {
                    "amber": {"label": "Âmbar", "color": "#ffb95b"}, "red": {"label": "Vermelho", "color": "#ff6654"}}}}
        if identifier == "spherical_droid":
            custom["decoration"] = {"label": "Sinalizador", "default": "none", "options": {"none": {"label": "Desligado"}, "beacon": {"label": "Centelha"}}}
        phrases = dict(PHRASES)
        if identifier == "dark_astromech":
            phrases.update(greeting=(("low", "answer"), ("servo", "low", "rise"), ("answer", "soft")),
                           happy=(("low", "trill"), ("answer", "warble"), ("soft", "rise")))
        if identifier == "spherical_droid":
            phrases.update(greeting=(("spark", "chirp", "rise"), ("trill", "bright"), ("chirp", "spark", "answer")))
        profile = dict(profile_version=1, id=identifier, name=name, description=description, manifest=manifest,
                       renderer="layered" if movement == "spherical" else "atlas", animations=CATEGORIES,
                       audio={"voice": "voice" if identifier == "r2_default" else f"droids/{identifier}/audio/voice",
                              "sounds": "sounds", "phrases": phrases}, personality=personality, movement=movement,
                       canvas=[64, 64], speed=0.8 if identifier == "dark_astromech" else 1,
                       theme=visual_theme, customization=custom,
                       art_status="Arte provisória original preservada" if identifier == "r2_default" else "Pixel art original procedural · validação artística pendente")
        save_json(directory / "profile.json", profile)
        if identifier == "r2_default":
            continue
        voice(directory / "audio/voice", 0.63 if movement == "astromech" else 1.24,
              1.22 if movement == "astromech" else 0.86, 0.32 if movement == "astromech" else 0.10)
        clips = {}
        if movement == "astromech":
            sheet = image(64 * 6, 64 * len(State))
            p = QPainter(sheet)
            for row, state in enumerate(State):
                count = 1 if state in {State.IDLE, State.SLEEP} else 6
                frames = []
                for i in range(count):
                    p.drawImage(i * 64, row * 64, dark_frame(state.value, i))
                    frames.append({"image": "../sprites/vesper.png", "rect": [i * 64, row * 64, 64, 64], "duration_ms": 140 if state != State.BLINK else 90})
                clips[state.value] = {"loop": state in {State.IDLE, State.SLEEP, State.WALK}, "frames": frames}
            p.end()
            sheet.save(str(directory / "sprites/vesper.png"))
            save_json(directory / "animations/manifest.json", {"manifest_version": 1, "canvas": [64, 64], "anchor": [32, 57], "clips": clips})
        else:
            sphere_components(directory)
            for state in State:
                count = 1 if state in {State.IDLE, State.SLEEP} else 8
                frames = []
                for i in range(count):
                    phase = math.sin(i / max(1, count - 1) * math.pi * 2)
                    tilt = phase * (14 if state in {State.CONFUSED, State.RECOVER, State.DRAG} else 9)
                    head_x = phase * 2 if state in {State.LOOK_AROUND, State.CURIOUS, State.WORK} else -3 if state == State.LOOK_LEFT else 3 if state == State.LOOK_RIGHT else 0
                    head_y = 2 if state == State.SLEEP else -abs(phase) * 2 if state in {State.SURPRISED, State.WAKE, State.GREETING} else 0
                    lift = -abs(phase) * 2 if state in {State.HAPPY, State.NOTIFICATION, State.INTERACT} else 0
                    if state == State.RECOVER:
                        tilt *= 1 - i / 7
                    frames.append({"duration_ms": 120 if state != State.BLINK else 75, "head_tilt": round(tilt, 2),
                                   "head_x": round(head_x, 2), "head_y": round(head_y, 2), "lift": round(lift, 2),
                                   "body_angle": round(phase * 8, 2) if state in {State.DRAG, State.RECOVER, State.CONFUSED} else 0})
                clips[state.value] = {"loop": state in {State.IDLE, State.SLEEP, State.WALK}, "frames": frames}
            save_json(directory / "animations/manifest.json", {"manifest_version": 2, "canvas": [64, 64], "body": "../sprites/body.png", "head": "../sprites/head.png", "clips": clips})


if __name__ == "__main__":
    main()
