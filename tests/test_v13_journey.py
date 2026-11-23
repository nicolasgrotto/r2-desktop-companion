import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from r2_companion.app import Companion
from r2_companion.core.language import activate_language
from r2_companion.features.timer import TimerState
from r2_companion.pet.state import State
from r2_companion.services.companion_state import CompanionStateStore
from r2_companion.services.storage import ConfigStore
from test_media_service import A, until
from test_media_ui import Player


@pytest.mark.parametrize(("language", "focus_label", "music_label"), [
    ("pt-BR", "Foco", "Música"),
    ("en", "Focus", "Music"),
])
def test_task_focus_music_completion_across_languages(native_desktop, qapp, tmp_path, clock,
                                                      language, focus_label, music_label):
    store = ConfigStore(tmp_path)
    assert store.acquire()
    store.load()
    preferences = CompanionStateStore(store)
    assert preferences.save_language(language)
    preferences.close()
    pet = Companion(qapp, store)
    player = Player()
    pet.media._factory = lambda: player
    try:
        pet.greeting_timer.stop()
        pet.countdown.clock = clock
        task_text = "Revisar capítulos"
        task = pet.productivity.add_task(task_text)
        pet.show_action_search()
        assert QTest.qWaitForWindowActive(pet.action_search)
        pet.action_search.query.setText(focus_label)
        row = next(i for i in range(pet.action_search.results.count())
                   if pet.action_search.results.item(i).data(Qt.ItemDataRole.UserRole) == "focus")
        pet.action_search.results.setCurrentRow(row)
        QTest.keyClick(pet.action_search.query, Qt.Key.Key_Return)
        assert pet.tools.tabs.currentWidget() is pet.tools.pages["focus"]
        run_id = pet.focus.start_focus(60, task_id=task)
        pet.project_focus()
        assert pet.window.projection.model.title == focus_label
        assert task_text in pet.window.projection_text

        pet.controller.enter(State.SLEEP)
        pet.set_media_enabled(True)
        until(qapp, lambda: pet.media.view.snapshot and pet.media.view.snapshot.session == A)
        player.change_playback(A, "playing")
        until(qapp, lambda: pet.presence.context.media_playing)
        assert pet.controller.state == State.SLEEP and not pet.presence.decision.spontaneous_audio
        pet.show_tools_page("media")
        pet.project_music()
        assert pet.window.projection.model.title == music_label
        pet.quiet_active = True
        pet.update_visibility()
        assert not pet.presence.decision.notifications
        pet.presence.select_mode("presentation")
        assert not pet.window.isVisible() and pet.window.projection.model is None
        clock.advance(60)
        pet.countdown.tick()
        assert pet.focus.session.state == TimerState.COMPLETED
        assert pet.focus.complete_task(run_id)
        assert pet.productivity.task(task)["done"]
        next_run = pet.focus.start_next_phase(run_id)
        assert next_run is not None
        pet.focus.pause(next_run)
        assert pet.focus.session.state == TimerState.PAUSED
        assert player.calls == []
    finally:
        pet.shutdown()
        activate_language(qapp, "pt-BR")
