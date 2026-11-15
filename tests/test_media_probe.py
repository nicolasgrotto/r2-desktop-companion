"""Probe safety/lifecycle tests; these do not certify native media compatibility."""
import asyncio
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import threading

import pytest

spec = importlib.util.spec_from_file_location("media_probe", Path(__file__).parents[1] / "tools/media_probe.py")
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


class Events:
    def __init__(self):
        self.handlers = {}
        self.next_token = 0

    def __getattr__(self, name):
        if name.startswith("add_"):
            def add(callback):
                self.next_token += 1
                self.handlers[self.next_token] = (name[4:], callback)
                return self.next_token
            return add
        if name.startswith("remove_"):
            return lambda token: self.handlers.pop(token)
        raise AttributeError(name)

    def fire(self, event):
        for name, callback in list(self.handlers.values()):
            if name == event:
                callback(self, None)


class Session(Events):
    def __init__(self, source="fixture", accepted=True, supported=True, error=None):
        super().__init__()
        self.source_app_user_model_id = source
        self.accepted, self.error = accepted, error
        self.calls = []
        self.controls = SimpleNamespace(**{control: supported for control, _ in probe.COMMANDS.values()})

    def get_playback_info(self):
        return SimpleNamespace(playback_status=SimpleNamespace(name="PAUSED"), controls=self.controls)

    async def try_get_media_properties_async(self):
        if self.error:
            raise self.error
        return SimpleNamespace(title="PRIVATE_TRACK", artist="PRIVATE_ARTIST")

    def __getattr__(self, name):
        if name in {method for _, method in probe.COMMANDS.values()}:
            async def command():
                self.calls.append(name)
                return self.accepted
            return command
        return super().__getattr__(name)


class Manager(Events):
    def __init__(self, sessions=()):
        super().__init__()
        self.sessions = list(sessions)

    def get_sessions(self):
        return self.sessions

    def get_current_session(self):
        return self.sessions[0] if self.sessions else None


def arguments(action="snapshot", source=None, seconds=0):
    return SimpleNamespace(action=action, source=source, seconds=seconds, timeout=0.1)


def execute(manager, args=None):
    records = []
    async def request():
        return manager
    code = asyncio.run(probe.execute(args or arguments(), lambda event, **fields: records.append(
        {"event": event, **fields}), request))
    return code, records


def test_snapshot_reads_capabilities_without_playing_or_recording_metadata():
    session = Session()
    manager = Manager([session])
    code, records = execute(manager)
    assert code == 0 and not session.calls
    snapshot = next(r for r in records if r["event"] == "snapshot")
    assert snapshot["sessions"][0]["title_present"]
    assert set(snapshot["sessions"][0]["capabilities"]) == {"play", "pause", "next", "previous"}
    assert "PRIVATE" not in json.dumps(records)
    assert not manager.handlers and not session.handlers
    assert records[-1] == {"event": "closed", "subscriptions_remaining": 0, "cleanup_errors": 0}


def test_empty_desktop_is_success_and_not_an_unsupported_platform():
    code, records = execute(Manager())
    assert code == 0
    assert next(r for r in records if r["event"] == "snapshot")["count"] == 0


@pytest.mark.parametrize("action", probe.COMMANDS)
def test_commands_only_reach_the_explicit_source_once(action):
    selected, other = Session("selected"), Session("other")
    code, records = execute(Manager([other, selected]), arguments(action, "selected"))
    assert code == 0
    assert selected.calls == [probe.COMMANDS[action][1]]
    assert other.calls == []
    assert next(r for r in records if r["event"] == "command")["outcome"] == "accepted"


@pytest.mark.parametrize("sessions,outcome", [
    ([Session("other")], "session_missing"),
    ([Session(), Session()], "ambiguous_source"),
    ([Session(supported=False)], "unsupported"),
    ([Session(accepted=False)], "refused"),
])
def test_refusal_missing_and_ambiguous_sessions_never_redirect(sessions, outcome):
    code, records = execute(Manager(sessions), arguments("play", "fixture"))
    assert code == 2
    assert next(r for r in records if r["event"] == "command")["outcome"] == outcome
    assert sum(len(s.calls) for s in sessions) == int(outcome == "refused")


def test_provider_errors_do_not_leak_content_and_other_sessions_are_read():
    error = OSError("PRIVATE_TRACK from provider")
    error.winerror = -2147024891
    bad, good = Session("bad", error=error), Session("good")
    code, records = execute(Manager([bad, good]))
    assert code == 1 and "PRIVATE" not in json.dumps(records)
    rows = next(r for r in records if r["event"] == "snapshot")["sessions"]
    assert rows[0]["hresult"] == "0x80070005"
    assert rows[1]["title_present"]
    assert not bad.handlers and not good.handlers


