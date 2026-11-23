from PySide6.QtCore import QDateTime, QLocale
from ..core.language import locale


def local_clock() -> str:
    now = QDateTime.currentDateTime()
    selected = locale()
    return selected.toString(now.time(), "HH:mm:ss") + "\n" + selected.toString(now.date(), QLocale.FormatType.LongFormat)
