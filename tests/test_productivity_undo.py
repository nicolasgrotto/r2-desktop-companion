from copy import deepcopy
import json

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QPushButton

from r2_companion.features.productivity import ProductivityStore
from r2_companion.ui.productivity import NotesPage, TasksPage
from test_context_v03 import pet


@pytest.fixture
def store(qapp, tmp_path):
    result = ProductivityStore(tmp_path)
    yield result
    result.close()


def button_fits_viewport(button, scroll_area):
    viewport = scroll_area.viewport()
    position = viewport.mapFromGlobal(button.mapToGlobal(QPoint()))
    return viewport.rect().contains(QRect(position, button.size()))


def test_restores_completed_task_with_original_id_and_order(store):
    store.add_task("Primeira")
    deleted = store.add_task("Concluída")
    store.add_task("Última")
    completion = QSignalSpy(store.task_completed)
    store.set_done(deleted, True)
    previous = deepcopy(store.data)
    assert store.remove("tasks", deleted)
    assert not store.remove("notes", "missing") and store.undo_collection == "tasks"
    assert all(task["id"] != deleted for task in store.data["tasks"])
    assert store.undo_remove() == "tasks"
    assert store.data == previous and completion.count() == 1
    assert store.undo_collection is None and store.undo_remove() is None


def test_last_deletion_is_shared_and_undo_detaches_stale_note_edits(store):
    tasks, notes = TasksPage(store), NotesPage(store)
    try:
        assert not tasks.undo_button.isEnabled() and not notes.undo_button.isEnabled()
        first_deleted = store.add_task("Apagar primeiro")
        tasks.render(selected=first_deleted)
        tasks.remove()
        assert "tarefa" in notes.undo_button.text()
        first = store.add_note()
        notes.add()
        deleted_id = notes.current_id
        body = "Projeto · detalhes\n" * 2600 + "x" * 600
        assert len(body) == 50000
        notes.title.setText("Anotação extensa · 中文")
        notes.body.setPlainText(body)
        before = deepcopy(store.data["notes"])
        notes.remove()
        assert notes.current_id is None and notes.list.currentItem() is None
        assert not notes.title.isEnabled() and not notes.body.isEnabled()
        assert notes.title.text() == notes.body.toPlainText() == ""
        notes.title.textEdited.emit("Título atrasado")
        notes.body.setPlainText("Edição atrasada")
        assert store.data["notes"] == before[:1] and store.data["notes"][0]["id"] == first

        assert "nota" in tasks.undo_button.text()
        tasks.undo_button.click()
        assert tasks.status.text() == "Nota restaurada."
        assert notes.current_id == deleted_id and notes.body.toPlainText() == body
        assert store.data["notes"] == before and not store.data["tasks"]
        assert not tasks.undo_button.isEnabled() and not notes.undo_button.isEnabled()
    finally:
        tasks.close()
        notes.close()


@pytest.mark.parametrize(("collection", "maximum"), [("tasks", 500), ("notes", 100)])
def test_collection_limit_keeps_records_and_undo_available(store, collection, maximum):
    entries = [{"id": str(i), "title": "Nota", "body": ""} if collection == "notes"
               else {"id": str(i), "text": "Tarefa", "done": False} for i in range(maximum)]
    store.change(store.data | {collection: entries})
    assert store.remove(collection, "5")
    add = store.add_note if collection == "notes" else lambda: store.add_task("Nova")
    add()
    previous = deepcopy(store.data)
    page = NotesPage(store) if collection == "notes" else TasksPage(store)
    try:
        page.undo_button.click()
        assert f"Limite de {maximum}" in page.status.text()
        assert store.data == previous and page.undo_button.isEnabled()
    finally:
        page.close()


def test_total_size_limit_preserves_the_deleted_note_for_a_retry(store):
    large_body = "🚀" * 50000
    notes = [{"id": str(i), "title": "Nota", "body": large_body} for i in range(41)]
    store.change(store.data | {"notes": notes})
    assert store.remove("notes", "5")
    new_note = store.add_note()
    store.edit_note(new_note, "Nova", large_body)
    previous = deepcopy(store.data)
    with pytest.raises(ValueError, match="limite total de 8 MiB"):
        store.undo_remove()
    assert store.data == previous and store.undo_collection == "notes"
    store.edit_note(new_note, "Nova", "")
    assert store.undo_remove() == "notes"
    assert store.data["notes"][5] == notes[5]


