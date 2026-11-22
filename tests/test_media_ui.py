from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QTest

from r2_companion.pet.state import State
from r2_companion.services.media import MediaCapabilities, MediaCommand, MediaService
from r2_companion.ui.media import MediaPage, music_projection
from test_context_v03 import pet
from test_focus_ui import tab_to
from test_media_service import A, B, FakeBackend, until


class Player(FakeBackend):
    def __init__(self):
        super().__init__()
        self.sessions, self.current = (A, B), A
        self.states = {}
        self.track = "<Faixa & título>"

    def playback(self, session):
        return self.states.get(session, "paused"), self.caps

    async def metadata(self, session):
        return self.track, None

    def change_playback(self, session, state):
        def update():
            self.states[session] = state
            self.notify("playback")
        self.loop.call_soon_threadsafe(update)


def test_media_page_names_absent_metadata_and_explicit_retry(qapp):
    attempts = []
    player = Player()
    player.answer = False
    player.caps = MediaCapabilities(next=True)

    def connect():
        attempts.append(1)
        if len(attempts) == 1:
            raise ImportError
        return player

    service = MediaService(backend_factory=connect)
    page = MediaPage(service)
    page.enable_requested.connect(service.set_enabled)
    page.show()
    try:
        assert not attempts and not page.project.isEnabled()
        page.enabled.click()
        until(qapp, lambda: page.retry.isEnabled())
        assert "indisponível" in page.feedback.text()
        page.retry.click()
        until(qapp, lambda: page.track.text() == player.track)
        assert not page.artist.isVisible()
        assert QAccessible.queryAccessibleInterface(page.sessions).text(QAccessible.Text.Name) == "Sessão de mídia"
        assert QAccessible.queryAccessibleInterface(page.controls[MediaCommand.PLAY]).state().disabled
        button = page.controls[MediaCommand.NEXT]
        assert QAccessible.queryAccessibleInterface(button).text(QAccessible.Text.Name) == "Próxima"
        assert music_projection(service.view).lines == (player.track, "Pausada")
        button.click()
        until(qapp, lambda: "recusou" in page.feedback.text())
        page.retry.click()
        until(qapp, lambda: page.track.text() == player.track and not page.feedback.text())
        assert player.calls == [(A, MediaCommand.NEXT)] and len(attempts) == 2
    finally:
        service.close()
        page.close()


def test_keyboard_music_journey_and_stale_click(pet, qapp):
    player = Player()
    pet.media._factory = lambda: player
    tools = pet.tools
    action = next(item for item in pet.menu.tools_ref.actions() if item.data() == "media")
    action.trigger()
    assert QTest.qWaitForWindowActive(tools)
    assert tools.tabs.currentWidget() is tools.pages["media"]
    page = tools.media_page
    tab_to(qapp, tools, page.enabled)
    QTest.keyClick(page.enabled, Qt.Key.Key_Space)
    until(qapp, lambda: page.track.text() == player.track)
    assert pet.companion_state.data["media"]["enabled"]
    tab_to(qapp, tools, page.sessions)
    QTest.keyClick(page.sessions, Qt.Key.Key_End)
    until(qapp, lambda: pet.media.view.pinned == B)
    tab_to(qapp, tools, page.controls[MediaCommand.PLAY])
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_Space)
    until(qapp, lambda: player.calls == [(B, MediaCommand.PLAY)] and not pet.media.pending(B))
    tab_to(qapp, tools, page.project)
    QTest.keyClick(page.project, Qt.Key.Key_Space)
    assert pet.window.projection_kind == "music"
    assert pet.window.projection_overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert not pet.window.projection_timer.isActive()
    assert player.track in tools.projection_details.toPlainText()
    # Remove the pinned session on the worker before its queued UI refresh is delivered.
    player.change((A,), A)
    page.controls[MediaCommand.NEXT].click()
    until(qapp, lambda: pet.media.view.error == "session_missing")
    assert player.calls == [(B, MediaCommand.PLAY)]
    assert pet.window.projection_kind == "music"
    assert "Sessão indisponível" in pet.window.projection_text
    QTest.keyClick(tools, Qt.Key.Key_Escape)
    assert not tools.isVisible()
    player.change_playback(A, "playing")
    until(qapp, lambda: pet.media.view.playing)
    assert not tools.isVisible() and player.calls == [(B, MediaCommand.PLAY)]
    pet.end_projection()
    pet.shutdown()
    assert player.closed and player.calls == [(B, MediaCommand.PLAY)]


def test_music_presence_real_edges_sleep_visibility_resume_and_droid_swaps(pet, qapp, monkeypatch):
    player = Player()
    player.states[A] = "playing"
    pet.media._factory = lambda: player
    settings = deepcopy(pet.store.settings)
    settings.sound_enabled = True
    pet.store.apply(settings)
    onsets = []
    original = pet.reactions.start_scene

    def start(action, **options):
        onsets.append(action)
        return original(action, **options)

    monkeypatch.setattr(pet.reactions, "start_scene", start)
    pet.set_media_enabled(True)
    until(qapp, lambda: pet.media.view.playing)
    assert not onsets and not pet.presence.decision.spontaneous_audio
    assert pet.presence.decision.explicit_audio
    pet.media.select(B)
    until(qapp, lambda: pet.media.view.pinned == B)
    assert pet.media.view.snapshot.playback == "paused" and pet.presence.context.media_playing
    player.change_playback(A, "paused")
    until(qapp, lambda: not pet.presence.context.media_playing)
    assert pet.presence.decision.spontaneous_audio
    pet.project_music()
    player.change_playback(B, "playing")
    until(qapp, lambda: onsets == ["media_started"])
    player.track = "Nova faixa"
    player.change((A, B), A, event="metadata")
    until(qapp, lambda: pet.media.view.snapshot.title == "Nova faixa")
    assert onsets == ["media_started"]
    for identifier in pet.droids.profiles:
        assert pet.equip_droid(identifier)
        assert pet.window.projection_kind == "music" and pet.presence.context.media_playing
    pet.hide_pet()
    assert pet.window.projection_kind == "music" and pet.window.projection.model is None
    player.change_playback(B, "paused")
    until(qapp, lambda: not pet.media.view.playing)
    player.change_playback(B, "playing")
    until(qapp, lambda: pet.media.view.playing)
    pet.show_pet()
    pet.controller.enter(State.SLEEP)
    player.change_playback(B, "paused")
    until(qapp, lambda: not pet.media.view.playing)
    player.change_playback(B, "playing")
    until(qapp, lambda: pet.media.view.playing)
    assert pet.controller.state == State.SLEEP and not pet.tools.isVisible()
    pet.set_suspended(True)
    assert pet.window.projection.model is None
    player.change_playback(B, "paused")
    until(qapp, lambda: not pet.media.view.playing)
    player.change_playback(B, "playing")
    until(qapp, lambda: pet.media.view.playing)
    pet.set_suspended(False)
    until(qapp, lambda: pet.window.projection.model is not None)
    assert "Reproduzindo" in pet.window.projection_text
    assert not pet.presence.decision.spontaneous_audio and pet.store.settings.sound_enabled
    assert onsets == ["media_started"] and not player.calls
