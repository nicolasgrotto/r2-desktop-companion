"""Qt adapter for presence; owns no animation, countdown or persistence timer."""
from dataclasses import replace

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QSystemTrayIcon

from .presence import FullscreenAction, PresenceContext, PresenceMode, PresencePolicy
from .state import State
from ..core.language import tr

class PresenceRuntime:
    def __init__(self, companion):
        self.companion = companion
        self.policy = PresencePolicy()
        document = companion.companion_state.data
        self.context = PresenceContext(manual_mode=document["presence"]["mode"],
                                      reduced_motion=document["accessibility"]["reduced_motion"])
        self.decision = self.policy.evaluate(self.context)
        self.refreshing = False
        self.focus_override = None
        companion.companion_state.changed.connect(self.saved_changed)
        companion.controller.context_changed.connect(self.refresh)

    def saved_changed(self, document):
        self.context = replace(self.context, reduced_motion=document["accessibility"]["reduced_motion"])
        if document["presence"]["mode"] != self.context.manual_mode:
            self.context = self.context.select_mode(document["presence"]["mode"])
        self.refresh()

    def select_mode(self, mode):
        self.context = self.context.select_mode(mode)
        self.companion.companion_state.update("presence", {"mode": self.context.manual_mode.value})
        self.refresh()

    def update_focus(self, session):
        requested = session.override_id if session else None
        previous = self.focus_override
        if requested == previous:
            return
        self.focus_override = requested
        if previous is not None:
            self.context = self.context.end_focus(previous)
        if requested is not None:
            self.context = self.context.begin_focus(requested)
        self.refresh()

    def refresh(self):
        c = self.companion
        if self.refreshing or c.closed:
            return
        self.refreshing = True
        try:
            tray = QSystemTrayIcon.isSystemTrayAvailable()
            if not tray:
                c.user_hidden = False
                if c.pass_through:
                    c.set_pass_through(False)
            settings = c.store.settings
            self.context = PresenceContext(
                manual_mode=self.context.manual_mode, focus_session_id=self.context.focus_session_id,
                quiet_hours=c.quiet_active, hidden=c.user_hidden or not QGuiApplication.screens(),
                suspended=c.session_hidden, fullscreen=FullscreenAction(c.fullscreen_action or "none"),
                transient_gates=frozenset(c.controller.gates - {"hidden", "session", "quiet_hours", "fullscreen"}),
                autonomy_enabled=settings.behavior.frequency != "off", movement_enabled=settings.behavior.movement,
                paused=c.controller.paused, sound_enabled=settings.sound_enabled, muted=settings.audio.muted,
                tray_available=tray,
                reduced_motion=self.context.reduced_motion,
                media_playing=c.media.view.playing,
            )
            update = self.policy.update(self.context)
            previous, self.decision = self.decision, update.decision
            d = self.decision
            reduced = self.context.reduced_motion
            if reduced and not c.positioning.reduced_motion and c.positioning.movement:
                c.positioning.movement.stop()
            c.positioning.reduced_motion = reduced
            c.controller.set_presence(d)
            c.animation.set_reduced_motion(reduced)
            c.audio.presence = d
            c.audio.spontaneous = c.controller.action_spontaneous
            c.audio.set_context(bool(c.controller.gates - {"radial", "hidden"}) or c.fullscreen_active
                                or not d.character_visible or d.mode == PresenceMode.PRESENTATION,
                                c.controller.state == State.SLEEP or c.controller.inactive)
            if not (d.spontaneous_audio if c.audio.spontaneous else d.explicit_audio):
                c.audio.stop()
            c.tray.notifications_enabled = d.notifications
            if not d.notifications:
                c.tray.notice.stop()
            c.window.set_projection_suspended(not d.passive_surfaces)
            c.controller.set_gate("hidden", not d.character_visible)
            if not d.character_visible:
                c.radial.hide()
                c.bubble.stop()
                c.window.hide()
            elif not c.window.isVisible():
                c.window.show()
            if not d.continuous_effects:
                c.window.sleep_effect.set_active(False)
                c.window.steam.set_active(False)
            elif not previous.continuous_effects:
                c.window.sleep_effect.set_active(c.controller.state == State.SLEEP)
                c.window.steam.set_active(c.controller.state == State.OVERHEAT)
            if d.reason == "presentation_recovery":
                c.animation.stop()
                c.positioning.stop()
            elif previous.reason == "presentation_recovery" and d.character_visible:
                c.animation.play(c.controller.state, c.controller.token)
            if update.decision_changed:
                c.tray.setToolTip(f"{c.profile.name} · {d.reason_text}")
                c.window.setToolTip(tr("{0} · {1}\nBotão direito para opções", c.profile.name, d.reason_text))
            self.update_controls()
        finally:
            self.refreshing = False
        c.radial.set_reduced_motion(self.context.reduced_motion)

    def update_controls(self):
        c = self.companion
        summary = self.decision.reason_text
        if self.decision.reason == "transient":
            summary = self.policy.evaluate(replace(self.context, transient_gates=frozenset())).reason_text
        if c.menu is not None and hasattr(c.menu, "presence_actions"):
            for mode, action in c.menu.presence_actions.items():
                action.setChecked(mode == self.context.manual_mode)
            c.menu.presence_status.setText(summary)
            if hasattr(c.menu, "status_summary"):
                c.menu.status_summary.setText(summary)
        if c.settings_dialog is not None:
            dialog = c.settings_dialog
            dialog.presence_status.setText(summary)
            if dialog.presence_mode.currentData() == dialog.presence_original:
                dialog.presence_original = self.context.manual_mode.value
                dialog.presence_mode.setCurrentIndex(dialog.presence_mode.findData(dialog.presence_original))
