from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QDoubleSpinBox, QFileDialog,
                              QFormLayout, QHBoxLayout, QInputDialog, QLineEdit, QListWidget,
                              QPushButton, QScrollArea, QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout, QWidget)

from ..core.config import Settings, Shortcut, Target
from ..features.launcher import validate_executable
from ..features.locations import validate_location
from ..pet.personality import apply_profile
from .targets import TargetDelegate, filter_targets, target_item
from .theme import apply_theme, card, header, icon, label


class SettingsDialog(QDialog):
    applied = Signal(object, object)

    def __init__(self, settings: Settings, startup_available: bool, startup_enabled: bool, startup_status: str):
        super().__init__()
        self.setWindowTitle("Configurações · R2 Companion")
        self.resize(720, 740)
        apply_theme(self)
        self.draft = deepcopy(settings)
        self.startup_original = startup_enabled
        layout = QVBoxLayout(self)
        layout.setContentsMargins(26, 24, 26, 20)
        layout.setSpacing(14)
        layout.addWidget(header("Do seu jeito", "Ajuste a personalidade do R2 e organize seus favoritos."))
        self.tabs = QTabWidget()
        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_layout.setContentsMargins(0, 16, 0, 0)
        panel, panel_layout = card()
        panel_layout.addWidget(label("PERSONALIDADE E PRESENÇA", "eyebrow"))
        form = QFormLayout()
        form.setSpacing(12)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        panel_layout.addLayout(form)
        general_layout.addWidget(panel)
        self.scale = QSpinBox()
        self.scale.setRange(64, 256)
        self.scale.setValue(settings.visual_scale)
        self.scale.setSuffix(" DIP")
        self.scale.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        form.addRow("Tamanho do mascote", self.scale)
        self.personality = QComboBox()
        for title, value in (("Personalizado", "custom"), ("Calmo", "calm"), ("Curioso", "curious"), ("Comunicativo", "talkative")):
            self.personality.addItem(title, value)
        self.personality.setCurrentIndex(self.personality.findData(settings.personality))
        form.addRow("Personalidade", self.personality)
        self.appearance = QComboBox()
        for title, value in (("Azul original", "blue"), ("Verde oceano", "teal"), ("Violeta", "violet"), ("Âmbar", "amber")):
            self.appearance.addItem(title, value)
        self.appearance.setCurrentIndex(self.appearance.findData(settings.appearance))
        form.addRow("Detalhes do robô", self.appearance)
        self.frequency = QComboBox()
        for caption, value in (("Desativado", "off"), ("Discreto", "quiet"), ("Normal", "normal")):
            self.frequency.addItem(caption, value)
        self.frequency.setCurrentIndex(self.frequency.findData(settings.behavior.frequency))
        form.addRow("Comportamento autônomo", self.frequency)
        self.sleep = QDoubleSpinBox()
        self.sleep.setRange(0.5, 120)
        self.sleep.setSingleStep(0.5)
        self.sleep.setDecimals(1)
        self.sleep.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.sleep.setSuffix(" min sem atividade")
        self.sleep.setValue(settings.behavior.sleep_seconds / 60)
        form.addRow("Entrar em repouso após", self.sleep)
        self.controls = {}
        for caption, key, value in (("Caminhar sozinho", "movement", settings.behavior.movement),
                                  ("Sempre acima de janelas normais", "topmost", settings.window.topmost),
                                  ("Balões de diálogo", "bubbles", settings.bubbles),
                                  ("Efeitos sonoros do R2", "sound_enabled", settings.sound_enabled),
                                  ("Observar o cursor", "cursor_attention", settings.behavior.cursor_attention),
                                  ("Reagir a bateria e CPU", "system_reactions", settings.behavior.system_reactions),
                                  ("Comemorar uma hora de atividade", "hourly_reaction", settings.behavior.hourly_reaction)):
            control = QCheckBox(caption)
            control.setChecked(value)
            self.controls[key] = control
            form.addRow(control)
        self.fullscreen = QComboBox()
        for title, value in (("Automático: canto escolhido ou ocultar", "auto"),
                             ("Sempre ocultar temporariamente", "hide"),
                             ("Permanecer no canto escolhido", "corner"),
                             ("Ficar na posição atual, em silêncio", "quiet")):
            self.fullscreen.addItem(title, value)
        self.fullscreen.setCurrentIndex(self.fullscreen.findData(settings.fullscreen_mode))
        form.addRow("Durante tela cheia", self.fullscreen)
        corner_info = label("Arraste o R2 até um canto para guardar sua preferência. Sem canto escolhido, o modo Automático oculta o mascote durante jogos.", "muted")
        corner_info.setWordWrap(True)
        form.addRow(corner_info)
        self.reaction_interval = QSpinBox()
        self.reaction_interval.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.reaction_interval.setRange(10, 600)
        self.reaction_interval.setSuffix(" s")
        self.reaction_interval.setValue(settings.behavior.reaction_interval)
        form.addRow("Pausa entre reações", self.reaction_interval)
        self.personality.currentIndexChanged.connect(self.select_profile)
        self.quiet = QCheckBox("Horário de silêncio")
        self.quiet.setChecked(settings.quiet_enabled)
        form.addRow(self.quiet)
        self.quiet_start, self.quiet_end = QTimeEdit(), QTimeEdit()
        for widget, minutes in ((self.quiet_start, settings.quiet_start), (self.quiet_end, settings.quiet_end)):
            widget.setDisplayFormat("HH:mm")
            widget.setTime(QTime(minutes // 60, minutes % 60))
        form.addRow("Silêncio a partir de", self.quiet_start)
        form.addRow("Retomar às", self.quiet_end)
        self.holograms = QCheckBox("Pequenas projeções nas ferramentas")
        self.holograms.setChecked(settings.holograms)
        form.addRow(self.holograms)
        self.startup = QCheckBox("Iniciar com o Windows (somente este usuário)")
        self.startup.setEnabled(startup_available)
        self.startup.setChecked(startup_enabled)
        form.addRow(self.startup)
        startup_info = label(startup_status, "muted")
        startup_info.setWordWrap(True)
        form.addRow(startup_info)
        tip = label("No modo Normal, o primeiro passeio acontece em cerca de 15–25 segundos de disponibilidade. Desative Caminhar sozinho se preferir o R2 parado.", "muted")
        tip.setWordWrap(True)
        general_layout.addWidget(tip)
        general_layout.addStretch()
        general_scroll = QScrollArea()
        general_scroll.setWidgetResizable(True)
        general_scroll.setWidget(general)
        self.tabs.addTab(general_scroll, icon("settings"), "Preferências")
        targets = QWidget()
        target_layout = QVBoxLayout(targets)
        target_layout.setContentsMargins(0, 16, 0, 0)
        target_layout.setSpacing(12)
        note = label("Seus favoritos, sempre à mão. Adicione um aplicativo, pasta ou arquivo e escolha um nome fácil de reconhecer.", "muted")
        note.setWordWrap(True)
        target_layout.addWidget(note)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Buscar nos seus favoritos…")
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.filter)
        target_layout.addWidget(self.search)
        self.targets = QListWidget()
        self.targets.setItemDelegate(TargetDelegate(self.targets))
        self.targets.itemSelectionChanged.connect(self.selection_changed)
        target_layout.addWidget(self.targets, 1)
        self.empty = label("Você ainda não adicionou favoritos.\nComece pelos botões abaixo.", "muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        target_layout.addWidget(self.empty)
        first = QHBoxLayout()
        for title, kind in (("Aplicativo", "app"), ("Pasta", "folder"), ("Arquivo", "file")):
            button = QPushButton("+ " + title)
            button.setIcon(icon("apps" if kind == "app" else "folder" if kind == "folder" else "file"))
            button.clicked.connect(lambda checked=False, k=kind: self.add_target(k))
            first.addWidget(button)
        target_layout.addLayout(first)
        second = QHBoxLayout()
        self.selection_buttons = []
        for title, callback in (("Criar atalho", self.add_alias), ("Renomear", self.rename), ("Remover", self.remove)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            second.addWidget(button)
            self.selection_buttons.append(button)
        target_layout.addLayout(second)
        self.tabs.addTab(targets, icon("apps"), "Aplicativos e atalhos")
        audio_page = QWidget()
        audio_form = QFormLayout(audio_page)
        self.muted = QCheckBox("Modo silencioso")
        self.muted.setChecked(settings.audio.muted)
        audio_form.addRow(self.muted)
        self.volume = QSpinBox()
        self.volume.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.volume.setRange(0, 100)
        self.volume.setSuffix(" %")
        self.volume.setValue(round(settings.audio.volume * 100))
        audio_form.addRow("Volume dos efeitos", self.volume)
        self.audio_interval = QDoubleSpinBox()
        self.audio_interval.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.audio_interval.setRange(0.1, 60)
        self.audio_interval.setSuffix(" s")
        self.audio_interval.setValue(settings.audio.min_interval)
        audio_form.addRow("Intervalo mínimo entre sons", self.audio_interval)
        self.audio_categories = {}
        for key, title in (("idle", "Reações espontâneas"), ("movement", "Movimentos"),
                           ("reactions", "Interações"), ("sleep", "Dormir e despertar"),
                           ("notifications", "Notificações e temporizador")):
            control = QCheckBox(title)
            control.setChecked(settings.audio.categories[key])
            self.audio_categories[key] = control
            audio_form.addRow(control)
        info = label("O volume é exclusivo do R2. Tela cheia e repouso suspendem sons; o sono permite apenas seu efeito de entrada ou saída.", "muted")
        info.setWordWrap(True)
        audio_form.addRow(info)
        self.tabs.addTab(audio_page, "Áudio")
        layout.addWidget(self.tabs, 1)
        self.error = label("", "error")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Apply | QDialogButtonBox.StandardButton.Cancel
                                  | QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(lambda: self.apply(False))
        buttons.button(QDialogButtonBox.StandardButton.Apply).setText("Aplicar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Salvar e fechar")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("role", "primary")
        buttons.accepted.connect(lambda: self.apply(True))
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.render_targets()

    def render_targets(self):
        self.targets.clear()
        for target in self.draft.applications + self.draft.locations:
            self.targets.addItem(target_item(target))
        targets = {t.id: t for t in self.draft.applications + self.draft.locations}
        for alias in self.draft.shortcuts:
            item = target_item(targets[alias.target_id], label_override=alias.label, alias=True)
            item.setData(Qt.ItemDataRole.UserRole, alias.id)
            self.targets.addItem(item)
        self.filter()

    def select_profile(self):
        self.draft = apply_profile(self.draft, self.personality.currentData())
        self.frequency.setCurrentIndex(self.frequency.findData(self.draft.behavior.frequency))
        self.reaction_interval.setValue(self.draft.behavior.reaction_interval)

    def filter(self, *_):
        count = filter_targets(self.targets, self.search.text())
        self.empty.setVisible(count == 0)
        self.empty.setText("Nenhum resultado para essa busca." if self.search.text().strip() else
                           "Você ainda não adicionou favoritos.\nComece pelos botões abaixo.")
        self.selection_changed()

    def selection_changed(self):
        item = self.targets.currentItem()
        enabled = item is not None and not item.isHidden()
        for button in getattr(self, "selection_buttons", []):
            button.setEnabled(enabled)

    def add_target(self, kind):
        if kind == "folder":
            path = QFileDialog.getExistingDirectory(self, "Escolher pasta local")
        else:
            pattern = "Aplicativos (*.exe)" if kind == "app" else "Arquivos permitidos (*.txt *.pdf *.png *.jpg *.jpeg *.wav *.mp3)"
            path, _ = QFileDialog.getOpenFileName(self, "Escolher destino local", "", pattern)
        if not path:
            return
        try:
            resolved = validate_executable(path) if kind == "app" else validate_location(path, kind)
            entry = Target(uuid4().hex, resolved.stem or resolved.name, str(resolved), kind)
            collection = self.draft.applications if kind == "app" else self.draft.locations
            if len(collection) >= 100:
                raise ValueError("Limite de 100 destinos por lista.")
            collection.append(entry)
            self.error.clear()
            self.render_targets()
        except (OSError, ValueError) as error:
            self.error.setText(str(error))

    def add_alias(self):
        item = self.targets.currentItem()
        if item is None:
            self.error.setText("Selecione primeiro um aplicativo ou local.")
            return
        target_id = item.data(Qt.ItemDataRole.UserRole)
        if not any(t.id == target_id for t in self.draft.applications + self.draft.locations):
            return
        label, accepted = QInputDialog.getText(self, "Criar atalho", "Nome do atalho:")
        if accepted and label.strip():
            self.draft.shortcuts.append(Shortcut(uuid4().hex, label.strip(), target_id))
            self.render_targets()

    def rename(self):
        item = self.targets.currentItem()
        if item is None:
            return
        entry = next(t for t in self.draft.applications + self.draft.locations + self.draft.shortcuts
                     if t.id == item.data(Qt.ItemDataRole.UserRole))
        label, accepted = QInputDialog.getText(self, "Renomear", "Nome:", text=entry.label)
        if accepted and label.strip():
            entry.label = label.strip()
            self.render_targets()

    def remove(self):
        item = self.targets.currentItem()
        if item is None:
            return
        entry_id = item.data(Qt.ItemDataRole.UserRole)
        self.draft.applications = [t for t in self.draft.applications if t.id != entry_id]
        self.draft.locations = [t for t in self.draft.locations if t.id != entry_id]
        self.draft.shortcuts = [t for t in self.draft.shortcuts if t.id != entry_id and t.target_id != entry_id]
        self.render_targets()

    def apply(self, close: bool):
        self.draft.personality = self.personality.currentData()
        self.draft.appearance = self.appearance.currentData()
        self.draft.quiet_enabled = self.quiet.isChecked()
        self.draft.quiet_start = self.quiet_start.time().hour() * 60 + self.quiet_start.time().minute()
        self.draft.quiet_end = self.quiet_end.time().hour() * 60 + self.quiet_end.time().minute()
        self.draft.holograms = self.holograms.isChecked()
        self.draft.visual_scale = self.scale.value()
        self.draft.behavior.frequency = self.frequency.currentData()
        self.draft.behavior.sleep_seconds = round(self.sleep.value() * 60)
        self.draft.behavior.movement = self.controls["movement"].isChecked()
        self.draft.window.topmost = self.controls["topmost"].isChecked()
        for key in ("bubbles", "sound_enabled"):
            setattr(self.draft, key, self.controls[key].isChecked())
        for key in ("cursor_attention", "system_reactions", "hourly_reaction"):
            setattr(self.draft.behavior, key, self.controls[key].isChecked())
        self.draft.behavior.reaction_interval = self.reaction_interval.value()
        self.draft.fullscreen_mode = self.fullscreen.currentData()
        self.draft.suppress_fullscreen = True
        self.draft.audio.volume = self.volume.value() / 100
        self.draft.audio.muted = self.muted.isChecked()
        self.draft.audio.min_interval = self.audio_interval.value()
        self.draft.audio.categories = {key: control.isChecked() for key, control in self.audio_categories.items()}
        try:
            checked = Settings.parse(self.draft.to_dict())
        except ValueError as error:
            self.error.setText(str(error))
            return
        request = self.startup.isChecked() if self.startup.isEnabled() and self.startup.isChecked() != self.startup_original else None
        self.error.clear()
        self.applied.emit(checked, request)
        if self.error.text():
            return
        self.startup_original = self.startup.isChecked()
        if close:
            self.accept()
