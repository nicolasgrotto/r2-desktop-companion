from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices

from .launcher import local_path

ALLOWED = {".txt", ".pdf", ".png", ".jpg", ".jpeg", ".wav", ".mp3"}


def validate_location(raw: str, kind: str) -> Path:
    path = local_path(raw)
    if kind == "folder" and path.is_dir():
        return path
    if kind == "file" and path.is_file() and path.suffix.lower() in ALLOWED:
        return path
    raise ValueError("Destino indisponível ou tipo de arquivo não permitido.")


def open_location(raw: str, kind: str, opener=None) -> bool:
    path = validate_location(raw, kind)
    return (opener or QDesktopServices.openUrl)(QUrl.fromLocalFile(str(path)))
