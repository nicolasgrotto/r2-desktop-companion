import json
from pathlib import Path
import re
from weakref import WeakKeyDictionary

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication

from .profiles import DroidTheme

COLOR_TOKENS = {}
for token, colors in {
    "background": "#edf3f9 #f2f5f8 #e5eef7",
    "panel": "#ffffff #fffdf8",
    "text": "#14314c #193b57 #244b6b #214763 #163b58 #15334e",
    "muted": "#647b91 #51728e #617c94 #718ba1 #6a8197",
    "primary": "#216eea #175dcc #3385ee #1652b4 #26b5ed #216a94",
    "focus": "#3188ee #70b0ee #4799ef #67d8ff",
    "hero": "#102c48 #091c30 #0b2138 #153751 #173c58 #102b43",
    "hero_text": "#f5faff #eaf5ff #eaf7ff #f0f8ff #f4faff #f4fcff #e6f7ff #d5edfa",
    "hero_muted": "#a8c5df #a9e6ff #76a6c4 #7893a4 #7796b1 #507c9d",
    "border": "#d8e5f1 #ccddea #caddea #e0e7ee #afc7dc #b9cede #1c486b #39739c #37617e #2d4b66 #38647f #398cb8 #346383 #1b4867 #244e69 #245675 #34769c",
    "selected": "#e8f3ff #d3e8ff #e2efff #a6d8ff #b3cced #e2edf6 #e8f2ff #e4effa #e3edf6",
    "disabled": "#8ba0b3 #91a3b4",
    "error": "#b94343",
    "decoration": "#5196b7",
    "accent": "#47c8f5 #67d2f6 #62bfea #6bcdf5 #71d6fb #62d5ff #67d8ff #73dcff",
}.items():
    for value in colors.split():
        COLOR_TOKENS[value] = token


class ThemeManager(QObject):
    changed = Signal(object)

    def __init__(self):
        super().__init__()
        path = Path(__file__).resolve().parents[1] / "assets/droids/r2_default/profile.json"
        self.active = DroidTheme.parse(json.loads(path.read_text(encoding="utf-8"))["theme"])
        self.widgets = WeakKeyDictionary()

    def render(self, template, theme=None):
        theme = theme or self.active
        colors = theme.colors
        def replace_color(match):
            token = COLOR_TOKENS.get(match[0].lower())
            return colors[token] if token else match[0]
        result = re.sub(r"#[0-9a-fA-F]{6}", replace_color, template)
        result = re.sub(r"\bwhite\b", colors["panel"], result)
        result = re.sub(r"border-radius:\s*(\d+)px", lambda m: f"border-radius: {theme.radius}px" if 8 <= int(m[1]) <= 20 else m[0], result)
        return re.sub(r"@([a-z_]+)", lambda m: colors[m[1]], result)

    def style(self, widget, template):
        self.widgets[widget] = template
        widget.setStyleSheet(self.render(template, theme_for(widget)))

    def refresh(self):
        for widget, template in list(self.widgets.items()):
            try:
                widget.setStyleSheet(self.render(template, theme_for(widget)))
                widget.update()
            except RuntimeError:
                self.widgets.pop(widget, None)
        for widget in QApplication.allWidgets():
            from ..ui.theme import refresh_icons
            refresh_icons(widget)
            widget.update()
        self.changed.emit(self.active)

    def apply(self, theme):
        self.active = theme
        app = QApplication.instance()
        if app:
            palette = app.palette()
            for role, key in ((QPalette.ColorRole.Window, "background"), (QPalette.ColorRole.WindowText, "text"),
                              (QPalette.ColorRole.Base, "panel"), (QPalette.ColorRole.Text, "text"),
                              (QPalette.ColorRole.Button, "panel"), (QPalette.ColorRole.ButtonText, "text"),
                              (QPalette.ColorRole.Highlight, "primary"), (QPalette.ColorRole.HighlightedText, "button_text")):
                palette.setColor(role, QColor(theme.colors[key]))
            app.setPalette(palette)
        self.refresh()


_manager = None


def theme_manager():
    global _manager
    if _manager is None:
        _manager = ThemeManager()
    return _manager


def theme_for(widget=None):
    while widget is not None:
        override = getattr(widget, "droid_preview_theme", None)
        if override is not None:
            return override
        widget = widget.parentWidget()
    return theme_manager().active


def color(key, widget=None):
    return theme_for(widget).colors[key]


def styled(widget, template):
    theme_manager().style(widget, template)


class PersistedThemeWatcher(QObject):
    profile_changed = Signal(object)

    def __init__(self, directory, assets, parent=None):
        super().__init__(parent)
        self.directory, self.assets = directory, assets
        self.last_id = None
        self.timer = QTimer(self)
        self.timer.setInterval(750)
        self.timer.timeout.connect(self.refresh)
        self.refresh()
        self.timer.start()

    def refresh(self):
        from ..core.config import Settings
        from .profiles import DroidRegistry
        try:
            path = self.directory / "config.json"
            if path.stat().st_size > 1024 * 1024:
                return
            settings = Settings.parse(json.loads(path.read_text(encoding="utf-8")))
            if settings.active_droid != self.last_id:
                registry = DroidRegistry(self.assets)
                profile = registry.get(settings.active_droid)
                theme_manager().apply(profile.theme)
                self.last_id = settings.active_droid
                self.profile_changed.emit(profile)
        except (OSError, ValueError, KeyError, TypeError):
            pass
