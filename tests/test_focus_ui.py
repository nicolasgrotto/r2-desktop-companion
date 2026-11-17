from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QMessageBox

from r2_companion.app import Companion
from r2_companion.features.focus import FocusPhase
from r2_companion.features.timer import TimerState
from r2_companion.pet.state import State
from r2_companion.services.storage import ConfigStore
from test_context_v03 import pet


def press(widget, key=Qt.Key.Key_Space):
    assert widget.isVisible() and widget.isEnabled()
    widget.setFocus()
    QTest.keyClick(widget, key)


def tab_to(qapp, dialog, target):
    seen = set()
    while (current := qapp.focusWidget()) is not target:
        assert current not in seen, f"{target} não foi alcançado por Tab"
        seen.add(current)
        QTest.keyClick(current or dialog, Qt.Key.Key_Tab)


def answer_confirmation(qapp, answer):
    def choose():
        modal = qapp.activeModalWidget()
        if isinstance(modal, QMessageBox):
            press(modal.button(answer))
    QTimer.singleShot(0, choose)


def test_keyboard_task_to_focus_to_break_and_new_cycle(pet, qapp, clock):
    pet.countdown.clock = clock
    task_id = pet.productivity.add_task("Revisar capítulo")
    tools = pet.tools
    tools.tasks_page.render(selected=task_id)
    pet.show_tools_page("tasks")
    tools.tasks_page.list.setFocus()
    tab_to(qapp, tools, tools.tasks_page.focus_button)
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_Space)
    page = tools.focus_page
    assert tools.tabs.currentWidget() is tools.pages["focus"]
    assert pet.focus.session.task_id == task_id and pet.countdown.remaining == 1500
    assert qapp.focusWidget() is page.pause_button
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_Space)
    assert pet.focus.session.state == TimerState.PAUSED
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_Space)
    assert pet.focus.session.state == TimerState.RUNNING
    clock.advance(1500)
    pet.countdown.tick()
    assert pet.focus.session.state == TimerState.COMPLETED
    assert not pet.productivity.task(task_id)["done"] and not pet.countdown.timer.isActive()
    tab_to(qapp, tools, page.finish_task_button)
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_Space)
    assert pet.productivity.task(task_id)["done"]
    assert tools.tasks_page.list.currentItem().checkState() == Qt.CheckState.Checked
    assert qapp.focusWidget() is page.next_button
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_Space)
    assert pet.focus.session.phase == FocusPhase.BREAK and pet.countdown.remaining == 300
    assert pet.presence.context.focus_session_id is None
    clock.advance(300)
    pet.countdown.tick()
    tab_to(qapp, tools, page.next_button)
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_Space)
    assert pet.focus.session.phase == FocusPhase.FOCUS and pet.countdown.remaining == 1500
    tab_to(qapp, tools, page.stop_button)
    QTest.keyClick(qapp.focusWidget(), Qt.Key.Key_Space)
    assert pet.focus.session is None and not pet.countdown.timer.isActive()


def test_timer_and_focus_confirm_replacement_in_both_directions(pet, qapp, clock):
    pet.countdown.clock = clock
    tools = pet.tools
    pet.show_tools_page("timer")
    tools.set_duration(35)
    press(tools.start_button)
    first = pet.countdown.run_id
    pet.show_tools_page("focus")
    page = tools.focus_page
    page.duration.setValue(2)
    answer_confirmation(qapp, QMessageBox.StandardButton.No)
    press(page.start_button)
    assert pet.countdown.run_id == first and pet.focus.session is None
    answer_confirmation(qapp, QMessageBox.StandardButton.Yes)
    press(page.start_button)
    assert pet.focus.session.duration == 120
    second = pet.countdown.run_id
    pet.show_tools_page("timer")
    assert not tools.stop_button.isEnabled() and not tools.restart_button.isEnabled()
    answer_confirmation(qapp, QMessageBox.StandardButton.No)
    press(tools.start_button)
    assert pet.focus.session.run_id == second
    answer_confirmation(qapp, QMessageBox.StandardButton.Yes)
    press(tools.start_button)
    assert pet.focus.session is None and pet.countdown.run_id != second and pet.countdown.remaining == 35
    press(tools.stop_button)
    assert pet.countdown.state == TimerState.STOPPED


def test_hidden_sleeping_focus_card_and_manual_mode_survive_task_removal(pet, clock, monkeypatch):
    monkeypatch.setattr("r2_companion.pet.presence_runtime.QSystemTrayIcon.isSystemTrayAvailable", lambda: True)
    pet.countdown.clock = clock
    task_id = pet.productivity.add_task("Tarefa do cartão")
    pet.controller.enter(State.SLEEP)
    assert pet.window.show_projection("clock")
    pet.hide_pet()
    pet.show_tools_page("focus")
    page = pet.tools.focus_page
    page.select_task(task_id)
    press(page.start_button)
    session = pet.focus.session
    assert pet.presence.context.focus_session_id == session.session_id
    assert pet.controller.state == State.SLEEP and not pet.window.isVisible()
    assert pet.window.projection_kind == "clock" and pet.window.projection.model is None
    assert not pet.tools.project_timer.isChecked()
    press(page.projection_button)
    assert pet.window.projection_kind == "focus" and not pet.window.projection_timer.isActive()
    pet.show_pet()
    assert "Tarefa do cartão" in pet.tools.projection_details.toPlainText()
    clock.advance(10)
    pet.window.projection.timer.timeout.emit()
    assert "24:50" in pet.tools.projection_details.toPlainText()
    pet.presence.select_mode("free")
    assert pet.presence.context.focus_session_id is None
    pet.productivity.remove("tasks", task_id)
    assert page.task_caption.isHidden() and pet.focus.session.task_id is None
    assert "Tarefa do cartão" not in pet.tools.projection_details.toPlainText()
    assert pet.focus.session.run_id == session.run_id and pet.countdown.remaining == 1490
    assert pet.presence.context.focus_session_id is None
    pet.presence.select_mode("presentation")
    press(page.pause_button)
    press(page.stop_button)
    assert pet.presence.context.manual_mode == "presentation" and not pet.window.isVisible()
    assert pet.window.projection_kind is None


def test_recovery_is_only_offered_on_focus_page_and_resumes_paused(pet, qapp, clock, monkeypatch):
    pet.countdown.clock = clock
    pet.focus.start_focus(100)
    clock.advance(17)
    directory = pet.store.directory
    pet.shutdown()
    qapp.processEvents()
    monkeypatch.setattr("r2_companion.app.uptime", clock)
    config = ConfigStore(directory)
    assert config.acquire()
    reopened = Companion(qapp, config)
    try:
        assert not reopened.tools.isVisible() and qapp.activeModalWidget() is None
        assert reopened.countdown.state == TimerState.STOPPED and reopened.presence.context.focus_session_id is None
        reopened.show_tools_page("focus")
        page = reopened.tools.focus_page
        assert "01:23 restantes" in page.summary.text()
        press(page.recover_button)
        assert reopened.focus.session.state == TimerState.PAUSED and reopened.countdown.remaining == 83
        assert reopened.presence.context.focus_session_id is None
        press(page.pause_button)
        assert reopened.focus.session.override_id == reopened.presence.context.focus_session_id
        clock.advance(100)
        reopened.countdown.tick()
        press(page.dismiss_button)
        assert reopened.focus.session is None and reopened.focus.recovery is None
    finally:
        reopened.shutdown()
