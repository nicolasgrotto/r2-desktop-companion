"""Interface language for the current Companion process."""
from functools import lru_cache
import json
from pathlib import Path

from PySide6.QtCore import QLocale, QTranslator


LANGUAGES = {"pt-BR": "Português (Brasil)", "en": "English"}
DEFAULT_LANGUAGE = "pt-BR"
_active = DEFAULT_LANGUAGE
_catalog = {}


def interface_language(value):
    return value if isinstance(value, str) and value in LANGUAGES else DEFAULT_LANGUAGE


def active_language():
    return _active


@lru_cache(maxsize=1)
def english_catalog():
    path = Path(__file__).resolve().parents[1] / "assets" / "translations" / "en.json"
    return json.loads(path.read_text(encoding="utf-8"))


def tr(source, *values):
    message = _catalog.get(source, source)
    return message.format(*values) if values else message


def locale():
    return QLocale("en_US" if _active == "en" else "pt_BR")


class StandardButtons(QTranslator):
    BUTTONS = {"OK": "OK", "Cancel": "Cancelar", "Close": "Fechar", "Save": "Salvar",
               "Don't Save": "Não salvar", "Open": "Abrir", "Apply": "Aplicar", "Reset": "Redefinir",
               "&Yes": "&Sim", "&No": "&Não", "Yes": "Sim", "No": "Não", "Retry": "Tentar novamente",
               "Ignore": "Ignorar", "Abort": "Abortar", "Help": "Ajuda", "Discard": "Descartar"}

    def isEmpty(self):
        return False

    def translate(self, context, sourceText, disambiguation=None, n=-1):
        if context in ("QPlatformTheme", "QDialogButtonBox", "QMessageBox"):
            return self.BUTTONS.get(sourceText, "")
        return ""


def activate_language(app, preference):
    global _active, _catalog
    requested = interface_language(preference)
    catalog = english_catalog() if requested == "en" else {}
    previous = getattr(app, "_companion_translator", None)
    if previous is not None:
        app.removeTranslator(previous)
    _active, _catalog = requested, catalog
    QLocale.setDefault(locale())
    app._companion_translator = StandardButtons(app) if requested == "pt-BR" else None
    if app._companion_translator is not None:
        app.installTranslator(app._companion_translator)
    if previous is not None:
        previous.deleteLater()
