import json
import threading

from r2_companion.services.navigation_trace import NavigationTrace


def read_records(directory):
    return [json.loads(line) for path in sorted(directory.glob("navigation.jsonl*"))
            for line in path.read_text(encoding="utf-8").splitlines()]


def test_navigation_trace_correlates_callbacks_without_recording_exception_values(tmp_path):
    trace = NavigationTrace(tmp_path)
    attempt = trace.begin()
    trace.record("click_received")
    trace.record("input_received", detail=True)
    try:
        raise ValueError("private user content")
    except ValueError as error:
        trace.record("callback_failed", error=error)
    trace.close()
    trace.close()
    records = read_records(tmp_path)
    assert [r["event"] for r in records] == ["click_received", "callback_failed", "trace_closed"]
    assert all(r["attempt"] == attempt and r["pid"] and r["version"] for r in records)
    assert [r["monotonic_ns"] for r in records] == sorted(r["monotonic_ns"] for r in records)
    assert records[1]["exception"] == "ValueError" and records[1]["frames"]
    assert "private user content" not in (tmp_path / "navigation.jsonl").read_text()
    assert not trace.worker.is_alive()


def test_navigation_trace_rotates_and_retains_essential_events(tmp_path):
    trace = NavigationTrace(tmp_path, verbose=True)
    trace.handler.maxBytes = 1024
    for _ in range(100):
        trace.begin()
        trace.record("input_received", detail=True)
    trace.record("callback_failed", error=RuntimeError())
    trace.close()
    paths = list(tmp_path.glob("navigation.jsonl*"))
    assert 1 < len(paths) <= 4
    assert any(r["event"] == "callback_failed" for r in read_records(tmp_path))


def test_slow_diagnostic_storage_does_not_block_the_ui_producer(tmp_path, monkeypatch):
    trace = NavigationTrace(tmp_path, verbose=True)
    entered = threading.Event()
    release = threading.Event()
    original = trace.handler.emit

    def delayed(record):
        entered.set()
        assert release.wait(5)
        original(record)

    monkeypatch.setattr(trace.handler, "emit", delayed)
    try:
        trace.record("first")
        assert entered.wait(2)
        for _ in range(1100):
            trace.record("input_received", detail=True)
        trace.record("callback_failed", error=RuntimeError())
        assert trace.omitted == 0
        assert trace.queue.qsize() <= 1025
    finally:
        release.set()
        trace.close()
    records = read_records(tmp_path)
    assert any(r.get("omitted_detail_records", 0) for r in records)
    assert any(r["event"] == "callback_failed" for r in records)
