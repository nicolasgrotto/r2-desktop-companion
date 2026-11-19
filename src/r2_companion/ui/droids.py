from copy import deepcopy
from dataclasses import replace
import math
import time

from PySide6.QtCore import QRectF, QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QListWidget, QListWidgetItem,
                              QPushButton, QScrollArea, QSlider, QSpinBox, QVBoxLayout, QWidget)

from ..droids.preferences import defaults_for, preferences_for
from ..droids.themes import color, resolve_theme, theme_manager
from ..droids.visuals import VISUAL_TYPES, load_profile_clips, paint_visual
from ..droids.movement import create_movement
from ..droids.expressions import paint_expression
from ..droids.rig import ArticulatedVisual
from ..pet.animation import AnimationManager, Clip
from ..pet.personality import apply_profile
from ..pet.scenes import CATALOG, SCENE_LABELS, scene_clips
from ..pet.state import State
from .theme import ActionRow, apply_character_name, apply_theme, configure_form, form_row, header, label

ANIMATION_NAMES = {"IDLE": "Repouso", "BLINK": "Piscar", "LOOK_AROUND": "Observar", "WALK": "Locomoção",
                   "HAPPY": "Felicidade", "CURIOUS": "Curiosidade", "SLEEP": "Sono", "INTERACT": "Interação",
                   "NOTIFICATION": "Comemoração", "SURPRISED": "Surpresa", "WORK": "Inspeção",
                   "CONFUSED": "Confusão", "DRAG": "Esforço no arrasto", "RECOVER": "Recuperar equilíbrio",
                   "WAKE": "Despertar", "GREETING": "Cumprimento", "WORRIED": "Preocupação",
                   "OVERHEAT": "Aquecimento", "LOOK_LEFT": "Olhar à esquerda", "LOOK_RIGHT": "Olhar à direita"}


class PreviewCanvas(QWidget):
    def __init__(self):
        super().__init__()
        self.setMinimumSize(220, 235)
        self.frame = QPixmap()
        self.angle = self.tilt = self.offset = 0
        self.illumination = None
        self.decoration = False
        self.appearance = "blue"
        self.articulation = {}
        self.movement = None
        self.previous_roll = 0
        self.state = None
        self.effect_started = time.monotonic()
        self.effect_timer = QTimer(self)
        self.effect_timer.setInterval(50)
        self.effect_timer.timeout.connect(self.update)
        self.started = time.monotonic()
        self.roll_timer = QTimer(self)
        self.roll_timer.setInterval(33)
        self.roll_timer.timeout.connect(self.roll)
        self.setAccessibleName("Prévia independente do personagem")

    def set_frame(self, frame):
        self.frame = frame
        self.update()

    def roll(self):
        t = ((time.monotonic() - self.started) % 3) / 3
        eased = t * t * (3 - 2 * t)
        self.angle = 360 * eased
        self.tilt = 8 * math.sin(t * math.pi * 2)
        if self.movement:
            travel = 30 * math.sin(t * math.pi * 2)
            self.movement.displaced(travel - self.previous_roll, 0)
            self.previous_roll = travel
        self.update()

    def set_articulation(self, channels):
        self.articulation = dict(channels)
        self.update()

    def configure_movement(self, profile):
        self.close_movement()
        if profile.renderer == "rigged":
            self.movement = create_movement(profile, self)

    def close_movement(self):
        if self.movement:
            self.movement.close()
            self.movement.deleteLater()
            self.movement = None
        self.articulation = {}

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), QColor(color("hero", self)))
        p.setPen(QPen(QColor(color("decoration", self)), 1))
        for x in range(0, self.width(), 28):
            p.drawLine(x, 0, x, self.height())
        for y in range(0, self.height(), 28):
            p.drawLine(0, y, self.width(), y)
        side = min(self.width() - 36, self.height() - 32, 256)
        rect = QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)
        if isinstance(self.frame, VISUAL_TYPES):
            paint_visual(p, rect, self.frame, self.angle, self.tilt, 0, self.illumination, self.decoration, self.articulation)
        elif not self.frame.isNull():
            p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)
            frame = self.frame
            if self.appearance != "blue" or self.illumination:
                palette = {"teal": ("#188b87", "#7be9d4"), "violet": ("#7855b8", "#c3a3ff"), "amber": ("#bc8128", "#ffdc8e")}
                picture = frame.toImage()
                mapping = {}
                if self.appearance != "blue":
                    first, second = palette[self.appearance]
                    mapping = {QColor("#286bc0").rgba(): QColor(first).rgba(), QColor("#71d1ee").rgba(): QColor(second).rgba()}
                if self.illumination:
                    mapping[QColor("#edac4b").rgba()] = QColor(self.illumination).rgba()
                for y in range(picture.height()):
                    for x in range(picture.width()):
                        value = picture.pixel(x, y)
                        if value in mapping:
                            picture.setPixel(x, y, mapping[value])
                frame = QPixmap.fromImage(picture)
            p.drawPixmap(rect.toRect(), frame)
        if self.state in {State.SLEEP, State.OVERHEAT} and not (
                isinstance(self.frame, ArticulatedVisual) and self.frame.expression_style):
            phase = ((time.monotonic()-self.effect_started)/2.8) % 1 if self.effect_timer.isActive() else 0.35
            paint_expression(p, self.state, phase, rect=rect)


