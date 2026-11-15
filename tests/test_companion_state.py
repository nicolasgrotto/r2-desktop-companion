from copy import deepcopy
import json

import pytest
from PySide6.QtTest import QSignalSpy, QTest

from r2_companion.core.config import FutureSchemaError, Settings
from r2_companion.services.companion_state import MAX_BYTES, CompanionStateStore, default_document, validate_document
from r2_companion.services.storage import ConfigStore


@pytest.fixture
def make_store(qapp, tmp_path):
    opened = []

    def create(directory=None, *, read_only=False, acquire=True):
        owner = ConfigStore(directory or tmp_path)
        owner.read_only = read_only
        if acquire:
            assert owner.acquire()
        owner.load()
        store = CompanionStateStore(owner)
        opened.append((store, owner))
        return store

    yield create
    for store, owner in reversed(opened):
        store.close()
        owner.close()


def checkpoint():
    return {"id": "session-1", "phase": "focus", "duration_seconds": 1500,
            "remaining_seconds": 732.5, "task_id": "task-1"}


def test_defaults_are_independent_and_partial_schema_gets_safe_defaults():
    original = default_document()
    checked = validate_document({"schema_version": 1})
    assert checked == original
    checked["appearance"]["theme_overrides"]["r2_default"] = "vigia"
    assert default_document() == original
    assert original["presence"]["mode"] == "free"
    assert original["focus"]["session"] is None
    assert not original["media"]["enabled"] and not original["actions"]["global_shortcut_enabled"]


@pytest.mark.parametrize("group,key,value", [
    ("presence", "mode", "unknown"), ("presence", "mode", None),
    ("accessibility", "reduced_motion", 1), ("accessibility", "ui_scale", 125.0),
    ("accessibility", "ui_scale", True), ("accessibility", "ui_scale", 200),
    ("media", "enabled", "false"), ("onboarding", "dismissed", 0),
    ("actions", "global_shortcut_enabled", None),
    ("appearance", "theme_overrides", []),
    ("appearance", "theme_overrides", {"r2_default": "../vigia"}),
    ("appearance", "theme_overrides", {"R2": "vigia"}),
    ("appearance", "theme_overrides", {"r2_default": None}),
    ("appearance", "theme_overrides", {f"droid_{i}": "vigia" for i in range(101)}),
    ("focus", "session", []), ("focus", "session", {}),
])
def test_invalid_known_preferences_rejected(group, key, value):
    data = default_document()
    data[group][key] = value
    with pytest.raises(ValueError):
        validate_document(data)


@pytest.mark.parametrize("raw", [None, [], {}, {"schema_version": True}, {"schema_version": 0},
                                  {"schema_version": 1, "presence": []},
                                  {"schema_version": 1, "extension": float("nan")},
                                  {"schema_version": 1, "extension": {1: "coerced key"}},
                                  {"schema_version": 1, "extension": (1, 2)}])
def test_invalid_documents_and_non_json_values_rejected(raw):
    with pytest.raises(ValueError):
        validate_document(raw)


@pytest.mark.parametrize("field,value", [
    ("id", ""), ("id", "bad\nreference"), ("phase", "running"),
    ("duration_seconds", 0), ("duration_seconds", 86401), ("duration_seconds", True),
    ("remaining_seconds", -1), ("remaining_seconds", 1501), ("remaining_seconds", float("inf")),
    ("task_id", "x" * 81),
])
def test_invalid_focus_checkpoint_rejected(field, value):
    data = default_document()
    data["focus"]["session"] = checkpoint() | {field: value}
    with pytest.raises(ValueError):
        validate_document(data)


def test_checkpoint_has_relative_time_and_retains_extension_fields():
    data = default_document()
    data["focus"]["session"] = checkpoint() | {"extension": {"format": 2}}
    checked = validate_document(data)
    assert checked["focus"]["session"] == data["focus"]["session"]
    assert "deadline" not in checked["focus"]["session"]
    data["focus"]["session"].pop("task_id")
    assert validate_document(data)["focus"]["session"]["task_id"] is None
    with pytest.raises(FutureSchemaError):
        validate_document({"schema_version": 2})


