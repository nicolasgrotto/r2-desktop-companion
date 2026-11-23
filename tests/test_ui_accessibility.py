import json
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QAccessible
from PySide6.QtTest import QSignalSpy, QTest
from PySide6.QtWidgets import QPushButton, QScrollArea, QWidget

from r2_companion.core.config import Settings
from r2_companion.droids.themes import theme_manager
from r2_companion.features.productivity import ProductivityStore
from r2_companion.ui.productivity import NotesPage, TasksPage
from r2_companion.ui.radial import RadialMenu
from r2_companion.ui.settings import SettingsDialog
from test_context_v03 import pet


@pytest.fixture
def ui_scale(qapp):
    manager = theme_manager()
    original = manager.ui_scale
    manager.set_ui_scale(100)
    yield manager
    manager.set_ui_scale(original)


def accessible_name(widget):
    return QAccessible.queryAccessibleInterface(widget).text(QAccessible.Text.Name)


def visible_in_scroll_area(widget, area):
    viewport = area.viewport()
    top_left = viewport.mapFromGlobal(widget.mapToGlobal(QPoint()))
    return viewport.rect().contains(QRect(top_left, widget.size()))


def test_settings_exposes_scaled_controls_to_qt_accessibility(qapp, ui_scale):
    dialog = SettingsDialog(Settings(), True, False, "Inicialização desativada.")
    try:
        assert accessible_name(dialog.ui_scale) == "Escala da interface"
        assert accessible_name(dialog.scale) == "Tamanho do mascote"
        ui_scale.set_ui_scale(150)
        dialog.ui_scale.ensurePolished()
        assert dialog.ui_scale.font().pixelSize() == 20
    finally:
        dialog.deleteLater()


def test_settings_scales_fonts_and_controls_and_keeps_large_form_navigable(native_desktop, ui_scale):
    dialog = SettingsDialog(Settings(), True, False, "Inicialização desativada.")
    dialog.resize(360, 390)
    dialog.show()
    try:
        select = dialog.ui_scale
        area = dialog.tabs.currentWidget()
        assert accessible_name(select) == "Escala da interface"
        assert "Tamanho do mascote" == accessible_name(dialog.scale)
        heights = []
        for percent in (100, 125, 150):
            ui_scale.set_ui_scale(percent)
            QTest.qWait(30)
            heights.append(select.sizeHint().height())
            assert select.font().pixelSize() == round(13 * percent / 100)
            assert area.horizontalScrollBar().maximum() == 0
            assert dialog.size().width() == 360
        assert heights[0] < heights[1] < heights[2]
        assert area.verticalScrollBar().maximum() > 0
        dialog.reduced_motion.setFocus()
        QTest.keyClick(dialog.reduced_motion, Qt.Key.Key_Space)
        QTest.keyClick(dialog.reduced_motion, Qt.Key.Key_Tab)
        assert dialog.reduced_motion.isChecked() and select.hasFocus()
        QTest.keyClick(select, Qt.Key.Key_Down)
        assert select.currentData() == 125
        QTest.keyClick(select, Qt.Key.Key_Tab)
        assert dialog.scale.hasFocus()
        assert visible_in_scroll_area(dialog.scale, area)
        dialog.tabs.setCurrentIndex(2)
        dialog.muted.setFocus()
        QTest.keyClick(dialog.muted, Qt.Key.Key_Tab)
        assert dialog.volume.hasFocus()
        QTest.keyClick(dialog.volume, Qt.Key.Key_Escape)
        assert not dialog.isVisible()
    finally:
        dialog.close()
        dialog.deleteLater()


def test_task_check_state_and_note_focus_are_accessible_by_keyboard(qapp, tmp_path):
    store = ProductivityStore(tmp_path)
    tasks, notes = TasksPage(store), NotesPage(store)
    tasks.show()
    try:
        tasks.input.setFocus()
        QTest.keyClicks(tasks.input, "Comprar pilhas")
        QTest.keyClick(tasks.input, Qt.Key.Key_Return)
        tasks.list.setCurrentRow(0)
        tasks.list.setFocus()
        QTest.keyClick(tasks.list, Qt.Key.Key_Space)
        assert store.data["tasks"][0]["done"] and tasks.list.currentRow() == 0
        assert accessible_name(tasks.list) == "Lista de tarefas"

        tasks.hide()
        notes.show()
        notes.activateWindow()
        notes.add()
        notes.body.setFocus()
        QTest.qWait(10)
        QTest.keyClicks(notes.body, "Texto da nota")
        QTest.keyClick(notes.body, Qt.Key.Key_Backtab, Qt.KeyboardModifier.ShiftModifier)
        assert notes.title.hasFocus()
        assert notes.body.toPlainText() == "Texto da nota"
        assert accessible_name(notes.body) == "Conteúdo da nota"
    finally:
        tasks.close()
        notes.close()
        store.close()


