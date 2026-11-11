import json
from pathlib import Path
from threading import Event
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from r2_companion.services.update_client import REPOSITORY, validate_release
from r2_companion.ui.updates import BUSY_STATES, UpdateCenter
from test_update_center import response, wait_for_worker


@pytest.fixture
def center(qapp, tmp_path):
    dialog = UpdateCenter(tmp_path)
    dialog.startup.stop()
    dialog.show()
    QTest.qWait(30)
    yield dialog
    dialog.handoff_timer.stop()
    dialog.closing = True
    dialog.close()


def wait_until(predicate):
    for _ in range(200):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate()


@pytest.mark.parametrize("state", sorted(BUSY_STATES))
def test_busy_states_keep_visible_feedback_and_reject_close_escape_and_duplicates(center, state):
    center.set_state(state, state, "Operação real em andamento")
    assert center.progress.isVisible() and center.isVisible()
    assert not center.action.isEnabled() and not center.later.isEnabled()
    center.act()
    center.check()
    center.download()
    assert center.state == state
    assert not center.close()
    QTest.keyClick(center, Qt.Key.Key_Escape)
    assert center.isVisible() and center.state == state


def test_check_disables_immediately_and_keeps_worker_running_after_close(center):
    release, _ = response()
    proceed = Event()
    calls = []
    def client(repository):
        calls.append(repository)
        proceed.wait(5)
        return validate_release(release, repository)
    center.client = client
    try:
        center.act()
        assert center.state == "checking" and not center.action.isEnabled()
        assert center.progress.minimum() == center.progress.maximum() == 0
        worker = center.worker
        center.act()
        center.close()
        assert center.isVisible() and center.worker is worker and not worker.isInterruptionRequested()
    finally:
        proceed.set()
        wait_for_worker(center)
    assert calls == [REPOSITORY] and center.state == "available" and center.action.isEnabled()


@pytest.mark.parametrize("total", [0, -1, 3000])
def test_download_progress_uses_real_bytes_or_indeterminate_indicator(center, total):
    center.set_state("download", "Baixando", "")
    center.download_progress(1200, total)
    if total > 0:
        assert center.progress.maximum() == total and center.progress.value() == 1200
        assert "%" in center.progress.text() and "de" in center.detail.text()
    else:
        assert center.progress.minimum() == center.progress.maximum() == 0
        assert "tamanho total indisponível" in center.detail.text()
        assert "de 0" not in center.detail.text()


def test_download_validation_and_preparation_are_reported_from_worker_events(center, tmp_path, monkeypatch):
    center.install = tmp_path / "install"
    center.directory = tmp_path / "data"
    raw, _ = response()
    center.checked(validate_release(raw, REPOSITORY))
    continue_download, continue_integrity = Event(), Event()
    calls, prepared = [], []
    def download(release, destination, progress, stage, cancelled):
        calls.append(destination)
        progress(1200, 3000)
        continue_download.wait(5)
        stage("integrity", "Verificando SHA-256")
        continue_integrity.wait(5)
        return destination
    monkeypatch.setattr("r2_companion.ui.updates.download_release", download)
    monkeypatch.setattr(center, "prepare_center", lambda: prepared.append(center.prepared))
    try:
        center.act()
        assert center.state == "download" and not center.action.isEnabled()
        assert "9.0.0" in center.package_label.text()
        center.act()
        wait_until(lambda: center.progress.value() == 1200)
        continue_download.set()
        wait_until(lambda: center.state == "integrity")
        assert center.progress.maximum() == 0 and center.isVisible()
    finally:
        continue_download.set()
        continue_integrity.set()
        wait_for_worker(center)
    assert len(calls) == 1 and prepared == calls and center.state == "preparing"


def test_preparation_copies_existing_install_async_and_reports_errors(center, tmp_path, monkeypatch):
    center.install = tmp_path / "installed"
    center.install.mkdir()
    (center.install / "R2Companion.exe").write_bytes(b"fixture")
    destinations = []
    monkeypatch.setattr(center, "spawn_center", lambda destination: destinations.append(destination))
    center.downloaded(tmp_path / "prepared")
    assert center.state == "preparing" and center.isVisible()
    wait_for_worker(center)
    assert (destinations[0] / "R2Companion.exe").read_bytes() == b"fixture"


