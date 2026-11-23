from datetime import datetime
import json
import os
from threading import Event
from time import monotonic

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QFileDialog, QMessageBox

from r2_companion.core.config import FutureSchemaError, Settings
from r2_companion.features.data_transfer import DataTransfer, VALIDATORS
from r2_companion.features.productivity import ProductivityStore
from r2_companion.services.companion_state import CompanionStateStore
from r2_companion.services.storage import ConfigStore
from r2_companion.ui.data_transfer import DataPage
from test_context_v03 import pet


def wait_for_backups(page):
    deadline = monotonic() + 15
    while (page.tasks.busy or page.restoring) and monotonic() < deadline:
        QTest.qWait(20)
    assert not (page.tasks.busy or page.restoring), page.status.text()


@pytest.fixture
def transfer(qapp, tmp_path):
    config = ConfigStore(tmp_path)
    assert config.acquire()
    tools = ProductivityStore(tmp_path)
    state = CompanionStateStore(config)

    def restore_config(settings, persist):
        persist(settings)
        config.accept_restored(settings)

    result = DataTransfer(config, tools, state, restore_config)
    yield result
    tools.close()
    state.close()
    config.close()


def test_exports_valid_utf8_and_protects_internal_files(transfer, tmp_path, monkeypatch):
    tools = transfer.productivity
    tools.add_task("Revisar montagem")
    note = tools.add_note()
    tools.edit_note(note, "Projeto", "Primeira linha\nSegunda — 日本語")
    assert tools.flush()
    document = tmp_path / "export.json"
    text = tmp_path / "export.txt"
    transfer.export_tasks_and_notes(document)
    transfer.export_note(note, text)
    assert json.loads(document.read_text(encoding="utf-8")) == tools.data
    assert text.read_bytes() == "Primeira linha\nSegunda — 日本語".encode()
    original = tools.path.read_bytes()
    with pytest.raises(ValueError, match="arquivos internos"):
        transfer.export_tasks_and_notes(tools.path)
    assert tools.path.read_bytes() == original

    def deny(*_):
        raise PermissionError("Destino sem permissão")

    with monkeypatch.context() as patch:
        patch.setattr(ConfigStore, "atomic_write", deny)
        with pytest.raises(PermissionError):
            transfer.export_note(note, text)
    assert text.read_bytes() == "Primeira linha\nSegunda — 日本語".encode()


@pytest.mark.parametrize("collection,other", [("tasks", "notes"), ("notes", "tasks")])
def test_partial_tools_restore_keeps_live_other_collection(transfer, collection, other):
    tools = transfer.productivity
    task = tools.add_task("Backup")
    note = tools.add_note()
    tools.edit_note(note, "Backup", "Texto do backup")
    assert tools.flush()
    tools.set_done(task, True)
    tools.edit_note(note, "Atual", "Texto atual")
    assert tools.flush()
    tools.remove(other, note if other == "notes" else task)
    current = tools.data
    backup = transfer.inspect("tools")

    recovery = transfer.restore(backup, collection)

    assert tools.data[collection] == backup.data[collection]
    assert tools.data[other] == current[other] == []
    assert tools.undo_collection == other and not tools.dirty
    assert tools.read(tools.path) == tools.data
    assert tools.read(recovery) == current


def test_backup_inspection_enforces_schema_size_and_confirmed_contents(transfer, tmp_path):
    tools = transfer.productivity
    valid = b'{"schema_version":1,"tasks":[],"notes":[]}'
    limit = VALIDATORS["tools"][0]
    tools.backup.write_bytes(valid.ljust(limit))
    checked = transfer.inspect("tools")
    tools.backup.write_bytes(valid)
    with pytest.raises(ValueError, match="mudou"):
        transfer.restore(checked)
    for contents, error in ((b"broken", ValueError), (b'{"schema_version":99}', FutureSchemaError),
                            (valid.ljust(limit + 1), ValueError)):
        tools.backup.write_bytes(contents)
        with pytest.raises(error):
            transfer.inspect("tools")
        assert not tools.path.exists()
    tools.backup.write_bytes(valid)
    checked = transfer.inspect("tools")
    tools.path.write_bytes(b'{"schema_version":99}')
    with pytest.raises(FutureSchemaError):
        transfer.restore(checked)
    assert tools.path.read_bytes() == b'{"schema_version":99}'
    tools.path.write_bytes(valid)
    prepared = transfer.prepare_restore(checked)
    ConfigStore.atomic_write(tools.path, b'{"schema_version":99}')
    with pytest.raises(ValueError, match="dados atuais mudaram"):
        transfer.apply_restore(prepared)


