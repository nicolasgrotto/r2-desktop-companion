import math
from pathlib import Path
import random
import struct
import wave

ROOT = Path(__file__).resolve().parents[1] / "src/r2_companion/assets/voice"
SYLLABLES = {
    "rise": (380, 1150, 0.17), "question": (650, 1350, 0.15),
    "bright": (1100, 1600, 0.10), "spark": (1550, 1800, 0.07),
    "fall": (980, 350, 0.17), "low": (420, 210, 0.20),
    "trill": (780, 1100, 0.20), "warble": (600, 500, 0.18),
    "chirp": (950, 1250, 0.12), "soft": (490, 300, 0.22),
    "answer": (850, 680, 0.13), "servo": (160, 230, 0.10)}


def main():
    ROOT.mkdir(parents=True, exist_ok=True)
    rng = random.Random(71)
    rate = 22050
    for name, (start, end, duration) in SYLLABLES.items():
        phase = 0
        samples = bytearray()
        for index in range(round(rate * duration)):
            t = index / rate
            u = t / duration
            frequency = start + (end - start) * u
            frequency *= 1 + (0.15 if name in {"trill", "warble"} else 0.025) * math.sin(t * 2 * math.pi * 28)
            phase += 2 * math.pi * frequency / rate
            envelope = min(1, t / 0.008) * min(1, (duration - t) / 0.03)
            gate = 0.55 + 0.45 * math.sin(t * 2 * math.pi * 32) if name == "trill" else 1
            value = math.sin(phase) + 0.18 * math.sin(phase * 2.01) + 0.06 * rng.uniform(-1, 1)
            amplitude = 2600 if name in {"soft", "servo"} else 5500
            samples.extend(struct.pack("<h", round(amplitude * envelope * gate * value)))
        with wave.open(str(ROOT / f"{name}.wav"), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(rate)
            output.writeframes(samples)


if __name__ == "__main__":
    main()
