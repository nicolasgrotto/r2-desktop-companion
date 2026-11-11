import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QLabel
from r2_companion.pet.state import State
from r2_companion.ui.theme import apply_character_name
from test_context_v03 import pet


def test_long_sleep_requires_a_click_even_after_user_returns_and_menus_close(pet, clock):
    controller = pet.controller
    controller.clock = clock
    controller.enter(State.SLEEP)
    clock.advance(181)
    controller.update_inactivity(0)
    assert controller.state == State.SLEEP and controller.requires_wake_click
    controller.set_gate('menu', True)
    controller.set_gate('menu', False)
    assert controller.state == State.SLEEP
    assert not controller.request(State.NOTIFICATION)
    pet.left_click()
    assert controller.state == State.WAKE
    assert not controller.requires_wake_click and not pet.radial.isVisible()
    pet.double_click()
    assert controller.state == State.WAKE and not pet.radial.isVisible()
    controller.finished(controller.token)
    assert controller.state == State.IDLE


def test_sleep_duration_counts_time_asleep_not_previous_inactivity(pet, clock):
    controller = pet.controller
    controller.clock = clock
    controller.update_inactivity(10000)
    assert controller.state == State.SLEEP and not controller.requires_wake_click
    clock.advance(20)
    controller.update_inactivity(0)
    assert controller.state != State.SLEEP


def test_deep_sleep_keeps_notifications_queued_until_manual_wake(pet, clock):
    c = pet.controller
    c.clock = clock
    c.enter(State.SLEEP)
    clock.advance(200)
    c.notify('timer-deep', 'Seu tempo terminou')
    assert len(c.pending_notifications) == 1 and c.state == State.SLEEP
    pet.left_click()
    c.finished(c.token)
    assert c.state == State.NOTIFICATION and len(c.pending_notifications) == 0


@pytest.mark.parametrize('identifier,name', [('spherical_droid','Orbita'), ('dark_astromech','Vesper')])
def test_active_name_appears_in_transmission_preferences_and_preview(pet, identifier, name):
    assert pet.equip_droid(identifier)
    assert any(name in field.text() and 'TRANSMISSÃO' in field.text() for field in pet.bubble.findChildren(QLabel))
    pet.show_settings()
    assert name in pet.settings_dialog.windowTitle()
    badge = next(field for field in pet.settings_dialog.findChildren(QLabel) if field.property('role') == 'brand')
    badge.ensurePolished()
    assert badge.width() >= badge.fontMetrics().horizontalAdvance(name)
    assert any('personalidade do ' + name in field.text() for field in pet.settings_dialog.findChildren(QLabel))
    pet.settings_dialog.close()
    pet.show_garage()
    g = pet.garage_dialog
    g.selector.setCurrentIndex(g.selector.findData('r2_default'))
    g.selector.setCurrentIndex(g.selector.findData(identifier))
    assert g.name.text() == name
    literal = QLabel('Minha tarefa com R2', pet.tools.tasks_page)
    apply_character_name(pet.tools, name)
    assert literal.text() == 'Minha tarefa com R2'


@pytest.mark.parametrize('identifier', ['r2_default','dark_astromech','spherical_droid'])
def test_overheat_emits_smoke_for_each_droid_and_cleans_it_up(pet, identifier):
    assert pet.equip_droid(identifier)
    pet.controller.enter(State.IDLE)
    assert pet.controller.react(State.OVERHEAT)
    QTest.qWait(80)
    steam = pet.window.steam
    assert steam.active and steam.isVisible() and steam.timer.isActive()
    assert steam.windowFlags() & Qt.WindowType.WindowTransparentForInput
    frame = steam.grab().toImage()
    assert any(frame.pixelColor(x,y).alpha() > 0 for x in range(0,frame.width(),4) for y in range(0,frame.height(),4))
    pet.controller.finished(pet.controller.token)
    assert not steam.active and not steam.timer.isActive() and not steam.isVisible()
    pet.controller.react(State.OVERHEAT)
    pet.shutdown()
    assert not steam.timer.isActive()


def test_equipping_another_droid_preserves_deep_sleep_with_new_animation(pet, clock):
    c = pet.controller
    c.clock = clock
    c.enter(State.SLEEP)
    clock.advance(200)
    c.update_inactivity(0)
    assert pet.equip_droid('spherical_droid')
    assert c.state == State.SLEEP and c.requires_wake_click
    assert pet.animation.clip is pet.animation.clips[State.SLEEP]
    pet.left_click()
    assert c.state == State.WAKE
