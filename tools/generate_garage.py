"""Reproduce the four 1.2 pixel rigs without touching the legacy artwork.

All coordinates are authored on the same 96px canvas. Transparent PNG pieces
retain that canvas so joint coordinates can be reviewed alongside the artwork.
"""
from copy import deepcopy
import json
import math
from pathlib import Path
import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter, QPen, QPolygon

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion.pet.state import State
from generate_droids import CATEGORIES, ROOT, save_json, theme, voice

INK = "#202e37"
SHADOW = "#536770"
METAL = "#a6b7b9"
WHITE = "#e4e7d7"
LIGHT = "#fff6db"
GREEN = "#628b59"
SAGE = "#a1bc78"
RED = "#b74f42"
ORANGE = "#c57a36"


class Pixels:
    def __init__(self):
        self.image = QImage(96, 96, QImage.Format.Format_ARGB32)
        self.image.fill(Qt.GlobalColor.transparent)
        self.p = QPainter(self.image)
        self.p.setPen(Qt.PenStyle.NoPen)

    def box(self, x, y, w, h, color):
        self.p.fillRect(x, y, w, h, QColor(color))

    def poly(self, points, color):
        self.p.setPen(Qt.PenStyle.NoPen)
        self.p.setBrush(QColor(color))
        self.p.drawPolygon(QPolygon([QPoint(x, y) for x, y in points]))

    def oval(self, x, y, w, h, color):
        self.p.setPen(Qt.PenStyle.NoPen)
        self.p.setBrush(QColor(color))
        self.p.drawEllipse(x, y, w, h)

    def line(self, x, y, xx, yy, color, width=1):
        self.p.setPen(QPen(QColor(color), width))
        self.p.drawLine(x, y, xx, yy)
        self.p.setPen(Qt.PenStyle.NoPen)

    def panel(self, x, y, w, h, base, highlight=LIGHT):
        self.box(x, y, w, h, INK)
        self.box(x + 1, y + 1, w - 2, h - 2, base)
        self.box(x + 2, y + 1, w - 4, 1, highlight)
        self.box(x + w - 2, y + 2, 1, h - 3, SHADOW)

    def lens(self, x, y, radius, tint="#7dcdd6"):
        d = radius * 2
        self.oval(x - radius, y - radius, d, d, INK)
        self.oval(x - radius + 1, y - radius + 1, d - 2, d - 2, METAL)
        self.oval(x - radius + 2, y - radius + 2, d - 4, d - 4, "#101e29")
        self.oval(x - radius + 3, y - radius + 3, d - 6, d - 6, "#355466")
        self.box(x - 2, y - radius + 3, 3, 2, tint)
        self.box(x + radius - 3, y + 1, 1, 2, "#527a8c")

    def rivets(self, points):
        for x, y in points:
            self.box(x, y, 1, 1, LIGHT)
            self.box(x, y + 1, 1, 1, SHADOW)


class Rig:
    def __init__(self, identifier):
        self.identifier = identifier
        self.directory = ROOT / "droids" / identifier
        (self.directory / "sprites").mkdir(parents=True, exist_ok=True)
        (self.directory / "animations").mkdir(exist_ok=True)
        self.parts = []
        self.joints = {}

    def part(self, name, joint, draw, parent=None, z=0, motion=None, lamp=None):
        art = Pixels()
        draw(art)
        art.p.end()
        if not art.image.save(str(self.directory / "sprites" / f"{name}.png")):
            raise RuntimeError("PNG não foi salvo")
        position = joint if parent is None else [joint[i] - self.joints[parent][i] for i in (0, 1)]
        spec = dict(name=name, parent=parent, image=f"../sprites/{name}.png",
                    position=list(position), pivot=list(joint), z=z, motion=motion or {})
        if lamp:
            spec["lamp"] = lamp
        self.parts.append(spec)
        self.joints[name] = joint


