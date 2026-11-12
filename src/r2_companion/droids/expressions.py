"""Small, deterministic animation cues in the artwork's 96-unit canvas."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainterPath, QPen

from ..pet.state import State

STYLES = {"lumo": "#a8df9a", "vigia": "#f0b66a", "pico": "#9ae0f0", "tranco": "#ffb47b"}


def paint_expression(p, state, phase, style="", rect=None):
    p.save()
    if rect is not None:
        p.translate(rect.x(), rect.y())
        p.scale(rect.width() / 96, rect.height() / 96)
    phase %= 1
    pulse = math.sin(phase * math.tau)
    tint = QColor(STYLES.get(style, "#a5dcf4"))
    p.setRenderHint(p.RenderHint.Antialiasing, True)
    p.setPen(QPen(tint, 1.3))
    p.setBrush(Qt.BrushStyle.NoBrush)
    x, y = 81, 15 + pulse*1.2

    def line(a, b, c, d):
        p.drawLine(QPointF(a, b), QPointF(c, d))

    def dot(a, b, radius=1):
        p.drawEllipse(QRectF(a-radius, b-radius, radius*2, radius*2))

    if state == State.SLEEP:
        for index in range(3):
            t = (phase + index / 3) % 1
            p.setOpacity(0.35 + 0.65 * math.sin(math.pi*t))
            xx, yy, size = 77 + t*7, 33 - t*27, 3 + t*3
            line(xx, yy, xx+size, yy)
            line(xx+size, yy, xx, yy+size)
            line(xx, yy+size, xx+size, yy+size)
    elif state == State.OVERHEAT:
        for index in range(5):
            t = (phase + index/5) % 1
            p.setOpacity((1-t)*0.75)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#c6d1d7"))
            radius = 1.6 + t*3
            xx, yy = 78 + math.sin(t*5+index)*4, 39-t*30
            p.drawEllipse(QRectF(xx-radius, yy-radius, radius*2, radius*2))
        p.setOpacity(1)
        p.setPen(QPen(QColor("#ff9a65"), 1.4))
        for xx in (72, 85):
            line(xx, 45, xx+2, 41)
            line(xx+2, 41, xx, 37)
    elif state in {State.SURPRISED, State.WORRIED}:
        p.setOpacity(0.65 + abs(pulse)*0.35)
        if state == State.WORRIED:
            path = QPainterPath(QPointF(x, y-7))
            path.lineTo(x+7, y+6); path.lineTo(x-7, y+6); path.closeSubpath()
            p.drawPath(path)
        line(x, y-4, x, y+1); dot(x, y+4, 0.6)
        if state == State.SURPRISED:
            for a in (-1, 1):
                line(x+a*5, y-3, x+a*8, y-6)
    elif state in {State.CURIOUS, State.CONFUSED}:
        for j in range(2 if state == State.CONFUSED else 1):
            xx = x-j*10
            path = QPainterPath(QPointF(xx-2, y-4))
            path.cubicTo(xx+4, y-9, xx+6, y, xx, y+1)
            path.lineTo(xx, y+3)
            p.drawPath(path); dot(xx, y+6, 0.6)
    elif state in {State.HAPPY, State.INTERACT}:
        p.translate(x, y+pulse*2)
        if state == State.INTERACT:
            path = QPainterPath(QPointF(0, 5))
            path.cubicTo(-12, -2, -4, -9, 0, -3)
            path.cubicTo(4, -9, 12, -2, 0, 5)
            p.drawPath(path)
        else:
            for a in range(4):
                theta = a*math.pi/2
                line(math.cos(theta)*2, math.sin(theta)*2, math.cos(theta)*6, math.sin(theta)*6)
            dot(0, 0, 1)
    elif state == State.NOTIFICATION:
        path = QPainterPath(QPointF(x-5, y+3))
        path.cubicTo(x-2, y+1, x-6, y-6, x, y-6)
        path.cubicTo(x+6, y-6, x+2, y+1, x+5, y+3)
        path.closeSubpath(); p.drawPath(path); dot(x, y+6, 0.8)
        line(x-8, y-3, x-9-abs(pulse)*2, y-5)
        line(x+8, y-3, x+9+abs(pulse)*2, y-5)
    elif state in {State.LOOK_AROUND, State.WORK}:
        dot(x, y, 6)
        angle = phase*math.tau
        line(x, y, x+math.cos(angle)*5, y+math.sin(angle)*5)
        if state == State.WORK:
            line(x+5, y+5, x+9, y+9)
            line(x-2, y, x+2, y); line(x, y-2, x, y+2)
    elif state in {State.LOOK_LEFT, State.LOOK_RIGHT}:
        sign = -1 if state == State.LOOK_LEFT else 1
        xx = x + pulse
        line(xx-sign*5, y, xx+sign*5, y)
        line(xx+sign*5, y, xx+sign, y-4)
        line(xx+sign*5, y, xx+sign, y+4)
    elif state == State.GREETING:
        for j in range(3):
            radius = 3+j*3
            p.setOpacity(0.4+0.6*((phase+j/3)%1))
            p.drawArc(QRectF(x-radius, y-radius, radius*2, radius*2), -60*16, 120*16)
    elif state == State.WAKE:
        radius = 3+phase*4
        dot(x, y, radius/2)
        for j in range(6):
            a = j*math.tau/6
            line(x+math.cos(a)*radius, y+math.sin(a)*radius,
                 x+math.cos(a)*(radius+2), y+math.sin(a)*(radius+2))
    elif state == State.DRAG:
        for j in range(3):
            xx = 13+j*4
            line(xx, 40+j*5, xx-4-pulse, 44+j*5)
    elif state == State.RECOVER:
        p.setOpacity(1-phase*0.7)
        line(75, 20, 79, 24); line(79, 24, 87, 13)
        p.drawArc(QRectF(72, 10, 20, 20), 30*16, 280*16)
    elif state == State.WALK:
        for j in range(3):
            line(8+j*3, 75+j*4, 12+j*3+phase*3, 75+j*4)
    elif state == State.BLINK:
        p.setOpacity(0.35+abs(pulse)*0.6)
        line(77, 16, 84, 16)
    elif state == State.IDLE:
        p.setOpacity(0.2+abs(pulse)*0.5)
        dot(x, y, 1)
        if style == "vigia":
            p.drawArc(QRectF(x-4, y-4, 8, 8), 0, 180*16)
    p.restore()