def test_radial_requests_conventional_menu_when_scaled_wheel_would_not_fit(qapp, ui_scale, monkeypatch):
    ui_scale.set_ui_scale(150)
    wheel = RadialMenu()
    anchor = QWidget()
    area = QRect(-400, 0, 400, 330)
    screen = SimpleNamespace(availableGeometry=lambda: area)
    monkeypatch.setattr("r2_companion.ui.radial.QGuiApplication", SimpleNamespace(screenAt=lambda _: screen))
    anchor.move(-200, 20)
    menu_requested = QSignalSpy(wheel.compact_menu_requested)
    try:
        wheel.popup_near(anchor)
        assert wheel.width() == 552 and not wheel.isVisible()
        assert menu_requested.count() == 1
        assert menu_requested.at(0) == [anchor.geometry().center()]
    finally:
        wheel.stop()
        wheel.deleteLater()


def test_scaled_preferences_radial_menu_and_tools_on_windows(pet):
    initial_pet_size = pet.window.size()
    pet.show_settings()
    settings = pet.settings_dialog
    assert QTest.qWaitForWindowActive(settings)
    try:
        settings.ui_scale.setFocus()
        QTest.keyClick(settings.ui_scale, Qt.Key.Key_End)
        apply = next(button for button in settings.findChildren(QPushButton) if button.text() == "Aplicar")
        apply.setFocus()
        QTest.keyClick(apply, Qt.Key.Key_Space)
        assert theme_manager().ui_scale == 150
        assert pet.window.size() == initial_pet_size
        document = json.loads((pet.store.directory / "companion_state.json").read_text(encoding="utf-8"))
        assert document["accessibility"]["ui_scale"] == 150
        QTest.keyClick(apply, Qt.Key.Key_Escape)
        assert pet.settings_dialog is None

        pet.companion_state.update("accessibility", {"reduced_motion": True})
        screen = pet.window.screen()
        if min(screen.availableGeometry().width(), screen.availableGeometry().height()) < 552:
            pet.radial.popup_near(pet.window)
            assert not pet.radial.isVisible() and pet.menu.isVisible()
            QTest.keyClick(pet.menu, Qt.Key.Key_Escape)
            assert not pet.menu.isVisible()
            pet.companion_state.update("accessibility", {"ui_scale": 100})
        pet.radial.popup_near(pet.window)
        wheel = pet.radial
        assert QTest.qWaitForWindowActive(wheel)
        QTest.keyClick(wheel.buttons["tools"], Qt.Key.Key_Return)
        assert wheel.level == "tools"
        QTest.keyClick(wheel.buttons["tools_center"], Qt.Key.Key_Tab)
        assert wheel.buttons["clock"].hasFocus()
        QTest.keyClick(wheel.buttons["clock"], Qt.Key.Key_Tab)
        assert wheel.buttons["timer"].hasFocus()
        QTest.keyClick(wheel.buttons["timer"], Qt.Key.Key_Space)
        assert not wheel.isVisible() and pet.tools.tabs.currentWidget() is pet.tools.pages["timer"]
        assert "radial" not in pet.controller.gates
        pet.tools.close()

        pet.show_menu(pet.window.geometry().center())
        menu = pet.menu
        action = next(action for action in menu.actions() if action.data() == "notes")
        menu.setActiveAction(action)
        QTest.keyClick(menu, Qt.Key.Key_Return)
        assert not menu.isVisible() and pet.tools.tabs.currentWidget() is pet.tools.pages["notes"]
        assert pet.tools.isVisible() and "menu" not in pet.controller.gates
        QTest.keyClick(pet.tools, Qt.Key.Key_Escape)
        assert not pet.tools.isVisible()
        pet.show_menu(pet.window.geometry().center())
        QTest.keyClick(pet.menu, Qt.Key.Key_Escape)
        assert not pet.menu.isVisible() and "menu" not in pet.controller.gates
    finally:
        theme_manager().set_ui_scale(100)


def test_narrow_tools_garage_and_audio_keep_essential_controls_reachable(pet):
    pet.companion_state.update("accessibility", {"ui_scale": 150})
    pet.show_tools_page("timer")
    pet.show_garage()
    pet.show_audio_center()
    try:
        timer = pet.tools.pages["timer"]
        audio = pet.audio_dialog
        save_audio = next(button for button in audio.findChildren(QPushButton) if button.text() == "Salvar preferências")
        garage = pet.garage_dialog
        for dialog, area, action in ((pet.tools, timer, pet.tools.start_button),
                                     (garage, garage.scroll_area, garage.equip_button),
                                     (audio, audio.scroll_area, save_audio)):
            assert dialog.screen().availableGeometry().contains(dialog.frameGeometry())
            dialog.resize(360, 340)
            dialog.activateWindow()
            QTest.qWait(30)
            assert dialog.width() == 360
            assert area.verticalScrollBar().maximum() > 0
            assert area.horizontalScrollBar().maximum() == 0, type(dialog).__name__
            area.ensureWidgetVisible(action)
            assert visible_in_scroll_area(action, area)
        assert garage.equip_button.minimumSizeHint().width() <= garage.equip_button.width()
        assert audio.findChild(QScrollArea) is audio.scroll_area
    finally:
        theme_manager().set_ui_scale(100)
