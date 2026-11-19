"""Event-driven media control. Only immutable views cross the worker boundary."""
import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from itertools import count
import logging
from threading import Thread
from typing import Protocol

from PySide6.QtCore import QObject, Qt, Signal, Slot


class MediaCommand(StrEnum):
    PLAY = "play"
    PAUSE = "pause"
    PREVIOUS = "previous"
    NEXT = "next"


@dataclass(frozen=True)
class MediaCapabilities:
    play: bool = False
    pause: bool = False
    previous: bool = False
    next: bool = False

    def allows(self, command: MediaCommand) -> bool:
        return isinstance(command, MediaCommand) and getattr(self, command.value)


@dataclass(frozen=True)
class MediaSession:
    id: str
    source: str


@dataclass(frozen=True)
class MediaSnapshot:
    session: MediaSession
    generation: int
    playback: str | None = None
    capabilities: MediaCapabilities = MediaCapabilities()
    title: str | None = None
    artist: str | None = None
    metadata_error: str | None = None


@dataclass(frozen=True)
class MediaView:
    status: str = "disabled"
    sessions: tuple[MediaSession, ...] = ()
    pinned: MediaSession | None = None  # None follows the Windows current session.
    snapshot: MediaSnapshot | None = None
    error: str | None = None


class MediaBackend(Protocol):
    """Methods and notifications run on the media event loop."""

    async def open(self, notify: Callable[[str], None]) -> None: ...
    def catalog(self) -> tuple[tuple[MediaSession, ...], MediaSession | None]: ...
    def watch(self, session: MediaSession | None) -> None: ...
    def playback(self, session: MediaSession) -> tuple[str | None, MediaCapabilities]: ...
    def metadata(self, session: MediaSession) -> Awaitable[tuple[str | None, str | None]]: ...
    def execute(self, session: MediaSession, command: MediaCommand) -> Awaitable[bool]: ...
    def close(self) -> None: ...


def _windows_backend():
    from .windows_media import WindowsMediaBackend
    return WindowsMediaBackend()


def _matches(current, target):
    return current is not None and (current.session, current.generation) == (target.session, target.generation)


async def _cancel_operation(task):
    # The first cancellation asks Windows for acknowledgement. PyWinRT's second
    # cancellation releases the awaiter even if the provider hasn't acknowledged.
    for _ in range(2):
        task.cancel()
        done, _ = await asyncio.wait({task}, timeout=0.25)
        if done:
            if not task.cancelled():
                task.exception()
            return
    raise RuntimeError("Media operation did not cancel")


async def bounded(operation, seconds):
    task = asyncio.ensure_future(operation)
    try:
        done, _ = await asyncio.wait({task}, timeout=seconds)
        if not done:
            raise TimeoutError
        if task.cancelled():
            raise RuntimeError("Media operation cancelled by provider")
        return task.result()
    finally:
        if not task.done():
            await asyncio.shield(_cancel_operation(task))


