from copy import deepcopy
import json
import sys
from types import SimpleNamespace

import pytest
from PySide6.QtTest import QTest

from r2_companion import __version__
from r2_companion.app import Companion
from r2_companion.services.storage import ConfigStore
from r2_companion.services.updates import confirm_startup, independent_environment, runtime_identity, UpdateService
from r2_companion.ui.updates import UpdateCenter
from test_navigation_v111 import click_item


def frozen_install(tmp_path, monkeypatch, version=__version__):
    installed = tmp_path / "installed"
    installed.mkdir()
    executable = installed / "R2Companion.exe"
    executable.touch()
    (installed / "release.json").write_text(json.dumps({
        "schema_version": 1, "repository": "owner/companion", "version": version}))
    bundle = installed / "_internal"
    bundle.mkdir()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(sys, "_MEIPASS", str(bundle), raising=False)
    return installed, bundle


def test_independent_launch_resets_bootloader_and_bundle_paths_without_mutating_parent(tmp_path, monkeypatch):
    installed, bundle = frozen_install(tmp_path, monkeypatch)
    monkeypatch.setenv("QT_PLUGIN_PATH", str(bundle / "PySide6/plugins"))
    monkeypatch.setenv("QML2_IMPORT_PATH", str(bundle / "PySide6/qml"))
    monkeypatch.setenv("PATH", str(bundle) + ";C:\\Windows\\System32;" + str(bundle / "PySide6"))
    monkeypatch.setenv("_PYI_ARCHIVE_FILE", str(installed / "R2Companion.exe"))
    environment = independent_environment()
    assert environment["PYINSTALLER_RESET_ENVIRONMENT"] == "1"
    assert environment["PATH"] == "C:\\Windows\\System32"
    assert "QT_PLUGIN_PATH" not in environment and "QML2_IMPORT_PATH" not in environment
    assert "QT_PLUGIN_PATH" in __import__("os").environ
    calls = []
    service = UpdateService(tmp_path / "data", process_factory=lambda *a, **kw: calls.append(kw) or SimpleNamespace(poll=lambda: 0))
    service.launch_center()
    assert calls[0]["env"] == environment


@pytest.mark.parametrize("mismatch", ["version", "bundle"])
def test_loaded_runtime_must_match_installed_version_and_bundle(tmp_path, monkeypatch, mismatch):
    installed, bundle = frozen_install(tmp_path, monkeypatch, "1.0.0" if mismatch == "version" else __version__)
    if mismatch == "bundle":
        monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "old-runtime/_internal"))
    with pytest.raises(ValueError, match="versão carregada"):
        runtime_identity()


def test_startup_confirmation_is_atomic_unique_and_identifies_running_code(qapp, tmp_path):
    updates = tmp_path / "updates"
    updates.mkdir()
    path = updates / ("startup-" + "a" * 32 + ".json")
    confirm_startup(path, tmp_path)
    value = json.loads(path.read_text())
    assert value["initialized"] and value["version"] == __version__
    assert value["data_directory"] == str(tmp_path.resolve())
    for invalid in (path, updates / "status.json", tmp_path / ("startup-" + "b" * 32 + ".json")):
        with pytest.raises(ValueError):
            confirm_startup(invalid, tmp_path)


def test_update_lifecycle_preserves_all_droids_and_rebuilds_working_navigation(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr("r2_companion.app.foreground_fullscreen", lambda hwnd: False)
    store = ConfigStore(tmp_path)
    assert store.acquire()
    previous = Companion(qapp, store)
    current = None
    try:
        for identifier in previous.droids.profiles:
            assert previous.equip_droid(identifier)
            draft = deepcopy(store.settings)
            draft.audio.volume = {"r2_default": 0.17, "dark_astromech": 0.29, "spherical_droid": 0.41}[identifier]
            store.apply(draft)
        previous.productivity.add_task("Preservar durante atualização")
        note = previous.productivity.add_note()
        previous.productivity.edit_note(note, "Antes", "Sem perder dados")
        preferences = deepcopy(store.settings.droid_preferences)
        tools_data = deepcopy(previous.productivity.data)
        previous.show_tools_page("diagnostics")
        previous.tools.diagnostics_page.start()
        previous.show_garage()
        previous.show_audio_center()
        previous.show_settings()
        previous.window.close()
        assert previous.closed and not store.lock.isLocked()
        assert not previous.tools.clock_timer.isActive() and not previous.tools.diagnostics_page.timer.isActive()
        assert not previous.animation.timer.isActive() and not previous.audio.preview_bank
        renewed = ConfigStore(tmp_path)
        assert renewed.acquire()
        renewed.load()
        current = Companion(qapp, renewed)
        assert renewed.settings.droid_preferences == preferences
        assert current.productivity.data == tools_data
        (tmp_path / "updates").mkdir()
        confirm_startup(tmp_path / "updates" / ("startup-" + "c" * 32 + ".json"), tmp_path)
        QTest.qWait(80)
        for page in current.tools.pages:
            current.radial.popup_near(current.window)
            if page not in {"minigames", "diagnostics"}:
                click_item(current, "tools")
            click_item(current, page)
            assert current.tools.isVisible() and current.tools.tabs.currentWidget() is current.tools.pages[page]
            current.tools.close()
            assert not current.tools.clock_timer.isActive() and not current.monitor.timer.isActive()
    finally:
        if current is not None:
            current.shutdown()
        previous.shutdown()


def test_installer_exit_without_terminal_status_cannot_announce_success(qapp, tmp_path):
    dialog = UpdateCenter(tmp_path)
    dialog.startup.stop()
    dialog.install = tmp_path
    (tmp_path / "release.json").write_text(json.dumps({
        "schema_version": 1, "repository": "owner/companion", "version": __version__}))
    dialog.status_path = tmp_path / "status.json"
    dialog.child = SimpleNamespace(poll=lambda: 0, returncode=0)
    try:
        dialog.poll_install()
        assert dialog.state == "error" and "sem confirmar" in dialog.detail.text()
    finally:
        dialog.close()
