from pathlib import Path, PureWindowsPath
import ctypes
import os
import re

from PySide6.QtCore import QProcess

BLOCKED = re.compile(r"^(cmd|powershell|pwsh|python[\d.w-]*|py|wscript|cscript|mshta|rundll32|regsvr32|bash|wsl|sh|node|perl|ruby|java|javaw|msiexec|schtasks|reg|certutil|bitsadmin|wmic)\.exe$", re.IGNORECASE)


def drive_type(anchor: str) -> int:
    if os.name != "nt":
        return 3
    function = ctypes.windll.kernel32.GetDriveTypeW
    function.argtypes = [ctypes.c_wchar_p]
    function.restype = ctypes.c_uint
    return function(anchor)


def local_path(raw: str) -> Path:
    if not raw or any(ord(c) < 32 for c in raw) or any(c in raw for c in ('"', '%', '|', '<', '>')):
        raise ValueError("Caminho local inválido.")
    win = PureWindowsPath(raw)
    if not win.is_absolute() or len(win.drive) != 2 or win.drive[1] != ':' or ':' in raw[2:]:
        raise ValueError("Escolha um caminho absoluto em unidade local; rede e comandos não são aceitos.")
    if drive_type(win.anchor) in {0, 1, 4}:
        raise ValueError("Unidade indisponível ou de rede; escolha um destino local.")
    path = Path(raw).resolve(strict=True)
    resolved = PureWindowsPath(str(path))
    if len(resolved.drive) != 2 or ':' in str(path)[2:]:
        raise ValueError("O destino resolvido não é um arquivo local permitido.")
    if drive_type(resolved.anchor) in {0, 1, 4}:
        raise ValueError("O destino resolvido usa uma unidade de rede ou indisponível.")
    return path


def validate_executable(raw: str) -> Path:
    path = local_path(raw)
    if not path.is_file() or path.suffix.lower() != ".exe" or BLOCKED.fullmatch(path.name):
        raise ValueError("Selecione um aplicativo .exe; scripts e interpretadores não são permitidos.")
    return path


def launch(raw: str, starter=None) -> bool:
    path = validate_executable(raw)
    starter = starter or QProcess.startDetached
    result = starter(str(path), [], str(path.parent))
    return bool(result[0] if isinstance(result, tuple) else result)
