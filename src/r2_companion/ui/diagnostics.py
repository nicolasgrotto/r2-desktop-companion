from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFormLayout, QPushButton, QScrollArea, QVBoxLayout, QWidget

from .theme import card, label


class DiagnosticsPage(QScrollArea):
    scan_requested = Signal()

    def __init__(self):
        super().__init__()
        self.provider = None
        self.setWidgetResizable(True)
        body = QWidget()
        self.setWidget(body)
        layout = QVBoxLayout(body)
        panel, content = card()
        content.addWidget(label("Autodiagnóstico", "heading"))
        self.message = label("Uma verificação rápida dos componentes locais do R2.", "muted")
        self.message.setWordWrap(True)
        content.addWidget(self.message)
        self.form = QFormLayout()
        self.fields = {}
        content.addLayout(self.form)
        self.button = QPushButton("Iniciar diagnóstico")
        self.button.setProperty("role", "primary")
        self.button.clicked.connect(self.start)
        content.addWidget(self.button)
        layout.addWidget(panel)
        layout.addStretch()
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(600)
        self.timer.timeout.connect(self.finish)

    def start(self):
        if self.provider is None or self.timer.isActive():
            return
        self.provider()
        self.button.setEnabled(False)
        self.message.setText("Verificando CPU, memória, bateria e áudio…")
        self.scan_requested.emit()
        self.timer.start()

    def finish(self):
        if self.provider is None:
            return
        report = self.provider()
        for key in ("Personagem", "Versão", "Sistema", "CPU", "Memória RAM", "Bateria", "Carregamento", "Áudio", "Som do R2"):
            if key not in report:
                continue
            value = report[key].split(" (")[0] if key == "Personagem" else report[key]
            if key not in self.fields:
                self.fields[key] = label("")
                self.fields[key].setWordWrap(True)
                self.fields[key].setProperty("characterLiteral", True)
                self.form.addRow(key, self.fields[key])
                caption = self.form.labelForField(self.fields[key])
                if "R2" in key:
                    caption.setProperty("characterText", key)
                    caption.setText(key.replace("R2", getattr(self, "character_name", "R2")))
            self.fields[key].setText(value)
        self.button.setEnabled(True)
        self.message.setText("Verificação concluída. A ausência de bateria é normal em um desktop.")

    def stop(self):
        self.timer.stop()
