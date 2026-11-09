from copy import deepcopy
import json

import pytest

from r2_companion.core.config import FutureSchemaError, Settings, Shortcut, Target
from r2_companion.services.storage import ConfigStore


def test_config_defaults_and_targets_round_trip():
    settings = Settings.parse({})
    settings.applications = [Target("one", "Editor", r"C:\Tools\editor.exe", "app")]
    settings.locations = [Target("two", "Pasta", r"C:\Users", "folder")]
    settings.shortcuts = [Shortcut("alias", "Meu editor", "one")]
    assert Settings.parse(json.loads(json.dumps(settings.to_dict()))) == settings


@pytest.mark.parametrize("change", [
    {"window": {"x": float("nan")}}, {"window": {"u": -1}},
    {"window": {"v": float("inf")}}, {"visual_scale": 10000},
    {"sound_enabled": "false"}, {"timer_seconds": 0}, {"schema_version": True},
    {"behavior": {"movement": 1}}, {"behavior": {"sleep_seconds": 0}},
    {"behavior": {"frequency": "unbounded"}}, {"applications": [None]},
    {"applications": [{"id": "x", "label": "bad\nname", "path": "path", "kind": "app"}]},
    {"shortcuts": [{"id": "a", "label": "Alias", "target_id": "missing"}]},
    {"locations": {}}, {"window": "no"}, {"schema_version": 0},
])
def test_invalid_configuration_rejected(change):
    with pytest.raises(ValueError):
        Settings.parse(change)


def test_duplicate_ids_rejected():
    item = {"id": "same", "label": "Target", "path": "path", "kind": "app"}
    with pytest.raises(ValueError):
        Settings.parse({"applications": [item, item]})


def test_future_schema_rejected():
    with pytest.raises(FutureSchemaError):
        Settings.parse({"schema_version": 42})


def test_persistence_backup_and_recovery(qapp, tmp_path):
    store = ConfigStore(tmp_path)
    assert store.acquire()
    first = Settings(visual_scale=128)
    store.apply(first)
    assert store.flush()
    second = Settings(visual_scale=192)
    store.apply(second)
    assert store.flush()
    assert json.loads(store.backup.read_text())["visual_scale"] == 128
    store.path.write_text("{broken", encoding="utf-8")
    recovered = ConfigStore(tmp_path)
    recovered.load()
    assert recovered.settings.visual_scale == 128
    assert (tmp_path / "config.corrupt.json").read_text() == "{broken"
    store.close()


def test_future_schema_preserved(qapp, tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"schema_version":99}', encoding="utf-8")
    store = ConfigStore(tmp_path)
    store.load()
    assert store.read_only
    store.apply(Settings(visual_scale=128))
    assert not store.flush()
    assert path.read_text() == '{"schema_version":99}'


def test_failed_atomic_save_preserves_old_file(qapp, tmp_path, monkeypatch):
    store = ConfigStore(tmp_path)
    store.apply(Settings(visual_scale=128))
    assert store.flush()
    old_bytes = store.path.read_bytes()
    actual_write = store.atomic_write
    def failing(path, contents):
        if path == store.path:
            raise OSError("disk full")
        actual_write(path, contents)
    monkeypatch.setattr(store, "atomic_write", failing)
    store.apply(Settings(visual_scale=192))
    assert not store.flush()
    assert store.path.read_bytes() == old_bytes
    assert json.loads(store.backup.read_text())["visual_scale"] == 128


def test_lock_prevents_second_writer(qapp, tmp_path):
    first, second = ConfigStore(tmp_path), ConfigStore(tmp_path)
    assert first.acquire()
    assert not second.acquire()
    first.close()
    assert second.acquire()
    second.close()


def test_load_oversized_config_uses_defaults(qapp, tmp_path):
    (tmp_path / "config.json").write_bytes(b" " * (1024 * 1024 + 1))
    store = ConfigStore(tmp_path)
    store.load()
    assert store.settings == Settings()
    assert store.notices
