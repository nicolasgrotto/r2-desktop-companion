import json
from pathlib import Path
import subprocess
import sys

from PySide6.QtTest import QSignalSpy, QTest

from r2_companion.app import ASSETS
from r2_companion.droids.themes import PersistedThemeWatcher, theme_manager
from r2_companion.services.companion_state import CompanionStateStore
from r2_companion.services.storage import ConfigStore
from r2_companion.ui.updates import UpdateCenter


def wait_for(predicate):
    for _ in range(200):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate()


def save(directory, identifier):
    ConfigStore.atomic_write(directory / "config.json", json.dumps({"active_droid": identifier}).encode())


def test_theme_events_handle_repeated_atomic_replacements_from_another_process(qapp, tmp_path):
    watcher = PersistedThemeWatcher(tmp_path, ASSETS)
    changes = QSignalSpy(watcher.profile_changed)
    try:
        for identifier in ("dark_astromech", "spherical_droid", "r2_default"):
            code = "import sys; from pathlib import Path; sys.path.insert(0,'src'); from r2_companion.services.storage import ConfigStore; ConfigStore.atomic_write(Path(sys.argv[1]),sys.argv[2].encode())"
            subprocess.run([sys.executable, "-c", code, str(tmp_path / "config.json"),
                            json.dumps({"active_droid": identifier})], check=True)
            wait_for(lambda: watcher.last_id == identifier)
            assert str(tmp_path) in watcher.watcher.directories()
            assert not watcher.watcher.files()
        assert changes.count() == 3
    finally:
        watcher.close()


