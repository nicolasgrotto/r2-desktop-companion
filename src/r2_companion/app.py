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
from .pet.animation import AnimationManager, load_clips
from .pet.behavior import BehaviorManager
from .pet.controller import PetController
from .pet.positioning import Positioner, detect_corner, fingerprint
from .pet.awareness import ContextReactions, fullscreen_policy
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
from .ui.theme import fit_dialog

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
        self.event_audio = False
        self.window = PetWindow()
        self.positioning = Positioner(self.window)
        self.animation = AnimationManager(load_clips(ASSETS / "characters/default/manifest.json"))
        self.behavior = BehaviorManager()
        self.controller = PetController(self.animation, self.positioning, self.behavior)
        self.bubble = Bubble()
        self.radial = RadialMenu()
        self.apps_panel = LaunchpadDialog("apps")
        self.locations_panel = LaunchpadDialog("locations")
        self.countdown = Countdown(uptime)
        self.monitor = SystemMonitor(SystemInfo())
        self.audio = AudioService(ASSETS / "sounds")
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
        self.window.set_topmost(settings.window.topmost)
        self.positioning.reconcile()
        self.audio.configure(settings.sound_enabled, deepcopy(settings.audio))
        self.tools.set_duration(settings.timer_seconds)
        self.apps_panel.set_settings(settings)
        self.locations_panel.set_settings(settings)
        self.behavior.schedule(self.controller.state == State.IDLE and not self.controller.gates and not self.controller.paused)
        self.controller.update_inactivity(0)
        self.session_events.bind(int(self.window.winId()))
        self.refresh_menu()
        if not self.initializing:
            self.check_desktop()

    def save_position(self, saved):
        if self.closed:
            return
        settings = deepcopy(self.store.settings)
        settings.window = saved
        self.store.apply(settings, notify=False)

    def save_duration(self, seconds):
        settings = deepcopy(self.store.settings)
        settings.timer_seconds = seconds
        self.store.apply(settings, notify=False)

    def state_changed(self, state):
        previous_sleep = self.audio.sleeping
        self.audio.set_context(bool(self.controller.gates - {"radial"}) or self.fullscreen_active, state == State.SLEEP)
        if state == State.SLEEP and not previous_sleep:
            self.audio.play("sleep", "enter")
        elif state in {State.WAKE, State.GREETING}:
            self.audio.play("sleep", "wake") if state == State.WAKE else self.audio.play("reactions", "celebrate")
        elif state == State.WALK:
            self.audio.play("movement", "servo")
        elif state == State.INTERACT:
            self.audio.play("reactions", "click")
        elif state == State.CONFUSED:
            self.audio.play("reactions", "confused")
        elif state == State.SURPRISED:
            self.audio.play("reactions", "surprise")
        elif state in {State.HAPPY, State.CURIOUS, State.WORK} and not self.event_audio:
            self.audio.play("idle")
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

    def check_idle(self):
        seconds = idle_seconds()
        self.controller.update_inactivity(seconds if seconds is not None else time.monotonic() - self.last_activity)

    def check_desktop(self):
        if self.closed:
            return
        active = (self.store.settings.suppress_fullscreen
                  and foreground_fullscreen(int(self.window.winId())))
        screen_name = "" if self.positioning.screen is None else fingerprint(self.positioning.screen)
        action = fullscreen_policy(self.store.settings.fullscreen_mode,
                                   self.store.settings.manual_position, screen_name) if active else ""
        self.fullscreen_active = active
        if active:
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
        self.tray.notifications_enabled = not (self.fullscreen_active or self.session_hidden)
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
        actions.update(tasks=lambda: self.show_tools_page(3), notes=lambda: self.show_tools_page(4),
                       updates=self.check_updates)
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

    def show_tools_page(self, index):
        self.tools.tabs.setCurrentIndex(index)
        self.show_tools()

    def task_completed(self, entry_id):
        self.event_audio = True
        try:
            if self.controller.react(State.HAPPY):
                self.audio.play("reactions", "celebrate")
        finally:
            self.event_audio = False

    def check_updates(self):
        try:
            self.updates.launch()
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
        dialog = SettingsDialog(self.store.settings, self.startup.available, enabled, status)
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
        self.audio.play("notifications", "timer")
        self.controller.notify(f"timer-{run_id}", message)

    def shutdown(self):
        if self.closed:
            return
        self.positioning.settle()
        self.closed = True
        self.idle_timer.stop()
        self.desktop_timer.stop()
        self.greeting_timer.stop()
        self.awareness.close()
        self.productivity.close()
        self.controller.close()
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
    parser.add_argument("--smoke-seconds", type=float, default=3)
    args = parser.parse_args(argv)
    if not 1 <= args.smoke_seconds <= 3600:
        parser.error("--smoke-seconds deve estar entre 1 e 3600")
    if args.smoke_test and args.data_dir is None:
        parser.error("--smoke-test requer --data-dir para isolar os dados de teste")
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
            companion.window.grab().save(str(directory / "smoke.png"))
            companion.shutdown()
            report["active_timers_after_shutdown"] = sum(t.isActive() for t in
                [companion.animation.timer, companion.behavior.timer, companion.positioning.timer,
                 companion.countdown.timer, companion.monitor.timer, companion.idle_timer,
                 companion.desktop_timer, companion.tools.clock_timer, companion.bubble.timer,
                 companion.radial.dismiss_timer, companion.greeting_timer, companion.awareness.timer,
                 companion.productivity.timer, companion.tray.notice.timer, store.timer])
            (directory / "smoke.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        QTimer.singleShot(round(args.smoke_seconds * 1000), finish_smoke)
    return app.exec()