def test_handoff_retains_original_until_successor_is_visible_and_acknowledged(center, tmp_path, monkeypatch):
    center.prepared = tmp_path / "prepared"
    center.prepared.mkdir()
    center.install = tmp_path / "installed"
    child = SimpleNamespace(pid=321, poll=lambda: None)
    commands = []
    monkeypatch.setattr("r2_companion.ui.updates.subprocess.Popen", lambda command, **kwargs: commands.append(command) or child)
    center.spawn_center(tmp_path / "copy")
    assert center.isVisible() and center.state == "handoff"
    center.poll_handoff()
    assert center.isVisible()
    center.handoff_file.write_text(json.dumps({"pid": 999, "visible": True}))
    center.poll_handoff()
    assert center.isVisible()
    center.handoff_file.write_text(json.dumps({"pid": 321, "visible": True}))
    center.poll_handoff()
    assert not center.isVisible() and center.handoff_file.with_suffix(".ack").is_file()
    assert "--update-ready-file" in commands[0] and not center.handoff_timer.isActive()


@pytest.mark.parametrize("failure", ["launch", "exit", "timeout"])
def test_failed_handoff_keeps_original_visible_and_allows_recovery(center, tmp_path, monkeypatch, failure):
    center.prepared = tmp_path
    center.install = tmp_path / "installed"
    def spawn(*args, **kwargs):
        if failure == "launch":
            raise OSError("Falha ao iniciar a central")
        return SimpleNamespace(pid=321, poll=lambda: 1 if failure == "exit" else None)
    monkeypatch.setattr("r2_companion.ui.updates.subprocess.Popen", spawn)
    center.spawn_center(tmp_path / "copy")
    if failure == "timeout":
        center.handoff_started -= 46
    if failure != "launch":
        center.poll_handoff()
    assert center.state == "error" and center.isVisible() and center.action.isEnabled()
    assert not center.handoff_timer.isActive()


def test_successor_waits_for_ack_before_installing(center, tmp_path, monkeypatch):
    center.ready_file = tmp_path / "ready.json"
    center.startup.timeout.disconnect()
    installs = []
    monkeypatch.setattr(center, "install_prepared", lambda path: installs.append(path))
    center.resume_install(tmp_path)
    center.startup.stop()
    assert center.ready_file.is_file() and not installs
    assert json.loads(center.ready_file.read_text())["visible"]
    center.ready_file.with_suffix(".ack").write_text("ready")
    center.resume_install(tmp_path)
    assert installs == [tmp_path]


@pytest.mark.parametrize("state", ["done", "restart_required", "error", "restarting"])
def test_installer_states_keep_honest_restart_completion_and_recovery(center, tmp_path, state):
    center.install = tmp_path / "installed"
    center.install.mkdir()
    (center.install / "release.json").write_text(json.dumps({"schema_version": 1, "version": "9.0.0", "repository": REPOSITORY}))
    raw, _ = response()
    center.release = validate_release(raw, REPOSITORY)
    center.status_path = tmp_path / "status.json"
    center.status_path.write_text(json.dumps({"state": state, "message": "Estado emitido pelo instalador"}))
    center.child = SimpleNamespace(poll=lambda: None if state == "restarting" else 1 if state == "error" else 0,
                                   returncode=1 if state == "error" else 0)
    center.poll_install()
    assert center.state == state and center.isVisible()
    assert center.action.isEnabled() == (state != "restarting")
    center.child = None


def test_installer_cannot_report_success_with_wrong_installed_version(center, tmp_path):
    center.install = tmp_path
    (tmp_path / "release.json").write_text(json.dumps({"schema_version": 1, "version": "1.0.0", "repository": REPOSITORY}))
    center.release = {"version": "9.0.0"}
    center.child = SimpleNamespace(poll=lambda: 0, returncode=0)
    center.status_path = tmp_path / "status.json"
    center.poll_install()
    assert center.state == "error" and "não corresponde" in center.detail.text()


def test_prepared_installer_identifies_package_and_retains_status_monitor(center, tmp_path, monkeypatch):
    raw, _ = response()
    prepared = tmp_path / "prepared"
    prepared.mkdir()
    (prepared / "candidate.json").write_text(json.dumps(raw))
    center.install = tmp_path / "install"
    commands = []
    child = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr("r2_companion.ui.updates.subprocess.Popen", lambda command, **kwargs: commands.append(command) or child)
    center.install_prepared(prepared)
    assert center.state == "installing" and center.poll.isActive()
    assert "9.0.0" in center.package_label.text()
    assert "-StatusPath" in commands[0] and "-PreparedDirectory" in commands[0]
    assert center.isVisible() and not center.later.isEnabled()
    center.child = None


def test_successor_readiness_requires_a_painted_exposed_window(center, tmp_path):
    center.ready_file = tmp_path / "visible-ready.json"
    center.hide()
    center.presented = False
    center.announce_ready()
    assert not center.ready_file.exists()
    center.show()
    QTest.qWait(50)
    center.announce_ready()
    assert center.ready_file.exists() and center.presented
    assert center.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
