import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from r2_companion.services.media import (
    MediaCapabilities, MediaCommand, MediaService, MediaSession, _MediaWorker, bounded,
)


A = MediaSession("first", "app.a")
B = MediaSession("second", "app.b")
ALL = MediaCapabilities(play=True, pause=True, previous=True, next=True)


class FakeBackend:
    def __init__(self):
        self.sessions = ()
        self.current = None
        self.caps = ALL
        self.calls = []
        self.reads = []
        self.answer = True
        self.hold_commands = False
        self.hold_metadata = False
        self.commands = []
        self.selected = None
        self.closed = False

    async def open(self, notify):
        self.thread = threading.get_ident()
        self.loop = asyncio.get_running_loop()
        self.notify = notify

    def catalog(self):
        assert threading.get_ident() == self.thread
        return self.sessions, self.current

    def watch(self, session):
        self.selected = session

    def playback(self, session):
        return "paused", self.caps

    async def metadata(self, session):
        future = self.loop.create_future()
        self.reads.append((session, future))
        if self.hold_metadata:
            return await future
        return None, None

    async def execute(self, session, command):
        future = self.loop.create_future()
        self.calls.append((session, command))
        self.commands.append(future)
        if self.hold_commands:
            return await future
        return self.answer

    def close(self):
        assert threading.get_ident() == self.thread
        self.selected = None
        self.closed = True

    def change(self, sessions, current, *, event="catalog"):
        def apply():
            self.sessions, self.current = sessions, current
            self.notify(event)
        self.loop.call_soon_threadsafe(apply)


def until(app, predicate):
    deadline = time.monotonic() + 4
    while not predicate():
        assert time.monotonic() < deadline, "Timed out waiting for media state"
        app.processEvents()
        time.sleep(0.002)


@pytest.fixture
def media(qapp):
    backend = FakeBackend()
    service = MediaService(backend_factory=lambda: backend)
    yield service, backend
    service.close()


def test_opt_in_discovery_pin_and_automatic_follow_windows(qapp, media):
    service, backend = media
    assert service.view.status == "disabled" and not hasattr(backend, "loop")
    service.set_enabled(True)
    until(qapp, lambda: service.view.status == "ready")
    assert service.view.snapshot is None and not service.view.sessions
    assert backend.thread != threading.get_ident()
    backend.change((A, B), B)
    until(qapp, lambda: service.view.snapshot and service.view.snapshot.session == B)
    assert service.view.snapshot.title is service.view.snapshot.artist is None
    service.select(A)
    until(qapp, lambda: service.view.pinned == A)
    captured = service.view.snapshot
    assert captured.session == A
    backend.change((B,), B)
    until(qapp, lambda: service.view.error == "session_missing")
    assert service.view.snapshot is None
    replacement = MediaSession("new", A.source)
    backend.change((B, replacement), replacement)
    until(qapp, lambda: replacement in service.view.sessions)
    assert service.view.snapshot is None and service.view.pinned == A
    assert not service.command(captured, MediaCommand.PLAY)
    service.select(None)
    until(qapp, lambda: service.view.snapshot and service.view.snapshot.session == replacement)
    service.close()
    assert backend.closed and backend.calls == []


@pytest.mark.parametrize("action", list(MediaCommand))
def test_refusal_and_lost_capability_do_not_retry(qapp, media, action):
    service, backend = media
    backend.sessions, backend.current = (A, B), B
    backend.answer = False
    results = []
    service.command_finished.connect(lambda target, result: results.append(result))
    service.set_enabled(True)
    until(qapp, lambda: service.view.snapshot)
    target = service.view.snapshot
    assert service.command(target, action)
    assert not service.command(target, action)
    until(qapp, lambda: results == ["refused"])
    assert backend.calls == [(B, action)] and not service.pending(B)
    backend.loop.call_soon_threadsafe(setattr, backend, "caps", MediaCapabilities())
    assert service.command(target, action)
    until(qapp, lambda: results == ["refused", "unsupported"])
    assert backend.calls == [(B, action)] and not service.command(target, action)


def test_late_command_and_metadata_do_not_contaminate_new_selection(qapp, media):
    service, backend = media
    backend.sessions, backend.current = (A, B), A
    backend.hold_commands = backend.hold_metadata = True
    results = []
    service.command_finished.connect(lambda target, result: results.append((target.session, result)))
    service.set_enabled(True)
    until(qapp, lambda: service.view.snapshot and backend.reads)
    first = service.view.snapshot
    assert service.command(first, MediaCommand.PLAY)
    until(qapp, lambda: len(backend.calls) == 1)
    backend.change((A, B), B)
    until(qapp, lambda: service.view.snapshot.session == B and len(backend.reads) == 2)
    second = service.view.snapshot
    assert second.generation != first.generation and not service.command(first, MediaCommand.PLAY)
    assert service.command(second, MediaCommand.NEXT)
    until(qapp, lambda: len(backend.calls) == 2)
    backend.loop.call_soon_threadsafe(backend.commands[1].set_result, True)
    backend.loop.call_soon_threadsafe(backend.reads[1][1].set_result, ("title B", None))
    until(qapp, lambda: not service.pending(B) and service.view.snapshot.title == "title B")
    backend.loop.call_soon_threadsafe(backend.commands[0].set_result, False)
    until(qapp, lambda: not service.pending(A))
    assert results == [(B, "accepted")] and backend.reads[0][1].cancelled()
    assert service.view.snapshot.artist is None
    backend.change((A, B), B, event="metadata")
    until(qapp, lambda: len(backend.reads) == 3 and service.view.snapshot.title is None)
    backend.loop.call_soon_threadsafe(backend.reads[2][1].set_result, (None, "artist"))
    until(qapp, lambda: service.view.snapshot.artist == "artist")
    assert service.view.snapshot.generation == second.generation


