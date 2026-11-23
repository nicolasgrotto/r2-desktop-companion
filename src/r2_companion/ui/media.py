from PySide6.QtCore import QSignalBlocker, Signal
from PySide6.QtWidgets import QCheckBox, QComboBox, QPushButton, QVBoxLayout, QWidget

from ..features.projections import ProjectionModel
from ..services.media import MediaCommand
from .theme import ActionRow, card, label
from ..core.language import tr


PLAYBACK = {
    "playing": "Reproduzindo", "paused": "Pausada", "stopped": "Parada",
    "changing": "Mudando de faixa", "opened": "Sessão aberta", "closed": "Sessão encerrada",
}
ERRORS = {
    "integration_unavailable": "Controle de mídia indisponível no Windows.",
    "session_unavailable": "O Windows não conseguiu consultar a sessão de mídia.",
    "session_missing": "A sessão fixada foi encerrada. Escolha outra sessão ou Automático.",
    "ambiguous_source": "O Windows encontrou sessões com a mesma origem. Os comandos estão indisponíveis para esta origem.",
    "metadata_timeout": "O aplicativo demorou para informar os dados da faixa.",
    "metadata_unavailable": "O aplicativo não pôde fornecer os dados da faixa.",
    "refused": "O aplicativo recusou o comando.",
    "unsupported": "O aplicativo deixou de oferecer este comando.",
    "command_timeout": "O aplicativo demorou para responder ao comando.",
    "command_failed": "Não foi possível enviar o comando.",
    "stale": "A sessão mudou. Confira o aplicativo selecionado.",
}


def playback_label(snapshot):
    return tr(PLAYBACK.get(snapshot.playback, "Estado de reprodução indisponível"))


def music_projection(view):
    snapshot = view.snapshot
    if view.status != "ready" or snapshot is None or snapshot.playback in {"stopped", "closed"}:
        return None
    lines = tuple(value for value in (snapshot.title, snapshot.artist) if value)
    return ProjectionModel("music", tr("Música"), (*lines, playback_label(snapshot)))


