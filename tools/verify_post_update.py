import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib

import psutil

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion.core.config import Settings
from r2_companion.droids.profiles import DroidRegistry
from r2_companion.droids.preferences import select_droid
from r2_companion.ui.navigation import NAVIGATION


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def wait_until(predicate, seconds=30):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.1)
    raise RuntimeError("Tempo excedido aguardando a condição de teste.")


def navigation_records(directory, pid):
    records = []
    for path in directory.glob("navigation.jsonl*"):
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("pid") == pid:
                records.append(record)
    return records


user32 = ctypes.WinDLL("user32", use_last_error=True)
callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]


def windows(pid):
    result = {}
    def visit(handle, parameter):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(handle):
            title = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(handle, title, len(title))
            result[title.value] = int(handle)
        return True
    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    return result


def mouse_click(handle, x, y):
    position = round(x) | round(y) << 16
    if not user32.PostMessageW(handle, 0x0201, 1, position):
        raise ctypes.WinError(ctypes.get_last_error())
    time.sleep(0.05)
    user32.PostMessageW(handle, 0x0202, 0, position)
    time.sleep(0.35)


def open_wheel(pid):
    pet = wait_until(lambda: next((handle for title, handle in windows(pid).items()
                                  if title.endswith(" · R2 Companion") and title.startswith(("R2", "Vesper", "Orbita"))), None))
    rectangle = wintypes.RECT()
    user32.GetClientRect(pet, ctypes.byref(rectangle))
    mouse_click(pet, rectangle.right / 2, rectangle.bottom * 0.7)
    return wait_until(lambda: windows(pid).get("Acesso rápido · R2 Companion"), 5)


def select_item(handle, level, key):
    items = NAVIGATION[level]
    index = next(index for index, item in enumerate(items) if item.id == key)
    angle = math.radians(-90 + index * 360 / len(items))
    mouse_click(handle, 184 + math.cos(angle) * 118, 184 + math.sin(angle) * 118)


