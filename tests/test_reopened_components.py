from copy import deepcopy

from test_context_v03 import pet


def test_minimized_launchpads_restore_existing_panels(pet):
    for panel in (pet.apps_panel, pet.locations_panel):
        pet.show_launchpad(panel)
        panel.showMinimized()
        pet.show_launchpad(panel)
        assert panel.isVisible() and not panel.isMinimized()
        panel.close()


def test_audio_center_reopens_with_current_persisted_preferences(pet):
    pet.show_audio_center()
    dialog = pet.audio_dialog
    dialog.close()
    draft = deepcopy(pet.store.settings)
    draft.sound_enabled = True
    draft.audio.volume = 0.37
    pet.store.apply(draft)
    pet.show_audio_center()
    assert dialog is pet.audio_dialog
    assert dialog.master.isChecked() and dialog.volume.value() == 37
    dialog.save()
    assert pet.store.settings.sound_enabled and pet.store.settings.audio.volume == 0.37
