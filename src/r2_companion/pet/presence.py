"""Pure presence decisions; integration with Qt belongs to the composition layer.

Permissions are additional ceilings, not commands. Existing controller gates,
sleep/wake rules, action tokens, audio categories and cooldowns still apply.
This module never changes timers, windows, external playback or stored settings.
"""
from dataclasses import dataclass, replace
from enum import StrEnum
from ..core.language import tr


class PresenceMode(StrEnum):
    FREE = "free"
    FOCUS = "focus"
    PRESENTATION = "presentation"


class FullscreenAction(StrEnum):
    NONE = "none"
    HIDE = "hide"
    CORNER = "corner"
    STAY = "stay"


@dataclass(frozen=True)
class PresenceContext:
    manual_mode: PresenceMode = PresenceMode.FREE
    focus_session_id: str | None = None
    quiet_hours: bool = False
    fullscreen: FullscreenAction = FullscreenAction.NONE
    hidden: bool = False
    suspended: bool = False  # Includes a locked Windows session.
    reduced_motion: bool = False
    media_playing: bool = False
    transient_gates: frozenset[str] = frozenset()
    autonomy_enabled: bool = True
    movement_enabled: bool = True
    paused: bool = False
    sound_enabled: bool = False
    muted: bool = False
    tray_available: bool = True

    def __post_init__(self):
        object.__setattr__(self, "manual_mode", PresenceMode(self.manual_mode))
        object.__setattr__(self, "fullscreen", FullscreenAction(self.fullscreen))
        gates = frozenset(self.transient_gates)
        if any(not isinstance(gate, str) or not gate for gate in gates):
            raise ValueError(tr("Bloqueio transitório inválido."))
        object.__setattr__(self, "transient_gates", gates)
        if self.focus_session_id is not None:
            _validate_session_id(self.focus_session_id)

    @property
    def effective_mode(self) -> PresenceMode:
        # Timer focus cannot make manual presentation less restrictive.
        if self.manual_mode == PresenceMode.PRESENTATION:
            return PresenceMode.PRESENTATION
        return PresenceMode.FOCUS if self.focus_session_id else self.manual_mode

    def select_mode(self, mode: PresenceMode) -> "PresenceContext":
        """Even selecting the same mode revokes temporary session ownership."""
        return replace(self, manual_mode=PresenceMode(mode), focus_session_id=None)

    def begin_focus(self, session_id: str) -> "PresenceContext":
        _validate_session_id(session_id)
        return replace(self, focus_session_id=session_id)

    def end_focus(self, session_id: str) -> "PresenceContext":
        """Pause/completion/cancellation releases only this session's override."""
        _validate_session_id(session_id)
        return replace(self, focus_session_id=None) if self.focus_session_id == session_id else self


def _validate_session_id(value):
    if (not isinstance(value, str) or not 1 <= len(value) <= 80
            or any(ord(character) < 32 for character in value)):
        raise ValueError(tr("Referência de sessão inválida."))


@dataclass(frozen=True)
class PresenceDecision:
    mode: PresenceMode
    autonomous_movement: bool
    initiative: bool
    spontaneous_audio: bool
    explicit_reactions: bool
    explicit_audio: bool
    notifications: bool
    character_visible: bool
    passive_surfaces: bool
    continuous_effects: bool
    reason: str
    reason_text: str


@dataclass(frozen=True)
class PresenceUpdate:
    decision: PresenceDecision
    context_changed: bool
    decision_changed: bool


class PresencePolicy:
    """evaluate is pure; update optionally deduplicates observations for adapters.

    FullscreenAction is the resolved result of the existing fullscreen_policy,
    not the saved auto/corner/quiet preference. Visibility of tools and tray,
    manual dragging, selected projection and logical countdown are not governed
    here. A false passive_surfaces suspends presentation, not its selection.
    Initiative covers stationary contextual poses; focus still permits these.
    Locomotion and spontaneous voice must also check their separate permissions.
    Explicit audio/notifications remain subject to AudioService categories and
    controller eligibility. Adapters must not translate focus into a total gate.
    """

    def __init__(self):
        self._context: PresenceContext | None = None
        self._decision: PresenceDecision | None = None

    @staticmethod
    def evaluate(context: PresenceContext) -> PresenceDecision:
        mode = context.effective_mode
        recovery = mode == PresenceMode.PRESENTATION and not context.tray_available
        fullscreen = context.fullscreen != FullscreenAction.NONE
        visible = not (context.suspended or context.hidden
                       or mode == PresenceMode.PRESENTATION and not recovery
                       or context.fullscreen == FullscreenAction.HIDE and not recovery)
        interactive = visible and not recovery and not fullscreen and not context.transient_gates
        initiative = (interactive and context.autonomy_enabled
                      and not context.paused and not context.quiet_hours)
        audio = interactive and context.sound_enabled and not context.muted and not context.quiet_hours
        passive = interactive
        # The first active restriction is a stable, content-free status reason.
        reasons = (
            (context.suspended, "suspended", tr("Sessão suspensa ou bloqueada")),
            (context.hidden, "hidden", tr("Personagem oculto")),
            (recovery, "presentation_recovery", tr("Apresentação: bandeja indisponível; mascote visível para acesso")),
            (mode == PresenceMode.PRESENTATION, "presentation", tr("Em apresentação")),
            (context.quiet_hours, "quiet_hours", tr("Horário de silêncio")),
            (fullscreen, "fullscreen", tr("Tela cheia")),
            (bool(context.transient_gates), "transient", tr("Interação em andamento")),
            (context.paused, "paused", tr("Autonomia pausada")),
            (mode == PresenceMode.FOCUS, "focus", tr("Em foco")),
            (context.reduced_motion, "reduced_motion", tr("Movimento reduzido")),
            (context.media_playing, "media_playing", tr("Música em reprodução")),
            (not context.autonomy_enabled, "autonomy_disabled", tr("Autonomia desativada")),
            (True, "free", tr("Livre")),
        )
        _, reason, text = next(item for item in reasons if item[0])
        return PresenceDecision(
            mode=mode,
            autonomous_movement=(initiative and context.movement_enabled
                                 and mode == PresenceMode.FREE and not context.reduced_motion),
            initiative=initiative,
            spontaneous_audio=(audio and initiative and mode == PresenceMode.FREE
                               and not context.media_playing),
            explicit_reactions=interactive,
            explicit_audio=audio,
            notifications=interactive and not context.quiet_hours,
            character_visible=visible,
            passive_surfaces=passive,
            continuous_effects=passive and not context.reduced_motion,
            reason=reason,
            reason_text=text,
        )

    def update(self, context: PresenceContext) -> PresenceUpdate:
        if context == self._context and self._decision is not None:
            return PresenceUpdate(self._decision, False, False)
        decision = self.evaluate(context)
        changed = decision != self._decision
        self._context, self._decision = context, decision
        return PresenceUpdate(decision, True, changed)
