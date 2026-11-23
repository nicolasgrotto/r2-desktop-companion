from string import Formatter
import sys

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox

from r2_companion.app import Companion
from r2_companion.core.language import activate_language, active_language, english_catalog, locale, tr
from r2_companion.services.companion_state import CompanionStateStore, validate_document
from r2_companion.services.storage import ConfigStore
from test_context_v03 import pet


def test_catalog_preserves_parameters_and_legacy_default():
    def fields(message):
        return sorted(field for _, field, _, _ in Formatter().parse(message) if field is not None)

    for source, target in english_catalog().items():
        assert fields(source) == fields(target), source
    assert validate_document({"schema_version": 1})["appearance"]["language"] == "pt-BR"
    assert validate_document({"schema_version": 1, "appearance": {"language": []}})["appearance"]["language"] == "pt-BR"


def test_standard_buttons_follow_selected_language(qapp):
    try:
        activate_language(qapp, "pt-BR")
        assert locale().name() == "pt_BR"
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        assert box.button(QDialogButtonBox.StandardButton.Cancel).text() == "Cancelar"
        activate_language(qapp, "en")
        assert locale().name() == "en_US"
        box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        assert box.button(QDialogButtonBox.StandardButton.Cancel).text() == "Cancel"
        assert tr("Temporizador #{0} concluído.", 42) == "Timer #42 finished."
    finally:
        activate_language(qapp, "pt-BR")


def test_language_restart_keeps_actions_and_user_text(pet, qapp, monkeypatch):
    directory = pet.store.directory
    task = pet.productivity.add_task("Foco")
    pet.show_settings()
    settings = pet.settings_dialog
    assert settings.language_choice.itemText(0) == "Português (Brasil)"
    assert settings.language_choice.itemText(1) == "English"
    settings.language_choice.setCurrentIndex(1)
    with monkeypatch.context() as failure:
        failure.setattr(pet.companion_state, "_write", lambda data: False)
        settings.language_save.click()
        assert "Português (Brasil)" in settings.language_status.text()
        assert pet.companion_state.data["appearance"]["language"] == "pt-BR"
    QTest.keyClick(settings.language_save, Qt.Key.Key_Space)
    assert active_language() == "pt-BR" and "Reinicie" in settings.language_status.text()
    pet.shutdown()
    store = ConfigStore(directory)
    assert store.acquire()
    store.load()
    english = Companion(qapp, store)
    try:
        assert active_language() == "en"
        assert english.tools.tabs.tabText(english.tools.tabs.indexOf(english.tools.pages["focus"])) == "Focus"
        assert {action.id for action in english.actions.search("focus")} >= {"focus"}
        english.dispatch_action("focus")
        assert english.tools.tabs.currentWidget() is english.tools.pages["focus"]
        english.tools.focus_page.start_for(task)
        english.project_focus()
        assert english.window.projection.model.title == "Focus"
        assert "Foco" in english.window.projection_text
        english.show_settings()
        dialog = english.settings_dialog
        assert dialog.language_save.text() == "Save language"
        dialog.language_choice.setCurrentIndex(0)
        dialog.language_save.click()
        assert "Restart" in dialog.language_status.text()
    finally:
        english.shutdown()
        activate_language(qapp, "pt-BR")
    saved = CompanionStateStore.read_document_file(directory / "companion_state.json")
    assert saved["appearance"]["language"] == "pt-BR"


def test_restart_button_saves_language_and_hands_off_the_same_profile(pet, monkeypatch):
    pet.show_settings()
    dialog = pet.settings_dialog
    dialog.language_choice.setCurrentIndex(1)
    calls = []

    def launch(command, **kwargs):
        calls.append(command)
        assert pet.store.lock.isLocked()
        if len(calls) == 1:
            raise OSError("mock failure")

    monkeypatch.setattr("r2_companion.app.subprocess.Popen", launch)
    dialog.language_restart.click()
    assert not pet.closed and "Não foi possível reiniciar" in dialog.language_status.text()
    assert pet.companion_state.data["appearance"]["language"] == "en"
    dialog.language_restart.click()
    assert pet.closed and not pet.store.lock.isLocked()
    assert calls[0] == calls[1]
    assert calls[1][0] == sys.executable
    assert calls[1][-3:] == ["--data-dir", str(pet.store.directory.resolve()), "--restart-wait"]


def test_scrolling_over_preference_preserves_value_and_scrolls_page(pet, qapp):
    pet.show_settings()
    dialog = pet.settings_dialog
    dialog.resize(600, 360)
    qapp.processEvents()
    area = dialog.tabs.widget(0)
    bar = area.verticalScrollBar()
    combo = dialog.presence_mode
    combo.setFocus()
    bar.setValue(0)
    event = QWheelEvent(QPointF(combo.rect().center()), QPointF(combo.mapToGlobal(combo.rect().center())),
                        QPoint(), QPoint(0, -120), Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                        Qt.ScrollPhase.NoScrollPhase, False)
    qapp.sendEvent(combo, event)
    assert combo.currentData() == "free"
    assert bar.value() > 0
    QTest.keyClick(combo, Qt.Key.Key_End)
    assert combo.currentData() == "presentation"
    assert "Oculta o mascote" in dialog.presence_description.text()
