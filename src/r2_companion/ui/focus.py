from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QMessageBox, QPushButton, QSpinBox, QVBoxLayout, QWidget

from ..features.focus import CountdownConflict, FOCUS_SECONDS, FocusPhase
from ..features.timer import TimerState
from .theme import ActionRow, card, configure_form, form_row, label


def confirm_countdown(parent, command, *, report):
    """Ask once for the exact run returned by the service."""
    try:
        result = command()
        if isinstance(result, CountdownConflict):
            current = "uma sessão de foco" if result.session_id else "um temporizador"
            answer = QMessageBox.question(
                parent, "Substituir contagem?",
                f"Já existe {current} com contagem em andamento ou em pausa. Deseja substituir essa contagem?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                return None
            result = command(replace_run_id=result.run_id)
            if not isinstance(result, int):
                report("A contagem mudou. Acione o controle novamente para continuar.")
                return None
        return result
    except ValueError as error:
        report(str(error))
        return None


class FocusPage(QWidget):
    projection_requested = Signal()
    task_finished = Signal()

    def __init__(self, focus, format_time):
        super().__init__()
        self.focus = focus
        self.format_time = format_time
        self.projections_enabled = True
        layout = QVBoxLayout(self)
        panel, body = card()
        layout.addWidget(panel)
        self.summary = label("Foco", "title")
        body.addWidget(self.summary)
        self.task_caption = label("", "muted")
        body.addWidget(self.task_caption)

        self.setup = QWidget()
        form = QFormLayout(self.setup)
        form.setContentsMargins(0, 0, 0, 0)
        configure_form(form)
        self.task = QComboBox()
        self.task.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.task.setMinimumContentsLength(13)
        self.duration = QSpinBox()
        self.duration.setRange(1, 1440)
        self.duration.setValue(FOCUS_SECONDS // 60)
        self.duration.setSuffix(" min")
        form_row(form, "&Tarefa da sessão de foco", self.task)
        form_row(form, "&Duração do foco em minutos", self.duration)
        body.addWidget(self.setup)

        actions = ActionRow()
        self.start_button = QPushButton("Iniciar foco")
        self.start_button.setProperty("role", "primary")
        self.start_button.clicked.connect(self.start)
        self.pause_button = QPushButton("Pausar foco")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.stop_button = QPushButton("Encerrar sessão")
        self.stop_button.clicked.connect(self.stop)
        self.projection_button = QPushButton("Projetar foco")
        self.projection_button.clicked.connect(self.projection_requested)
        self.next_button = QPushButton("Iniciar intervalo")
        self.next_button.clicked.connect(self.start_next)
        self.finish_task_button = QPushButton("Concluir tarefa")
        self.finish_task_button.clicked.connect(self.finish_task)
        self.dismiss_button = QPushButton("Fechar indicação")
        self.dismiss_button.clicked.connect(self.dismiss)
        self.recover_button = QPushButton("Recuperar sessão")
        self.recover_button.clicked.connect(self.recover)
        self.discard_button = QPushButton("Descartar recuperação")
        self.discard_button.clicked.connect(self.discard_recovery)
        for button in (self.start_button, self.pause_button, self.stop_button, self.projection_button,
                       self.next_button, self.finish_task_button, self.dismiss_button,
                       self.recover_button, self.discard_button):
            button.setAutoDefault(False)
            actions.addWidget(button)
        body.addWidget(actions)
        self.message = label("", "muted")
        body.addWidget(self.message)
        layout.addStretch()
        focus.changed.connect(self.refresh)
        focus.recovery_changed.connect(self.refresh)
        focus.countdown.changed.connect(self.refresh_time)
        focus.productivity.tasks_changed.connect(self.refresh_tasks)
        self.refresh_tasks()

    def refresh_tasks(self):
        selected = self.task.currentData()
        self.task.clear()
        self.task.addItem("Sem tarefa", None)
        for task in self.focus.productivity.data["tasks"]:
            self.task.addItem(task["text"], task["id"])
        self.select_task(selected)
        self.refresh()

    def select_task(self, task_id):
        self.task.setCurrentIndex(max(0, self.task.findData(task_id)))

    def refresh_time(self):
        session = self.focus.session
        if session:
            phase = "Foco" if session.phase == FocusPhase.FOCUS else "Intervalo"
            text = f"{phase} · {session.state.value} · {self.format_time(self.focus.countdown.remaining)}"
            if text != self.summary.text():
                self.summary.setText(text)

    def refresh(self, *_):
        session, offer = self.focus.session, self.focus.recovery
        active = session is not None and session.state in (TimerState.RUNNING, TimerState.PAUSED)
        done = session is not None and session.state == TimerState.COMPLETED
        task_id = session.task_id if session else offer.task_id if offer else None
        task = self.focus.productivity.task(task_id)
        self.task_caption.setText(task["text"] if task else "")
        self.task_caption.setVisible(task is not None)
        if offer:
            phase = "Foco" if offer.phase == FocusPhase.FOCUS else "Intervalo"
            status = f"{self.format_time(offer.remaining)} restantes" if offer.remaining else "Sessão concluída"
            self.summary.setText(f"Recuperação disponível · {phase} · {status}")
        elif session:
            self.refresh_time()
        else:
            self.summary.setText("Configurar sessão de foco")
        ready = session is None and offer is None
        self.setup.setVisible(ready)
        self.start_button.setVisible(ready)
        self.recover_button.setVisible(offer is not None)
        self.discard_button.setVisible(offer is not None)
        action = "Retomar" if active and session.state == TimerState.PAUSED else "Pausar"
        self.pause_button.setText(f"{action} sessão")
        self.pause_button.setVisible(active)
        self.stop_button.setVisible(active)
        self.projection_button.setVisible(active)
        self.projection_button.setEnabled(self.projections_enabled)
        self.dismiss_button.setVisible(done)
        self.next_button.setVisible(done)
        self.next_button.setText("Iniciar intervalo" if done and session.next_phase == FocusPhase.BREAK
                                 else "Iniciar novo ciclo")
        self.finish_task_button.setVisible(bool(done and session.phase == FocusPhase.FOCUS and task and not task["done"]))

    def start(self):
        self.start_for(self.task.currentData(), self.duration.value() * 60)

    def start_for(self, task_id, seconds=FOCUS_SECONDS):
        self.select_task(task_id)
        if self.focus.recovery:
            self.recover_button.setFocus()
            return
        self.message.clear()
        result = confirm_countdown(
            self, lambda **confirmation: self.focus.start_focus(seconds, task_id=task_id, **confirmation),
            report=self.message.setText,
        )
        if result is not None:
            self.pause_button.setFocus()

    def recover(self):
        self.message.clear()
        result = confirm_countdown(self, self.focus.recover, report=self.message.setText)
        if result is not None:
            button = self.pause_button if self.focus.session.state == TimerState.PAUSED else self.next_button
            button.setFocus()

    def discard_recovery(self):
        self.focus.discard_recovery()
        self.start_button.setFocus()

    def toggle_pause(self):
        session = self.focus.session
        if session:
            action = self.focus.resume if session.state == TimerState.PAUSED else self.focus.pause
            action(session.run_id)

    def stop(self):
        if session := self.focus.session:
            self.focus.cancel(session.run_id)
            self.start_button.setFocus()

    def dismiss(self):
        if session := self.focus.session:
            self.focus.dismiss(session.run_id)
            self.start_button.setFocus()

    def start_next(self):
        if session := self.focus.session:
            if self.focus.start_next_phase(session.run_id) is not None:
                self.pause_button.setFocus()

    def finish_task(self):
        if session := self.focus.session:
            if self.focus.complete_task(session.run_id):
                self.task_finished.emit()
                self.message.setText("Tarefa concluída.")
                self.next_button.setFocus()
