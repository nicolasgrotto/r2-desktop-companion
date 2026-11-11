from dataclasses import dataclass

from .movement import create_movement
from .profiles import DroidProfile
from .visuals import load_profile_clips


@dataclass
class PreparedDroid:
    profile: DroidProfile
    clips: dict
    movement: object
    audio_bank: dict


class DroidController:
    def __init__(self, registry, audio, window):
        self.registry, self.audio, self.window = registry, audio, window

    def prepare(self, identifier):
        self.registry.get(identifier)
        profile = DroidProfile.load(self.registry.sources[identifier], self.registry.assets)
        clips = load_profile_clips(profile)
        movement = create_movement(profile, self.window)
        try:
            bank = self.audio.prepare_profile(profile.audio)
        except (OSError, ValueError, RuntimeError):
            movement.close()
            movement.deleteLater()
            raise
        return PreparedDroid(profile, clips, movement, bank)