def lumo(r):
    def chassis(a):
        a.poly([(41, 43), (52, 43), (56, 52), (51, 70), (44, 73), (39, 65)], INK)
        a.poly([(43, 45), (50, 45), (53, 53), (49, 67), (44, 69), (42, 63)], WHITE)
        a.box(45, 47, 6, 12, GREEN)
        a.box(46, 48, 2, 9, SAGE)
        a.line(51, 57, 48, 67, SHADOW, 2)
        a.oval(43, 66, 7, 7, METAL)
        a.oval(45, 68, 3, 3, INK)
        a.box(42, 51, 2, 5, LIGHT)
    r.part("body", (45, 71), chassis, z=2, motion={"angle": ["lean", 1]})
    def tire(a):
        a.oval(26, 54, 35, 35, INK)
        a.oval(28, 56, 31, 31, "#3d4b4d")
        a.oval(31, 59, 25, 25, WHITE)
        a.oval(33, 61, 21, 21, METAL)
        a.oval(35, 63, 17, 17, GREEN)
        a.oval(38, 66, 11, 11, "#456853")
        a.oval(40, 68, 7, 7, WHITE)
        a.oval(42, 70, 3, 3, INK)
        for i in range(12):
            t = i * math.pi / 6
            a.line(round(43 + math.cos(t) * 16), round(71 + math.sin(t) * 16),
                   round(43 + math.cos(t) * 17), round(71 + math.sin(t) * 17), "#728084")
        for i in range(3):
            t = i * math.pi * 2 / 3
            a.line(round(43 + math.cos(t) * 7), round(71 + math.sin(t) * 7),
                   round(43 + math.cos(t) * 10), round(71 + math.sin(t) * 10), SAGE, 2)
    r.part("wheel", (43, 71), tire, z=1, motion={"angle": ["wheel", 1]})
    def neck(a):
        a.poly([(44, 48), (48, 48), (52, 32), (48, 30), (43, 40)], INK)
        a.line(46, 44, 50, 33, METAL, 2)
        a.oval(44, 41, 7, 7, GREEN)
        a.oval(46, 43, 3, 3, SAGE)
    r.part("neck", (46, 46), neck, "body", 3)
    def head(a):
        a.poly([(27, 19), (64, 27), (61, 42), (26, 36), (23, 28)], INK)
        a.poly([(29, 21), (61, 28), (58, 39), (28, 34), (26, 28)], WHITE)
        a.poly([(49, 25), (60, 28), (58, 39), (47, 37)], GREEN)
        a.line(51, 26, 48, 36, SAGE, 2)
        a.poly([(30, 22), (47, 26), (46, 29), (28, 26)], LIGHT)
        a.oval(23, 20, 12, 17, GREEN)
        a.oval(24, 21, 9, 14, WHITE)
        a.oval(25, 23, 7, 10, INK)
        a.box(27, 25, 2, 3, "#85ced4")
        a.box(29, 30, 1, 2, SHADOW)
        for x in (37, 40, 43):
            a.line(x, 30, x - 1, 34, SHADOW)
        a.rivets([(56, 30), (54, 36), (34, 27)])
        a.box(37, 22, 5, 1, METAL)
        a.line(59, 25, 64, 18, SHADOW)
        a.box(63, 17, 2, 3, GREEN)
    r.part("head", (49, 33), head, "neck", 4, {"angle": ["head", 1]}, [-22, -8, 2, 2])


