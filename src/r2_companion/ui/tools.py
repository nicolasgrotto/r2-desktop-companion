import math

from PySide6.QtCore import QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QAbstractSpinBox, QDialog, QHBoxLayout, QProgressBar,
                              QPushButton, QScrollArea, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from ..features.clock import local_clock
from ..features.timer import TimerState
from .theme import BLUE, MUTED, apply_theme, card, header, icon, label
from .productivity import NotesPage, TasksPage
from .minigames import MinigamesPage
from .diagnostics import DiagnosticsPage
from ..droids.themes import color, styled


def timer_text(seconds: float) -> str:
    hours, rest = divmod(max(0, math.ceil(seconds)), 3600)
    minutes, seconds = divmod(rest, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


class TimerDial(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(190, 220)
        self.value = 300
        self.total = 300
        self.status = "PRONTO"

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width() - 20, self.height() - 24)
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        p.setPen(QPen(QColor(color("border", self)), 9))
        p.drawEllipse(rect)
        p.setPen(QPen(QColor(color("primary", self)), 9, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        progress = max(0, min(1, self.value / max(1, self.total)))
        p.drawArc(rect, 90 * 16, -round(progress * 360 * 16))
        p.setPen(QColor(color("text", self)))
        p.setFont(QFont("Consolas", 25 if self.value < 3600 else 19, QFont.Weight.Bold))
        p.drawText(rect.adjusted(0, -8, 0, -8), Qt.AlignmentFlag.AlignCenter, timer_text(self.value))
        p.setPen(QColor(color("muted", self)))
        p.setFont(QFont("Segoe UI", 8, QFont.Weight.DemiBold))
        p.drawText(rect.adjusted(0, 55, 0, 0), Qt.AlignmentFlag.AlignCenter, self.status)


class ToolsDialog(QDialog):
    duration_selected = Signal(int)

    def __init__(self, countdown, monitor, duration: int, productivity=None):
        super().__init__()
        self.setWindowTitle("Central de ferramentas · R2 Companion")
        self.resize(760, 650)
        apply_theme(self)
        self.countdown, self.monitor = countdown, monitor
        self.battery = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 22)
        layout.setSpacing(14)
        layout.addWidget(header("Central de ferramentas", "Seu tempo e seu computador, em sintonia."))
        self.tabs = QTabWidget()
        self.tabs.addTab(self.overview(), icon("clock"), "Relógio")
        self.tabs.addTab(self.timer_page(), icon("play"), "Temporizador")
        self.tabs.addTab(self.system_page(), icon("system"), "Sistema")
        if productivity is not None:
            self.tasks_page = TasksPage(productivity)
            self.notes_page = NotesPage(productivity)
            self.tabs.addTab(self.tasks_page, "Tarefas")
            self.tabs.addTab(self.notes_page, "Notas")
        self.minigames_page = MinigamesPage()
        self.diagnostics_page = DiagnosticsPage()
        self.tabs.addTab(self.minigames_page, "Minigames")
        self.tabs.addTab(self.diagnostics_page, "Diagnóstico")
        self.tabs.setUsesScrollButtons(True)
        layout.addWidget(self.tabs, 1)
        self.completion = label("Tudo pronto. Escolha uma ferramenta para começar.", "muted")
        self.completion.setWordWrap(True)
        layout.addWidget(self.completion)
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

    @staticmethod
    def scroll(content):
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setWidget(content)
        return area

    def overview(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(16)
        hero, content = card("hero")
        content.addWidget(label("HORA LOCAL / AGORA", "muted"))
        self.clock_label = label("00:00:00")
        styled(self.clock_label, "font: 48px 'Consolas'; color: #f4faff;")
        content.addWidget(self.clock_label)
        self.date_label = label("", "muted")
        self.date_label.setWordWrap(True)
        content.addWidget(self.date_label)
        layout.addWidget(hero)
        row = QHBoxLayout()
        quick, box = card()
        box.addWidget(label("TEMPO PARA VOCÊ", "eyebrow"))
        box.addWidget(label("Um intervalo na medida certa"))
        self.timer_summary = label("Seu temporizador está pronto.", "muted")
        box.addWidget(self.timer_summary)
        button = QPushButton("Abrir temporizador  →")
        button.setProperty("role", "primary")
        button.clicked.connect(lambda: self.tabs.setCurrentIndex(1))
        box.addWidget(button)
        row.addWidget(quick, 1)
        system, box = card()
        box.addWidget(label("SEU COMPUTADOR", "eyebrow"))
        self.metrics = label("CPU —\nMemória —")
        self.metrics.setStyleSheet("font-size: 19px; font-weight: 600;")
        box.addWidget(self.metrics)
        button = QPushButton("Ver sistema  →")
        button.clicked.connect(lambda: self.tabs.setCurrentIndex(2))
        box.addWidget(button)
        row.addWidget(system, 1)
        layout.addLayout(row)
        layout.addStretch()
        return self.scroll(page)

    def timer_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 16, 0, 0)
        panel, content = card()
        content.addWidget(label("DEFINA SEU PRÓXIMO INTERVALO", "eyebrow"))
        body = QHBoxLayout()
        self.dial = TimerDial()
        body.addWidget(self.dial, 1)
        controls = QVBoxLayout()
        controls.addWidget(label("Quanto tempo você precisa?"))
        durations = QHBoxLayout()
        self.minutes = QSpinBox()
        self.minutes.setRange(0, 1440)
        self.minutes.setSuffix(" min")
        self.minutes.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.minutes.setAccessibleName("Minutos do temporizador")
        self.seconds = QSpinBox()
        self.seconds.setRange(0, 59)
        self.seconds.setSuffix(" s")
        self.seconds.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.seconds.setAccessibleName("Segundos do temporizador")
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
        self.start_button = QPushButton("Iniciar contagem")
        self.start_button.setIcon(icon("play", "#ffffff"))
        self.start_button.setProperty("role", "primary")
        self.start_button.clicked.connect(self.start)
        controls.addWidget(self.start_button)
        row = QHBoxLayout()
        self.pause_button = QPushButton("Pausar")
        self.pause_button.clicked.connect(self.toggle_pause)
        self.restart_button = QPushButton("Reiniciar")
        self.restart_button.clicked.connect(self.countdown.restart)
        row.addWidget(self.pause_button)
        row.addWidget(self.restart_button)
        controls.addLayout(row)
        controls.addStretch()
        body.addLayout(controls, 2)
        content.addLayout(body)
        self.timer_label = label("Pronto", "muted")
        content.addWidget(self.timer_label)
        layout.addWidget(panel)
        note = label("O R2 avisa quando terminar. A contagem continua com o mascote oculto; sair da aplicação encerra o temporizador.", "muted")
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
        for key, title, description in (("cpu", "Processador", "Uso atual da CPU"),
                                         ("ram", "Memória", "RAM em uso"),
                                         ("battery", "Bateria", "Carga disponível, quando houver bateria")):
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
            bar.setFixedHeight(9)
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
            self.completion.setText("Escolha um intervalo entre 1 segundo e 24 horas.")
            return
        self.duration_selected.emit(seconds)
        self.completion.setText("Seu tempo está correndo. Pode deixar que o R2 avisa.")
        self.countdown.start(seconds)

    def toggle_pause(self):
        if self.countdown.state == TimerState.RUNNING:
            self.countdown.pause()
        else:
            self.countdown.resume()

    def completed(self, run_id):
        self.completion.setText(f"✓ Temporizador #{run_id} concluído. Seu intervalo chegou ao fim.")

    def refresh_clock(self):
        time_text, date_text = local_clock().split("\n", 1)
        self.clock_label.setText(time_text)
        self.date_label.setText(date_text)

    def refresh_timer(self, *_):
        if not hasattr(self, "start_button"):
            return
        state = self.countdown.state
        remaining = self.selected_duration() if state == TimerState.STOPPED else self.countdown.remaining
        self.dial.value = remaining
        self.dial.total = self.selected_duration() if state == TimerState.STOPPED else self.countdown.duration
        self.dial.status = {TimerState.STOPPED: "PRONTO", TimerState.RUNNING: "EM CONTAGEM",
                            TimerState.PAUSED: "PAUSADO", TimerState.COMPLETED: "CONCLUÍDO"}[state]
        if self.isVisible():
            self.dial.update()
        self.timer_label.setText(f"{state.value} · {timer_text(remaining)}")
        self.timer_summary.setText(f"{state.value} · {timer_text(remaining)}")
        active = state in {TimerState.RUNNING, TimerState.PAUSED}
        self.start_button.setEnabled(not active)
        self.pause_button.setEnabled(active)
        self.pause_button.setText("Continuar" if state == TimerState.PAUSED else "Pausar")
        self.restart_button.setEnabled(state != TimerState.STOPPED)
        for control in (self.minutes, self.seconds, *self.presets):
            control.setEnabled(not active)

    def update_metrics(self, values):
        if "battery" in values:
            self.battery = values["battery"]
        values = values | {"battery": self.battery}
        for key, value in values.items():
            self.metric_labels[key].setText(("Não disponível" if key == "battery" else "Aguardando…") if value is None else f"{value:.0f}%")
            self.metric_bars[key].setValue(0 if value is None else round(value))
        cpu = "—" if values["cpu"] is None else f"{values['cpu']:.0f}%"
        ram = "—" if values["ram"] is None else f"{values['ram']:.0f}%"
        self.metrics.setText(f"CPU {cpu}\nMemória {ram}")

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
        self.diagnostics_page.stop()
        self.clock_timer.stop()
        self.hide()