def test_cancel_and_atomic_restore_failure_leave_current_data_and_backup(transfer, monkeypatch):
    tools = transfer.productivity
    tools.add_task("Anterior")
    assert tools.flush()
    tools.add_task("Atual")
    assert tools.flush()
    document, backup = tools.path.read_bytes(), tools.backup.read_bytes()
    page = DataPage(transfer)
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.No)
    page.refresh()
    wait_for_backups(page)
    choices = page.rows["tools"][1].menu().actions()
    assert [choice.text() for choice in choices] == ["Restaurar tarefas e notas", "Restaurar somente notas",
                                                     "Restaurar somente tarefas"]
    choices[0].trigger()
    wait_for_backups(page)
    assert page.status.text() == "Restauração cancelada."
    assert tools.path.read_bytes() == document and not transfer.recovery_path(tools).exists()

    checked = transfer.inspect("tools")
    writer = ConfigStore.atomic_write

    def fail_main(path, contents):
        if path == tools.path:
            raise OSError("Falha simulada")
        writer(path, contents)

    with monkeypatch.context() as patch:
        patch.setattr(ConfigStore, "atomic_write", fail_main)
        with pytest.raises(OSError, match="simulada"):
            transfer.restore(checked)
    assert tools.path.read_bytes() == document and tools.backup.read_bytes() == backup
    assert len(tools.data["tasks"]) == 2
    assert json.loads(transfer.recovery_path(tools).read_text(encoding="utf-8")) == tools.data


def test_data_page_shows_availability_and_respects_read_only(transfer):
    tools = transfer.productivity
    page = DataPage(transfer)
    page.refresh()
    wait_for_backups(page)
    assert not page.rows["tools"][1].isEnabled()
    tools.backup.write_bytes(b'{"schema_version":99}')
    page.refresh()
    wait_for_backups(page)
    assert "versão futura" in page.rows["tools"][0].text()
    tools.backup.write_bytes(b'{"schema_version":1,"tasks":[],"notes":[]}')
    tools.read_only = True
    page.refresh()
    wait_for_backups(page)
    assert not page.rows["tools"][1].isEnabled()
    assert "somente leitura" in page.rows["tools"][0].text()
    with pytest.raises(OSError, match="somente leitura"):
        transfer.restore(transfer.inspect("tools"))


def test_manual_backup_refresh_shows_dates_and_leaves_gui_responsive(transfer, monkeypatch):
    tools = transfer.productivity
    contents = b'{"schema_version":1,"tasks":[],"notes":[]}'
    tools.backup.write_bytes(contents)
    timestamp = 1_700_000_000
    os.utime(tools.backup, (timestamp, timestamp))
    inspect = transfer.inspect
    release = Event()

    def paused_inspect(group):
        if group == "tools":
            assert release.wait(5)
        return inspect(group)

    monkeypatch.setattr(transfer, "inspect", paused_inspect)
    page = DataPage(transfer)
    try:
        page.refresh_button.click()
        assert page.refresh_status.text() == "Consultando backups…"
        assert not page.refresh_button.isEnabled() and not page.rows["tools"][1].isEnabled()
        QTimer.singleShot(0, release.set)
        wait_for_backups(page)
        assert release.is_set()
        assert page.refresh_status.text().startswith("Estado dos backups atualizado em ")
        assert datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y às %H:%M:%S") in page.rows["tools"][0].text()
        assert page.refresh_button.isEnabled() and page.rows["tools"][1].isEnabled()
        assert tools.backup.read_bytes() == contents and tools.backup.stat().st_mtime == timestamp
    finally:
        release.set()
        page.tasks.close()


def test_restore_from_tools_updates_open_pages_and_equipped_droid(pet, tmp_path, monkeypatch):
    pet.show_tools_page("data")
    page = pet.tools.pages["data"]
    assert page.isVisible()
    wait_for_backups(page)
    result = tmp_path / "export.txt"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args: (str(result), ""))
    monkeypatch.setattr(QMessageBox, "question", lambda *args, **kwargs: QMessageBox.StandardButton.Yes)

    note_page = pet.tools.notes_page
    note_page.add()
    note_page.body.setPlainText("Nota exportada")
    note_page.export_button.click()
    assert result.read_text() == "Nota exportada"
    assert pet.productivity.flush()
    note_page.add()
    assert pet.productivity.flush()
    page.restore("tools")
    wait_for_backups(page)
    assert note_page.list.count() == 1 and note_page.current_id is None
    assert not note_page.export_button.isEnabled()

    state = pet.companion_state
    assert state.update("accessibility", {"ui_scale": 125}, immediate=True)
    assert state.update("accessibility", {"ui_scale": 150}, immediate=True)
    page.restore("companion_state")
    wait_for_backups(page)
    assert state.data["accessibility"]["ui_scale"] == 125
    assert page.status.text().startswith("Backup restaurado.")

    saved = Settings()
    saved.active_droid = "pico"
    saved.timer_seconds = 60
    pet.store.backup.write_text(json.dumps(saved.to_dict()), encoding="utf-8")
    original = pet.profile.id
    page.restore("config")
    wait_for_backups(page)
    assert pet.profile.id == pet.audio.profile_id == "pico"
    assert pet.tools.selected_duration() == 60
    assert pet.tools.notes_page.list.item(0).data(Qt.ItemDataRole.UserRole)
    recovery = pet.data_transfer.recovery_path(pet.store)
    assert json.loads(recovery.read_text(encoding="utf-8"))["active_droid"] == original
    assert page.status.text().startswith("Backup restaurado.")