def vigia(r):
    def body(a):
        a.poly([(23, 28), (29, 20), (42, 16), (60, 18), (70, 24), (75, 36),
                (70, 45), (58, 49), (34, 47), (22, 40)], INK)
        a.poly([(25, 29), (31, 22), (43, 18), (59, 20), (68, 26), (71, 37),
                (66, 43), (56, 46), (35, 44), (25, 38)], "#414c56")
        a.poly([(29, 26), (40, 20), (57, 21), (64, 25), (60, 28), (35, 28)], "#687680")
        a.line(34, 29, 30, 38, "#8a9695")
        a.line(62, 29, 67, 37, "#252f3b", 2)
        a.panel(32, 39, 27, 6, "#313f49", "#78858c")
        for x in range(35, 58, 4):
            a.box(x, 40, 2, 3, "#111d29")
        a.line(36, 20, 34, 9, METAL)
        a.box(33, 8, 3, 3, "#929c9c")
        a.line(58, 19, 61, 11, SHADOW)
        a.box(60, 10, 3, 2, "#a77e5c")
        a.oval(20, 30, 10, 12, "#34434d")
        a.rivets([(29, 31), (67, 30), (35, 24), (59, 24)])
    r.part("body", (48, 35), body, z=4,
           motion={"angle": ["bank", 1], "y": ["lift", 1]})
    def sensors(a):
        a.panel(35, 28, 27, 11, "#2c3743", "#71818c")
        a.lens(54, 33, 8, "#efb969")
        a.lens(37, 32, 5, "#e57961")
        a.lens(68, 35, 4, "#83b8c0")
        a.box(44, 30, 3, 2, "#ad6554")
        a.box(44, 35, 2, 2, "#92a9a8")
    r.part("head", (48, 33), sensors, "body", 6, {"angle": ["head", 1]}, [4, -4, 2, 2])
    # Every suspended manipulator has its own shoulder and elbow.
    for name, start, elbow, tip, z in (
        ("rear_left", (34, 41), (20, 57), (17, 70), 1),
        ("rear_right", (62, 41), (76, 56), (78, 71), 1),
        ("left", (31, 43), (26, 62), (33, 78), 5),
        ("right", (64, 43), (69, 63), (62, 82), 5),
        ("center", (48, 44), (45, 66), (47, 86), 3)):
        def upper(a, s=start, e=elbow):
            a.line(*s, *e, INK, 6)
            a.line(s[0] - 1, s[1], e[0] - 1, e[1], "#63727a", 2)
            a.oval(s[0] - 3, s[1] - 3, 6, 6, "#9eaaa9")
            a.oval(e[0] - 3, e[1] - 3, 6, 6, "#303e49")
            a.box(e[0] - 1, e[1] - 1, 2, 2, "#a58a64")
        r.part(name + "_arm", start, upper, "body", z)
        def lower(a, e=elbow, t=tip):
            a.line(*e, *t, INK, 4)
            a.line(e[0], e[1] + 2, t[0], t[1] - 1, "#82918f")
            a.line(t[0], t[1], t[0] - 4, t[1] + 4, INK, 2)
            a.line(t[0], t[1], t[0] + 3, t[1] + 4, SHADOW, 2)
            a.box(t[0] - 2, t[1] - 3, 4, 4, "#607078")
        r.part(name + "_claw", elbow, lower, name + "_arm", z + 0.1)


def pico(r):
    def body(a):
        a.poly([(35, 43), (58, 43), (63, 50), (57, 58), (36, 56), (32, 49)], INK)
        a.poly([(36, 44), (57, 44), (60, 49), (55, 55), (37, 53), (35, 49)], WHITE)
        a.panel(40, 46, 14, 7, "#7e8d90", LIGHT)
        a.box(43, 48, 8, 2, "#314653")
        a.box(55, 44, 4, 6, RED)
        a.box(34, 47, 4, 4, RED)
    r.part("body", (47, 51), body, z=4,
           motion={"angle": ["lean", 1], "y": ["lift", 1]})
    for name, hip, knee, foot, z in (("left", (37, 51), (30, 66), (35, 82), 2),
                                    ("right", (57, 51), (64, 66), (59, 82), 5)):
        def thigh(a, h=hip, k=knee):
            a.line(*h, *k, INK, 8)
            a.line(h[0], h[1] + 1, k[0], k[1] - 1, WHITE, 4)
            a.line(h[0] + 2, h[1] + 3, k[0] + 1, k[1] - 2, RED, 2)
            a.oval(h[0] - 4, h[1] - 3, 8, 7, METAL)
            a.oval(h[0] - 2, h[1] - 1, 4, 3, INK)
        r.part(name + "_thigh", hip, thigh, "body", z, {"angle": [name + "_step", 1]})
        def shin(a, k=knee, f=foot):
            a.line(*k, *f, INK, 6)
            a.line(k[0], k[1], f[0], f[1], METAL, 2)
            a.line(k[0] + 2, k[1] + 4, f[0] + 2, f[1] - 2, SHADOW)
            a.oval(k[0] - 4, k[1] - 4, 8, 8, INK)
            a.oval(k[0] - 2, k[1] - 2, 4, 4, RED)
            a.box(k[0] - 1, k[1] - 1, 2, 1, LIGHT)
        r.part(name + "_shin", knee, shin, name + "_thigh", z + 0.1,
               {"angle": [name + "_knee", 1 if name == "left" else -1]})
        def shoe(a, f=foot):
            a.poly([(f[0] - 4, f[1] - 3), (f[0] + 3, f[1] - 3), (f[0] + 8, f[1] + 2),
                    (f[0] + 7, f[1] + 5), (f[0] - 7, f[1] + 5), (f[0] - 7, f[1])], INK)
            a.box(f[0] - 5, f[1], 10, 3, WHITE)
            a.box(f[0] - 5, f[1] + 3, 12, 1, SHADOW)
            a.box(f[0] - 4, f[1] + 1, 3, 2, RED)
        r.part(name + "_foot", foot, shoe, name + "_shin", z + 0.2, {"angle": [name + "_foot", 1]})
    def neck(a):
        a.line(47, 45, 49, 33, INK, 7)
        a.line(46, 43, 48, 35, METAL, 2)
        a.oval(44, 35, 9, 7, SHADOW)
        a.oval(46, 36, 4, 4, WHITE)
    r.part("neck", (47, 44), neck, "body", 6)
    def head(a):
        a.poly([(20, 20), (29, 16), (68, 17), (76, 23), (73, 37), (64, 41),
                (26, 39), (19, 33)], INK)
        a.poly([(22, 21), (30, 18), (67, 19), (73, 24), (70, 35), (63, 38),
                (27, 36), (22, 32)], WHITE)
        a.box(24, 20, 12, 3, RED)
        a.box(64, 21, 7, 4, RED)
        a.box(40, 21, 12, 14, "#889b9e")
        a.box(43, 23, 6, 10, INK)
        a.lens(32, 29, 10)
        a.lens(61, 29, 9, "#bddf90")
        a.box(44, 25, 4, 2, "#84deb6")
        a.box(44, 30, 4, 1, SHADOW)
        a.line(27, 19, 25, 11, SHADOW)
        a.box(24, 10, 3, 2, RED)
        a.line(69, 19, 73, 13, METAL)
        a.rivets([(23, 25), (27, 35), (68, 35), (57, 20)])
    r.part("head", (48, 33), head, "neck", 7, {"angle": ["head", 1]}, [-5, -8, 3, 2])