class DroidStudio(QDialog):
    def __init__(self, companion, title):
        super().__init__()
        self.companion = companion
        self.registry = companion.droids
        self.profile = None
        self.clips = {}
        self.animation = AnimationManager({})
        self.animation.set_reduced_motion(companion.presence.context.reduced_motion)
        companion.companion_state.changed.connect(self.motion_preferences_changed)
        self.setWindowTitle(title + " · R2 Companion")
        self.resize(830, 740)
        apply_theme(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        outer.addWidget(self.scroll_area)
        content = QWidget()
        self.scroll_area.setWidget(content)
        self.layout_main = QVBoxLayout(content)
        self.layout_main.setContentsMargins(14, 20, 14, 20)
        self.layout_main.addWidget(header(title, "Explore a identidade e as animações de cada companheiro."))
        self.selector = QComboBox()
        self.selector.setAccessibleName("Personagem para visualizar")
        self.selector.setMaxVisibleItems(7)
        for profile in self.registry.profiles.values():
            self.selector.addItem(profile.name, profile.id)
        self.layout_main.addWidget(self.selector)
        self.equipped = label("", "eyebrow")
        self.layout_main.addWidget(self.equipped)
        self.name = label("", "heading")
        self.description = label("", "muted")
        self.description.setWordWrap(True)
        self.layout_main.addWidget(self.name)
        self.layout_main.addWidget(self.description)
        row = ActionRow()
        self.preview = PreviewCanvas()
        row.addWidget(self.preview, 3)
        animation_controls = QWidget()
        column = QVBoxLayout(animation_controls)
        column.setContentsMargins(0, 0, 0, 0)
        self.category = QComboBox()
        self.category.setAccessibleName("Categoria das animações")
        column.addWidget(self.category)
        self.animations = QListWidget()
        self.animations.setAccessibleName("Animações do personagem")
        column.addWidget(self.animations, 1)
        self.frame_variant = QComboBox()
        self.frame_variant.setAccessibleName("Frame ou variação da animação")
        column.addWidget(self.frame_variant)
        row.addWidget(animation_controls, 2)
        self.layout_main.addWidget(row, 1)
        controls = ActionRow()
        self.repeat = QCheckBox("Repetir sequência")
        self.repeat.setChecked(True)
        controls.addWidget(self.repeat)
        for title, callback in (("Anterior", lambda: self.step(-1)), ("Reproduzir", self.play),
                                ("Parar", self.stop), ("Próxima", lambda: self.step(1))):
            button = QPushButton(title)
            button.clicked.connect(callback)
            controls.addWidget(button)
        self.layout_main.addWidget(controls)
        self.status = label("", "muted")
        self.status.setWordWrap(True)
        self.layout_main.addWidget(self.status)
        self.animation.frame_changed.connect(self.preview.set_frame)
        self.animation.clip_finished.connect(lambda token: self.preview.roll_timer.stop())
        self.animation.clip_finished.connect(lambda token: self.preview.effect_timer.stop())
        self.animations.currentRowChanged.connect(self.animation_selected)
        self.frame_variant.currentIndexChanged.connect(self.show_variant)
        self.repeat.toggled.connect(self.play)
        self.category.currentIndexChanged.connect(self.filter_animations)
        self.selector.currentIndexChanged.connect(self.load_selected)

    def initialize(self):
        self.selector.setCurrentIndex(self.selector.findData(self.registry.active_id))
        self.load_selected()

    def load_selected(self, *_):
        self.stop()
        try:
            profile = self.registry.get(self.selector.currentData())
            clips = load_profile_clips(profile)
        except (OSError, ValueError, KeyError, TypeError) as error:
            self.status.setText(f"Prévia indisponível: {error}")
            return
        self.profile, self.clips = profile, clips
        self.preview.configure_movement(profile)
        self.droid_preview_theme = profile.theme
        self.animation.clips = clips
        self.name.setText(profile.name)
        self.description.setText(profile.description)
        self.equipped.setText(f"EQUIPADO: {self.registry.active.name}  /  PRÉVIA: {profile.name}")
        self.status.setText(profile.art_status)
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItem("Todas as categorias", "")
        if profile.id in CATALOG:
            self.category.addItem("Cenas do personagem", "scenes")
        for category in sorted(set(profile.animations.values())):
            self.category.addItem(category, category)
        self.category.blockSignals(False)
        self.filter_animations()
        self.profile_loaded()
        theme_manager().refresh(root=self)
        for field in (self.name, self.description, self.equipped, self.status):
            field.setProperty("characterLiteral", True)
        apply_character_name(self, profile.name)

    def profile_loaded(self):
        preferences = preferences_for(self.companion.store.settings, self.profile)
        custom = self.profile.customizations(preferences.customization)
        self.preview.appearance = preferences.appearance if "appearance" in custom else "blue"
        self.preview.illumination = None
        if "illumination" in custom:
            self.preview.illumination = self.profile.customization["illumination"]["options"][custom["illumination"]]["color"]
        self.preview.decoration = custom.get("decoration") == "beacon"
        self.preview.update()

    def filter_animations(self, *_):
        if self.profile is None:
            return
        category = self.category.currentData()
        with QSignalBlocker(self.animations):
            self.animations.clear()
            if category == "scenes":
                for key, scene in CATALOG[self.profile.id].items():
                    item = QListWidgetItem(SCENE_LABELS[key])
                    item.setData(Qt.ItemDataRole.UserRole, key)
                    item.setToolTip(" → ".join(ANIMATION_NAMES[state.value] for state, _ in scene.steps))
                    self.animations.addItem(item)
            else:
                for state, group in self.profile.animations.items():
                    if not category or group == category:
                        item = QListWidgetItem(ANIMATION_NAMES.get(state.value, state.value))
                        item.setData(Qt.ItemDataRole.UserRole, state)
                        item.setToolTip(f"{state.value} · {len(self.clips[state].frames)} frames · {group}")
                        self.animations.addItem(item)
            self.animations.setCurrentRow(0)
        self.animation_selected()

    def animation_selected(self, *_):
        item = self.animations.currentItem()
        self.frame_variant.blockSignals(True)
        self.frame_variant.clear()
        self.frame_variant.addItem("Sequência completa", -1)
        is_scene = self.category.currentData() == "scenes"
        self.frame_variant.setEnabled(not is_scene)
        if item is not None and not is_scene:
            clip = self.clips[item.data(Qt.ItemDataRole.UserRole)]
            for i in range(len(clip.frames)):
                self.frame_variant.addItem(f"Frame {i + 1}", i)
        self.frame_variant.blockSignals(False)
        self.play()

    def play(self):
        self.stop()
        item = self.animations.currentItem()
        if item is None:
            return
        state = item.data(Qt.ItemDataRole.UserRole)
        if self.category.currentData() == "scenes":
            scene = CATALOG[self.profile.id][state]
            clips = tuple(clip for _, clip in scene_clips(scene, self.clips))
            if clips:
                frames = tuple(frame for clip in clips for frame in clip.frames)
                self.preview.state = None
                preview_clip = Clip(frames, self.repeat.isChecked(), clips[0].still_index)
                self.animation.play(State.IDLE, 1, clip=preview_clip)
            return
        if state not in self.clips:
            return
        self.frame_variant.blockSignals(True)
        self.frame_variant.setCurrentIndex(0)
        self.frame_variant.blockSignals(False)
        self.animation.clips = {state: replace(self.clips[state], loop=self.repeat.isChecked())}
        self.preview.state = state
        self.preview.effect_started = time.monotonic()
        self.animation.play(state, 1)
        self.start_preview_effects(state)

    def start_preview_effects(self, state):
        if self.animation.reduced_motion:
            return
        if state in {State.SLEEP, State.OVERHEAT} and self.profile.renderer != "rigged":
            self.preview.effect_timer.start()
        if state == State.WALK and self.profile.renderer in {"layered", "rigged"}:
            self.preview.started = time.monotonic()
            self.preview.previous_roll = 0
            self.preview.roll_timer.start()

    def motion_preferences_changed(self, document):
        enabled = document["accessibility"]["reduced_motion"]
        if enabled == self.animation.reduced_motion:
            return
        self.animation.set_reduced_motion(enabled)
        if enabled:
            self.preview.roll_timer.stop()
            self.preview.effect_timer.stop()
            if self.preview.movement:
                self.preview.movement.stop()
            self.preview.update()
        elif self.animation.clip is not None:
            self.start_preview_effects(self.preview.state)

    def stop(self):
        self.animation.stop()
        self.preview.effect_timer.stop()
        self.preview.roll_timer.stop()
        if self.preview.movement:
            self.preview.movement.stop()
        self.preview.angle = self.preview.tilt = 0
        self.preview.update()

    def show_variant(self, *_):
        if self.frame_variant.currentData() is None or self.frame_variant.currentData() < 0:
            return
        item = self.animations.currentItem()
        if item is None:
            return
        self.stop()
        frame = self.clips[item.data(Qt.ItemDataRole.UserRole)].frames[self.frame_variant.currentData()]
        self.preview.set_frame(frame.visual if frame.visual is not None else frame.pixmap)

    def step(self, direction):
        count = self.animations.count()
        if count:
            self.animations.setCurrentRow((self.animations.currentRow() + direction) % count)

    def release_preview(self):
        self.stop()
        self.preview.state = None
        self.animation.clips = {}
        self.clips = {}
        self.preview.set_frame(QPixmap())
        self.preview.close_movement()

    def closeEvent(self, event):
        self.release_preview()
        super().closeEvent(event)

    def hideEvent(self, event):
        self.release_preview()
        super().hideEvent(event)

    def showEvent(self, event):
        if not self.clips:
            self.load_selected()
        super().showEvent(event)


class DroidGarage(DroidStudio):
    def __init__(self, companion):
        super().__init__(companion, "Droid Garage")
        self.preferences = None
        self.custom_controls = {}
        self.form_widget = QWidget()
        self.form = QFormLayout(self.form_widget)
        configure_form(self.form)
        self.personality = QComboBox()
        for name, key in (("Personalizado", "custom"), ("Calmo", "calm"), ("Curioso", "curious"), ("Comunicativo", "talkative")):
            self.personality.addItem(name, key)
        form_row(self.form, "Personalidade individual", self.personality)
        self.personality.currentIndexChanged.connect(self.personality_changed)
        self.layout_main.addWidget(self.form_widget)
        theme_form = QFormLayout()
        configure_form(theme_form)
        self.theme_choice = QComboBox()
        self.theme_choice.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.theme_choice.setMinimumContentsLength(15)
        self.theme_choice.addItem("Usar tema original", None)
        for profile in self.registry.profiles.values():
            self.theme_choice.addItem(f"{profile.theme.name} · {profile.name}", profile.id)
        self.theme_choice.setAccessibleDescription(
            "Vale para o personagem selecionado na Garage. Confirme com Salvar tema.")
        form_row(theme_form, "Tema da interface", self.theme_choice)
        self.save_theme_button = QPushButton("Salvar tema")
        self.save_theme_button.clicked.connect(self.save_theme)
        theme_form.addRow(self.save_theme_button)
        self.theme_status = label("", "muted")
        self.theme_status.setProperty("characterLiteral", True)
        theme_form.addRow(self.theme_status)
        self.layout_main.addLayout(theme_form)
        self.theme_choice.currentIndexChanged.connect(self.preview_theme)
        self.unavailable_theme_index = None
        row = ActionRow()
        self.reset_button = QPushButton("Restaurar padrão individual")
        self.reset_button.clicked.connect(self.restore_defaults)
        row.addWidget(self.reset_button)
        self.voice_button = QPushButton("Testar vocalização")
        self.voice_button.clicked.connect(self.test_voice)
        row.addWidget(self.voice_button)
        self.equip_button = QPushButton("Equipar e salvar")
        self.equip_button.setAccessibleDescription("Equipe este personagem e salve sua personalização.")
        self.equip_button.setProperty("role", "primary")
        self.equip_button.clicked.connect(self.equip)
        row.addWidget(self.equip_button)
        self.layout_main.addWidget(row)
        self.initialize()

    def profile_loaded(self):
        self.preferences = preferences_for(self.companion.store.settings, self.profile)
        self.render_preferences()
        self.load_theme_choice()

    def load_theme_choice(self):
        store = self.companion.companion_state
        saved = store.theme_override_for(self.profile.id)
        with QSignalBlocker(self.theme_choice):
            if self.unavailable_theme_index is not None:
                self.theme_choice.removeItem(self.unavailable_theme_index)
                self.unavailable_theme_index = None
            index = self.theme_choice.findData(saved) if saved is not None else 0
            if index < 0:
                index = self.theme_choice.count()
                self.theme_choice.addItem(f"Tema indisponível · {saved}", saved)
                self.theme_choice.model().item(index).setEnabled(False)
                self.unavailable_theme_index = index
            self.theme_choice.setCurrentIndex(index)
        self.theme_choice.setEnabled(not store.read_only)
        self.preview_theme()

    def preview_theme(self, *_):
        store = self.companion.companion_state
        saved = store.theme_override_for(self.profile.id)
        selected = self.theme_choice.currentData()
        effective = resolve_theme(self.registry, self.profile, saved)
        preview = resolve_theme(self.registry, self.profile, selected)
        status = f"Tema em uso para {self.profile.name}: {effective.name}."
        if saved is not None and saved not in self.registry.profiles:
            status += " A escolha salva está indisponível. O tema original está em uso."
        if store.read_only:
            status += " Preferência somente leitura."
        elif selected != saved:
            status += f" Prévia: {preview.name}."
        self.theme_status.setText(status)
        self.save_theme_button.setEnabled(not store.read_only and selected != saved)
        if self.droid_preview_theme != preview:
            self.droid_preview_theme = preview
            theme_manager().refresh(root=self)

    def save_theme(self):
        if not self.save_theme_button.isEnabled():
            return
        store = self.companion.companion_state
        try:
            saved = store.save_theme_override(self.profile.id, self.theme_choice.currentData())
        except ValueError as error:
            self.preview_theme()
            self.theme_status.setText(self.theme_status.text() + f" {error}")
            return
        if saved:
            self.load_theme_choice()
            self.theme_status.setText(f"Tema salvo para {self.profile.name}: {self.droid_preview_theme.name}.")
        else:
            self.preview_theme()
            self.theme_status.setText(self.theme_status.text() + " Não foi possível salvar a escolha.")

    def render_preferences(self):
        self.personality.blockSignals(True)
        self.personality.setCurrentIndex(self.personality.findData(self.preferences.personality))
        self.personality.blockSignals(False)
        while self.form.rowCount() > 1:
            self.form.removeRow(1)
        self.custom_controls = {}
        values = self.profile.customizations(self.preferences.customization)
        for key, spec in self.profile.customization.items():
            control = QComboBox()
            for value, option in spec["options"].items():
                control.addItem(option["label"], value)
            selected = self.preferences.appearance if key == "appearance" else values[key]
            control.setCurrentIndex(control.findData(selected))
            form_row(self.form, spec["label"], control)
            self.custom_controls[key] = control
            control.currentIndexChanged.connect(self.customization_changed)
        order = (self.personality, *self.custom_controls.values(), self.theme_choice, self.save_theme_button,
                 self.reset_button, self.voice_button,
                 self.equip_button)
        for current, following in zip(order, order[1:]):
            QWidget.setTabOrder(current, following)
        self.customization_changed()

    def personality_changed(self, *_):
        if self.preferences is None:
            return
        draft = deepcopy(self.companion.store.settings)
        draft.behavior, draft.audio = deepcopy(self.preferences.behavior), deepcopy(self.preferences.audio)
        draft = apply_profile(draft, self.personality.currentData())
        self.preferences.behavior, self.preferences.audio = draft.behavior, draft.audio
        self.preferences.personality = draft.personality

    def customization_changed(self, *_):
        if self.preferences is None:
            return
        self.preferences.customization = {k: w.currentData() for k, w in self.custom_controls.items()}
        self.preview.illumination = None
        if "appearance" in self.custom_controls:
            self.preferences.appearance = self.custom_controls["appearance"].currentData()
        self.preview.appearance = self.preferences.appearance if "appearance" in self.custom_controls else "blue"
        if "illumination" in self.custom_controls:
            value = self.custom_controls["illumination"].currentData()
            self.preview.illumination = self.profile.customization["illumination"]["options"][value]["color"]
        self.preview.decoration = self.preferences.customization.get("decoration") == "beacon"
        self.preview.update()

    def restore_defaults(self):
        self.preferences = defaults_for(self.profile)
        self.render_preferences()

    def test_voice(self):
        try:
            played = self.companion.audio.preview(self.profile.audio, "voice", "greeting", -1, self.preferences.audio)
            self.status.setText("Vocalização iniciada." if played else "Som indisponível: verifique master, silêncio, categoria e intervalo na Central de Áudio.")
        except (OSError, ValueError, RuntimeError) as error:
            self.status.setText(str(error))

    def equip(self):
        if self.companion.equip_droid(self.profile.id, self.preferences):
            self.equipped.setText(f"EQUIPADO: {self.profile.name}")
            self.status.setText("Personagem equipado e preferências salvas.")
        else:
            self.status.setText(self.companion.droid_error)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.companion.audio.clear_preview()


class AudioCenter(QDialog):
    def __init__(self, companion):
        super().__init__()
        self.companion = companion
        self.profile = None
        self.setWindowTitle("Central de Áudio · R2 Companion")
        self.resize(700, 660)
        apply_theme(self)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        outer.addWidget(self.scroll_area)
        content = QWidget()
        self.scroll_area.setWidget(content)
        layout = QVBoxLayout(content)
        layout.addWidget(header("Central de Áudio", "Compare vozes e salve preferências individuais."))
        self.selector = QComboBox()
        self.selector.setAccessibleName("Personagem para testar e editar o áudio")
        for profile in companion.droids.profiles.values():
            self.selector.addItem(profile.name, profile.id)
        layout.addWidget(self.selector)
        self.master = QCheckBox("Habilitar áudio")
        self.master.setAccessibleDescription("Esta opção vale para todos os personagens.")
        self.master.setChecked(companion.store.settings.sound_enabled)
        layout.addWidget(self.master)
        self.mute = QCheckBox("Silenciar este personagem")
        layout.addWidget(self.mute)
        form = QFormLayout()
        configure_form(form)
        self.volume = QSpinBox()
        self.volume.setRange(0, 100)
        self.volume.setSuffix(" %")
        form_row(form, "Volume individual", self.volume)
        layout.addLayout(form)
        self.catalog = QListWidget()
        self.catalog.setAccessibleName("Frases e efeitos sonoros")
        layout.addWidget(self.catalog, 1)
        variant_form = QFormLayout()
        configure_form(variant_form)
        self.variant = QComboBox()
        self.variant.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.variant.setMinimumContentsLength(12)
        self.variant.addItem("Todas as variantes", -1)
        form_row(variant_form, "Variante da frase", self.variant)
        layout.addLayout(variant_form)
        self.categories = {}
        row = ActionRow()
        for category, title in (("idle", "Espontâneo"), ("movement", "Movimento"), ("reactions", "Reações"), ("sleep", "Sono"), ("notifications", "Avisos")):
            control = QCheckBox(title)
            self.categories[category] = control
            row.addWidget(control)
        layout.addWidget(row)
        self.status = label("As prévias respeitam master, mute ativo, tela cheia, silêncio e cooldowns.", "muted")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        row = ActionRow()
        for title, callback in (("Testar selecionado", self.test_selected), ("Parar áudio", companion.audio.stop), ("Salvar preferências", self.save)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        layout.addWidget(row)
        self.selector.currentIndexChanged.connect(self.load_selected)
        self.catalog.currentRowChanged.connect(self.update_variants)
        self.selector.setCurrentIndex(self.selector.findData(companion.droids.active_id))
        self.load_selected()

    def load_selected(self, *_):
        self.companion.audio.clear_preview()
        self.profile = self.companion.droids.get(self.selector.currentData())
        self.preferences = preferences_for(self.companion.store.settings, self.profile)
        self.volume.setValue(round(self.preferences.audio.volume * 100))
        self.mute.setChecked(self.preferences.audio.muted)
        for key, control in self.categories.items():
            control.setChecked(self.preferences.audio.categories[key])
        self.catalog.clear()
        from PySide6.QtWidgets import QListWidgetItem
        for emotion in self.profile.audio.phrases:
            item = QListWidgetItem("Frase · " + emotion)
            item.setData(Qt.ItemDataRole.UserRole, ("voice", emotion))
            self.catalog.addItem(item)
        for path in sorted(self.profile.audio.sounds.glob("*/*.wav")):
            item = QListWidgetItem(f"Efeito · {path.parent.name} / {path.stem}")
            item.setData(Qt.ItemDataRole.UserRole, ("effect", path.stem))
            self.catalog.addItem(item)
        self.catalog.setCurrentRow(0)
        apply_character_name(self, self.profile.name)

    def update_variants(self, *_):
        self.variant.clear()
        self.variant.addItem("Todas as variantes", -1)
        item = self.catalog.currentItem()
        if item is None:
            return
        kind, name = item.data(Qt.ItemDataRole.UserRole)
        if kind == "voice":
            for i, syllables in enumerate(self.profile.audio.phrases[name]):
                self.variant.addItem(f"{i + 1} · " + " / ".join(syllables), i)

    def draft_audio(self):
        settings = deepcopy(self.preferences.audio)
        settings.volume = self.volume.value() / 100
        settings.muted = self.mute.isChecked()
        settings.categories = {k: w.isChecked() for k, w in self.categories.items()}
        return settings

    def test_selected(self):
        item = self.catalog.currentItem()
        if item is None:
            return
        kind, name = item.data(Qt.ItemDataRole.UserRole)
        try:
            played = self.companion.audio.preview(self.profile.audio, kind, name, self.variant.currentData(), self.draft_audio())
            self.status.setText("Reprodução iniciada." if played else "Prévia bloqueada ou carregando. Confira master salvo, mute, categoria, contexto e cooldown.")
        except (OSError, ValueError, RuntimeError) as error:
            self.status.setText(str(error))

    def save(self):
        settings = deepcopy(self.companion.store.settings)
        settings.sound_enabled = self.master.isChecked()
        preferences = preferences_for(settings, self.profile)
        preferences.audio = self.draft_audio()
        settings.droid_preferences[self.profile.id] = preferences
        if settings.active_droid == self.profile.id:
            settings.audio = deepcopy(preferences.audio)
        self.companion.store.apply(settings)
        self.status.setText("Preferências salvas." if self.companion.store.flush() else "Preferências aplicadas nesta sessão; falha ao gravar.")

    def hideEvent(self, event):
        self.companion.audio.clear_preview()
        super().hideEvent(event)

    def showEvent(self, event):
        self.master.setChecked(self.companion.store.settings.sound_enabled)
        self.load_selected()
        super().showEvent(event)
