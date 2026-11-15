"""Isolated GSMTC investigation; never imported by the Companion application."""
import argparse
import asyncio
from datetime import datetime, timezone
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

COMMANDS = {
    "play": ("is_play_enabled", "try_play_async"),
    "pause": ("is_pause_enabled", "try_pause_async"),
    "previous": ("is_previous_enabled", "try_skip_previous_async"),
    "next": ("is_next_enabled", "try_skip_next_async"),
}


def error_fields(error):
    # Exception messages from providers can contain track metadata or paths.
    result = {"error_type": type(error).__name__}
    code = getattr(error, "winerror", None)
    if isinstance(code, int):
        result["hresult"] = f"0x{code & 0xffffffff:08X}"
    return result


class Evidence:
    def __init__(self, directory=None):
        self.handle = None
        self.closed = False
        if directory is not None:
            directory.mkdir(parents=True, exist_ok=False)
            self.handle = (directory / "events.jsonl").open("x", encoding="utf-8")

    def __call__(self, event, **fields):
        if self.closed:
            return
        line = json.dumps({"timestamp_utc": datetime.now(timezone.utc).isoformat(),
                           "event": event, **fields}, ensure_ascii=True)
        print(line, flush=True)
        if self.handle:
            self.handle.write(line + "\n")
            self.handle.flush()

    def close(self):
        self.closed = True
        if self.handle:
            self.handle.close()


async def bounded(operation, seconds):
    """Bound cancellation too: PyWinRT can await native acknowledgement once."""
    task = asyncio.ensure_future(operation)
    try:
        done, _ = await asyncio.wait({task}, timeout=seconds)
        if done:
            return task.result()
        raise TimeoutError()
    finally:
        if not task.done():
            task.cancel()
            done, _ = await asyncio.wait({task}, timeout=0.25)
            if not done:
                # PyWinRT's second cancellation abandons acknowledgement waiting.
                task.cancel()
                done, _ = await asyncio.wait({task}, timeout=0.25)
            if not done:
                raise RuntimeError("operation_did_not_cancel")
        if task.done() and not task.cancelled():
            task.exception()  # Consume a late failure without logging provider text.


class Probe:
    def __init__(self, manager, emit, timeout=5):
        self.manager, self.emit, self.timeout = manager, emit, timeout
        self.loop = asyncio.get_running_loop()
        self.dirty = asyncio.Event()
        self.closed = False
        self.subscriptions = []
        self.session_subscriptions = []
        self.events = {}
        self.cleanup_errors = 0
        self.read_errors = 0

    def notify(self, event):
        if not self.closed:
            self.events[event] = self.events.get(event, 0) + 1
            self.dirty.set()

    def subscribe(self, owner, event, target):
        def callback(sender, args):
            # WinRT may deliver on arbitrary threads. Keep all state on asyncio.
            if not self.closed:
                try:
                    self.loop.call_soon_threadsafe(self.notify, event)
                except RuntimeError:
                    pass  # A callback already in flight after the loop closed.
        token = getattr(owner, "add_" + event)(callback)
        target.append((owner, event, token, callback))

    def unsubscribe(self, subscriptions):
        while subscriptions:
            owner, event, token, _ = subscriptions.pop()
            try:
                getattr(owner, "remove_" + event)(token)
            except Exception as error:
                self.cleanup_errors += 1
                self.emit("unsubscribe_failed", subscription=event, **error_fields(error))

    def start(self):
        for event in ("sessions_changed", "current_session_changed"):
            self.subscribe(self.manager, event, self.subscriptions)

    async def snapshot(self):
        # Rebind to the current native objects, including same-source replacements.
        self.unsubscribe(self.session_subscriptions)
        sessions = list(self.manager.get_sessions())
        current = self.manager.get_current_session()
        current_source = current.source_app_user_model_id if current is not None else None
        rows = []
        for session in sessions:
            row = {"source": session.source_app_user_model_id}
            try:
                for event in ("media_properties_changed", "playback_info_changed"):
                    self.subscribe(session, event, self.session_subscriptions)
                info = session.get_playback_info()
                row["state"] = info.playback_status.name
                row["capabilities"] = {name: bool(getattr(info.controls, control))
                                       for name, (control, _) in COMMANDS.items()}
                media = await bounded(session.try_get_media_properties_async(), self.timeout)
                # Content is read to prove the API, but never enters evidence.
                row["title_present"] = bool(media and media.title)
                row["artist_present"] = bool(media and media.artist)
            except Exception as error:
                self.read_errors += 1
                row.update(error_fields(error))
            rows.append(row)
        self.emit("snapshot", count=len(rows), current_source=current_source, sessions=rows)
        return rows

    async def command(self, action, source):
        matches = [s for s in self.manager.get_sessions() if s.source_app_user_model_id == source]
        if len(matches) != 1:
            self.emit("command", action=action, source=source,
                      outcome="session_missing" if not matches else "ambiguous_source")
            return False
        session = matches[0]  # Bind this command once; never redirect or retry.
        control, method = COMMANDS[action]
        if not getattr(session.get_playback_info().controls, control):
            self.emit("command", action=action, source=source, outcome="unsupported")
            return False
        accepted = await bounded(getattr(session, method)(), self.timeout)
        self.emit("command", action=action, source=source, outcome="accepted" if accepted else "refused")
        return bool(accepted)

    async def watch(self, seconds):
        deadline = time.monotonic() + seconds
        while (remaining := deadline - time.monotonic()) > 0:
            try:
                await asyncio.wait_for(self.dirty.wait(), remaining)
            except TimeoutError:
                break
            self.dirty.clear()
            events, self.events = self.events, {}
            self.emit("changed", counts=events)
            # A burst is coalesced; only one snapshot can be in flight.
            await self.snapshot()

    def close(self):
        self.closed = True
        self.unsubscribe(self.session_subscriptions)
        self.unsubscribe(self.subscriptions)
        self.manager = None
        self.emit("closed", subscriptions_remaining=self.cleanup_errors, cleanup_errors=self.cleanup_errors)


