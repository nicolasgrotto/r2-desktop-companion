from PySide6.QtCore import QDateTime, QLocale


def local_clock() -> str:
    now = QDateTime.currentDateTime()
    locale = QLocale()
    return locale.toString(now.time(), "HH:mm:ss") + "\n" + locale.toString(now.date(), QLocale.FormatType.LongFormat)
