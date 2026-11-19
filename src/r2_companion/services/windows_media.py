"""GSMTC bindings, confined to the activated media worker's COM apartment."""
import asyncio
from collections import Counter
from uuid import uuid4

from .media import MediaCapabilities, MediaCommand, MediaSession


class WindowsMediaBackend:
    def __init__(self):
        self._manager = None
        self._uninit = None
        self._sessions = {}
        self._enumerated = {}
        self._manager_tokens = []
        self._session_tokens = []
        self._selected = None
        self._notify = None

    async def open(self, notify):
        from winrt.runtime import ApartmentType, init_apartment, uninit_apartment
        from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager

        init_apartment(ApartmentType.MULTI_THREADED)
        self._uninit = uninit_apartment
        self._loop = asyncio.get_running_loop()
        self._notify = notify
        self._manager = await GlobalSystemMediaTransportControlsSessionManager.request_async()
        self._subscribe(self._manager, "sessions_changed", "catalog", self._manager_tokens)
        self._subscribe(self._manager, "current_session_changed", "catalog", self._manager_tokens)

    def _subscribe(self, owner, name, event, tokens):
        session = self._selected

        def deliver():
            if self._notify and (event == "catalog" or session == self._selected):
                self._notify(event)

        def callback(sender, args):
            try:
                self._loop.call_soon_threadsafe(deliver)
            except RuntimeError:
                pass  # A native callback already in flight while the loop closed.

        token = getattr(owner, "add_" + name)(callback)
        tokens.append((getattr(owner, "remove_" + name), token))

    @staticmethod
    def _unsubscribe(tokens):
        failed = []
        for remove, token in tokens:
            try:
                remove(token)
            except Exception:
                failed.append((remove, token))
        tokens[:] = failed
        if failed:
            raise RuntimeError("Media event removal failed")

    def catalog(self):
        natives = tuple(self._manager.get_sessions())
        current = self._manager.get_current_session()
        previous_sources = Counter(key.source for key in self._sessions)
        sources = Counter(native.source_app_user_model_id for native in natives)
        unique = {key.source: key for key in self._sessions if previous_sources[key.source] == 1}
        sessions = {}
        enumerated = {}
        selected = None
        for native in natives:
            source = native.source_app_user_model_id
            key = self._enumerated.get(native)
            if key is None and sources[source] == 1 and sources.keys() != previous_sources.keys():
                # Windows may recreate every enumeration proxy when another app
                # joins/leaves. Keep the original transport object for the surviving
                # source. A command can never migrate to a replacement proxy.
                key = unique.get(source)
            if key is None:
                key = MediaSession(uuid4().hex, source)
            sessions[key] = self._sessions.get(key, native)
            enumerated[native] = key
            if native == current:
                selected = key
        self._sessions = sessions
        self._enumerated = enumerated
        if selected is None and current is not None:
            candidates = [s for s in sessions if s.source == current.source_app_user_model_id]
            if len(candidates) == 1:
                selected = candidates[0]
        return tuple(sessions), selected

    def watch(self, session):
        if session == self._selected:
            return
        self._unsubscribe(self._session_tokens)
        self._selected = session
        if session is not None:
            native = self._sessions[session]
            try:
                self._subscribe(native, "playback_info_changed", "playback", self._session_tokens)
                self._subscribe(native, "media_properties_changed", "metadata", self._session_tokens)
            except Exception:
                self._selected = None
                self._unsubscribe(self._session_tokens)
                raise

    def playback(self, session):
        info = self._sessions[session].get_playback_info()
        if info is None:
            return None, MediaCapabilities()
        controls = info.controls
        return info.playback_status.name.lower(), MediaCapabilities(
            play=controls.is_play_enabled, pause=controls.is_pause_enabled,
            previous=controls.is_previous_enabled, next=controls.is_next_enabled,
        )

    async def metadata(self, session):
        media = await self._sessions[session].try_get_media_properties_async()
        return (media.title or None, media.artist or None) if media else (None, None)

    def execute(self, session, command):
        native = self._sessions[session]
        methods = {
            MediaCommand.PLAY: native.try_play_async,
            MediaCommand.PAUSE: native.try_pause_async,
            MediaCommand.NEXT: native.try_skip_next_async,
            MediaCommand.PREVIOUS: native.try_skip_previous_async,
        }
        return methods[command]()

    def close(self):
        self._notify = None
        try:
            self._unsubscribe(self._session_tokens)
        finally:
            try:
                self._unsubscribe(self._manager_tokens)
            finally:
                self._sessions.clear()
                self._enumerated.clear()
                self._manager = None
                if self._uninit:
                    self._uninit()
                    self._uninit = None