def test_theme_watcher_does_not_poll_or_reread_unchanged_configuration(qapp, tmp_path, monkeypatch):
    save(tmp_path, "r2_default")
    watcher = PersistedThemeWatcher(tmp_path, ASSETS)
    reads = []
    read_text = Path.read_text
    def tracked(path, *args, **kwargs):
        if path == tmp_path / "config.json":
            reads.append(path)
        return read_text(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", tracked)
    try:
        QTest.qWait(900)
        assert not reads and not watcher.timer.isActive()
        ConfigStore.atomic_write(tmp_path / "tools.json", b"{}")
        QTest.qWait(100)
        assert not reads
        save(tmp_path, "dark_astromech")
        wait_for(lambda: watcher.last_id == "dark_astromech")
        assert len(reads) == 1
    finally:
        watcher.close()


def test_theme_watcher_recovers_after_corruption_deletion_and_recreation(qapp, tmp_path):
    save(tmp_path, "r2_default")
    watcher = PersistedThemeWatcher(tmp_path, ASSETS)
    try:
        ConfigStore.atomic_write(tmp_path / "config.json", b"{broken")
        QTest.qWait(100)
        assert watcher.last_id == "r2_default"
        (tmp_path / "config.json").unlink()
        QTest.qWait(100)
        save(tmp_path, "spherical_droid")
        wait_for(lambda: watcher.last_id == "spherical_droid")
    finally:
        watcher.close()


def test_theme_watcher_handles_directory_created_after_startup(qapp, tmp_path):
    directory = tmp_path / "later"
    watcher = PersistedThemeWatcher(directory, ASSETS)
    try:
        directory.mkdir()
        save(directory, "dark_astromech")
        wait_for(lambda: watcher.last_id == "dark_astromech")
        assert watcher.watcher.directories() == [str(directory)]
    finally:
        watcher.close()


def test_closing_theme_watcher_removes_notifications(qapp, tmp_path):
    save(tmp_path, "r2_default")
    watcher = PersistedThemeWatcher(tmp_path, ASSETS)
    watcher.close()
    save(tmp_path, "dark_astromech")
    QTest.qWait(100)
    assert watcher.last_id == "r2_default"
    assert not watcher.timer.isActive()
    assert not watcher.watcher.files() and not watcher.watcher.directories()


def test_theme_watcher_does_not_lock_config_during_repeated_character_changes(qapp, tmp_path):
    watcher = PersistedThemeWatcher(tmp_path, ASSETS)
    try:
        for identifier in ("dark_astromech", "r2_default", "spherical_droid") * 5:
            save(tmp_path, identifier)
            wait_for(lambda: watcher.last_id == identifier)
            assert not watcher.watcher.files()
    finally:
        watcher.close()


def state_for(provider, scale=100, schema=1):
    return json.dumps({"schema_version": schema, "accessibility": {"ui_scale": scale},
                       "appearance": {"theme_overrides": {"r2_default": provider}}}).encode()


def test_theme_watcher_observes_only_new_state_and_separates_identity(qapp, tmp_path, monkeypatch):
    save(tmp_path, "r2_default")
    manager = theme_manager()
    previous = manager.active
    watcher = PersistedThemeWatcher(tmp_path, ASSETS)
    changes = QSignalSpy(manager.changed)
    identities = QSignalSpy(watcher.profile_changed)
    preferences = QSignalSpy(watcher.accessibility_changed)
    path = tmp_path / "companion_state.json"
    reads = []
    read = CompanionStateStore.read_document_file

    def tracked(path):
        reads.append(path)
        return read(path)

    monkeypatch.setattr(CompanionStateStore, "read_document_file", staticmethod(tracked))
    try:
        code = ("import sys; from pathlib import Path; sys.path.insert(0,'src'); "
                "from r2_companion.services.storage import ConfigStore; "
                "ConfigStore.atomic_write(Path(sys.argv[1]),sys.argv[2].encode())")
        subprocess.run([sys.executable, "-c", code, str(path), state_for("vigia", 125).decode()], check=True)
        wait_for(lambda: manager.active == watcher.registry.get("vigia").theme)
        assert watcher.last_id == "r2_default" and identities.count() == 0
        assert changes.count() == preferences.count() == 1 and reads == [path]
        ConfigStore.atomic_write(tmp_path / "companion_state.backup.json", state_for("pico"))
        ConfigStore.atomic_write(tmp_path / "tools.json", b"{}")
        QTest.qWait(150)
        assert reads == [path] and changes.count() == 1 and not watcher.timer.isActive()
        watcher.close()
        ConfigStore.atomic_write(path, state_for("lumo"))
        QTest.qWait(100)
        assert reads == [path] and changes.count() == 1 and preferences.count() == 1
    finally:
        watcher.close()
        manager.apply(previous)


def test_theme_watcher_resolves_backup_corruption_and_future_state(qapp, tmp_path):
    manager = theme_manager()
    previous = manager.active
    save(tmp_path, "r2_default")
    path = tmp_path / "companion_state.json"
    backup = tmp_path / "companion_state.backup.json"
    ConfigStore.atomic_write(path, b"{broken")
    ConfigStore.atomic_write(backup, state_for("vigia"))
    watcher = PersistedThemeWatcher(tmp_path, ASSETS)
    try:
        assert manager.active == watcher.registry.get("vigia").theme
        ConfigStore.atomic_write(path, state_for("unavailable"))
        wait_for(lambda: manager.active == watcher.profile.theme)
        assert json.loads(path.read_text())["appearance"]["theme_overrides"]["r2_default"] == "unavailable"
        path.unlink()
        wait_for(lambda: manager.active == watcher.registry.get("vigia").theme)
        future = state_for("lumo", schema=99)
        ConfigStore.atomic_write(path, future)
        wait_for(lambda: manager.active == watcher.profile.theme)
        assert path.read_bytes() == future
    finally:
        watcher.close()
        manager.apply(previous)


def test_open_update_center_restyles_its_controls_without_reloading_the_droid(qapp, tmp_path):
    manager = theme_manager()
    previous, original_scale = manager.active, manager.ui_scale
    save(tmp_path, "r2_default")
    center = UpdateCenter(tmp_path, auto_check=False)
    center.show()
    try:
        clips = center.animation.clips
        previous_style = center.styleSheet()
        ConfigStore.atomic_write(tmp_path / "companion_state.json", state_for("vigia", 150))
        expected = center.theme_watcher.registry.get("vigia").theme
        wait_for(lambda: manager.active == expected and manager.ui_scale == 150)
        assert center.styleSheet() != previous_style and expected.colors["hero"] in center.styleSheet()
        assert center.animation.clips is clips and center.theme_watcher.profile.id == "r2_default"
    finally:
        center.close()
        manager.apply(previous)
        manager.set_ui_scale(original_scale)
