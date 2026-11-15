import pytest

from r2_companion.pet.presence import PresenceContext, PresencePolicy
from test_audio_productivity import audio


@pytest.mark.parametrize("mode,spontaneous,allowed", [
    ("free", True, True), ("free", False, True),
    ("focus", True, False), ("focus", False, True),
    ("presentation", True, False), ("presentation", False, False),
])
def test_presence_audio_distinguishes_origin_without_changing_volume(audio, mode, spontaneous, allowed):
    before = audio.settings.volume
    audio.presence = PresencePolicy.evaluate(PresenceContext(manual_mode=mode, sound_enabled=True))
    audio.spontaneous = spontaneous
    assert audio.play("reactions") == allowed
    assert audio.settings.volume == before


@pytest.mark.parametrize("restriction", ["quiet", "master", "mute", "category"])
def test_explicit_focus_audio_still_obeys_existing_limits(audio, restriction):
    audio.presence = PresencePolicy.evaluate(PresenceContext(
        manual_mode="focus", sound_enabled=True, quiet_hours=restriction == "quiet"))
    if restriction == "master":
        audio.enabled = False
    elif restriction == "mute":
        audio.settings.muted = True
    elif restriction == "category":
        audio.settings.categories["notifications"] = False
    assert not audio.play("notifications")