def test_missing_document_persists_defaults_using_only_owner_lock(make_store, tmp_path):
    store = make_store()
    lock = store.config_store.lock
    assert store.data == default_document() and store.dirty and store.timer.isActive()
    assert not store.path.exists()
    assert store.flush()
    assert json.loads(store.path.read_text()) == default_document()
    assert store.config_store.lock is lock and lock.isLocked()
    assert list(tmp_path.glob("*.lock")) == [tmp_path / "companion.lock"]
    assert not (tmp_path / "config.json").exists() and not (tmp_path / "tools.json").exists()


def test_unknown_fields_survive_update_backup_and_snapshot_mutation(make_store, tmp_path):
    raw = default_document()
    raw["extension"] = {"private": [1, "texto", None]}
    raw["presence"]["future_option"] = {"a": True}
    raw["appearance"]["theme_overrides"] = {"r2_default": "unavailable_profile"}
    raw["focus"]["session"] = checkpoint() | {"future_checkpoint": 99}
    original = json.dumps(raw, ensure_ascii=False).encode()
    (tmp_path / "companion_state.json").write_bytes(original)
    store = make_store()
    assert not store.dirty and not store.timer.isActive()
    snapshot = store.data
    snapshot["extension"]["private"].clear()
    assert store.data == raw
    store.changed.connect(lambda data: data["presence"].update(mode="tampered"))
    assert store.update("presence", {"mode": "focus"}, immediate=True)
    saved = json.loads(store.path.read_text(encoding="utf-8"))
    assert saved == raw | {"presence": raw["presence"] | {"mode": "focus"}}
    assert store.backup.read_bytes() == original
    assert store.update("appearance", {"theme_overrides": {}}, immediate=True)
    assert store.data["extension"] == raw["extension"]
    assert store.data["appearance"]["theme_overrides"] == {}


@pytest.mark.parametrize("primary", [b'{broken PRIVATE_CONTENT', b'{"schema_version":1,"presence":false}', None])
def test_backup_recovery_never_rotates_invalid_primary_over_good_backup(make_store, tmp_path, primary):
    raw = default_document()
    raw["presence"]["mode"] = "presentation"
    backup = json.dumps(raw).encode()
    (tmp_path / "companion_state.backup.json").write_bytes(backup)
    if primary is not None:
        (tmp_path / "companion_state.json").write_bytes(primary)
    store = make_store()
    assert store.data == raw and store.notices and store.dirty
    assert store.flush()
    assert store.backup.read_bytes() == backup
    assert json.loads(store.path.read_bytes()) == raw
    assert "PRIVATE_CONTENT" not in str(store.notices)


@pytest.mark.parametrize("filename", ["companion_state.json", "companion_state.backup.json"])
def test_future_schema_is_preserved_byte_for_byte(make_store, tmp_path, filename):
    content = b' \n{ "schema_version": 99, "unknown": [1, 2, 3] }\n'
    path = tmp_path / filename
    path.write_bytes(content)
    store = make_store()
    assert store.read_only and store.notices and store.data == default_document()
    assert not store.config_store.read_only
    warning = QSignalSpy(store.warning)
    assert not store.update("media", {"enabled": True}, immediate=True)
    assert store.data["media"]["enabled"]
    assert warning.count() == 1 and path.read_bytes() == content
    store.close()
    assert path.read_bytes() == content and not store.timer.isActive()


@pytest.mark.parametrize("filename", ["companion_state.json", "companion_state.backup.json"])
def test_future_file_appearing_before_flush_is_not_overwritten(make_store, filename):
    store = make_store()
    assert store.flush()
    primary = store.path.read_bytes()
    future = b'{"schema_version":88,"private":"FUTURE_CONTENT"}'
    path = store.path.with_name(filename)
    path.write_bytes(future)
    store.update("presence", {"mode": "focus"})
    assert not store.flush() and store.read_only
    assert path.read_bytes() == future
    if path == store.backup:
        assert store.path.read_bytes() == primary