async def execute(args, emit, request_manager=None):
    probe = None
    result = 0
    loop = asyncio.get_running_loop()
    async_errors = []
    def async_error(loop, context):
        fields = error_fields(context.get("exception", RuntimeError()))
        async_errors.append(fields)
        emit("async_error", **fields)
    # This entrypoint owns its asyncio.run loop. Keep the sanitized handler
    # through loop shutdown, including abandoned native completion callbacks.
    loop.set_exception_handler(async_error)
    try:
        if request_manager is None:
            from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager
            request_manager = GlobalSystemMediaTransportControlsSessionManager.request_async
        if args.action == "cancel":
            operation = request_manager()
            diagnostic = {}
            # Explicit native cancellation, including the race with fast completion.
            operation.cancel()
            try:
                await bounded(operation, args.timeout)
                outcome = "completed_before_cancel"
            except asyncio.CancelledError:
                outcome = "cancelled"
            except Exception as error:
                # This provider/PyWinRT combination can call GetResults after
                # native cancellation, which raises E_ILLEGAL_METHOD_CALL.
                # Only the native terminal status proves cancellation; never
                # infer it from an HRESULT alone.
                if getattr(getattr(operation, "status", None), "name", None) != "CANCELED":
                    emit("cancel_result", outcome="error", **error_fields(error))
                    return 1
                outcome, diagnostic = "cancelled", error_fields(error)
            emit("cancel_result", outcome=outcome,
                 native_status=getattr(getattr(operation, "status", None), "name", None), **diagnostic)
            return 0
        manager = await bounded(request_manager(), args.timeout)
        probe = Probe(manager, emit, args.timeout)
        probe.start()
        await probe.snapshot()
        if args.action in COMMANDS:
            accepted = await probe.command(args.action, args.source)
            await probe.watch(args.seconds)
            result = 0 if accepted else 2
        elif args.action == "watch":
            await probe.watch(args.seconds)
    except Exception as error:
        emit("error", operation=args.action, **error_fields(error))
        result = 1
    finally:
        if probe is not None:
            probe.close()
        else:
            emit("closed", subscriptions_remaining=0, cleanup_errors=0)
    return 1 if async_errors or probe and (probe.read_errors or probe.cleanup_errors) else result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("snapshot", "watch", *COMMANDS, "cancel"), nargs="?", default="snapshot")
    parser.add_argument("--source", help="Exact source ID from snapshot; commands reject duplicate IDs")
    parser.add_argument("--seconds", type=float, default=5, help="Observation time after command, or watch duration")
    parser.add_argument("--timeout", type=float, default=5, help="Timeout per async call, plus up to 0.5 s cancellation")
    parser.add_argument("--data-dir", type=Path, help="New evidence directory; no metadata content is logged")
    args = parser.parse_args(argv)
    if not 0 <= args.seconds <= 300 or not 0 < args.timeout <= 30:
        parser.error("Use seconds 0..300 and timeout 0..30 (exclusive of zero)")
    if args.action in COMMANDS and not args.source:
        parser.error("Playback commands require an explicit --source")
    try:
        evidence = Evidence(args.data_dir)
    except OSError as error:
        print(json.dumps({"event": "evidence_unavailable", **error_fields(error)}))
        return 1
    try:
        versions = {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()
                    if d.metadata["Name"].lower().startswith("winrt-") or d.metadata["Name"] == "typing_extensions"}
        evidence("environment", python=platform.python_version(), architecture=platform.machine(),
                 windows=platform.platform(), packages=versions)
        return asyncio.run(execute(args, evidence))
    except KeyboardInterrupt:
        evidence("interrupted")
        return 130
    finally:
        evidence.close()


if __name__ == "__main__":
    raise SystemExit(main())
