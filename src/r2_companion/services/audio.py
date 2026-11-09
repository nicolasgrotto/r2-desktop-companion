import logging
import os
from pathlib import Path


class AudioService:
    def __init__(self, sound: Path):
        self.sound = sound
        self.enabled = False

    def play(self) -> None:
        if self.enabled and os.name == "nt" and self.sound.is_file():
            import winsound
            try:
                winsound.PlaySound(str(self.sound), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
            except RuntimeError:
                logging.getLogger(__name__).warning("Áudio indisponível")

    def close(self) -> None:
        if os.name == "nt":
            import winsound
            winsound.PlaySound(None, 0)