class _MediaWorker(Thread):
    COMMAND_TIMEOUT = 3.0
    METADATA_TIMEOUT = 5.0

    def __init__(self, factory, deliver, finished, generations):
        super().__init__(name="CompanionMedia")
        self.factory, self.deliver, self.finished = factory, deliver, finished
        self.generations = generations
        self.loop = asyncio.new_event_loop()
        self.backend: MediaBackend | None = None
        self.view = MediaView(status="connecting")
        self.pinned = None
        self.tasks = set()
        self.reader = None
        self.dirty = set()
        self.opened = False
        self.stopping = False
        self.closed_cleanly = False

    def run(self):
        asyncio.set_event_loop(self.loop)
        # The default handler includes repr(callback/exception), which may contain metadata.
        self.loop.set_exception_handler(lambda loop, context: logging.getLogger(__name__).error(
            "Falha assíncrona no serviço de mídia."))
        try:
            self.spawn(self.open())
            self.loop.run_forever()
        finally:
            self.opened = False
            tasks = tuple(self.tasks)
            for task in tasks:
                if not task.cancelling():
                    task.cancel()
            self.loop.run_until_complete(asyncio.gather(*tasks, return_exceptions=True))
            # A timeout followed immediately by shutdown can leave a shielded
            # native cancellation finishing on this dedicated loop.
            remaining = asyncio.all_tasks(self.loop)
            if remaining:
                self.loop.run_until_complete(asyncio.gather(*remaining, return_exceptions=True))
            try:
                if self.backend is not None:
                    self.backend.close()
                    self.backend = None
                self.closed_cleanly = True
            finally:
                self.loop.close()

    def spawn(self, coroutine):
        task = self.loop.create_task(coroutine)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return task

    def publish(self, view):
        if view != self.view:
            self.view = view
            self.deliver(self, view)

    async def open(self):
        try:
            self.backend = self.factory()
            await bounded(self.backend.open(self.notify), self.METADATA_TIMEOUT)
        except Exception:
            self.publish(MediaView(status="unavailable", error="integration_unavailable"))
            return
        self.opened = True
        self.refresh(metadata=True)

    def notify(self, event):
        if self.opened:
            if not self.dirty:
                self.loop.call_soon(self.process_events)
            self.dirty.add(event)

    def process_events(self):
        events, self.dirty = self.dirty, set()
        if self.opened:
            self.refresh(metadata="metadata" in events)

    def select(self, session):
        if session != self.pinned:
            self.pinned = session
            if self.opened:
                self.refresh(metadata=False, selection_changed=True)

    def refresh(self, *, metadata, selection_changed=False):
        old = self.view.snapshot
        try:
            sessions, current = self.backend.catalog()
            pinned = self.pinned
            selected = pinned if pinned is not None else current
            if selected not in sessions:
                selected = None
            changed = selection_changed or (old.session if old else None) != selected
            self.backend.watch(selected)
            snapshot = None
            error = "session_missing" if pinned and selected is None else None
            if selected is not None:
                snapshot = MediaSnapshot(selected, next(self.generations)) if changed or old is None else old
                playback, capabilities = self.backend.playback(selected)
                if sum(s.source == selected.source for s in sessions) > 1:
                    capabilities, error = MediaCapabilities(), "ambiguous_source"
                snapshot = replace(snapshot, playback=playback, capabilities=capabilities)
            if changed or metadata:
                self.cancel_reader()
                if snapshot is not None:
                    snapshot = replace(snapshot, title=None, artist=None, metadata_error=None)
                    self.reader = self.spawn(self.read_metadata(snapshot))
            self.publish(MediaView("ready", sessions, pinned, snapshot, error))
        except Exception:
            self.cancel_reader()
            self.publish(MediaView(status="unavailable", pinned=self.pinned, error="session_unavailable"))

    def cancel_reader(self):
        if self.reader is not None:
            self.reader.cancel()
            self.reader = None

    async def read_metadata(self, target):
        title = artist = error = None
        try:
            title, artist = await bounded(self.backend.metadata(target.session), self.METADATA_TIMEOUT)
        except TimeoutError:
            error = "metadata_timeout"
        except Exception:
            error = "metadata_unavailable"
        current = self.view.snapshot
        if self.reader is asyncio.current_task() and _matches(current, target):
            self.reader = None
            self.publish(replace(self.view, snapshot=replace(current, title=title, artist=artist, metadata_error=error)))

    async def command(self, target, action):
        result = "stale"
        try:
            # Re-enumerate at dispatch, even if the Windows notification is still queued.
            self.refresh(metadata=False)
            if _matches(self.view.snapshot, target):
                result = "unsupported"
                if self.view.snapshot.capabilities.allows(action):
                    accepted = await bounded(self.backend.execute(target.session, action), self.COMMAND_TIMEOUT)
                    result = "accepted" if accepted else "refused"
        except TimeoutError:
            result = "command_timeout"
        except Exception:
            result = "command_failed"
        self.finished(self, target, result)

    def dispatch(self, target, action):
        self.spawn(self.command(target, action))


class MediaService(QObject):
    """Qt-thread facade. Pass the displayed snapshot back with each explicit click."""

    changed = Signal()
    command_finished = Signal(object, str)
    _delivery = Signal(object, object)
    _completion = Signal(object, object, str)

    def __init__(self, parent=None, *, backend_factory=_windows_backend):
        super().__init__(parent)
        self.view = MediaView()
        self._factory = backend_factory
        self._worker = None
        self._generations = count(1)
        self._pending = set()
        self._delivery.connect(self._receive, Qt.ConnectionType.QueuedConnection)
        self._completion.connect(self._finish, Qt.ConnectionType.QueuedConnection)

    def set_enabled(self, enabled: bool):
        if not enabled:
            self.close()
        elif self._worker is None:
            self._worker = _MediaWorker(self._factory, self._delivery.emit, self._completion.emit, self._generations)
            self.view = MediaView(status="connecting")
            self._worker.start()
            self.changed.emit()

    def select(self, session: MediaSession | None):
        if self._worker is not None:
            self._worker.loop.call_soon_threadsafe(self._worker.select, session)

    def pending(self, session: MediaSession) -> bool:
        return session in self._pending

    def command(self, target: MediaSnapshot, action: MediaCommand) -> bool:
        if (self._worker is None or not _matches(self.view.snapshot, target) or
                not self.view.snapshot.capabilities.allows(action) or self.pending(target.session)):
            return False
        self._pending.add(target.session)
        self._worker.loop.call_soon_threadsafe(self._worker.dispatch, target, action)
        self.changed.emit()
        return True

    @Slot(object, object)
    def _receive(self, sender, view):
        if sender is self._worker:
            self.view = view
            self.changed.emit()

    @Slot(object, object, str)
    def _finish(self, sender, target, result):
        if sender is self._worker:
            self._pending.discard(target.session)
            if _matches(self.view.snapshot, target):
                self.command_finished.emit(target, result)
            self.changed.emit()

    def close(self):
        worker = self._worker
        if worker is None:
            return
        if not worker.stopping:
            worker.stopping = True
            worker.loop.call_soon_threadsafe(worker.loop.stop)
        worker.join(timeout=2)
        if worker.is_alive() or not worker.closed_cleanly:
            raise RuntimeError("Media worker shutdown failed")
        self._worker = None
        self.view = MediaView()
        self._pending.clear()
        self.changed.emit()
