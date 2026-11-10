import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time
import tomllib

import psutil


def ps_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".runtime-release-v03"))
    parser.add_argument("--previous-install", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    workspace = args.data_dir.resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    installed = workspace / "installed"
    if installed.exists():
        parser.error("Use um diretorio de teste novo para preservar evidencias anteriores.")
    shutil.copytree(args.previous_install or root / "dist/1.0.1/R2Companion", installed)
    metadata = json.loads((installed / "release.json").read_text())
    (installed / "release.json").write_text(json.dumps(metadata), encoding="utf-8")
    data = workspace / "dados com espaço"
    data.mkdir()
    tools = {"schema_version": 1, "tasks": [{"id": "one", "text": "Preservar tarefa", "done": False}],
             "notes": [{"id": "two", "title": "Minha nota", "body": "Conteúdo preservado após atualização."}]}
    (data / "tools.json").write_text(json.dumps(tools, ensure_ascii=False), encoding="utf-8")
    original_tools = (data / "tools.json").read_bytes()
    archive = root / "dist/R2Companion-Windows-x64.zip"
    updater = root / "dist" / version / "R2Companion/_internal/scripts/update-r2-companion.ps1"
    if updater.read_bytes() != (root / "scripts/update-r2-companion.ps1").read_bytes():
        raise RuntimeError("O script empacotado difere do fonte; gere o build novamente.")
    checksum = archive.with_suffix(".zip.sha256")
    response = {"draft": False, "prerelease": False, "tag_name": f"v{version}", "assets": [
        {"name": path.name, "size": path.stat().st_size,
         "browser_download_url": f"https://github.com/{metadata['repository']}/releases/download/v{version}/{path.name}"}
        for path in (archive, checksum)]}
    fixture = workspace / "release.json"
    fixture.write_text(json.dumps(response), encoding="utf-8")
    executable = installed / "R2Companion.exe"
    process = subprocess.Popen([str(executable), "--data-dir", str(data), "--smoke-test", "--smoke-seconds", "120"],
                               cwd=installed, creationflags=subprocess.CREATE_NO_WINDOW)
    old_process = psutil.Process(process.pid)
    script = workspace / "verify.ps1"
    script.write_text(f"""
$ErrorActionPreference = 'Stop'
. {ps_quote(updater)}
function Get-R2LatestRelease {{ Get-Content -LiteralPath {ps_quote(fixture)} -Raw | ConvertFrom-Json }}
function Get-R2Download {{
    param($Url, $Destination)
    $source = if ($Url.EndsWith('.sha256')) {{ {ps_quote(checksum)} }} else {{ {ps_quote(archive)} }}
    Copy-Item -LiteralPath $source -Destination $Destination
}}
function Show-R2Message {{ param($Message, [switch]$Question) Write-Host $Message }}
$InstallDirectory = {ps_quote(installed)}
$DataDirectory = {ps_quote(data)}
$ExpectedProcessId = {process.pid}
$ProcessStarted = {int(old_process.create_time())}
$Yes = $true
Invoke-R2Update
""", encoding="utf-8-sig")
    report = {"old_pid": process.pid, "transport": "local fixture", "real_close_and_restart": True}
    try:
        limit = time.monotonic() + 20
        while not (data / "companion.log").exists():
            if process.poll() is not None or time.monotonic() >= limit:
                raise RuntimeError("Executável anterior não iniciou.")
            time.sleep(0.1)
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                                cwd=workspace, capture_output=True, timeout=120)
        (workspace / "powershell.log").write_bytes(result.stdout + result.stderr)
        report["updater_exit"] = result.returncode
        report["old_exited"] = process.poll() is not None
        report["installed_version"] = json.loads((installed / "release.json").read_text())["version"]
        report["tools_preserved"] = (data / "tools.json").read_bytes() == original_tools
        report["backup_count"] = len(list(workspace.glob("installed.backup-*")))
        with archive.open("rb") as handle:
            report["package_sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
        report["passed"] = (result.returncode == 0 and report["old_exited"] and report["tools_preserved"]
                            and report["installed_version"] == version and report["backup_count"] == 1)
    finally:
        close = workspace / "close.ps1"
        close.write_text(f". {ps_quote(updater)}\nStop-R2Installation {ps_quote(installed)}", encoding="utf-8-sig")
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(close)],
                       cwd=workspace, capture_output=True, timeout=25)
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
        (workspace / "release-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