def tranco(r):
    def body(a):
        a.poly([(28, 37), (66, 37), (69, 70), (63, 78), (31, 78), (25, 70)], INK)
        a.poly([(30, 39), (64, 39), (66, 69), (61, 75), (33, 75), (28, 69)], "#b8c1b4")
        a.box(31, 41, 11, 29, WHITE)
        a.box(32, 42, 8, 10, ORANGE)
        a.box(32, 57, 8, 12, "#839390")
        a.panel(44, 41, 16, 12, "#657b7e", METAL)
        a.box(47, 44, 10, 6, INK)
        for y in (44, 46, 48):
            a.box(48, y, 8, 1, "#93adab")
        a.panel(44, 56, 17, 16, "#888e79", LIGHT)
        a.box(47, 59, 11, 8, "#364b52")
        a.box(49, 60, 3, 5, ORANGE)
        a.box(54, 60, 2, 5, "#91a790")
        a.line(31, 73, 61, 73, SHADOW)
        a.rivets([(31, 40), (61, 40), (32, 70), (61, 70)])
        a.box(35, 55, 4, 1, SHADOW)
        a.box(56, 68, 3, 1, WHITE)
    r.part("body", (47, 73), body, z=4,
           motion={"angle": ["lean", 1], "y": ["lift", 1]})
    for name, x, z in (("left", 19, 3), ("right", 67, 5)):
        def strut(a, x=x):
            a.panel(x, 44, 10, 34, "#9daca5", WHITE)
            a.box(x + 2, 48, 5, 10, ORANGE)
            a.box(x + 3, 61, 3, 12, SHADOW)
            a.line(x + 1, 75, x - 2, 81, METAL, 3)
            a.panel(x - 5, 79, 19, 7, "#637c7c", WHITE)
        r.part(name + "_strut", (x + 5, 47), strut, "body", z)
        def wheel(a, x=x):
            a.oval(x + 1, 80, 8, 8, INK)
            a.oval(x + 2, 81, 6, 6, METAL)
            a.line(x + 5, 81, x + 5, 87, "#5a7272")
            a.line(x + 2, 84, x + 8, 84, "#5a7272")
        r.part(name + "_wheel", (x + 5, 84), wheel, name + "_strut", z + 0.1,
               {"angle": ["wheel", 1]})
    def head(a):
        a.poly([(27, 25), (32, 17), (44, 14), (62, 17), (69, 25), (68, 36), (27, 36)], INK)
        a.poly([(29, 25), (34, 19), (44, 16), (60, 19), (66, 25), (65, 33), (29, 33)], ORANGE)
        a.poly([(32, 23), (43, 18), (55, 19), (60, 23)], "#edac5c")
        a.box(29, 29, 37, 5, "#7a5740")
        a.box(34, 23, 8, 5, "#b5baa7")
        a.lens(51, 27, 6, "#82dbe8")
        a.box(61, 28, 3, 3, "#dce7b5")
        a.box(29, 35, 37, 3, METAL)
        a.box(31, 37, 33, 2, SHADOW)
        a.line(36, 18, 33, 7, METAL, 2)
        a.box(31, 6, 4, 3, ORANGE)
        a.line(59, 18, 62, 10, SHADOW)
        a.box(61, 8, 2, 3, LIGHT)
        a.box(38, 30, 3, 2, "#e6b16d")
        a.rivets([(31, 27), (63, 25)])
    r.part("head", (48, 35), head, "body", 7, {"angle": ["head", 1]}, [13, -7, 2, 2])
    for name, x, direction, z in (("left", 28, -1, 8), ("right", 66, 1, 8)):
        def arm(a, x=x, d=direction):
            a.oval(x - 3, 41, 7, 7, INK)
            a.line(x, 44, x + d * 5, 55, INK, 4)
            a.line(x, 44, x + d * 5, 55, METAL, 2)
            a.oval(x + d * 5 - 2, 53, 5, 5, SHADOW)
        r.part(name + "_arm", (x, 44), arm, "body", z)
        def claw(a, x=x, d=direction):
            xx = x + d * 5
            a.line(xx, 55, xx, 65, INK, 4)
            a.line(xx, 56, xx, 64, WHITE)
            a.line(xx, 64, xx - 3, 68, SHADOW, 2)
            a.line(xx, 64, xx + 3, 68, METAL, 2)
        r.part(name + "_claw", (x + direction * 5, 55), claw, name + "_arm", z + 0.1)


