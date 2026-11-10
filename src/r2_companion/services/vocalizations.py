from pathlib import Path
import wave

PHRASES = {
    "curious": (("rise", "trill"), ("question", "chirp", "trill"), ("servo", "rise", "warble")),
    "happy": (("bright", "chirp", "spark"), ("spark", "bright", "chirp"), ("chirp", "trill", "bright")),
    "confused": (("answer", "question", "fall"), ("warble", "answer", "low"), ("question", "warble", "fall")),
    "surprised": (("spark", "question"), ("bright", "spark"), ("spark", "rise")),
    "worried": (("low", "fall"), ("warble", "low"), ("answer", "fall", "low")),
    "greeting": (("chirp", "answer", "rise"), ("rise", "bright", "answer", "trill"), ("answer", "chirp", "question")),
    "sleep": (("soft", "low"), ("soft", "soft"), ("answer", "soft")),
    "wake": (("low", "rise", "chirp"), ("soft", "question", "bright"), ("rise", "answer")),
    "celebrate": (("rise", "trill", "spark", "bright"), ("bright", "chirp", "trill", "spark"), ("chirp", "rise", "bright")),
    "affection": (("soft", "warble", "chirp"), ("warble", "soft"), ("soft", "answer", "chirp"))}


def compose_phrases(source: Path, destination: Path):
    syllables = {}
    for name in {name for variants in PHRASES.values() for phrase in variants for name in phrase}:
        with wave.open(str(source / f"{name}.wav"), "rb") as sound:
            if (sound.getnchannels(), sound.getsampwidth(), sound.getframerate()) != (1, 2, 22050):
                raise ValueError("Sílaba sonora incompatível.")
            if sound.getnframes() > 11025:
                raise ValueError("Sílaba sonora extensa demais.")
            syllables[name] = sound.readframes(sound.getnframes())
    result = {}
    for emotion, variants in PHRASES.items():
        result[emotion] = []
        for index, phrase in enumerate(variants):
            path = destination / f"{emotion}-{index}.wav"
            frames = (b"\x00\x00" * 330).join(syllables[name] for name in phrase)
            with wave.open(str(path), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(22050)
                output.writeframes(frames)
            result[emotion].append(path)
    return result
