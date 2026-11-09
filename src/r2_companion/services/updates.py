import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

import psutil


def read_release(path: Path):
    if path.stat().st_size > 4096:
        raise ValueError("Metadata de atualização inválida.")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if (not isinstance(data, dict) or type(data.get("schema_version")) is not int or data.get("schema_version") != 1
            or not isinstance(data.get("repository"), str) or not isinstance(data.get("version"), str)
            or not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", data.get("repository", ""))
            or not re.fullmatch(r"\d+\.\d+\.\d+", data.get("version", ""))):
        raise ValueError("Metadata de atualização inválida.")
    return data


class UpdateService:
    def __init__(self, directory, executable=None, script=None, process_factory=subprocess.Popen):
        self.directory = Path(directory).resolve()
        self.executable = executable or (Path(sys.executable) if getattr(sys, "frozen", False) else None)
        bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[3]))
        self.script = script or bundle / "scripts/update-r2-companion.ps1"
        self.process_factory = process_factory
        self.process = None

    def launch(self):
        if self.executable is None or os.name != "nt":
            raise ValueError("Atualizações estão disponíveis no executável instalado. Pelo código, use o processo de build documentado.")
        if self.process is not None and self.process.poll() is None:
            raise ValueError("Uma verificação de atualização já está em andamento.")
        executable = Path(self.executable).resolve(strict=True)
        read_release(executable.parent / "release.json")
        if self.directory == executable.parent or executable.parent in self.directory.parents:
            raise ValueError("Mova o diretório de dados para fora da instalação antes de atualizar.")
        script = Path(self.script).resolve(strict=True)
        directory = self.directory / "updates"
        directory.mkdir(parents=True, exist_ok=True)
        copy = directory / f"updater-{uuid4().hex}.ps1"
        shutil.copyfile(script, copy)
        powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        if not powershell.is_file():
            raise ValueError("Windows PowerShell 5.1 indisponível.")
        self.process = self.process_factory([
            str(powershell), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
            "-File", str(copy), "-InstallDirectory", str(executable.parent),
            "-DataDirectory", str(self.directory), "-ExpectedProcessId", str(os.getpid()),
            "-ProcessStarted", str(int(psutil.Process().create_time()))],
            cwd=str(directory), creationflags=subprocess.CREATE_NO_WINDOW)
        return self.process