def test_undo_refuses_duplicate_id_across_tasks_and_notes(store):
    deleted = store.add_task("Original")
    assert store.remove("tasks", deleted)
    note = {"id": deleted, "title": "Registro com a mesma identificação", "body": ""}
    store.change(store.data | {"notes": [note]})
    previous = deepcopy(store.data)
    with pytest.raises(ValueError, match="mesmo identificador"):
        store.undo_remove()
    assert store.data == previous and store.undo_collection == "tasks"
    store.change(store.data | {"notes": []})
    assert store.undo_remove() == "tasks"
    assert store.data["tasks"][0]["id"] == deleted


def test_restoration_survives_restart_and_backup_while_undo_expires(store, tmp_path):
    restored = store.add_note()
    store.edit_note(restored, "Projeto", "Linha 1\nLinha 2 · 中文")
    assert store.flush()
    assert store.remove("notes", restored) and store.flush()
    assert store.undo_remove() == "notes" and store.flush()
    disposable = store.add_task("Excluir antes de encerrar")
    assert store.flush()
    assert store.remove("tasks", disposable)
    expected = deepcopy(store.data)
    store.close()
    assert store.undo_remove() is None
    assert json.loads(store.path.read_text(encoding="utf-8")) == expected

    reopened = ProductivityStore(tmp_path)
    try:
        assert reopened.data == expected and reopened.undo_remove() is None
    finally:
        reopened.close()
    store.path.write_text("{broken", encoding="utf-8")
    recovered = ProductivityStore(tmp_path)
    try:
        assert recovered.data["notes"] == expected["notes"]
        assert recovered.data["tasks"][0]["id"] == disposable
        assert any("recuperadas do backup" in notice for notice in recovered.notices)
        assert recovered.undo_remove() is None
    finally:
        recovered.close()


def test_undo_in_tools_can_restore_completed_task_with_the_keyboard(pet):
    pet.companion_state.update("accessibility", {"ui_scale": 150})
    pet.show_tools_page("tasks")
    tools = pet.tools
    tools.resize(360, 390)
    page = tools.tasks_page
    identifier = pet.productivity.add_task("Tarefa concluída")
    pet.productivity.set_done(identifier, True)
    page.render(selected=identifier)
    completion = QSignalSpy(pet.productivity.task_completed)
    delete = next(btn for btn in page.findChildren(QPushButton) if btn.text() == "Excluir selecionada")

    tools.activateWindow()
    assert QTest.qWaitForWindowActive(tools, 2000)
    QTest.qWait(30)
    assert tools.pages["tasks"].horizontalScrollBar().maximum() == 0
    delete.setFocus()
    QTest.keyClick(delete, Qt.Key.Key_Space)
    assert page.list.count() == 0
    assert page.undo_button.isEnabled() and tools.notes_page.undo_button.isEnabled()
    QTest.keyClick(delete, Qt.Key.Key_Tab)
    assert page.undo_button.hasFocus()
    assert button_fits_viewport(page.undo_button, tools.scroll_area)
    QTest.keyClick(page.undo_button, Qt.Key.Key_Space)
    assert page.list.currentItem().data(Qt.ItemDataRole.UserRole) == identifier
    assert page.list.currentItem().checkState() == Qt.CheckState.Checked
    assert completion.count() == 0
    assert not page.undo_button.isEnabled() and not tools.notes_page.undo_button.isEnabled()

    pet.show_tools_page("notes")
    notes = tools.notes_page
    notes.add()
    identifier = notes.current_id
    notes.body.setPlainText("Nota que volta pelo teclado")
    notes.remove()
    QTest.qWait(30)
    assert tools.pages["notes"].horizontalScrollBar().maximum() == 0
    copy = next(btn for btn in notes.findChildren(QPushButton) if btn.text() == "Copiar conteúdo")
    copy.setFocus()
    QTest.keyClick(copy, Qt.Key.Key_Tab)
    assert notes.undo_button.hasFocus()
    assert button_fits_viewport(notes.undo_button, tools.scroll_area)
    QTest.keyClick(notes.undo_button, Qt.Key.Key_Space)
    assert notes.current_id == identifier
    assert notes.body.toPlainText() == "Nota que volta pelo teclado"