def test_dispatch_revalidates_current_even_before_windows_notification(qapp, media):
    service, backend = media
    backend.sessions, backend.current = (A, B), A
    service.set_enabled(True)
    until(qapp, lambda: service.view.snapshot)
    target = service.view.snapshot
    backend.loop.call_soon_threadsafe(setattr, backend, "current", B)
    assert service.command(target, MediaCommand.NEXT)
    until(qapp, lambda: service.view.snapshot.session == B and not service.pending(A))
    assert not backend.calls
    duplicate = MediaSession("third", B.source)
    backend.change((B, duplicate), B)
    until(qapp, lambda: service.view.error == "ambiguous_source")
    assert not service.command(service.view.snapshot, MediaCommand.PLAY)
    assert not backend.calls


def test_disable_cancels_awaits_joins_and_ignores_old_queued_updates(qapp, media):
    service, backend = media
    backend.sessions, backend.current = (A,), A
    backend.hold_commands = backend.hold_metadata = True
    service.set_enabled(True)
    until(qapp, lambda: service.view.snapshot and backend.reads)
    target = service.view.snapshot
    assert service.command(target, MediaCommand.NEXT)
    until(qapp, lambda: backend.commands)
    worker = service._worker
    service.set_enabled(False)
    assert not worker.is_alive() and worker.closed_cleanly and backend.closed
    assert backend.reads[0][1].cancelled() and backend.commands[0].cancelled()
    service.set_enabled(True)
    until(qapp, lambda: service.view.snapshot)
    assert not service.command(target, MediaCommand.PAUSE)
    assert backend.calls == [(A, MediaCommand.NEXT)]
    service.close()
    qapp.processEvents()
    assert service.view.status == "disabled" and service.view.snapshot is None


def test_unavailable_backend_and_immediate_shutdown(qapp):
    def missing():
        raise ImportError("private provider text")
    service = MediaService(backend_factory=missing)
    service.set_enabled(True)
    try:
        until(qapp, lambda: service.view.status == "unavailable")
        assert service.view.error == "integration_unavailable"
    finally:
        service.close()
    service.set_enabled(True)
    service.close()
    qapp.processEvents()
    assert service.view.status == "disabled"


def test_timeout_bounds_for_metadata_and_command(qapp, media, monkeypatch):
    assert (_MediaWorker.COMMAND_TIMEOUT, _MediaWorker.METADATA_TIMEOUT) == (3, 5)
    monkeypatch.setattr(_MediaWorker, "METADATA_TIMEOUT", .08)
    monkeypatch.setattr(_MediaWorker, "COMMAND_TIMEOUT", .05)
    service, backend = media
    backend.sessions, backend.current = (A,), A
    backend.hold_commands = backend.hold_metadata = True
    results = []
    service.command_finished.connect(lambda target, result: results.append(result))
    service.set_enabled(True)
    until(qapp, lambda: service.view.snapshot)
    assert service.command(service.view.snapshot, MediaCommand.PAUSE)
    until(qapp, lambda: results and service.view.snapshot.metadata_error)
    assert results == ["command_timeout"] and service.view.snapshot.metadata_error == "metadata_timeout"
    assert len(backend.calls) == 1 and backend.commands[0].cancelled()
    assert backend.reads[0][1].cancelled() and not service.pending(A)


def test_timeout_abandons_native_cancellation_acknowledgement():
    async def scenario():
        async def native():
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                await asyncio.Future()
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(bounded(native(), .01), 1)
        assert len(asyncio.all_tasks()) == 1
    asyncio.run(scenario())


def test_windows_catalog_keeps_original_transport_and_retires_replaced_source():
    from r2_companion.services.windows_media import WindowsMediaBackend

    class Native:
        def __init__(self, source):
            self.source_app_user_model_id = source
            self.calls = []

        def try_play_async(self):
            self.calls.append("play")

        try_pause_async = try_skip_next_async = try_skip_previous_async = try_play_async

    a, b = Native("a"), Native("b")
    sessions = [a]
    backend = WindowsMediaBackend()
    backend._manager = SimpleNamespace(get_sessions=lambda: sessions, get_current_session=lambda: sessions[0])
    _, first = backend.catalog()
    proxy = Native("a")
    sessions[:] = [proxy, b]
    both, current = backend.catalog()
    assert len(both) == 2 and current == first
    backend.catalog()
    backend.execute(first, MediaCommand.PLAY)
    assert a.calls == ["play"] and not proxy.calls and not b.calls
    sessions[0] = Native("a")
    _, replacement = backend.catalog()
    assert replacement != first
    with pytest.raises(KeyError):
        backend.execute(first, MediaCommand.PLAY)
    backend.close()


def test_timeout_and_disable_during_native_acknowledgement(qapp, monkeypatch):
    cancelling = threading.Event()
    released = threading.Event()

    class DelayedBackend(FakeBackend):
        async def execute(self, session, command):
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancelling.set()
                try:
                    await asyncio.Future()
                finally:
                    released.set()

    backend = DelayedBackend()
    backend.sessions, backend.current = (A,), A
    monkeypatch.setattr(_MediaWorker, "COMMAND_TIMEOUT", .03)
    service = MediaService(backend_factory=lambda: backend)
    try:
        service.set_enabled(True)
        until(qapp, lambda: service.view.snapshot)
        assert service.command(service.view.snapshot, MediaCommand.NEXT)
        until(qapp, cancelling.is_set)
    finally:
        service.close()
    assert released.is_set() and backend.closed
