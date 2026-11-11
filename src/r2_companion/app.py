import argparse
from copy import deepcopy
from dataclasses import replace
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys
import time

from PySide6.QtCore import QObject, QPointF, QRectF, QSizeF, QStandardPaths, QTimer, QUrl, Qt, qVersion
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

from . import __version__
from .features.launcher import launch
from .features.locations import validate_location
from .features.system_monitor import SystemMonitor
from .features.timer import Countdown
from .features.productivity import ProductivityStore
from .features.minigames import open_game
from .features.diagnostics import collect_diagnostics
from .pet.animation import AnimationManager, load_clips
from .pet.behavior import BehaviorManager
from .pet.controller import PetController
from .pet.positioning import Positioner, detect_corner, fingerprint
from .pet.awareness import ContextReactions, fullscreen_policy
from .pet.reactions import ReactionDirector
from .pet.personality import quiet_now
from .pet.state import State
from .pet.window import PetWindow
from .services.audio import AudioService
from .services.storage import ConfigStore
from .services.system_info import SystemInfo
from .services.tasks import LocalTasks
from .services.updates import UpdateService
from .services.windows import (SessionEvents, StartupService, foreground_fullscreen, idle_seconds,
                               packaged_executable, uptime)
from .ui.bubble import Bubble
from .ui.context_menu import create_menu
from .ui.settings import SettingsDialog
from .ui.tools import ToolsDialog
from .ui.tray import Tray
from .ui.radial import RadialMenu
from .ui.targets import LaunchpadDialog
from .ui.theme import fit_dialog, icon
from .droids.profiles import DroidRegistry
from .droids.preferences import preferences_for, select_droid
from .droids.controller import DroidController
from .droids.movement import create_movement, MOVEMENT_CONTROLLERS
from .droids.visuals import load_profile_clips
from .droids.themes import color, theme_manager

ASSETS = Path(__file__).resolve().parent / "assets"
log = logging.getLogger(__name__)


