import json
from pathlib import Path
import re
from weakref import WeakKeyDictionary

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QWidget

from ..core.config import FutureSchemaError, Settings
from ..services.companion_state import CompanionStateStore, default_document
from .profiles import DroidRegistry

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
    scale_changed = Signal(int)

    def __init__(self):
        super().__init__()
        assets = Path(__file__).resolve().parents[1] / "assets"
        self.active = DroidRegistry(assets).active.theme
        self.ui_scale = 100
        self.widgets = WeakKeyDictionary()

    def dip(self, value):
        return round(value * self.ui_scale / 100)

    def render(self, template, theme=None):
        theme = theme or self.active
        colors = theme.colors
        def replace_color(match):
            token = COLOR_TOKENS.get(match[0].lower())
            return colors[token] if token else match[0]
        result = re.sub(r"#[0-9a-fA-F]{6}", replace_color, template)
        result = re.sub(r"\bwhite\b", colors["panel"], result)
        result = re.sub(r"border-radius:\s*(\d+)px", lambda m: f"border-radius: {theme.radius}px" if 8 <= int(m[1]) <= 20 else m[0], result)
        result = re.sub(r"@([a-z_]+)", lambda m: colors[m[1]], result)
        if self.ui_scale != 100:
            # Qt applies monitor DPI to these logical pixels separately.
            result = re.sub(
                r"(?<![\w-])(?:font(?:-size)?|padding(?:-[a-z]+)?|spacing|(?:min-)?(?:width|height)|icon-size)\s*:[^;}]+",
                lambda declaration: re.sub(r"(\d+)px", lambda px: f"{self.dip(int(px[1]))}px", declaration[0]),
                result,
            )
        return result

    def style(self, widget, template):
        self.widgets[widget] = template
        widget.setStyleSheet(self.render(template, theme_for(widget)))

    def refresh(self, *, theme_changed=True, root=None):
        refreshed = set()
        for widget, template in list(self.widgets.items()):
            try:
                if root is not None and widget is not root and not root.isAncestorOf(widget):
                    continue
                widget.setStyleSheet(self.render(template, theme_for(widget)))
                from ..ui.theme import refresh_icons
                for child in (widget, *widget.findChildren(QWidget)):
                    if child not in refreshed:
                        refreshed.add(child)
                        if theme_changed:
                            refresh_icons(child)
                        child.update()
            except RuntimeError:
                self.widgets.pop(widget, None)
        if theme_changed and root is None:
            self.changed.emit(self.active)

    def set_ui_scale(self, percent):
        if percent not in (100, 125, 150):
            raise ValueError("Escala da interface inválida.")
        if percent != self.ui_scale:
            self.ui_scale = percent
            self.refresh(theme_changed=False)
            self.scale_changed.emit(percent)

    def unregister_tree(self, root):
        for widget in list(self.widgets):
            try:
                if widget is root or root.isAncestorOf(widget):
                    self.widgets.pop(widget, None)
            except RuntimeError:
                self.widgets.pop(widget, None)

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


def resolve_theme(registry, profile, provider_id):
    if provider_id == profile.id:
        return profile.theme
    return registry.profiles.get(provider_id, profile).theme


class PersistedThemeWatcher(QObject):
    profile_changed = Signal(object)
    accessibility_changed = Signal(object)

    def __init__(self, directory, assets, parent=None):
        super().__init__(parent)
        self.directory = Path(directory).resolve()
        self.registry = DroidRegistry(assets)
        self.profile = self.registry.active
        self.accessibility = default_document()["accessibility"]
        self.last_id = None
        self.last_stamp = None
        self.state_cache = {}
        self.closed = False
        self.watcher = QFileSystemWatcher(self)
        self.watcher.fileChanged.connect(self.queue_refresh)
        self.watcher.directoryChanged.connect(self.queue_refresh)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(0)
        self.timer.timeout.connect(self.refresh)
        self.refresh()

    def queue_refresh(self, *_):
        if not self.closed:
            self.timer.start()

    def sync_paths(self):
        directory = self.directory
        while not directory.is_dir() and directory != directory.parent:
            directory = directory.parent
        desired = {str(directory)}
        current = set(self.watcher.directories() + self.watcher.files())
        if current - desired:
            self.watcher.removePaths(sorted(current - desired))
        if desired - current:
            self.watcher.addPaths(sorted(desired - current))

    def read_profile(self):
        path = self.directory / "config.json"
        try:
            stat = path.stat()
            stamp = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
            if stamp != self.last_stamp:
                self.last_stamp = stamp
                if stat.st_size <= 1024 * 1024:
                    settings = Settings.parse(json.loads(path.read_text(encoding="utf-8")))
                    return self.registry.profiles.get(settings.active_droid, self.registry.active)
        except FileNotFoundError:
            self.last_stamp = None
        except (OSError, ValueError, KeyError, TypeError, RecursionError):
            pass
        return self.profile

    def read_state_file(self, name):
        path = self.directory / name
        try:
            stat = path.stat()
        except OSError:
            self.state_cache.pop(name, None)
            return None
        stamp = (stat.st_ino, stat.st_mtime_ns, stat.st_size)
        cached_stamp, document = self.state_cache.get(name, (None, None))
        if stamp != cached_stamp:
            try:
                document = CompanionStateStore.read_document_file(path)
            except FutureSchemaError:
                document = default_document()
            except (OSError, ValueError, RecursionError):
                document = None
            self.state_cache[name] = stamp, document
        return document

    def refresh(self):
        if self.closed:
            return
        try:
            self.sync_paths()
        except OSError:
            return
        profile = self.read_profile()
        document = (self.read_state_file("companion_state.json")
                    or self.read_state_file("companion_state.backup.json") or default_document())
        provider = document["appearance"]["theme_overrides"].get(profile.id)
        manager = theme_manager()
        theme = resolve_theme(self.registry, profile, provider)
        if manager.active != theme:
            manager.apply(theme)
        if profile.id != self.last_id:
            self.profile, self.last_id = profile, profile.id
            self.profile_changed.emit(profile)
        accessibility = document["accessibility"]
        if accessibility != self.accessibility:
            self.accessibility = accessibility
            self.accessibility_changed.emit(accessibility)

    def close(self):
        self.closed = True
        self.timer.stop()
        paths = self.watcher.files() + self.watcher.directories()
        if paths:
            self.watcher.removePaths(paths)