def test_events_cross_threads_rebind_sessions_and_ignore_late_callbacks():
    async def scenario():
        first, second = Session("one"), Session("two")
        manager = Manager([first])
        records = []
        instance = probe.Probe(manager, lambda event, **fields: records.append({"event": event, **fields}))
        instance.start()
        await instance.snapshot()
        stale_callback = next(iter(first.handlers.values()))[1]
        manager.sessions = [second]
        thread = threading.Thread(target=lambda: manager.fire("sessions_changed"))
        thread.start()
        thread.join(timeout=1)
        await instance.watch(0.03)
        assert not first.handlers and second.handlers
        assert records[-1]["sessions"][0]["source"] == "two"
        assert any(r["event"] == "changed" for r in records)
        instance.close()
        before = list(records)
        stale_callback(first, None)
        await asyncio.sleep(0)
        assert records == before
        assert not manager.handlers and not second.handlers
        assert not first.calls and not second.calls
    asyncio.run(scenario())


def test_timeout_cancels_even_when_native_acknowledgement_never_arrives():
    async def scenario():
        cancellations = []
        async def unresponsive():
            try:
                await asyncio.Future()
            except asyncio.CancelledError:
                cancellations.append(1)
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    cancellations.append(2)
                    raise
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(probe.bounded(unresponsive(), 0.01), 1)
        assert cancellations == [1, 2]
        assert len(asyncio.all_tasks()) == 1
    asyncio.run(scenario())


def test_cancelling_probe_cancels_inflight_operation():
    async def scenario():
        started, stopped = asyncio.Event(), asyncio.Event()
        async def native():
            started.set()
            try:
                await asyncio.Future()
            finally:
                stopped.set()
        pending = asyncio.create_task(probe.bounded(native(), 10))
        await started.wait()
        pending.cancel()
        with pytest.raises(asyncio.CancelledError):
            await pending
        assert stopped.is_set() and len(asyncio.all_tasks()) == 1
    asyncio.run(scenario())


def test_cancellation_command_explicitly_calls_native_cancel():
    class Operation:
        cancelled = False
        def cancel(self):
            self.cancelled = True
        def __await__(self):
            async def finish():
                assert self.cancelled
                raise asyncio.CancelledError()
            return finish().__await__()
    operation, records = Operation(), []
    code = asyncio.run(probe.execute(arguments("cancel"), lambda event, **kw: records.append((event, kw)),
                                    lambda: operation))
    assert code == 0 and operation.cancelled
    assert next(fields for event, fields in records if event == "cancel_result")["outcome"] == "cancelled"


@pytest.mark.parametrize("status,expected", [("CANCELED", 0), ("ERROR", 1), ("COMPLETED", 1)])
def test_native_cancel_status_is_required_to_classify_get_results_error(status, expected):
    class Operation:
        def cancel(self):
            pass
        def __await__(self):
            async def finish():
                error = OSError("PRIVATE_PROVIDER_TEXT")
                error.winerror = -2147483634
                raise error
            return finish().__await__()
    operation, records = Operation(), []
    operation.status = SimpleNamespace(name=status)
    code = asyncio.run(probe.execute(arguments("cancel"), lambda event, **kw: records.append({"event": event, **kw}),
                                    lambda: operation))
    assert code == expected and "PRIVATE" not in json.dumps(records)
    row = next(r for r in records if r["event"] == "cancel_result")
    assert row["outcome"] == ("cancelled" if status == "CANCELED" else "error")


def test_unsubscribe_failure_is_not_reported_as_clean_success():
    manager = Manager()
    manager.remove_sessions_changed = lambda token: (_ for _ in ()).throw(OSError("PRIVATE"))
    code, records = execute(manager)
    assert code == 1 and "PRIVATE" not in json.dumps(records)
    assert records[-1]["cleanup_errors"] == records[-1]["subscriptions_remaining"] == 1


def test_partial_subscription_failure_still_unsubscribes_manager():
    manager = Manager()
    manager.add_current_session_changed = lambda callback: (_ for _ in ()).throw(OSError("PRIVATE"))
    code, records = execute(manager)
    assert code == 1 and not manager.handlers
    assert "PRIVATE" not in json.dumps(records)


def test_data_directory_is_exclusive_and_existing_evidence_is_preserved(tmp_path):
    directory = tmp_path / "evidence"
    evidence = probe.Evidence(directory)
    evidence("test", state="PAUSED")
    evidence.close()
    before = (directory / "events.jsonl").read_bytes()
    assert probe.main(["--data-dir", str(directory)]) == 1
    assert (directory / "events.jsonl").read_bytes() == before
    evidence("late_callback")
    assert (directory / "events.jsonl").read_bytes() == before


def test_async_callback_failure_is_redacted_and_fails_the_probe():
    records = []
    async def request():
        asyncio.get_running_loop().call_exception_handler({
            "message": "PRIVATE_TRACK", "exception": ValueError("PRIVATE_ARTIST")})
        return Manager()
    code = asyncio.run(probe.execute(arguments(), lambda event, **kw: records.append({"event": event, **kw}), request))
    assert code == 1 and "PRIVATE" not in json.dumps(records)
    assert any(r["event"] == "async_error" for r in records)


@pytest.mark.parametrize("action", probe.COMMANDS)
def test_playback_requires_explicit_target(action):
    with pytest.raises(SystemExit) as error:
        probe.main([action])
    assert error.value.code == 2
