from pathlib import Path
import math
import random
import struct
import wave

ROOT = Path(__file__).resolve().parents[1] / "src/r2_companion/assets/sounds"
SOUNDS = {
    "idle/curious_1": (520, 830, 640), "idle/curious_2": (640, 920),
    "idle/happy": (660, 880, 1100),
    "movement/servo_1": (140, 180), "movement/servo_2": (200, 130),
    "movement/head": (240, 320),
    "reactions/click_1": (740, 980), "reactions/click_2": (880, 620, 920),
    "reactions/celebrate": (660, 830, 990, 1320),
    "reactions/surprise": (420, 1200), "reactions/confused": (700, 580, 390),
    "sleep/enter": (520, 390, 260), "sleep/wake": (260, 520, 780),
    "notifications/timer": (660, 880, 1100, 880),
    "notifications/event": (520, 780, 1040)}


def main():
    rng = random.Random(32)
    rate = 22050
    for name, notes in SOUNDS.items():
        path = ROOT / (name + ".wav")
        path.parent.mkdir(parents=True, exist_ok=True)
        frames = bytearray()
        phase = 0.0
        length = 0.12 if not name.startswith("sleep") else 0.18
        for frequency in notes:
            for index in range(round(rate * length)):
                t = index / rate
                phase += 2 * math.pi * frequency * (1 + 0.018 * math.sin(t * 65)) / rate
                envelope = min(1, t / 0.012) * max(0, 1 - t / length) ** 1.4
                value = math.sin(phase) + 0.15 * math.sin(phase * 2)
                if name.startswith("movement"):
                    value = 0.4 * value + 0.12 * rng.uniform(-1, 1)
                frames.extend(struct.pack("<h", round(6500 * envelope * value)))
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(frames)


if __name__ == "__main__":
    main()