def poses(identifier, state, i):
    t = i / 12
    wave = math.sin(t * math.tau)
    slow = math.sin(t * math.tau + 0.7)
    envelope = math.sin(i / 11 * math.pi)
    energetic = state in {State.HAPPY, State.NOTIFICATION, State.INTERACT, State.GREETING}
    looking = state in {State.LOOK_AROUND, State.CURIOUS, State.WORK}
    startled = state in {State.SURPRISED, State.WAKE}
    stressed = state in {State.CONFUSED, State.DRAG, State.RECOVER, State.WORRIED, State.OVERHEAT}
    tilt = wave * (15 if looking or energetic else 5)
    x = wave * 2 if looking else 0
    if state in {State.LOOK_LEFT, State.LOOK_RIGHT}:
        x = (-3 if state == State.LOOK_LEFT else 3) * envelope
        tilt = x * 3
    if stressed:
        tilt = wave * 11 * (1 - i / 12 if state == State.RECOVER else 1)
    pose = {"head": {"angle": round(tilt, 2), "x": round(x, 2)}}
    if identifier == "lumo":
        pose["body"] = {"angle": round(wave * (6 if energetic else 1.5), 2)}
        pose["neck"] = {"angle": round(slow * (6 if looking else 2), 2)}
        if startled:
            pose["neck"]["angle"] = round(-13 * envelope, 2)
        if state == State.SLEEP:
            pose["neck"]["angle"] = 19
            pose["head"]["angle"] = 8
    elif identifier == "vigia":
        pose["body"] = {"y": round(wave * (0.8 if state == State.SLEEP else 2.4), 2),
                        "angle": round(slow * 1.4, 2)}
        pose["head"]["angle"] *= 0.45
        for j, name in enumerate(("rear_left", "rear_right", "left", "right", "center")):
            phase = math.sin(t * math.tau + j * 1.2)
            pose[name + "_arm"] = {"angle": round(phase * (10 if looking else 5), 2)}
            pose[name + "_claw"] = {"angle": round(math.sin(t * math.tau + j + 2) * 9, 2)}
        if state == State.SLEEP:
            pose["head"]["opacity"] = 0.6
    elif identifier == "pico":
        pose["head"]["angle"] *= 1.3
        pose["neck"] = {"angle": round(-slow * (8 if looking else 2), 2)}
        pose["body"] = {"y": round(-abs(wave) * (2 if energetic else 0.6), 2)}
        if looking:
            pose["body"]["angle"] = round(wave * 3, 2)
        if startled:
            pose["head"]["y"] = round(-3 * envelope, 2)
        if state == State.SLEEP:
            pose["neck"]["angle"] = 13
            pose["head"]["angle"] = 16
            pose["body"]["y"] = 3
    else:
        # Deliberately quick, angular gestures with separate telescopic claws.
        snap = (0, -1, -1, 0.6, 0.6, 0, 0, 1, 1, -0.5, -0.5, 0)[i]
        pose["head"]["angle"] = snap * (10 if energetic or stressed else 3)
        pose["body"] = {"angle": snap * (2 if energetic else 0.4)}
        for name, sign in (("left", 1), ("right", -1)):
            pose[name + "_arm"] = {"angle": round(sign * (abs(wave) * 65 if energetic else slow * 4), 2)}
            pose[name + "_claw"] = {"y": round(-7 + (7 * abs(wave) if energetic else 1), 2),
                                    "angle": round(sign * wave * (25 if energetic else 3), 2)}
        if state == State.SLEEP:
            pose["head"]["y"] = 2
    if state == State.BLINK:
        pose["head"]["scale_y"] = 0.92 if i in {4, 5} else 1
        pose["head"]["opacity"] = 0.55 if i in {4, 5} else 1
    return pose


