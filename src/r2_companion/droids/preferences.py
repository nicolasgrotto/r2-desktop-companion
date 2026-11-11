from copy import deepcopy
from dataclasses import asdict

from ..core.config import DroidPreferences, Settings
from ..pet.personality import apply_profile


def defaults_for(profile):
    settings = apply_profile(Settings(), profile.personality)
    return DroidPreferences.from_settings(settings, profile.customizations({}))


def preferences_for(settings, profile):
    return deepcopy(settings.droid_preferences.get(profile.id) or defaults_for(profile))


def select_droid(settings, profile, preferences=None):
    result = deepcopy(settings)
    result.capture_droid()
    selected = deepcopy(preferences or preferences_for(result, profile))
    selected.customization = profile.customizations(selected.customization)
    result.active_droid = profile.id
    result.behavior = deepcopy(selected.behavior)
    result.audio = deepcopy(selected.audio)
    result.personality = selected.personality
    result.appearance = selected.appearance
    result.droid_preferences[profile.id] = selected
    return Settings.parse(result.to_dict())