def installation_processes(directory):
    result = []
    for process in psutil.process_iter(["exe"]):
        try:
            if process.info["exe"] and Path(process.info["exe"]).resolve().is_relative_to(directory):
                result.append(process)
        except (psutil.Error, OSError):
            pass
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--previous-install", type=Path, default=Path("dist/1.1.1/R2Companion"))
    parser.add_argument("--legacy-updater", action="store_true")
    parser.add_argument("--fail-startup", action="store_true")
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--require-navigation-trace", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text())["project"]["version"]
    workspace = args.data_dir.resolve()
    if workspace.exists() or not workspace.is_relative_to(root):
        parser.error("Use uma pasta nova dentro do repositório.")
    workspace.mkdir(parents=True)
    installed = workspace / "installed"
    shutil.copytree(args.previous_install.resolve(), installed)
    original_version = json.loads((installed / "release.json").read_text())["version"]
    if original_version == version:
        parser.error("É necessário um executável anterior real para este ensaio.")
    data = workspace / "dados do usuário"
    data.mkdir()
    settings = Settings(suppress_fullscreen=False)
    registry = DroidRegistry(root / "src/r2_companion/assets")
    for index, profile in enumerate(registry.profiles.values()):
        settings = select_droid(settings, profile)
        settings.audio.volume = 0.13 + index * 0.1
        settings.behavior.movement = False
        settings.behavior.cursor_attention = False
        settings.capture_droid()
    expected_preferences = settings.to_dict()["droid_preferences"]
    (data / "config.json").write_text(json.dumps(settings.to_dict()), encoding="utf-8")
    tools = {"schema_version": 1, "tasks": [{"id": "one", "text": "Preservar tarefa", "done": False}],
             "notes": [{"id": "two", "title": "Minha nota", "body": "Conteúdo preservado após atualização."}]}
    original_tools = json.dumps(tools, ensure_ascii=False).encode("utf-8")
    (data / "tools.json").write_bytes(original_tools)
    archive = args.archive.resolve() if args.archive else root / "dist/R2Companion-Windows-x64.zip"
    if archive.name != "R2Companion-Windows-x64.zip":
        transport = workspace / "transport"
        transport.mkdir()
        source_archive = archive
        archive = transport / "R2Companion-Windows-x64.zip"
        shutil.copyfile(source_archive, archive)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if source_archive.with_suffix(".zip.sha256").read_text().split()[0] != digest:
            raise ValueError("Checksum da candidata divergente")
        archive.with_suffix(".zip.sha256").write_text(digest + "  " + archive.name + "\n")
    checksum = archive.with_suffix(".zip.sha256")
    metadata = json.loads((installed / "release.json").read_text())
    response = {"draft": False, "prerelease": False, "tag_name": f"v{version}", "assets": [
        {"name": path.name, "size": path.stat().st_size,
         "browser_download_url": f"https://github.com/{metadata['repository']}/releases/download/v{version}/{path.name}"}
        for path in (archive, checksum)]}
    fixture = workspace / "release-fixture.json"
    fixture.write_text(json.dumps(response))
    updater = installed / "_internal/scripts/update-r2-companion.ps1" if args.legacy_updater else root / "scripts/update-r2-companion.ps1"
    script_copy = workspace / "updater.ps1"
    shutil.copyfile(updater, script_copy)
    status = data / "updates/validation/status.json"
    status.parent.mkdir(parents=True)
    environment = os.environ.copy()
    executable = installed / "R2Companion.exe"
    old = subprocess.Popen([str(executable), "--data-dir", str(data), "--smoke-test", "--smoke-seconds", "180"],
                           cwd=workspace, creationflags=subprocess.CREATE_NO_WINDOW)
    report = {"original_version": original_version, "target_version": version, "legacy_updater": args.legacy_updater,
              "injected_startup_failure": args.fail_startup, "transport": "local fixtures", "passed": False}
    try:
        wheel = open_wheel(old.pid)
        select_item(wheel, "main", "tools")
        select_item(wheel, "tools", "tools_center")
        wait_until(lambda: windows(old.pid).get("Central de ferramentas · R2 Companion"), 5)
        wheel = open_wheel(old.pid)
        select_item(wheel, "main", "garage")
        wait_until(lambda: any("Droid Garage" in title for title in windows(old.pid)), 5)
        report["old_secondary_windows"] = list(windows(old.pid))
        report["old_pid"] = old.pid
        report["old_start"] = psutil.Process(old.pid).create_time()
        environment.update({"_PYI_ARCHIVE_FILE": str(executable), "_PYI_APPLICATION_HOME_DIR": str(installed / "_internal"),
                            "_PYI_PARENT_PROCESS_LEVEL": "1", "QT_PLUGIN_PATH": str(installed / "_internal/PySide6/plugins")})
        failure = ""
        if args.fail_startup:
            failure = f"""
    if ((Read-R2Release $WorkingDirectory).version -eq '{version}') {{
        $changed = Read-R2Release $WorkingDirectory
        $changed.version = '9.9.9'
        $changed | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $WorkingDirectory 'release.json') -Encoding UTF8
    }}
"""
        wrapper = workspace / "verify.ps1"
        wrapper.write_text(f"""
$ErrorActionPreference = 'Stop'
. {quote(script_copy)}
function Get-R2LatestRelease {{ Get-Content -LiteralPath {quote(fixture)} -Raw | ConvertFrom-Json }}
function Get-R2Download {{
    param($Url, $Destination)
    $source = if ($Url.EndsWith('.sha256')) {{ {quote(checksum)} }} else {{ {quote(archive)} }}
    Copy-Item -LiteralPath $source -Destination $Destination
}}
function Show-R2Message {{ param($Message, [switch]$Question) Write-Host $Message }}
function Start-Process {{
    param($FilePath, $WorkingDirectory, $WindowStyle, $PassThru, $ArgumentList)
    {failure}
    $arguments = @($ArgumentList) + @('--smoke-test', '--smoke-navigation', '--smoke-droids', '--smoke-seconds', '20')
    Microsoft.PowerShell.Management\\Start-Process -FilePath $FilePath -WorkingDirectory $WorkingDirectory -WindowStyle Hidden -PassThru -ArgumentList $arguments
}}
$InstallDirectory = {quote(installed)}
$DataDirectory = {quote(data)}
$ExpectedProcessId = {old.pid}
$ProcessStarted = {int(report['old_start'])}
$StatusPath = {quote(status)}
$Yes = $true
try {{ Invoke-R2Update }} catch {{ Write-R2Status 'error' $_.Exception.Message; throw }}
""", encoding="utf-8-sig")
        result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                                cwd=workspace, env=environment, capture_output=True, timeout=120,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        (workspace / "installer.log").write_bytes(result.stdout + result.stderr)
        report["updater_exit"] = result.returncode
        report["status"] = json.loads(status.read_text(encoding="utf-8-sig"))
        report["old_exited"] = old.poll() is not None
        restarted = wait_until(lambda: next((process for process in installation_processes(installed)
                                             if process.pid != old.pid), None), 10)
        if args.require_navigation_trace or (data / "navigation.jsonl").exists():
            completed = wait_until(lambda: next((r for r in navigation_records(data, restarted.pid)
                if r["event"] == "navigation_smoke_completed"), None), 10)
            if not completed["passed"]:
                raise RuntimeError("Navegação inicial pós-atualização falhou")
        else:
            time.sleep(3)
        report["native_post_update_tools"] = {}
        for page in ("clock", "timer", "system", "tasks", "notes", "minigames", "diagnostics"):
            wheel = open_wheel(restarted.pid)
            if page not in {"minigames", "diagnostics"}:
                select_item(wheel, "main", "tools")
                select_item(wheel, "tools", page)
            else:
                select_item(wheel, "main", page)
            tools_window = wait_until(lambda: windows(restarted.pid).get("Central de ferramentas · R2 Companion"), 5)
            report["native_post_update_tools"][page] = bool(tools_window)
            if (data / "navigation.jsonl").exists():
                observed = wait_until(lambda: next((r for r in reversed(navigation_records(data, restarted.pid))
                    if r["event"] == "destination_observed" and r.get("action") == page), None), 3)
                if not observed["destination_visible"] or observed["destination_page"] != page:
                    raise RuntimeError("A roda abriu uma ferramenta diferente da seleção")
            user32.PostMessageW(tools_window, 0x0010, 0, 0)
            time.sleep(0.15)
        smoke_file = data / "smoke.json"
        wait_until(smoke_file.is_file, 40)
        smoke = json.loads(smoke_file.read_text())
        report["first_launch"] = smoke
        report["installed_version"] = json.loads((installed / "release.json").read_text(encoding="utf-8-sig"))["version"]
        report["tools_preserved"] = (data / "tools.json").read_bytes() == original_tools
        saved = json.loads((data / "config.json").read_text())
        report["all_droid_preferences_preserved"] = saved["droid_preferences"] == expected_preferences
        report["startup_confirmations"] = [json.loads(path.read_text()) for path in (data / "updates").glob("startup-*.json")]
        report["backup_versions"] = [json.loads((path / "release.json").read_text(encoding="utf-8-sig"))["version"]
                                     for path in workspace.glob("installed.backup-*")]
        report["failed_versions"] = [json.loads((path / "release.json").read_text(encoding="utf-8-sig"))["version"]
                                     for path in workspace.glob("installed.failed-*")]
        wait_until(lambda: not installation_processes(installed), 10)
        report["no_residual_processes"] = True
        (data / "smoke.json").rename(workspace / "after-update-smoke.json")
        direct = subprocess.run([str(executable), "--data-dir", str(data), "--smoke-test", "--smoke-navigation", "--smoke-droids",
                                 "--smoke-seconds", "8"], cwd=workspace, capture_output=True, timeout=40,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        direct_smoke = json.loads((data / "smoke.json").read_text())
        report["direct_launch"] = direct_smoke
        report["same_navigation_on_first_and_direct_launch"] = smoke["navigation"] == direct_smoke["navigation"]
        expected_version = original_version if args.fail_startup else version
        report["passed"] = (report["old_exited"] and report["tools_preserved"] and report["all_droid_preferences_preserved"]
                            and len(report["native_post_update_tools"]) == 7 and all(report["native_post_update_tools"].values())
                            and report["installed_version"] == expected_version and smoke["version"] == expected_version
                            and bool(smoke["navigation"]) and all(smoke["navigation"].values())
                            and len(smoke["droids"]) == 3 and all(item["accepted"] for item in smoke["droids"])
                            and smoke["active_timers_after_shutdown"] == 0 and not smoke["movement_timer_after_shutdown"]
                            and direct.returncode == 0 and report["same_navigation_on_first_and_direct_launch"]
                            and (bool(report["failed_versions"]) if args.fail_startup else report["backup_versions"] == [original_version])
                            and (result.returncode != 0 if args.fail_startup else result.returncode == 0)
                            and (args.legacy_updater or args.fail_startup or bool(report["startup_confirmations"])))
        with archive.open("rb") as handle:
            report["sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
    except Exception as error:
        report["error"] = str(error)
    finally:
        for process in installation_processes(installed):
            for handle in windows(process.pid).values():
                user32.PostMessageW(handle, 0x0010, 0, 0)
            try:
                process.wait(20)
            except psutil.TimeoutExpired:
                process.terminate()
                process.wait(5)
        report["residual_processes_after_cleanup"] = [p.pid for p in installation_processes(installed)]
        (workspace / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"first_launch", "direct_launch", "old_secondary_windows"}}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