def main():
    app = QGuiApplication.instance() or QGuiApplication([])
    baseline = json.loads((ROOT / "droids/spherical_droid/profile.json").read_text(encoding="utf-8"))
    specs = (
        ("lumo", "Lumo", "Pequeno explorador de cerâmica e verde musgo. Equilibra-se em uma única roda e inclina o cone para escutar.", "monocycle", "curious", lumo, 1.4, 0.88),
        ("vigia", "Vigia", "Sentinela suspensa em grafite, com sensores atentos e cinco manipuladores independentes. Patrulha flutuando.", "hover", "calm", vigia, 0.52, 1.15),
        ("pico", "Pico", "Bípede de campo branco e vermelho. Seus olhos binoculares, pescoço e pernas articuladas revelam curiosidade.", "biped", "curious", pico, 1.65, 0.78),
        ("tranco", "Tranco", "Mecânico robusto em laranja gasto. Antenas, braços retráteis e gestos decididos dão ritmo à oficina.", "traction", "talkative", tranco, 0.79, 0.96))
    for identifier, name, description, movement, personality, draw, pitch, pace in specs:
        rig = Rig(identifier)
        draw(rig)
        clips = {}
        for state in State:
            duration = 210 if state in {State.IDLE, State.SLEEP} else 100 if state == State.WALK else 85 if state == State.BLINK else 120
            clips[state.value] = {"loop": state in {State.IDLE, State.SLEEP, State.WALK},
                                  "frames": [{"duration_ms": duration, "pose": poses(identifier, state, i)} for i in range(12)]}
        emitter = {"lumo": [-22, -7], "vigia": [6, 0], "pico": [-16, -4], "tranco": [3, -8]}[identifier]
        save_json(rig.directory / "animations/manifest.json", dict(manifest_version=3, canvas=[96, 96],
                  parts=rig.parts, emitter={"part": "head", "point": emitter}, clips=clips))
        profile = deepcopy(baseline)
        profile.update(id=identifier, name=name, description=description, renderer="rigged", canvas=[96, 96],
                       manifest=f"droids/{identifier}/animations/manifest.json", movement=movement,
                       personality=personality, speed={"lumo": 0.92, "vigia": 0.68, "pico": 0.86, "tranco": 0.8}[identifier],
                       art_status="Pixel art original · peças articuladas em 96 × 96")
        profile["audio"]["voice"] = f"droids/{identifier}/audio/voice"
        profile["animations"] = CATEGORIES
        visual_theme = theme({"lumo": "Jardim mecânico", "vigia": "Observatório", "pico": "Expedição", "tranco": "Oficina solar"}[identifier],
                             dark=identifier == "vigia", orange=identifier == "tranco")
        if identifier == "lumo":
            visual_theme["colors"].update(primary="#416338", focus="#416338", selected="#e2edda", hologram="#a4e6ac")
        if identifier == "pico":
            visual_theme["colors"].update(primary="#a23e39", focus="#a23e39", selected="#f6e1de", hologram="#ffb5a6")
        profile["theme"] = visual_theme
        profile["customization"] = {"illumination": {"label": "Luz do sensor", "default": "mint", "options": {
            "mint": {"label": "Menta", "color": "#9de6cf"}, "amber": {"label": "Âmbar", "color": "#ffbf70"},
            "blue": {"label": "Azul", "color": "#8cdbff"}}}}
        save_json(rig.directory / "profile.json", profile)
        voice(rig.directory / "audio/voice", pitch, pace, 0.23 if identifier in {"vigia", "tranco"} else 0.12)


if __name__ == "__main__":
    main()
