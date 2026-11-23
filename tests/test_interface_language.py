from string import Formatter

from PySide6.QtCore import Qt
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