class Companion(QObject):
    def __init__(self, qt_app: QApplication, store: ConfigStore):
        super().__init__()
        self.qt_app, self.store = qt_app, store
        self.closed = False
        self.initializing = True
        self.user_hidden = False
        self.fullscreen_hidden = False
        self.fullscreen_active = False
        self.fullscreen_action = ""
        self.session_hidden = False
        self.pass_through = False
        self.last_activity = time.monotonic()
        self.settings_dialog = None
        self.warning_history: set[str] = set()
        self.quiet_active = False
        self._switching_droid = False
        self.droid_error = ""
        self.garage_dialog = self.audio_dialog = self.gallery_dialog = None
        self.droids = DroidRegistry(ASSETS)
        identifier = store.settings.active_droid
        if identifier not in self.droids.profiles:
            store.notices.append("Personagem salvo indisponível; o padrão foi restaurado e suas preferências foram preservadas.")
            identifier = "r2_default"
        self.droids.active_id = identifier
        self.profile = self.droids.active
        try:
            clips = load_profile_clips(self.profile)
            if self.profile.movement not in MOVEMENT_CONTROLLERS:
                raise ValueError("Controlador de locomoção indisponível.")
        except (OSError, ValueError, RuntimeError):
            store.notices.append("Recursos do personagem indisponíveis; usando o padrão.")
            self.droids.active_id = "r2_default"
            self.profile = self.droids.active
            clips = load_profile_clips(self.profile)
        store.apply(select_droid(store.settings, self.profile), notify=False)
        self.window = PetWindow()
        self.positioning = Positioner(self.window)
        self.positioning.movement = create_movement(self.profile, self.window)
        self.animation = AnimationManager(clips)
        self.behavior = BehaviorManager()
        self.controller = PetController(self.animation, self.positioning, self.behavior)
        self.bubble = Bubble()
        self.radial = RadialMenu()
        self.apps_panel = LaunchpadDialog("apps")
        self.locations_panel = LaunchpadDialog("locations")
        self.countdown = Countdown(uptime)
        self.monitor = SystemMonitor(SystemInfo())
        self.audio = AudioService(ASSETS / "sounds", profile=self.profile.audio)
        self.droid_controller = DroidController(self.droids, self.audio, self.window)
        self.productivity = ProductivityStore(store.directory, store.read_only)
        self.awareness = ContextReactions(self.controller, self.positioning, store, self.audio)
        self.updates = UpdateService(store.directory)
        self.tasks = LocalTasks()
        self.startup = StartupService(packaged_executable())
        self.tools = ToolsDialog(self.countdown, self.monitor, store.settings.timer_seconds, self.productivity)
        self.icon = QIcon(str(ASSETS / "icons/companion.png"))
        self.qt_app.setWindowIcon(self.icon)
        self.tray = Tray(self.icon)
        self.menu = None
        self.session_events = SessionEvents()
        self.qt_app.installNativeEventFilter(self.session_events)
        self.session_events.signals.suspended.connect(self.set_suspended)
        self.session_events.signals.ending.connect(self.shutdown)
        self.window.clicked.connect(self.left_click)
        self.window.context_requested.connect(self.show_menu)
        self.window.drag_started.connect(self.drag_started)
        self.window.double_clicked.connect(self.double_click)
        self.window.dragged.connect(self.positioning.drag)
        self.window.drag_finished.connect(self.drag_finished)
        self.window.exit_requested.connect(self.shutdown)
        self.radial.opened.connect(lambda: self.controller.set_gate("radial", True))
        self.radial.dismissed.connect(lambda: self.controller.set_gate("radial", False))
        self.radial.action_selected.connect(self.radial_action)
        for panel in (self.apps_panel, self.locations_panel):
            panel.target_requested.connect(self.open_target)
            panel.configure_requested.connect(self.configure_targets)
        self.positioning.settled.connect(self.save_position)
        self.positioning.screens_changed.connect(self.display_changed)
        self.animation.frame_changed.connect(self.window.set_frame)
        self.controller.state_changed.connect(self.state_changed)
        self.reactions = ReactionDirector(self.controller, self.audio)
        self.window.petted.connect(lambda: self.reactions.start("affection"))
        self.tools.minigames_page.game_requested.connect(self.launch_minigame)
        self.tools.diagnostics_page.provider = self.droid_diagnostics
        self.tools.diagnostics_page.scan_requested.connect(lambda: self.reactions.start("diagnosis"))
        self.controller.notification_presented.connect(self.present_bubble)
        self.countdown.completed.connect(self.timer_completed)
        self.tools.duration_selected.connect(self.save_duration)
        self.store.changed.connect(self.apply_preferences)
        self.store.warning.connect(self.warning)
        self.productivity.warning.connect(self.warning)
        self.productivity.warning.connect(self.tools.completion.setText)
        self.productivity.task_completed.connect(self.task_completed)
        self.tray.activated.connect(self.tray_activated)
        self.idle_timer = QTimer(self)
        self.idle_timer.setInterval(5000)
        self.idle_timer.timeout.connect(self.check_idle)
        self.desktop_timer = QTimer(self)
        self.desktop_timer.setInterval(2000)
        self.desktop_timer.timeout.connect(self.check_desktop)
        self.qt_app.aboutToQuit.connect(self.shutdown)
        initial_position = deepcopy(store.settings.window)
        self.apply_preferences(store.settings)
        self.positioning.restore(initial_position)
        self.positioning.settle()
        self.controller.start()
        self.window.show()
        self.initializing = False
        self.check_desktop()
        if self.window.windowHandle() is not None:
            self.window.windowHandle().screenChanged.connect(lambda screen: self.positioning.reconcile())
        self.session_events.bind(int(self.window.winId()))
        self.tray.show()
        self.idle_timer.start()
        self.desktop_timer.start()
        self.refresh_menu()
        self.greeting_timer = QTimer(self)
        self.greeting_timer.setSingleShot(True)
        self.greeting_timer.timeout.connect(self.awareness.greet)
        self.greeting_timer.start(750)
        for notice in store.notices + self.productivity.notices:
            QTimer.singleShot(100, lambda message=notice: self.warning(message))

    def apply_preferences(self, settings):
        self.behavior.settings = deepcopy(settings.behavior)
        self.positioning.display_size = settings.visual_scale
        self.positioning.aspect = self.profile.canvas[0] / self.profile.canvas[1]
        self.window.configure_droid(self.profile, preferences_for(settings, self.profile))
        if theme_manager().active != self.profile.theme:
            theme_manager().apply(self.profile.theme)
        self.radial.center.setText(self.profile.name.split()[0][:2].upper())
        self.window.set_topmost(settings.window.topmost)
        self.positioning.reconcile()
        self.audio.configure(settings.sound_enabled, deepcopy(settings.audio))
        self.tools.set_duration(settings.timer_seconds)
        self.apps_panel.set_settings(settings)
        self.locations_panel.set_settings(settings)
        self.behavior.schedule(self.controller.state == State.IDLE and not self.controller.gates and not self.controller.paused)
        if not self._switching_droid:
            self.controller.update_inactivity(0)
        self.session_events.bind(int(self.window.winId()))
        self.refresh_menu()
        if not self.initializing:
            self.check_desktop()

    def droid_diagnostics(self):
        result = collect_diagnostics(self.awareness.info, self.audio)
        result.update({"Personagem": f"{self.profile.name} ({self.profile.id})",
                       "Locomoção": type(self.positioning.movement).__name__,
                       "Renderizador": self.profile.renderer, "Animações registradas": str(len(self.profile.animations)),
                       "Perfil vocal": self.audio.profile_id, "Tema": self.profile.theme.name,
                       "Arte": self.profile.art_status, "Perfis rejeitados": str(len(self.droids.errors))})
        return result

    def show_droid_dialog(self, attribute, factory):
        self.radial.hide()
        dialog = getattr(self, attribute)
        if dialog is None:
            dialog = factory(self)
            setattr(self, attribute, dialog)
        fit_dialog(dialog, self.window)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def show_garage(self):
        from .ui.droids import DroidGarage
        self.show_droid_dialog("garage_dialog", DroidGarage)

    def show_audio_center(self):
        from .ui.droids import AudioCenter
        self.show_droid_dialog("audio_dialog", AudioCenter)

    def show_animation_gallery(self):
        from .ui.droids import AnimationGallery
        self.show_droid_dialog("gallery_dialog", AnimationGallery)

    def equip_droid(self, identifier, preferences=None):
        if self.closed or self._switching_droid or self.window.dragging:
            self.droid_error = "Aguarde o término do arrasto ou da troca em andamento."
            return False
        prepared = None
        try:
            prepared = self.droid_controller.prepare(identifier)
            selected = select_droid(self.store.settings, prepared.profile, preferences)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            if prepared:
                prepared.movement.close()
                prepared.movement.deleteLater()
                self.audio.release_bank(prepared.audio_bank)
            self.droid_error = f"Não foi possível preparar o personagem: {error}"
            return False
        previous = deepcopy(self.store.settings)
        previous_dirty = self.store.dirty
        previous_state = self.controller.state
        previous_inactive = self.controller.inactive
        old_profile, old_clips = self.profile, self.animation.clips
        old_movement = self.positioning.movement
        old_bank = None
        position = self.positioning.snapshot()
        self._switching_droid = True
        self.controller.set_gate("droid_swap", True)
        self.reactions.close()
        try:
            self.animation.stop()
            self.positioning.stop()
            self.window.stop_effects()
            old_bank = self.audio.activate_profile(prepared.audio_bank)
            self.profile = prepared.profile
            self.animation.clips = prepared.clips
            self.positioning.movement = prepared.movement
            self.apply_preferences(selected)
            if position:
                self.positioning.restore(position)
            self.controller.enter(State.SLEEP if previous_inactive else State.IDLE)
            snapshot = self.positioning.snapshot()
            if snapshot:
                selected.window = snapshot
            self.store.apply(selected, notify=False)
            if not self.store.flush():
                raise OSError("Falha ao persistir a troca; o personagem anterior foi mantido.")
            self.droids.profiles[identifier] = self.profile
            self.droids.active_id = identifier
            old_movement.close()
            old_movement.deleteLater()
            self.audio.release_bank(old_bank)
            self.droid_error = ""
            if self.settings_dialog is not None:
                self.settings_dialog.close()
            return True
        except (OSError, ValueError, KeyError, TypeError, RuntimeError) as error:
            self.animation.stop()
            self.positioning.stop()
            prepared.movement.close()
            prepared.movement.deleteLater()
            self.profile, self.animation.clips = old_profile, old_clips
            self.positioning.movement = old_movement
            if old_bank is not None:
                rejected = self.audio.activate_profile(old_bank)
                self.audio.release_bank(rejected)
            else:
                self.audio.release_bank(prepared.audio_bank)
            self.store.timer.stop()
            self.store.settings, self.store.dirty = previous, previous_dirty
            if previous_dirty:
                self.store.timer.start()
            self.apply_preferences(previous)
            if position:
                self.positioning.restore(position)
            self.controller.inactive = previous_inactive
            self.controller.enter(previous_state if previous_state != State.WALK else State.IDLE)
            self.droid_error = f"Troca cancelada: {error}"
            log.warning("%s", self.droid_error)
            return False
        finally:
            self._switching_droid = False
            self.controller.set_gate("droid_swap", False)
            self.refresh_menu()
            self.check_desktop()

    def save_position(self, saved):
        if self.closed or self._switching_droid:
            return
        settings = deepcopy(self.store.settings)
        settings.window = saved
        self.store.apply(settings, notify=False)

    def save_duration(self, seconds):
        settings = deepcopy(self.store.settings)
        settings.timer_seconds = seconds
        self.store.apply(settings, notify=False)

    def state_changed(self, state):
        self.audio.set_context(bool(self.controller.gates - {"radial"}) or self.fullscreen_active,
                               state == State.SLEEP or self.controller.inactive)
        if state == State.INTERACT:
            self.present_bubble("Bip! Pronto para acompanhar você.")

    def present_bubble(self, message):
        if self.store.settings.bubbles and self.window.isVisible() and not self.controller.gates:
            self.bubble.present(message, self.window)

    def warning(self, message):
        log.warning("%s", message)
        if message in self.warning_history:
            return
        self.warning_history.add(message)
        self.tray.notify(message)
        self.present_bubble(message)

    def interact(self):
        self.last_activity = time.monotonic()
        self.controller.set_gate("menu", False)
        self.controller.interact()

    def left_click(self):
        if self.awareness.click():
            self.radial.hide()
            self.controller.react(State.CONFUSED)
            return
        if self.radial.isVisible():
            self.radial.hide()
            return
        self.interact()
        self.radial.popup_near(self.window, self.controller.paused)

    def double_click(self):
        self.radial.hide()
        self.last_activity = time.monotonic()
        self.controller.update_inactivity(0)
        self.controller.react(State.GREETING)

    def radial_action(self, action):
        if action == "tools":
            self.show_tools()
        elif action == "apps":
            self.show_launchpad(self.apps_panel)
        elif action == "locations":
            self.show_launchpad(self.locations_panel)
        elif action == "settings":
            self.show_settings()
        elif action == "explore":
            self.walk_now()
        elif action == "pause":
            self.toggle_pause()

    def show_launchpad(self, panel):
        self.radial.hide()
        panel.set_settings(self.store.settings)
        fit_dialog(panel, self.window)
        panel.show()
        panel.raise_()
        panel.activateWindow()

    def configure_targets(self):
        self.show_settings()
        if self.settings_dialog is not None:
            self.settings_dialog.tabs.setCurrentIndex(1)

    def walk_now(self):
        self.radial.hide()
        self.controller.set_gate("menu", False)
        if not self.controller.gates:
            self.controller.enter(State.IDLE)
            if self.controller.request(State.WALK):
                self.behavior.accepted(State.WALK)

    def drag_started(self):
        self.controller.set_gate("drag", True)
        self.controller.enter(State.DRAG)

    def drag_finished(self):
        movement = self.positioning.movement
        drag_tilt = getattr(movement, "head_tilt", 0)
        drag_offset = getattr(movement, "head_offset", 0)
        self.last_activity = time.monotonic()
        self.positioning.settle()
        saved = self.positioning.snapshot()
        if saved is not None:
            saved.corner = detect_corner(QPointF(self.window.pos()),
                QRectF(self.positioning.screen.availableGeometry()), QSizeF(self.window.size()))
            settings = deepcopy(self.store.settings)
            settings.manual_position = saved
            self.store.apply(settings, notify=False)
            self.store.flush()
        self.controller.set_gate("drag", False)
        self.controller.react(State.RECOVER)
        if movement and not self.controller.gates:
            if hasattr(movement, "head_tilt"):
                movement.head_tilt, movement.head_offset = drag_tilt, drag_offset
                self.window.set_motion(movement.angle, drag_tilt, drag_offset)
            movement.release()

    def check_idle(self):
        seconds = idle_seconds()
        self.controller.update_inactivity(seconds if seconds is not None else time.monotonic() - self.last_activity)

    def check_desktop(self):
        if self.closed:
            return
        self.quiet_active = quiet_now(self.store.settings)
        self.controller.set_gate("quiet_hours", self.quiet_active)
        active = (self.store.settings.suppress_fullscreen
                  and foreground_fullscreen(int(self.window.winId())))
        screen_name = "" if self.positioning.screen is None else fingerprint(self.positioning.screen)
        action = fullscreen_policy(self.store.settings.fullscreen_mode,
                                   self.store.settings.manual_position, screen_name) if active else ""
        self.fullscreen_active = active
        if active:
            self.window.stop_effects()
            self.radial.hide()
            self.bubble.stop()
        self.controller.set_gate("fullscreen", active)
        if action == "corner" and self.fullscreen_action != action and not self.window.dragging:
            self.positioning.restore(self.store.settings.manual_position)
            self.positioning.settle()
        self.fullscreen_action = action
        self.fullscreen_hidden = action == "hide"
        self.audio.set_context(active or bool(self.controller.gates - {"radial"}), self.controller.state == State.SLEEP)
        if not QSystemTrayIcon.isSystemTrayAvailable() and self.user_hidden:
            self.user_hidden = False
        if not QSystemTrayIcon.isSystemTrayAvailable() and self.pass_through:
            self.set_pass_through(False)
        self.update_visibility()
        self.awareness.observe()

    def set_suspended(self, active):
        self.session_hidden = active
        self.controller.set_gate("session", active)
        if active:
            self.idle_timer.stop()
            self.desktop_timer.stop()
        else:
            self.positioning.reconcile()
            self.countdown.tick()
            self.idle_timer.start()
            self.desktop_timer.start()
            self.check_idle()
        self.update_visibility()

    def update_visibility(self):
        self.tray.notifications_enabled = not (self.fullscreen_active or self.session_hidden or self.quiet_active)
        if not self.tray.notifications_enabled:
            self.tray.notice.stop()
        hidden = self.user_hidden or self.fullscreen_hidden or self.session_hidden or not QGuiApplication.screens()
        self.controller.set_gate("hidden", hidden)
        if hidden:
            self.radial.hide()
            self.window.hide()
            self.bubble.stop()
        elif not self.window.isVisible() and not self.closed:
            self.window.show()

    def display_changed(self):
        if not self.closed:
            if self.controller.state == State.WALK:
                self.controller.enter(State.IDLE)
            self.radial.hide()
            self.bubble.reposition()
            self.refresh_menu()
            self.update_visibility()

    def show_pet(self):
        self.user_hidden = False
        self.update_visibility()

    def hide_pet(self):
        if QSystemTrayIcon.isSystemTrayAvailable():
            self.user_hidden = True
            self.update_visibility()

    def restore_position(self):
        self.positioning.stop()
        self.controller.enter(State.IDLE)
        settings = replace(self.store.settings.window, screen="", u=0.85, v=0.9)
        self.positioning.restore(settings)
        self.positioning.settle()
        preferences = deepcopy(self.store.settings)
        preferences.manual_position = None
        self.store.apply(preferences, notify=False)
        self.show_pet()

    def move_screen(self, screen):
        if screen in QGuiApplication.screens():
            self.controller.enter(State.IDLE)
            self.positioning.place(QPointF(screen.availableGeometry().center()), screen)
            self.positioning.settle()

    def toggle_pause(self):
        self.controller.set_paused(not self.controller.paused)

    def set_pass_through(self, enabled: bool):
        if enabled and not QSystemTrayIcon.isSystemTrayAvailable():
            return
        self.pass_through = enabled
        self.window.set_pass_through(enabled)
        self.session_events.bind(int(self.window.winId()))
        self.positioning.reconcile()

    def refresh_menu(self):
        if self.closed:
            return
        old_menu = self.menu
        actions = {"interact": self.interact, "settings": self.show_settings, "tools": self.show_tools,
                   "show": self.show_pet, "hide": self.hide_pet, "pause": self.toggle_pause,
                   "paused": lambda: self.controller.paused, "restore": self.restore_position,
                   "pass_through": lambda: self.set_pass_through(not self.pass_through),
                   "passing": lambda: self.pass_through,
                   "screen": self.move_screen, "exit": self.shutdown, "target": self.open_target}
        actions.update(garage=self.show_garage, audio=self.show_audio_center, gallery=self.show_animation_gallery)
        actions.update(tasks=lambda: self.show_tools_page(3), notes=lambda: self.show_tools_page(4),
                       updates=self.check_updates, minigames=lambda: self.show_tools_page(self.tools.tabs.indexOf(self.tools.minigames_page)),
                       diagnostics=lambda: self.show_tools_page(self.tools.tabs.indexOf(self.tools.diagnostics_page)))
        self.menu = create_menu(self.window, actions, self.store.settings, QGuiApplication.screens(),
                                QSystemTrayIcon.isSystemTrayAvailable())
        self.menu.aboutToShow.connect(self.menu_opened)
        self.menu.aboutToHide.connect(lambda: self.controller.set_gate("menu", False))
        self.tray.setContextMenu(self.menu)
        if old_menu is not None:
            old_menu.deleteLater()

    def menu_opened(self):
        self.radial.hide()
        self.controller.set_gate("menu", True)
        if not self.fullscreen_active and not self.controller.inactive:
            self.controller.enter(State.LOOK_AROUND)
        self.bubble.stop()

    def show_menu(self, point):
        self.refresh_menu()
        self.menu.popup(point)

    def tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self.show_pet()
        elif reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.show_tools()

    def show_tools(self):
        self.radial.hide()
        fit_dialog(self.tools, self.window)
        self.tools.show()
        self.tools.raise_()
        self.tools.activateWindow()
        self.project_tool("clock")

    def project_tool(self, glyph):
        if self.store.settings.holograms and not self.controller.gates and not self.quiet_active:
            self.window.project(icon(glyph, color("hologram")).pixmap(32, 32))

    def show_tools_page(self, index):
        self.tools.tabs.setCurrentIndex(index)
        self.show_tools()

    def task_completed(self, entry_id):
        self.reactions.start("task")

    def launch_minigame(self, game_id):
        try:
            if not open_game(game_id):
                self.warning("O Windows não aceitou abrir o jogo no navegador.")
                return False
        except (ValueError, OSError) as error:
            self.warning(str(error))
            return False
        self.reactions.start("game")
        self.project_tool("play")
        return True

    def check_updates(self):
        try:
            self.updates.launch_center()
        except (OSError, ValueError) as error:
            QMessageBox.information(self.tools if self.tools.isVisible() else None, "Atualizações do R2", str(error))

    def show_settings(self):
        self.radial.hide()
        if self.settings_dialog is not None:
            self.settings_dialog.show()
            self.settings_dialog.raise_()
            return
        try:
            enabled = self.startup.enabled()
            status = ("Registro do Companion ativo. O Windows pode desabilitá-lo em Aplicativos de inicialização."
                      if enabled else "Registro do Companion desativado.")
        except (OSError, ValueError):
            enabled = False
            status = "Registro indisponível ou conflitante; outros registros serão preservados."
        if not self.startup.available:
            status = "Para inicialização automática, copie a versão empacotada para um local estável fora de dist/build."
        dialog = SettingsDialog(self.store.settings, self.startup.available, enabled, status, self.profile)
        self.settings_dialog = dialog
        self.controller.set_gate("settings", True)
        self.bubble.stop()
        dialog.applied.connect(self.save_settings)
        dialog.finished.connect(self.settings_closed)
        fit_dialog(dialog, self.window)
        dialog.show()

    def settings_closed(self, result):
        dialog = self.settings_dialog
        self.settings_dialog = None
        if dialog is not None:
            dialog.deleteLater()
        self.controller.set_gate("settings", False)

    def save_settings(self, settings, startup_request):
        try:
            if settings.active_droid != self.store.settings.active_droid:
                raise ValueError("O personagem mudou. Reabra Configurações para editar o personagem equipado.")
            settings.droid_preferences = deepcopy(self.store.settings.droid_preferences)
            settings.window = replace(self.store.settings.window, topmost=settings.window.topmost)
            settings.manual_position = deepcopy(self.store.settings.manual_position)
            if startup_request is not None:
                self.startup.set_enabled(startup_request)
                settings.startup = startup_request
            self.store.apply(settings)
            if not self.store.flush():
                self.settings_dialog.error.setText("Preferências aplicadas nesta sessão; não foi possível gravar o arquivo.")
        except (OSError, ValueError) as error:
            self.settings_dialog.error.setText(str(error))

    def open_target(self, target):
        if target.kind == "app":
            operation = lambda: launch(target.path)
        else:
            operation = lambda: validate_location(target.path, target.kind)
        def deliver(result):
            if isinstance(result, Exception):
                self.warning(str(result))
            elif target.kind == "app":
                if not result:
                    self.warning("O Windows não aceitou iniciar o aplicativo.")
            elif not QDesktopServices.openUrl(QUrl.fromLocalFile(str(result))):
                self.warning("O Windows não aceitou abrir o local.")
        if not self.tasks.submit(operation, deliver):
            self.warning("Aguarde a operação local em andamento.")

    def timer_completed(self, run_id):
        if self.closed:
            return
        message = f"Temporizador #{run_id} concluído."
        if not self.fullscreen_active:
            self.tray.notify(message)
        self.controller.notify(f"timer-{run_id}", message)

    def shutdown(self):
        if self.closed:
            return
        self.positioning.settle()
        self.closed = True
        self.reactions.close()
        for dialog in (self.garage_dialog, self.audio_dialog, self.gallery_dialog):
            if dialog is not None:
                dialog.close()
        if self.positioning.movement:
            self.positioning.movement.close()
        self.window.stop_effects()
        self.idle_timer.stop()
        self.desktop_timer.stop()
        self.greeting_timer.stop()
        self.awareness.close()
        self.productivity.close()
        self.controller.close()
        self.positioning.close()
        self.radial.stop()
        self.apps_panel.hide()
        self.locations_panel.hide()
        self.tasks.close()
        self.tools.stop()
        self.countdown.close()
        self.monitor.close()
        self.bubble.stop()
        self.audio.close()
        if self.settings_dialog is not None:
            self.settings_dialog.close()
        self.tray.hide()
        self.window.hide()
        self.session_events.close()
        self.qt_app.removeNativeEventFilter(self.session_events)
        self.qt_app.aboutToQuit.disconnect(self.shutdown)
        self.store.close()
        log.info("R2 Companion encerrado; timers interrompidos")
        self.qt_app.quit()


