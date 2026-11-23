from copy import deepcopy
from uuid import uuid4

from PySide6.QtCore import Qt, QTime, Signal
from PySide6.QtWidgets import (QAbstractSpinBox, QCheckBox, QComboBox, QDialog, QDoubleSpinBox, QFileDialog,
                              QFormLayout, QInputDialog, QLineEdit, QListWidget, QPushButton,
                              QSpinBox, QTabWidget, QTimeEdit, QVBoxLayout, QWidget)

from ..core.config import Settings, Shortcut, Target
from ..features.launcher import validate_executable
from ..features.locations import validate_location
from ..pet.personality import apply_profile
from ..pet.presence import PRESENCE_DESCRIPTIONS
from .targets import TargetDelegate, filter_targets, target_item
from .theme import (ActionRow, apply_character_name, apply_theme, card, configure_form, form_row,
                    header, icon, label, scrollable)
from ..core.language import LANGUAGES, active_language, tr


class SettingsDialog(QDialog):
    applied = Signal(object, object)
    presence_applied = Signal(str)
    accessibility_applied = Signal(int, bool)
    restart_requested = Signal()

    def __init__(self, settings: Settings, startup_available: bool, startup_enabled: bool, startup_status: str,
                 droid_profile=None, *, ui_scale=100, shortcut_settings=None, language_store=None):
        super().__init__()
        self.setWindowTitle(tr("Configurações · R2 Companion"))
        self.resize(720, 740)
        apply_theme(self)
        self.draft = deepcopy(settings)
        self.startup_original = startup_enabled
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        body = QWidget()
        outer.addWidget(scrollable(body))
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)
        layout.addWidget(header(tr("Do seu jeito"), tr("Ajuste a personalidade do R2 e organize seus favoritos.")))
        self.tabs = QTabWidget()
        self.tabs.tabBar().setAccessibleName(tr("Páginas de configurações"))
        self.tabs.setUsesScrollButtons(True)
        general = QWidget()
        general_layout = QVBoxLayout(general)
        general_layout.setContentsMargins(0, 16, 0, 0)
        panel, panel_layout = card()
        panel_layout.setContentsMargins(12, 16, 12, 16)
        panel_layout.addWidget(label(tr("PERSONALIDADE E PRESENÇA"), "eyebrow"))
        form = QFormLayout()
        form.setSpacing(12)
        configure_form(form)
        panel_layout.addLayout(form)
        general_layout.addWidget(panel)
        self.presence_mode = QComboBox()
        for caption, value in ((tr("Livre"), "free"), (tr("Foco"), "focus"), (tr("Apresentação"), "presentation")):
            self.presence_mode.addItem(caption, value)
            self.presence_mode.setItemData(self.presence_mode.count() - 1, tr(PRESENCE_DESCRIPTIONS[value]),
                                           Qt.ItemDataRole.ToolTipRole)
        form_row(form, tr("Modo de presença"), self.presence_mode)
        self.presence_description = label("", "muted")
        self.presence_mode.currentIndexChanged.connect(self.describe_presence)
        self.describe_presence()
        form.addRow(self.presence_description)
        self.presence_status = label(tr("Livre"), "muted")
        self.presence_status.setWordWrap(True)
        form.addRow(self.presence_status)
        self.presence_original = "free"
        self.reduced_motion = QCheckBox(tr("Reduzir movimento"))
        self.reduced_motion.setToolTip(tr("Usa poses estáticas e desativa passeios automáticos e transições da roda."))
        form.addRow(self.reduced_motion)
        self.ui_scale = QComboBox()
        for percent in (100, 125, 150):
            self.ui_scale.addItem(f"{percent}%", percent)
        self.ui_scale.setCurrentIndex(self.ui_scale.findData(ui_scale))
        self.ui_scale.setAccessibleDescription(tr("Ajusta textos e controles da interface. O tamanho do mascote tem seu próprio ajuste."))
        form_row(form, tr("Escala da interface"), self.ui_scale)
        if language_store:
            self.language_choice = QComboBox()
            for key, title in LANGUAGES.items():
                self.language_choice.addItem(title, key)
            self.language_choice.setCurrentIndex(self.language_choice.findData(language_store.data["appearance"]["language"]))
            self.language_status = label(tr("Reinicie o Companion para aplicar a escolha."), "muted")
            self.language_status.setAccessibleName(tr("Estado do idioma"))
            self.language_save = QPushButton(tr("Salvar idioma"))
            self.language_save.setAutoDefault(False)
            self.language_save.clicked.connect(lambda: self.save_language(language_store))
            form_row(form, "Idioma / Language", self.language_choice)
            row = ActionRow()
            row.addWidget(self.language_save)
            self.language_restart = QPushButton(tr("Reiniciar Companion"))
            self.language_restart.setAutoDefault(False)
            self.language_restart.clicked.connect(lambda: self.restart_with_language(language_store))
            row.addWidget(self.language_restart)
            form.addRow(row)
            form.addRow(self.language_status)
        if shortcut_settings is not None:
            form.addRow(shortcut_settings)
        self.scale = QSpinBox()
        self.scale.setRange(64, 256)
        self.scale.setValue(settings.visual_scale)
        self.scale.setSuffix(" DIP")
        self.scale.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        form_row(form, tr("Tamanho do mascote"), self.scale)
        self.personality = QComboBox()
        for title, value in ((tr("Personalizado"), "custom"), (tr("Calmo"), "calm"), (tr("Curioso"), "curious"), (tr("Comunicativo"), "talkative")):
            self.personality.addItem(title, value)
        self.personality.setCurrentIndex(self.personality.findData(settings.personality))
        form_row(form, tr("Personalidade"), self.personality)
        self.appearance = QComboBox()
        for title, value in ((tr("Azul original"), "blue"), (tr("Verde oceano"), "teal"), (tr("Violeta"), "violet"), (tr("Âmbar"), "amber")):
            self.appearance.addItem(title, value)
        self.appearance.setCurrentIndex(self.appearance.findData(settings.appearance))
        form_row(form, tr("Detalhes do robô"), self.appearance)
        if droid_profile is not None and "appearance" not in droid_profile.customization:
            self.appearance.setEnabled(False)
            self.appearance.setToolTip(tr("As personalizações deste personagem estão no Droid Garage."))
        self.frequency = QComboBox()
        for caption, value in ((tr("Desativado"), "off"), (tr("Discreto"), "quiet"), (tr("Normal"), "normal")):
            self.frequency.addItem(caption, value)
        self.frequency.setCurrentIndex(self.frequency.findData(settings.behavior.frequency))
        form_row(form, tr("Comportamento autônomo"), self.frequency)
        self.sleep = QDoubleSpinBox()
        self.sleep.setRange(0.5, 120)
        self.sleep.setSingleStep(0.5)
        self.sleep.setDecimals(1)
        self.sleep.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.sleep.setSuffix(tr(" min sem atividade"))
        self.sleep.setValue(settings.behavior.sleep_seconds / 60)
        form_row(form, tr("Entrar em repouso após"), self.sleep)
        self.controls = {}
        for caption, key, value in ((tr("Caminhar sozinho"), "movement", settings.behavior.movement),
                                  (tr("Sempre visível à frente"), "topmost", settings.window.topmost),
                                  (tr("Balões de diálogo"), "bubbles", settings.bubbles),
                                  (tr("Efeitos sonoros do R2"), "sound_enabled", settings.sound_enabled),
                                  (tr("Observar o cursor"), "cursor_attention", settings.behavior.cursor_attention),
                                  (tr("Reagir a bateria e CPU"), "system_reactions", settings.behavior.system_reactions),
                                  (tr("Comemorar a cada hora"), "hourly_reaction", settings.behavior.hourly_reaction)):
            control = QCheckBox(caption)
            control.setChecked(value)
            self.controls[key] = control
            form.addRow(control)
        self.fullscreen = QComboBox()
        for title, value in ((tr("Automático"), "auto"), (tr("Ocultar mascote"), "hide"),
                             (tr("Ficar no canto"), "corner"), (tr("Ficar em silêncio"), "quiet")):
            self.fullscreen.addItem(title, value)
        self.fullscreen.setCurrentIndex(self.fullscreen.findData(settings.fullscreen_mode))
        form_row(form, tr("Durante tela cheia"), self.fullscreen)
        corner_info = label(tr("Arraste o R2 até um canto para guardar sua preferência. Sem canto escolhido, o modo Automático oculta o mascote durante jogos."), "muted")
        corner_info.setWordWrap(True)
        form.addRow(corner_info)
        self.reaction_interval = QSpinBox()
        self.reaction_interval.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.reaction_interval.setRange(10, 600)
        self.reaction_interval.setSuffix(" s")
        self.reaction_interval.setValue(settings.behavior.reaction_interval)
        form_row(form, tr("Pausa entre reações"), self.reaction_interval)
        self.personality.currentIndexChanged.connect(self.select_profile)
        self.quiet = QCheckBox(tr("Horário de silêncio"))
        self.quiet.setChecked(settings.quiet_enabled)
        form.addRow(self.quiet)
        self.quiet_start, self.quiet_end = QTimeEdit(), QTimeEdit()
        for widget, minutes in ((self.quiet_start, settings.quiet_start), (self.quiet_end, settings.quiet_end)):
            widget.setDisplayFormat("HH:mm")
            widget.setTime(QTime(minutes // 60, minutes % 60))
        form_row(form, tr("Silêncio a partir de"), self.quiet_start)
        form_row(form, tr("Retomar às"), self.quiet_end)
        self.holograms = QCheckBox(tr("Permitir projeções"))
        self.holograms.setAccessibleDescription(tr("Disponíveis pelo menu Projetar."))
        self.holograms.setChecked(settings.holograms)
        form.addRow(self.holograms)
        self.startup = QCheckBox(tr("Iniciar com o Windows"))
        self.startup.setAccessibleDescription(tr("Vale somente para este usuário."))
        self.startup.setEnabled(startup_available)
        self.startup.setChecked(startup_enabled)
        form.addRow(self.startup)
        startup_info = label(startup_status, "muted")
        startup_info.setWordWrap(True)
        form.addRow(startup_info)
        tip = label(tr("No modo Normal, o primeiro passeio acontece em cerca de 15–25 segundos de disponibilidade. Desative Caminhar sozinho se preferir o R2 parado."), "muted")
        tip.setWordWrap(True)
        general_layout.addWidget(tip)
        general_layout.addStretch()
        self.tabs.addTab(scrollable(general), icon("settings"), tr("Preferências"))
        targets = QWidget()
        target_layout = QVBoxLayout(targets)
        target_layout.setContentsMargins(0, 16, 0, 0)
        target_layout.setSpacing(12)
        note = label(tr("Seus favoritos, sempre à mão. Adicione um aplicativo, pasta ou arquivo e escolha um nome fácil de reconhecer."), "muted")
        note.setWordWrap(True)
        target_layout.addWidget(note)
        self.search = QLineEdit()
        self.search.setAccessibleName(tr("Buscar favoritos"))
        self.search.setPlaceholderText(tr("Buscar nos seus favoritos…"))
        self.search.addAction(icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.search.textChanged.connect(self.filter)
        target_layout.addWidget(self.search)
        self.targets = QListWidget()
        self.targets.setAccessibleName(tr("Aplicativos, locais e atalhos"))
        self.targets.setItemDelegate(TargetDelegate(self.targets))
        self.targets.itemSelectionChanged.connect(self.selection_changed)
        target_layout.addWidget(self.targets, 1)
        self.empty = label(tr("Você ainda não adicionou favoritos.\nComece pelos botões abaixo."), "muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)
        target_layout.addWidget(self.empty)
        first = ActionRow()
        for title, kind in ((tr("Aplicativo"), "app"), (tr("Pasta"), "folder"), (tr("Arquivo"), "file")):
            button = QPushButton("+ " + title)
            button.setIcon(icon("apps" if kind == "app" else "folder" if kind == "folder" else "file"))
            button.clicked.connect(lambda checked=False, k=kind: self.add_target(k))
            first.addWidget(button)
        target_layout.addWidget(first)
        second = ActionRow()
        self.selection_buttons = []
        for title, callback in ((tr("Criar atalho"), self.add_alias), (tr("Renomear"), self.rename), (tr("Remover"), self.remove)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            second.addWidget(button)
            self.selection_buttons.append(button)
        target_layout.addWidget(second)
        self.tabs.addTab(scrollable(targets), icon("apps"), tr("Aplicativos e atalhos"))
        audio_page = QWidget()
        audio_form = QFormLayout(audio_page)
        configure_form(audio_form)
        self.muted = QCheckBox(tr("Modo silencioso"))
        self.muted.setChecked(settings.audio.muted)
        audio_form.addRow(self.muted)
        self.volume = QSpinBox()
        self.volume.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.volume.setRange(0, 100)
        self.volume.setSuffix(" %")
        self.volume.setValue(round(settings.audio.volume * 100))
        form_row(audio_form, tr("Volume dos efeitos"), self.volume)
        self.audio_interval = QDoubleSpinBox()
        self.audio_interval.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.audio_interval.setRange(0.1, 60)
        self.audio_interval.setSuffix(" s")
        self.audio_interval.setValue(settings.audio.min_interval)
        form_row(audio_form, tr("Intervalo mínimo entre sons"), self.audio_interval)
        self.audio_categories = {}
        for key, title in (("idle", tr("Reações espontâneas")), ("movement", tr("Movimentos")),
                           ("reactions", tr("Interações")), ("sleep", tr("Dormir e despertar")),
                           ("notifications", tr("Notificações e temporizador"))):
            control = QCheckBox(title)
            control.setChecked(settings.audio.categories[key])
            self.audio_categories[key] = control
            audio_form.addRow(control)
        info = label(tr("O volume é exclusivo do R2. Tela cheia e repouso suspendem sons; o sono permite apenas seu efeito de entrada ou saída."), "muted")
        info.setWordWrap(True)
        audio_form.addRow(info)
        self.tabs.addTab(scrollable(audio_page), tr("Áudio"))
        layout.addWidget(self.tabs, 1)
        self.error = label("", "error")
        self.error.setWordWrap(True)
        layout.addWidget(self.error)
        buttons = ActionRow()
        apply = QPushButton(tr("Aplicar"))
        apply.clicked.connect(lambda: self.apply(False))
        buttons.addWidget(apply)
        cancel = QPushButton(tr("Cancelar"))
        cancel.clicked.connect(self.reject)
        buttons.addWidget(cancel)
        save = QPushButton(tr("Salvar e fechar"))
        save.setProperty("role", "primary")
        save.setDefault(True)
        save.clicked.connect(lambda: self.apply(True))
        buttons.addWidget(save)
        for button in (apply, cancel, save):
            button.setProperty("compact", True)
        layout.addWidget(buttons)
        self.render_targets()

        if droid_profile is not None:
            apply_character_name(self, droid_profile.name)
            self.setWindowTitle(tr("Configurações · {0} · R2 Companion", droid_profile.name))

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
        self.empty.setText(tr("Nenhum resultado para essa busca.") if self.search.text().strip() else
                           tr("Você ainda não adicionou favoritos.\nComece pelos botões abaixo."))
        self.selection_changed()

    def selection_changed(self):
        item = self.targets.currentItem()
        enabled = item is not None and not item.isHidden()
        for button in getattr(self, "selection_buttons", []):
            button.setEnabled(enabled)

    def add_target(self, kind):
        if kind == "folder":
            path = QFileDialog.getExistingDirectory(self, tr("Escolher pasta local"))
        else:
            pattern = "Aplicativos (*.exe)" if kind == "app" else tr("Arquivos permitidos (*.txt *.pdf *.png *.jpg *.jpeg *.wav *.mp3)")
            path, _ = QFileDialog.getOpenFileName(self, tr("Escolher destino local"), "", pattern)
        if not path:
            return
        try:
            resolved = validate_executable(path) if kind == "app" else validate_location(path, kind)
            entry = Target(uuid4().hex, resolved.stem or resolved.name, str(resolved), kind)
            collection = self.draft.applications if kind == "app" else self.draft.locations
            if len(collection) >= 100:
                raise ValueError(tr("Limite de 100 destinos por lista."))
            collection.append(entry)
            self.error.clear()
            self.render_targets()
        except (OSError, ValueError) as error:
            self.error.setText(str(error))

    def add_alias(self):
        item = self.targets.currentItem()
        if item is None:
            self.error.setText(tr("Selecione primeiro um aplicativo ou local."))
            return
        target_id = item.data(Qt.ItemDataRole.UserRole)
        if not any(t.id == target_id for t in self.draft.applications + self.draft.locations):
            return
        label, accepted = QInputDialog.getText(self, tr("Criar atalho"), tr("Nome do atalho:"))
        if accepted and label.strip():
            self.draft.shortcuts.append(Shortcut(uuid4().hex, label.strip(), target_id))
            self.render_targets()

    def rename(self):
        item = self.targets.currentItem()
        if item is None:
            return
        entry = next(t for t in self.draft.applications + self.draft.locations + self.draft.shortcuts
                     if t.id == item.data(Qt.ItemDataRole.UserRole))
        label, accepted = QInputDialog.getText(self, tr("Renomear"), "Nome:", text=entry.label)
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

    def describe_presence(self, *_):
        description = tr(PRESENCE_DESCRIPTIONS[self.presence_mode.currentData()])
        self.presence_description.setText(description)
        self.presence_mode.setAccessibleDescription(description)

    def restart_with_language(self, store):
        if self.save_language(store):
            self.restart_requested.emit()

    def save_language(self, store):
        requested = self.language_choice.currentData()
        if not store.save_language(requested):
            saved = store.data["appearance"]["language"]
            self.language_status.setText(tr("Não foi possível salvar. O Companion voltará a abrir em {0}.", LANGUAGES[saved]))
            return False
        elif requested == active_language():
            self.language_status.setText(tr("Idioma salvo · {0}", LANGUAGES[requested]))
        else:
            self.language_status.setText(tr("Idioma salvo. Reinicie o Companion para usar {0}.", LANGUAGES[requested]))
        return True

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
        self.accessibility_applied.emit(self.ui_scale.currentData(), self.reduced_motion.isChecked())
        if self.error.text():
            return
        if self.presence_mode.currentData() != self.presence_original:
            self.presence_applied.emit(self.presence_mode.currentData())
            self.presence_original = self.presence_mode.currentData()
        self.startup_original = self.startup.isChecked()
        if close:
            self.accept()