def test_oversized_file_and_oversized_update_cannot_destroy_existing_data(make_store, tmp_path):
    store = make_store(tmp_path / "writable")
    assert store.flush()
    before = store.path.read_bytes()
    data = store.data | {"extension": "é" * (MAX_BYTES // 2)}
    with pytest.raises(ValueError):
        store.apply(data)
    assert store.path.read_bytes() == before and not store.dirty
    large = tmp_path / "large"
    large.mkdir()
    path = large / "companion_state.json"
    contents = b'{"schema_version":99,"padding":"' + b'x' * MAX_BYTES + b'"}'
    path.write_bytes(contents)
    protected = make_store(large)
    assert protected.read_only
    assert not protected.update("presence", {"mode": "focus"}, immediate=True)
    assert path.read_bytes() == contents


@pytest.mark.parametrize("failure_target", ["primary", "backup"])
def test_atomic_failure_preserves_previous_files_and_can_retry(make_store, monkeypatch, caplog, failure_target):
    store = make_store()
    assert store.flush()
    before = store.path.read_bytes()
    writer = ConfigStore.atomic_write
    failed = store.path if failure_target == "primary" else store.backup

    def fail(path, contents):
        if path == failed:
            raise OSError("PRIVATE_ERROR_CONTENT")
        writer(path, contents)

    monkeypatch.setattr(ConfigStore, "atomic_write", staticmethod(fail))
    warning = QSignalSpy(store.warning)
    assert not store.update("accessibility", {"ui_scale": 125}, immediate=True)
    assert store.dirty and not store.timer.isActive() and warning.count() == 1
    assert store.path.read_bytes() == before
    if store.backup.exists():
        assert store.backup.read_bytes() == before
    assert "PRIVATE_ERROR_CONTENT" not in caplog.text
    monkeypatch.setattr(ConfigStore, "atomic_write", staticmethod(writer))
    assert store.flush() and not store.dirty
    assert json.loads(store.path.read_bytes())["accessibility"]["ui_scale"] == 125


@pytest.mark.parametrize("mode", ["read_only", "no_lock", "released_lock"])
def test_owner_controls_write_permission_without_a_second_lock(make_store, mode):
    store = make_store(read_only=mode == "read_only", acquire=mode != "no_lock")
    if mode == "released_lock":
        store.config_store.close()
    assert store.read_only
    assert not store.update("presence", {"mode": "focus"}, immediate=True)
    assert not store.path.exists() and not store.backup.exists()


def test_debounce_checkpoint_and_close_flush_without_late_writes(make_store, monkeypatch):
    store = make_store()
    store.timer.setInterval(25)
    writes = []
    writer = ConfigStore.atomic_write
    monkeypatch.setattr(ConfigStore, "atomic_write", staticmethod(lambda path, data: (writes.append(path), writer(path, data))[-1]))
    saved = QSignalSpy(store.saved)
    store.update("accessibility", {"ui_scale": 125})
    store.update("accessibility", {"ui_scale": 150})
    assert not store.path.exists()
    QTest.qWait(80)
    assert writes.count(store.path) == saved.count() == 1
    assert store.data["accessibility"]["ui_scale"] == 150
    assert store.update("focus", {"session": checkpoint()}, immediate=True)
    assert not store.timer.isActive()
    store.update("onboarding", {"dismissed": True})
    assert store.close()
    count = len(writes)
    QTest.qWait(80)
    assert len(writes) == count and not store.timer.isActive()
    assert json.loads(store.path.read_bytes())["onboarding"]["dismissed"]
    with pytest.raises(RuntimeError):
        store.update("media", {"enabled": True})


def test_rejected_update_preserves_memory_and_pending_valid_changes(make_store):
    store = make_store()
    store.update("presence", {"mode": "focus"})
    before = store.data
    with pytest.raises(ValueError):
        store.update("accessibility", {"ui_scale": 999})
    with pytest.raises(ValueError):
        store.update("schema_version", {})
    assert store.data == before and store.dirty
    assert store.flush()


def test_legacy_round_trip_and_restart_preserve_complementary_and_tool_bytes(make_store, tmp_path):
    legacy = ConfigStore(tmp_path)
    assert legacy.acquire()
    legacy.apply(Settings(visual_scale=128))
    assert legacy.flush()
    legacy.close()
    config_bytes = (tmp_path / "config.json").read_bytes()
    tools = tmp_path / "tools.json"
    tools.write_bytes(b'{"schema_version":1,"tasks":[],"notes":[]}')
    tool_bytes = tools.read_bytes()
    store = make_store()
    store.update("appearance", {"theme_overrides": {"r2_default": "vigia"}})
    assert store.close()
    state_bytes = store.path.read_bytes()
    assert (tmp_path / "config.json").read_bytes() == config_bytes and tools.read_bytes() == tool_bytes
    store.config_store.close()
    old = ConfigStore(tmp_path)
    assert old.acquire()
    old.load()
    settings = Settings.parse(old.settings.to_dict())
    settings.visual_scale = 192
    old.apply(settings)
    assert old.flush()
    old.close()
    assert store.path.read_bytes() == state_bytes and tools.read_bytes() == tool_bytes
    restored = make_store()
    assert restored.data["appearance"]["theme_overrides"] == {"r2_default": "vigia"}
    assert restored.config_store.settings.visual_scale == 192


def test_corrupt_documents_fall_back_without_touching_legacy_files(make_store, tmp_path):
    (tmp_path / "companion_state.json").write_bytes(b'PRIVATE_INVALID')
    (tmp_path / "companion_state.backup.json").write_bytes(b'PRIVATE_BACKUP')
    tools = tmp_path / "tools.json"
    tools.write_bytes(b'legacy tools bytes')
    store = make_store()
    assert store.data == default_document() and len(store.notices) == 2
    assert "PRIVATE" not in str(store.notices)
    assert store.flush()
    assert tools.read_bytes() == b'legacy tools bytes'


@pytest.mark.parametrize("stage", ["load", "flush"])
def test_unreadable_file_is_preserved_even_when_backup_is_valid(make_store, tmp_path, monkeypatch, stage):
    original = b'{"schema_version":99,"private":"UNREADABLE_CONTENT"}'
    primary = tmp_path / "companion_state.json"
    backup = tmp_path / "companion_state.backup.json"
    backup_bytes = json.dumps(default_document()).encode()
    backup.write_bytes(backup_bytes)
    reader = CompanionStateStore._read

    def denied(path):
        if path == primary:
            raise PermissionError("PRIVATE_PERMISSION_ERROR")
        return reader(path)

    if stage == "load":
        primary.write_bytes(original)
        monkeypatch.setattr(CompanionStateStore, "_read", staticmethod(denied))
        store = make_store()
        assert store.read_only and store.data == default_document()
        assert "PRIVATE" not in str(store.notices)
    else:
        store = make_store()
        primary.write_bytes(original)
        monkeypatch.setattr(CompanionStateStore, "_read", staticmethod(denied))
    assert not store.update("presence", {"mode": "focus"}, immediate=True)
    assert primary.read_bytes() == original and backup.read_bytes() == backup_bytes


def test_future_legacy_config_makes_complementary_state_read_only(make_store, tmp_path):
    legacy = b'{"schema_version":99,"extension":"legacy future"}'
    state = json.dumps(default_document()).encode()
    (tmp_path / "config.json").write_bytes(legacy)
    (tmp_path / "companion_state.json").write_bytes(state)
    store = make_store()
    assert store.config_store.read_only and store.read_only
    assert not store.update("media", {"enabled": True}, immediate=True)
    assert store.path.read_bytes() == state
    assert store.config_store.path.read_bytes() == legacy