def configure_logging(directory: Path):
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    try:
        handler = RotatingFileHandler(directory / "companion.log", maxBytes=1024 * 1024,
                                      backupCount=3, encoding="utf-8")
    except OSError:
        handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(handler)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="R2 Companion — mascote local para Windows")
    parser.add_argument("--data-dir", type=Path, help="Diretório alternativo de dados, útil para testes isolados")
    parser.add_argument("--smoke-test", action="store_true", help="Executa brevemente, grava diagnóstico e encerra")
    parser.add_argument("--smoke-droids", action="store_true")
    parser.add_argument("--smoke-seconds", type=float, default=3)
    parser.add_argument("--update-center", action="store_true")
    parser.add_argument("--install-dir", type=Path)
    parser.add_argument("--owner-pid", type=int, default=0)
    parser.add_argument("--owner-start", type=int, default=0)
    parser.add_argument("--resume-update", type=Path)
    args = parser.parse_args(argv)
    if args.update_center:
        from .ui.updates import run_update_center
        return run_update_center(args.data_dir or Path.home() / "AppData/Local/R2DesktopCompanion/R2Companion",
                                 args.install_dir, args.owner_pid, args.owner_start, args.resume_update)
    if not 1 <= args.smoke_seconds <= 3600:
        parser.error("--smoke-seconds deve estar entre 1 e 3600")
    if args.smoke_test and args.data_dir is None:
        parser.error("--smoke-test requer --data-dir para isolar os dados de teste")
    if args.smoke_droids and not args.smoke_test:
        parser.error("--smoke-droids requer --smoke-test")
    app = QApplication([sys.argv[0]])
    app.setOrganizationName("R2DesktopCompanion")
    app.setApplicationName("R2Companion")
    app.setApplicationDisplayName("R2 Companion")
    app.setApplicationVersion(__version__)
    app.setQuitOnLastWindowClosed(False)
    directory = args.data_dir.resolve() if args.data_dir else Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation))
    store = ConfigStore(directory)
    if not store.acquire():
        if args.smoke_test:
            return 2
        QMessageBox.information(None, "R2 Companion", "Já existe uma instância usando este diretório de dados.")
        return 2
    configure_logging(directory)
    store.load()
    try:
        companion = Companion(app, store)
    except Exception:
        log.exception("Falha ao iniciar")
        store.close()
        if not args.smoke_test:
            QMessageBox.critical(None, "R2 Companion", "Não foi possível iniciar. Consulte companion.log no diretório de dados.")
        return 1
    if args.smoke_test:
        droid_checks = []
        if args.smoke_droids:
            for index, identifier in enumerate(companion.droids.profiles):
                def check_droid(identifier=identifier):
                    accepted = companion.equip_droid(identifier)
                    companion.window.grab().save(str(directory / f"droid-{identifier}.png"))
                    droid_checks.append({"id": identifier, "accepted": accepted, "error": companion.droid_error,
                                         "diagnostics": companion.droid_diagnostics()})
                QTimer.singleShot(200 + index * 450, check_droid)
        def finish_smoke():
            import psutil
            process = psutil.Process()
            report = {"python": sys.version, "qt": qVersion(), "platform": sys.platform,
                      "screen_count": len(QGuiApplication.screens()),
                      "screens": [{"name": s.name(), "dpr": s.devicePixelRatio(),
                                   "work_area": s.availableGeometry().getRect()} for s in QGuiApplication.screens()],
                      "visible": companion.window.isVisible(), "state": companion.controller.state.value,
                      "working_set_bytes": process.memory_info().rss,
                      "geometry": companion.window.geometry().getRect()}
            report["droids"] = droid_checks
            report["active_droid"] = companion.profile.id
            companion.window.grab().save(str(directory / "smoke.png"))
            companion.shutdown()
            report["movement_timer_after_shutdown"] = bool(getattr(companion.positioning.movement, "timer", None)
                                                          and companion.positioning.movement.timer.isActive())
            report["active_timers_after_shutdown"] = sum(t.isActive() for t in
                [companion.animation.timer, companion.behavior.timer, companion.positioning.timer,
                 companion.countdown.timer, companion.monitor.timer, companion.idle_timer,
                 companion.desktop_timer, companion.tools.clock_timer, companion.bubble.timer,
                 companion.radial.dismiss_timer, companion.greeting_timer, companion.awareness.timer,
                 companion.productivity.timer, companion.tray.notice.timer, companion.window.affection_timer,
                 companion.window.hologram_timer, companion.tools.diagnostics_page.timer, store.timer])
            (directory / "smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        QTimer.singleShot(round(args.smoke_seconds * 1000), finish_smoke)
    return app.exec()