class MediaPage(QWidget):
    enable_requested = Signal(bool)
    projection_requested = Signal()
    projection_end_requested = Signal()

    def __init__(self, service):
        super().__init__()
        self.service = service
        self.projections_enabled = True
        self.projecting = False
        self._shown = None
        self._options = None
        self._command_feedback = ""

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 16, 0, 0)
        panel, contents = card()
        layout.addWidget(panel)
        layout.addStretch()
        self.enabled = QCheckBox(tr("Ativar controle musical do Windows"))
        self.enabled.toggled.connect(self.enable_requested.emit)
        contents.addWidget(self.enabled)

        self.sessions = QComboBox()
        self.sessions.setAccessibleName(tr("Sessão de mídia"))
        self.sessions.setAccessibleDescription(tr("Automático acompanha a sessão indicada pelo Windows."))
        self.sessions.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.sessions.setMinimumContentsLength(18)
        self.sessions.activated.connect(self._select)
        caption = label(tr("&Sessão de mídia"))
        caption.setBuddy(self.sessions)
        contents.addWidget(caption)
        contents.addWidget(self.sessions)

        self.track = label("", "title")
        self.artist = label("", "muted")
        self.status = label("")
        self.feedback = label("", "muted")
        for widget in (self.track, self.artist, self.status, self.feedback):
            contents.addWidget(widget)

        transport = ActionRow()
        self.controls = {}
        for action, title in ((MediaCommand.PREVIOUS, tr("Anterior")), (MediaCommand.PLAY, tr("Reproduzir")),
                              (MediaCommand.PAUSE, tr("Pausar")), (MediaCommand.NEXT, tr("Próxima"))):
            button = QPushButton(title)
            button.clicked.connect(lambda checked=False, action=action: self._command(action))
            self.controls[action] = button
            transport.addWidget(button)
        contents.addWidget(transport)
        tools = ActionRow()
        self.project = QPushButton(tr("Projetar música"))
        self.project.clicked.connect(self.projection_requested.emit)
        self.end_project = QPushButton(tr("Encerrar projeção de música"))
        self.end_project.clicked.connect(self.projection_end_requested.emit)
        self.retry = QPushButton(tr("Tentar novamente"))
        self.retry.setAccessibleDescription(tr("Atualiza a conexão ou a sessão de mídia."))
        self.retry.clicked.connect(self._retry)
        tools.addWidget(self.project)
        tools.addWidget(self.end_project)
        tools.addWidget(self.retry)
        contents.addWidget(tools)
        service.changed.connect(self.refresh)
        service.command_finished.connect(self._finished)
        self.refresh()

    def _select(self, index):
        self.service.select(self.sessions.itemData(index))

    def _command(self, action):
        snapshot = self._shown
        if snapshot is not None:
            self._command_feedback = ""
            if not self.service.command(snapshot, action):
                self._command_feedback = tr(ERRORS["stale"])
                self.refresh()

    def _finished(self, snapshot, result):
        shown = self._shown
        if shown and shown.generation == snapshot.generation and shown.session == snapshot.session:
            self._command_feedback = tr(ERRORS.get(result, ""))
            self.refresh()

    def _retry(self):
        self._command_feedback = ""
        self.service.retry()
        self.refresh()

    def set_projecting(self, projecting):
        if self.projecting != projecting:
            previous = self.end_project if self.projecting else self.project
            focused = previous.hasFocus()
            self.projecting = projecting
            self.update_projection_controls()
            if focused:
                (self.end_project if projecting else self.project).setFocus()

    def update_projection_controls(self):
        self.project.setVisible(not self.projecting)
        self.project.setEnabled(self.projections_enabled and music_projection(self.service.view) is not None)
        self.end_project.setVisible(self.projecting)

    def _sessions(self, view):
        options = (view.sessions, view.pinned)
        if options == self._options:
            return
        self._options = options
        with QSignalBlocker(self.sessions):
            self.sessions.clear()
            self.sessions.addItem(tr("Automático"), None)
            for session in view.sessions:
                self.sessions.addItem(session.source or tr("Origem indisponível"), session)
            if view.pinned and view.pinned not in view.sessions:
                self.sessions.addItem(tr("Sessão fixada indisponível"), view.pinned)
            index = self.sessions.findData(view.pinned) if view.pinned else 0
            self.sessions.setCurrentIndex(index)

    def refresh(self):
        view = self.service.view
        snapshot = view.snapshot
        previous = self._shown
        if (snapshot is None or previous is None or snapshot.generation != previous.generation):
            self._command_feedback = ""
        self._shown = snapshot
        with QSignalBlocker(self.enabled):
            self.enabled.setChecked(view.status != "disabled")
        self._sessions(view)
        self.sessions.setEnabled(view.status == "ready")

        for widget, value in ((self.track, snapshot.title if snapshot else None),
                              (self.artist, snapshot.artist if snapshot else None)):
            widget.setText(value or "")
            widget.setVisible(bool(value))
        pending = snapshot is not None and self.service.pending(snapshot.session)
        if snapshot:
            source = snapshot.session.source
            status = playback_label(snapshot)
            if source:
                status = f"{status} · {source}"
        else:
            status = {
                "disabled": tr("Ative para controlar o aplicativo que publica mídia no Windows."),
                "connecting": tr("Conectando ao controle de mídia do Windows…"),
                "unavailable": tr("Controle musical indisponível"),
            }.get(view.status, tr("Nenhuma sessão de mídia disponível"))
        self.status.setText(status)
        error = view.error or (snapshot.metadata_error if snapshot else None)
        feedback = tr("Aguardando resposta do aplicativo…") if pending else self._command_feedback or tr(ERRORS.get(error, ""))
        self.feedback.setText(feedback)
        self.feedback.setVisible(bool(feedback))
        for action, button in self.controls.items():
            button.setEnabled(bool(snapshot and snapshot.capabilities.allows(action) and not pending))
        self.update_projection_controls()
        self.retry.setEnabled(not pending and view.status in {"ready", "unavailable"} and
                              (bool(feedback) or snapshot is None))
