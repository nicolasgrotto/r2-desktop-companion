import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QSignalSpy, QTest

from r2_companion.features.timer import Countdown, TimerState
from test_context_v03 import pet


@pytest.mark.parametrize("paused", [False, True])
def test_cancel_does_not_complete_or_resurrect_and_allows_another_run(qapp, clock, paused):
    timer = Countdown(clock)
    completed = QSignalSpy(timer.completed)
    changed = QSignalSpy(timer.changed)
    timer.start(60)
    clock.advance(10)
    if paused:
        timer.pause()
    timer.stop()
    assert timer.state == TimerState.STOPPED and timer.remaining == 0
    assert timer.deadline == timer.remaining_at_pause == 0
    assert not timer.timer.isActive()
    assert changed.count() >= 2
    clock.advance(1000)
    timer.tick()  # Even a timeout already queued before cancellation is harmless.
    timer.resume()
    timer.set_visible(True)
    assert timer.state == TimerState.STOPPED and completed.count() == 0
    timer.start(15)
    assert timer.run_id == 2 and timer.remaining == 15
    clock.advance(15)
    timer.tick()
    timer.tick()
    assert completed.count() == 1 and completed.at(0)[0] == 2
    timer.close()


@pytest.mark.parametrize("paused", [False, True])
@pytest.mark.parametrize("projection", ["timer", "clock"])
def test_stop_button_unlocks_duration_and_only_clears_timer_projection(pet, clock, paused, projection):
    pet.countdown.clock = clock
    pet.show_tools_page("timer")
    tools = pet.tools
    assert not tools.stop_button.isEnabled()
    tools.project_timer.setChecked(True)
    tools.set_duration(300)
    QTest.mouseClick(tools.start_button, Qt.MouseButton.LeftButton)
    if paused:
        QTest.mouseClick(tools.pause_button, Qt.MouseButton.LeftButton)
    if projection == "clock":
        pet.project_tool("clock")
    completed = QSignalSpy(pet.countdown.completed)
    assert not tools.start_button.isEnabled() and tools.stop_button.isEnabled()
    QTest.mouseClick(tools.stop_button, Qt.MouseButton.LeftButton)
    assert pet.countdown.state == TimerState.STOPPED
    assert tools.start_button.isEnabled() and not tools.stop_button.isEnabled()
    assert not tools.pause_button.isEnabled() and not tools.restart_button.isEnabled()
    assert all(c.isEnabled() for c in (tools.minutes, tools.seconds, *tools.presets))
    assert "encerrado" in tools.completion.text() and tools.dial.status == "PRONTO"
    assert pet.window.projection_kind == (None if projection == "timer" else "clock")
    tools.close()
    tools.show()
    assert tools.start_button.isEnabled() and not tools.stop_button.isEnabled()
    clock.advance(500)
    pet.countdown.tick()
    assert completed.count() == 0
    tools.set_duration(30)
    QTest.mouseClick(tools.start_button, Qt.MouseButton.LeftButton)
    assert pet.countdown.remaining == 30 and pet.countdown.run_id == 2
    assert pet.window.projection_kind == "timer"
    QTest.mouseClick(tools.stop_button, Qt.MouseButton.LeftButton)


def test_repeated_stop_at_deadline_never_announces_completion(qapp, clock):
    timer = Countdown(clock)
    completed = QSignalSpy(timer.completed)
    timer.start(1)
    clock.advance(1)
    timer.stop()
    timer.stop()
    timer.tick()
    assert completed.count() == 0 and timer.state == TimerState.STOPPED
