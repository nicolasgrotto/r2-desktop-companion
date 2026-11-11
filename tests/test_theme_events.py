import json
from pathlib import Path
import subprocess
import sys

from PySide6.QtTest import QSignalSpy, QTest

from r2_companion.app import ASSETS
from r2_companion.droids.themes import PersistedThemeWatcher
from r2_companion.services.storage import ConfigStore


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
            assert str(tmp_path / "config.json") in watcher.watcher.files()
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
