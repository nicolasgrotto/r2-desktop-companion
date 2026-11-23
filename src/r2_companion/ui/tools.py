import math

from PySide6.QtCore import QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QDialog, QHBoxLayout, QPlainTextEdit, QProgressBar,
                              QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..features.clock import local_clock
from ..features.timer import TimerState
from .theme import ActionRow, apply_theme, card, header, icon, label, scrollable
from .productivity import NotesPage, TasksPage
from .minigames import MinigamesPage
from .diagnostics import DiagnosticsPage
from .data_transfer import DataPage
from .focus import FocusPage, confirm_countdown
from .media import MediaPage
from ..droids.themes import color, styled, theme_manager
from ..core.language import tr


def timer_text(seconds: float) -> str:
    hours, rest = divmod(max(0, math.ceil(seconds)), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


class TimerDial(QWidget):
    def __init__(self):
        super().__init__()
        theme_manager().scale_changed.connect(self.resize_dial)
        self.resize_dial()
        self.value = 300
        self.total = 300
        self.status = tr("PRONTO")

    def resize_dial(self, *_):
        dip = theme_manager().dip
        self.setMinimumSize(dip(144), dip(190))
        self.updateGeometry()
        self.update()

    def sizeHint(self):
        dip = theme_manager().dip
        return QSize(dip(190), dip(220))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        dip = theme_manager().dip
        side = min(self.width() - dip(20), self.height() - dip(24))
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        p.setPen(QPen(QColor(color("border", self)), 9))
        p.drawEllipse(rect)
        p.setPen(QPen(QColor(color("primary", self)), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        progress = max(0, min(1, self.value / max(1, self.total)))
        p.drawArc(rect, 90 * 16, -round(progress * 360 * 16))
        p.setPen(QColor(color("text", self)))
        timer_font = QFont("Consolas")
        timer_font.setPixelSize(dip(34 if self.value < 3600 else 25))
        timer_font.setWeight(QFont.Weight.Bold)
        p.setFont(timer_font)
        p.drawText(rect.translated(0, -dip(8)), Qt.AlignmentFlag.AlignCenter, timer_text(self.value))
        p.setPen(QColor(color("muted", self)))
        status_font = QFont("Segoe UI")
        status_font.setPixelSize(dip(11))
        status_font.setWeight(QFont.Weight.DemiBold)
        p.setFont(status_font)
        p.drawText(rect.adjusted(0, dip(55), 0, 0), Qt.AlignmentFlag.AlignCenter, self.status)


class ToolsDialog(QDialog):
    duration_selected = Signal(int)

    def __init__(self, countdown, monitor, duration: int, productivity=None, project_timer=False, data_transfer=None,
                 focus=None, media=None, companion_state=None):
        super().__init__()
        self.setWindowTitle(tr("Central de ferramentas · R2 Companion"))
        self.resize(760, 650)
        apply_theme(self)
        self.countdown, self.monitor = countdown, monitor
        self.focus = focus
        self.project_timer = QCheckBox(tr("Projetar timer"))
        self.project_timer.setChecked(project_timer)
        self.project_timer.setToolTip(tr("Exibir a contagem no holograma do droide até terminar."))
        self.project_timer.setAccessibleDescription(self.project_timer.toolTip())
        self.battery = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        outer.addWidget(self.scroll_area)
        body = QWidget()
        self.scroll_area.setWidget(body)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(14, 18, 14, 18)
        layout.setSpacing(14)
        layout.addWidget(header(tr("Central de ferramentas"), tr("Seu tempo e seu computador, em sintonia.")))
        self.tabs = QTabWidget()
        self.tabs.tabBar().setAccessibleName(tr("Páginas da central de ferramentas"))
        self.tabs.addTab(self.overview(), icon("clock"), tr("Relógio"))
        self.tabs.addTab(self.timer_page(), icon("play"), tr("Temporizador"))
        self.tabs.addTab(self.system_page(), icon("system"), tr("Sistema"))
        if productivity is not None:
            self.tasks_page = TasksPage(productivity, focus_available=focus is not None)
            self.notes_page = NotesPage(productivity, data_transfer)
            self.tasks_page.setProperty("characterLiteral", True)
            self.notes_page.setProperty("characterLiteral", True)
            self.tabs.addTab(scrollable(self.tasks_page), tr("Tarefas"))
            self.tabs.addTab(scrollable(self.notes_page), tr("Notas"))
        self.minigames_page = MinigamesPage(store=companion_state)
        self.diagnostics_page = DiagnosticsPage()
        self.tabs.addTab(self.minigames_page, "Minigames")
        self.tabs.addTab(self.diagnostics_page, tr("Diagnóstico"))
        self.pages = {"clock": self.tabs.widget(0), "timer": self.tabs.widget(1),
                      "system": self.tabs.widget(2), "minigames": self.minigames_page,
                      "diagnostics": self.diagnostics_page}
        if productivity is not None:
            self.pages.update(tasks=self.tabs.widget(3), notes=self.tabs.widget(4))
        if data_transfer is not None:
            data_page = DataPage(data_transfer)
            self.tabs.addTab(data_page, tr("Dados"))
            self.pages["data"] = data_page
        if focus is not None:
            self.focus_page = FocusPage(focus, timer_text)
            self.focus_page.setProperty("characterLiteral", True)
            self.pages["focus"] = scrollable(self.focus_page)
            self.tabs.addTab(self.pages["focus"], tr("Foco"))
            self.tasks_page.focus_requested.connect(self.start_task_focus)
            self.focus_page.task_finished.connect(self.tasks_page.render)
        if media is not None:
            self.media_page = MediaPage(media)
            self.media_page.setProperty("characterLiteral", True)
            self.pages["media"] = scrollable(self.media_page)
            self.tabs.addTab(self.pages["media"], tr("Música"))
        self.tabs.setUsesScrollButtons(True)
        layout.addWidget(self.tabs, 1)
        self.completion = label(tr("Tudo pronto. Escolha uma ferramenta para começar."), "muted")
        self.completion.setWordWrap(True)
        layout.addWidget(self.completion)
        self.projection_details = QPlainTextEdit()
        self.projection_details.setReadOnly(True)
        self.projection_details.setTabChangesFocus(True)
        self.projection_details.setAccessibleName(tr("Conteúdo da projeção"))
        self.projection_details.setMaximumHeight(135)
        self.projection_details.hide()
        layout.addWidget(self.projection_details)
        self.clock_timer = QTimer(self)
        self.clock_timer.setInterval(1000)
        self.clock_timer.timeout.connect(self.refresh_clock)
        countdown.changed.connect(self.refresh_timer)
        countdown.completed.connect(self.completed)
        monitor.updated.connect(self.update_metrics)
        self.tabs.currentChanged.connect(self.page_changed)
        self.minutes.valueChanged.connect(self.refresh_timer)
        self.seconds.valueChanged.connect(self.refresh_timer)
        self.set_duration(duration)
        self.refresh_clock()
        self.refresh_timer()

    def select_page(self, page):
        if isinstance(page, str):
            widget = self.pages.get(page)
            if widget is None:
                return False
            index = self.tabs.indexOf(widget)
        else:
            index = page
        if not isinstance(index, int) or not 0 <= index < self.tabs.count():
            return False
        self.tabs.setCurrentIndex(index)
        if self.tabs.currentWidget() is self.diagnostics_page:
            self.diagnostics_page.finish()
        return True

    def show_projection_details(self, model):
        details = self.projection_details
        details.setVisible(model is not None)
        text = model.accessible_text if model else ""
        if details.toPlainText() != text:
            details.setPlainText(text)

    def start_task_focus(self, task_id):
        self.select_page("focus")
        self.focus_page.start_for(task_id)

    @staticmethod
    def scroll(content):
        return scrollable(content)

    def overview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(16)
        hero, content = card("hero")
        content.addWidget(label(tr("HORA LOCAL / AGORA"), "muted"))
        self.clock_label = label("00:00:00")
        styled(self.clock_label, "font: 48px 'Consolas'; color: #f4faff;")
        content.addWidget(self.clock_label)
        self.date_label = label("", "muted")
        self.date_label.setWordWrap(True)
        content.addWidget(self.date_label)
        layout.addWidget(hero)
        row = ActionRow()
        quick, box = card()
        box.addWidget(label(tr("TEMPO PARA VOCÊ"), "eyebrow"))
        box.addWidget(label(tr("Um intervalo na medida certa")))
        self.timer_summary = label(tr("Seu temporizador está pronto."), "muted")
        box.addWidget(self.timer_summary)
        button = QPushButton(tr("Abrir temporizador  →"))
        button.setProperty("role", "primary")
        button.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        box.addWidget(button)
        row.addWidget(quick, 1)
        system, box = card()
        box.addWidget(label(tr("SEU COMPUTADOR"), "eyebrow"))
        self.metrics = label(tr("CPU —\nMemória —"))
        styled(self.metrics, "font-size: 19px; font-weight: 600;")
        box.addWidget(self.metrics)
        button = QPushButton(tr("Ver sistema  →"))
        button.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        box.addWidget(button)
        row.addWidget(system, 1)
        layout.addWidget(row)
        layout.addStretch()
        return self.scroll(page)

    def timer_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 16, 0, 0)
        panel, content = card()
        content.setContentsMargins(14, 16, 14, 16)
        content.addWidget(label(tr("DEFINA SEU PRÓXIMO INTERVALO"), "eyebrow"))
        body = ActionRow()
        self.dial = TimerDial()
        body.addWidget(self.dial, 1)
        controls_widget = QWidget()
        controls = QVBoxLayout(controls_widget)
        controls.setContentsMargins(0, 0, 0, 0)
        controls.addWidget(label(tr("Quanto tempo você precisa?")))
        durations = QHBoxLayout()
        self.minutes = QSpinBox()
        self.minutes.setRange(0, 1440)
        self.minutes.setSuffix(" min")
        self.minutes.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.minutes.setAccessibleName(tr("Minutos do temporizador"))
        self.seconds = QSpinBox()
        self.seconds.setRange(0, 59)
        self.seconds.setSuffix(" s")
        self.seconds.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.seconds.setAccessibleName(tr("Segundos do temporizador"))
        durations.addWidget(self.minutes)
        durations.addWidget(self.seconds)
        controls.addLayout(durations)
        presets = QHBoxLayout()
        self.presets = []
        for title, seconds in (("1 min", 60), ("5 min", 300), ("25 min", 1500)):
            button = QPushButton(title)
            button.setProperty("role", "preset")
            button.clicked.connect(lambda checked=False, value=seconds: self.set_duration(value))
            presets.addWidget(button)
            self.presets.append(button)
        controls.addLayout(presets)
        controls.addWidget(self.project_timer)
        self.start_button = QPushButton(tr("Iniciar contagem"))
        self.start_button.setIcon(icon("play", "#ffffff"))
        self.start_button.setProperty("role", "primary")
        self.start_button.clicked.connect(self.start)
        controls.addWidget(self.start_button)
        row = ActionRow()
        self.pause_button = QPushButton(tr("Pausar"))
        self.pause_button.clicked.connect(self.toggle_pause)
        self.restart_button = QPushButton(tr("Reiniciar"))
        self.restart_button.clicked.connect(self.restart_countdown)
        row.addWidget(self.pause_button)
        row.addWidget(self.restart_button)
        controls.addWidget(row)
        self.stop_button = QPushButton(tr("Encerrar"))
        self.stop_button.setAccessibleName(tr("Encerrar temporizador"))
        self.stop_button.setToolTip(tr("Cancelar a contagem atual e liberar a escolha de outro intervalo."))
        self.stop_button.clicked.connect(self.stop_countdown)
        controls.addWidget(self.stop_button)
        controls.addStretch()
        body.addWidget(controls_widget, 2)
        content.addWidget(body)
        self.timer_label = label(tr("Pronto"), "muted")
        content.addWidget(self.timer_label)
        layout.addWidget(panel)
        note = label(tr("O R2 avisa quando terminar. A contagem continua com o mascote oculto; sair da aplicação encerra o temporizador."), "muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch()
        return self.scroll(page)

    def system_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(16)
        self.metric_labels, self.metric_bars = {}, {}
        for key, title, description in (("cpu", tr("Processador"), tr("Uso atual da CPU")),
                                         ("ram", tr("Memória"), tr("RAM em uso")),
                                         ("battery", tr("Bateria"), tr("Carga disponível, quando houver bateria"))):
            panel, content = card()
            row = QHBoxLayout()
            row.addWidget(label(title))
            value = label("—")
            styled(value, "font-size: 23px; font-weight: 700; color: #216eea;")
            row.addStretch()
            row.addWidget(value)
            content.addLayout(row)
            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setTextVisible(False)
            bar.setAccessibleName(title)
            content.addWidget(bar)
            content.addWidget(label(description, "muted"))
            self.metric_labels[key], self.metric_bars[key] = value, bar
            layout.addWidget(panel)
        layout.addStretch()
        return self.scroll(page)

    def set_duration(self, seconds: int):
        self.minutes.setValue(seconds // 60)
        self.seconds.setValue(seconds % 60)

    def selected_duration(self) -> int:
        return self.minutes.value() * 60 + self.seconds.value()

    def start(self):
        seconds = self.selected_duration()
        if not 1 <= seconds <= 86400:
            self.completion.setText(tr("Escolha um intervalo entre 1 segundo e 24 horas."))
            return
        if self.focus is None:
            self.countdown.start(seconds)
        elif confirm_countdown(self, lambda **confirmation: self.focus.start_timer(seconds, **confirmation),
                               report=self.completion.setText) is None:
            return
        self.duration_selected.emit(seconds)
        self.completion.setText(tr("Seu tempo está correndo. Pode deixar que {0} avisa.", getattr(self, 'character_name', 'R2')))

    def has_focus_session(self):
        return self.focus is not None and self.focus.session is not None

    def toggle_pause(self):
        if self.has_focus_session():
            return
        if self.countdown.state == TimerState.RUNNING:
            self.countdown.pause()
        else:
            self.countdown.resume()

    def stop_countdown(self):
        if self.has_focus_session():
            return
        self.countdown.stop()
        self.completion.setText(tr("Temporizador encerrado. Escolha outro intervalo para iniciar uma nova contagem."))

    def completed(self, run_id):
        if self.has_focus_session() or self.countdown.run_id != run_id:
            return
        self.completion.setText(tr("✓ Temporizador #{0} concluído. Seu intervalo chegou ao fim.", run_id))

    def restart_countdown(self):
        if not self.has_focus_session():
            self.countdown.restart()

    def refresh_clock(self):
        time_text, date_text = local_clock().split("\n", 1)
        self.clock_label.setText(time_text)
        self.date_label.setText(date_text)

    def refresh_timer(self, *_):
        if not hasattr(self, "start_button"):
            return
        focus_active = self.has_focus_session()
        state = TimerState.STOPPED if focus_active else self.countdown.state
        remaining = self.selected_duration() if state == TimerState.STOPPED else self.countdown.remaining
        self.dial.value = remaining
        self.dial.total = self.selected_duration() if state == TimerState.STOPPED else self.countdown.duration
        self.dial.status = {TimerState.STOPPED: tr("PRONTO"), TimerState.RUNNING: tr("EM CONTAGEM"),
                            TimerState.PAUSED: tr("PAUSADO"), TimerState.COMPLETED: tr("CONCLUÍDO")}[state]
        if self.isVisible():
            self.dial.update()
        description = (tr("Sessão na página Foco") if focus_active else f"{tr(state.value)} · {timer_text(remaining)}")
        self.timer_label.setText(description)
        self.timer_summary.setText(description)
        active = state in {TimerState.RUNNING, TimerState.PAUSED}
        self.start_button.setEnabled(not active)
        self.pause_button.setEnabled(active)
        self.stop_button.setEnabled(active)
        self.pause_button.setText(tr("Continuar") if state == TimerState.PAUSED else tr("Pausar"))
        self.restart_button.setEnabled(state != TimerState.STOPPED)
        for control in (self.minutes, self.seconds, *self.presets):
            control.setEnabled(not active)

    def update_metrics(self, values):
        if "battery" in values:
            self.battery = values["battery"]
        values = values | {"battery": self.battery}
        for key, value in values.items():
            self.metric_labels[key].setText((tr("Não disponível") if key == "battery" else tr("Aguardando…")) if value is None else f"{value:.0f}%")
            self.metric_bars[key].setValue(0 if value is None else round(value))
        cpu = "—" if values["cpu"] is None else f"{values['cpu']:.0f}%"
        ram = "—" if values["ram"] is None else f"{values['ram']:.0f}%"
        self.metrics.setText(tr("CPU {0}\nMemória {1}", cpu, ram))

    def page_changed(self, index):
        if not hasattr(self, "clock_timer") or not self.isVisible():
            return
        self.clock_timer.start() if index == 0 else self.clock_timer.stop()
        self.monitor.set_visible(index in (0, 2))

    def showEvent(self, event):
        self.refresh_clock()
        self.page_changed(self.tabs.currentIndex())
        self.countdown.set_visible(True)
        super().showEvent(event)

    def hideEvent(self, event):
        self.clock_timer.stop()
        self.countdown.set_visible(False)
        self.monitor.set_visible(False)
        super().hideEvent(event)

    def stop(self):
        if "data" in self.pages:
            self.pages["data"].tasks.close()
        self.diagnostics_page.stop()
        self.clock_timer.stop()
        self.hide()
