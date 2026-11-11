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


def read_pcm(path, maximum=11025):
    try:
        with wave.open(str(path), "rb") as sound:
            if (sound.getnchannels(), sound.getsampwidth(), sound.getframerate()) != (1, 2, 22050):
                raise ValueError("Sílaba sonora incompatível.")
            if not 1 <= sound.getnframes() <= maximum:
                raise ValueError("Recurso sonoro fora do limite de duração.")
            samples = sound.readframes(sound.getnframes())
            if len(samples) != sound.getnframes() * 2:
                raise ValueError("Recurso sonoro truncado.")
            return samples
    except (wave.Error, EOFError) as error:
        raise ValueError("Recurso PCM inválido.") from error


def compose_phrases(source: Path, destination: Path, phrases=None):
    phrases = PHRASES if phrases is None else phrases
    syllables = {}
    for name in {name for variants in phrases.values() for phrase in variants for name in phrase}:
        syllables[name] = read_pcm(source / f"{name}.wav")
    result = {}
    for emotion, variants in phrases.items():
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
