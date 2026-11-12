import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from uuid import uuid4

import psutil

from .. import __version__


def independent_environment():
    environment = os.environ.copy()
    environment["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    if getattr(sys, "frozen", False):
        bundle = Path(sys._MEIPASS).resolve()
        for key in ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH"):
            environment.pop(key, None)
        environment["PATH"] = os.pathsep.join(
            entry for entry in environment.get("PATH", "").split(os.pathsep)
            if entry and not Path(os.path.abspath(entry.strip('"'))).is_relative_to(bundle))
    return environment


def runtime_identity():
    executable = Path(sys.executable).resolve()
    bundle = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1])).resolve()
    if getattr(sys, "frozen", False):
        metadata = read_release(executable.parent / "release.json")
        if metadata["version"] != __version__ or bundle != executable.parent / "_internal":
            raise ValueError("A versão carregada não corresponde à instalação. Consulte o log de atualização.")
    return {"pid": os.getpid(), "version": __version__, "executable": str(executable), "bundle": str(bundle)}


def confirm_startup(path, directory):
    from .storage import ConfigStore
    path, directory = Path(path).absolute(), Path(directory).resolve()
    if (path.parent.resolve() != directory / "updates" or path.parent != path.parent.resolve()
            or not re.fullmatch(r"startup-[a-f0-9]{32}\.json", path.name) or path.exists() or path.is_symlink()):
        raise ValueError("Caminho de confirmação de inicialização inválido.")
    ConfigStore.atomic_write(path, json.dumps(runtime_identity() | {
        "data_directory": str(directory), "initialized": True}).encode("utf-8"))


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

    def launch_center(self):
        if self.process is not None and self.process.poll() is None:
            raise ValueError("A central de atualizações já está aberta.")
        if self.executable is not None:
            executable = Path(self.executable).resolve(strict=True)
            read_release(executable.parent / "release.json")
            command = [str(executable), "--update-center", "--install-dir", str(executable.parent)]
        else:
            root = Path(__file__).resolve().parents[3]
            command = [sys.executable, str(root / "run_companion.py"), "--update-center"]
        command += ["--data-dir", str(self.directory), "--owner-pid", str(os.getpid()),
                    "--owner-start", str(int(psutil.Process().create_time()))]
        self.process = self.process_factory(command, cwd=str(self.directory), env=independent_environment(),
                                            creationflags=subprocess.CREATE_NO_WINDOW)
        return self.process

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
            cwd=str(directory), env=independent_environment(), creationflags=subprocess.CREATE_NO_WINDOW)
        return self.process
