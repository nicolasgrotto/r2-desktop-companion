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
from uuid import uuid4

import psutil
from PySide6.QtGui import QImage

from verify_media_probe_package import clean_environment

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion.core.config import Settings
from r2_companion.droids.profiles import DroidRegistry
from r2_companion.droids.preferences import select_droid
from r2_companion.features.minigames import load_thumbnail, new_entry
from r2_companion.services.companion_state import default_document
from r2_companion.ui.navigation import NAVIGATION


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def wait_until(predicate, seconds: float = 30.0):
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
                                  if title.endswith(" · R2 Companion") and title.startswith(("R2", "Vesper", "Orbita", "Lumo", "Vigia", "Pico", "Tranco"))), None))
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


def verified_startup(path, executable, data, version, pid):
    ready = json.loads(path.read_text(encoding="utf-8"))
    if ready != {"pid": pid, "version": version, "initialized": True, "executable": str(executable),
                 "bundle": str(executable.parent / "_internal"), "data_directory": str(data)}:
        raise RuntimeError("A confirmação não corresponde ao executável, bundle e dados esperados.")
    return ready


def validate_roundtrip(workspace, installed, data, environment, original_version, version, report):
    executable = installed / "R2Companion.exe"
    backup, = workspace.glob("installed.backup-*")
    candidate = workspace / "candidate-in-waiting"
    report["older_version_roundtrip"] = {}
    roundtrip = report["older_version_roundtrip"]

    def run(name, expected_version, exercise_droids=False):
        smoke_path = data / "smoke.json"
        if smoke_path.exists():
            smoke_path.rename(workspace / f"{name}-previous-smoke.json")
        ready = data / "updates" / f"startup-{uuid4().hex}.json"
        seconds = 50 if exercise_droids else 8
        command = [str(executable), "--data-dir", str(data), "--startup-ready-file", str(ready),
                   "--smoke-test", "--smoke-seconds", str(seconds)]
        if exercise_droids:
            command.append("--smoke-droids")
        with (workspace / f"{name}.log").open("wb") as log:
            process = subprocess.Popen(command, cwd=workspace, env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
                                       stdout=log, stderr=subprocess.STDOUT)
            try:
                if process.wait(timeout=seconds + 30):
                    raise RuntimeError(f"{name}: processo encerrou com código {process.returncode}")
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
        roundtrip[name + "_startup"] = verified_startup(ready, executable, data, expected_version, process.pid)
        smoke = json.loads(smoke_path.read_text(encoding="utf-8"))
        if (not smoke["visible"] or smoke["active_timers_after_shutdown"]
                or smoke["movement_timer_after_shutdown"] or smoke.get("media_worker_after_shutdown")):
            raise RuntimeError(f"{name}: visibilidade ou encerramento inválido")
        return smoke

    settings_file = data / "config.json"
    previous_selection = json.loads(settings_file.read_text(encoding="utf-8"))["active_droid"]
    installed.rename(candidate)
    try:
        backup.rename(installed)
        try:
            downgraded = run("downgrade", original_version, exercise_droids=True)
            saved = json.loads(settings_file.read_text(encoding="utf-8"))
            roundtrip["legacy_saved_active_droid"] = saved["active_droid"]
            roundtrip["legacy_preferences_write"] = (saved["active_droid"] != previous_selection
                                                     and downgraded["active_droid"] == saved["active_droid"])
        finally:
            installed.rename(backup)
    finally:
        candidate.rename(installed)
    reloaded = run("return", version)
    roundtrip["selection_recovered"] = reloaded["active_droid"] == roundtrip["legacy_saved_active_droid"]
    roundtrip["personal_catalog_loaded"] = (reloaded["personal_minigames"] == 1
                                            and reloaded["personal_minigame_thumbnails"] == 1)
    themed = run("themes", version, exercise_droids=True)
    roundtrip["interface_themes"] = {item["id"]: item["interface_theme"] for item in themed["droids"] if item["accepted"]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--previous-install", type=Path, default=Path("dist/1.1.1/R2Companion"))
    parser.add_argument("--previous-version", choices=("1.1.1", "1.2.2"), default="1.1.1")
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
    source = args.previous_install.resolve()
    original_version = json.loads((source / "release.json").read_text(encoding="utf-8-sig"))["version"]
    if original_version != args.previous_version or original_version == version:
        parser.error("A versão do executável anterior precisa corresponder a --previous-version.")
    shipping_baseline = original_version == "1.2.2"
    workspace.mkdir(parents=True)
    installed = workspace / "installed"
    shutil.copytree(source, installed)
    data = workspace / "dados do usuário"
    data.mkdir()
    settings = Settings(suppress_fullscreen=False, fullscreen_mode="quiet")
    registry = DroidRegistry(root / "src/r2_companion/assets")
    for index, profile in enumerate(registry.profiles.values()):
        settings = select_droid(settings, profile)
        settings.audio.volume = 0.13 + index * 0.1
        settings.behavior.movement = False
        settings.behavior.cursor_attention = False
        # Native navigation checks run independently of OS idle/fullscreen state.
        # Sleep/wake policy has its own tests; a click during WAKE is consumed.
        settings.behavior.frequency = "off"
        settings.capture_droid()
    if shipping_baseline:
        settings = select_droid(settings, registry.profiles["r2_default"])
        overrides = {"r2_default": "vigia", "pico": "tranco"}
        document = default_document()
        document["appearance"]["theme_overrides"] = overrides
        thumbnail_path = workspace / "minigame-image.png"
        image = QImage(96, 72, QImage.Format.Format_ARGB32)
        image.fill(0xff216eea)
        if not image.save(str(thumbnail_path)):
            raise RuntimeError("Não foi possível gravar a imagem do ensaio.")
        entry = new_entry("Órbita de teste", "https://example.invalid/game?level=2", "Descrição preservada.",
                          "play", load_thumbnail(thumbnail_path))
        document["minigames"]["entries"]["a" * 32] = entry
        original_document = json.dumps(document, ensure_ascii=False).encode("utf-8")
        (data / "companion_state.json").write_bytes(original_document)
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
    temporary = workspace / "temporary"
    temporary.mkdir()
    environment = clean_environment(temporary) if shipping_baseline else os.environ.copy()
    executable = installed / "R2Companion.exe"
    old_ready = data / "updates" / f"startup-{uuid4().hex}.json"
    startup_args = ["--startup-ready-file", str(old_ready)] if shipping_baseline else []
    old = subprocess.Popen([str(executable), "--data-dir", str(data), "--smoke-test", "--smoke-seconds", "180",
                            *startup_args], cwd=workspace, env=environment, creationflags=subprocess.CREATE_NO_WINDOW)
    report = {"original_version": original_version, "target_version": version, "legacy_updater": args.legacy_updater,
              "injected_startup_failure": args.fail_startup, "transport": "local fixtures", "passed": False}
    try:
        if shipping_baseline:
            wait_until(old_ready.is_file)
            report["old_startup"] = verified_startup(old_ready, executable, data, original_version, old.pid)
            old_ready.rename(workspace / "old-startup.json")
        else:
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
        droid_smoke = "" if shipping_baseline else "'--smoke-droids', "
        restart_seconds = 45 if shipping_baseline else 20
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
    $arguments = @($ArgumentList) + @('--smoke-test', '--smoke-navigation', {droid_smoke}'--smoke-seconds', '{restart_seconds}')
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
        powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        result = subprocess.run([str(powershell), "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(wrapper)],
                                cwd=workspace, env=environment, capture_output=True, timeout=120,
                                creationflags=subprocess.CREATE_NO_WINDOW)
        (workspace / "installer.log").write_bytes(result.stdout + result.stderr)
        report["updater_exit"] = result.returncode
        report["status"] = json.loads(status.read_text(encoding="utf-8-sig"))
        report["old_exited"] = old.poll() is not None
        restarted = wait_until(lambda: next((process for process in installation_processes(installed)
                                             if process.pid != old.pid), None), 10)
        if not shipping_baseline and (args.require_navigation_trace or (data / "navigation.jsonl").exists()):
            completed = wait_until(lambda: next((r for r in navigation_records(data, restarted.pid)
                if r["event"] == "navigation_smoke_completed"), None), 10)
            if not completed["passed"]:
                raise RuntimeError("Navegação inicial pós-atualização falhou")
            if completed.get("controller_state") == "WAKE":
                # The smoke scene explicitly sleeps and wakes the character.
                # Respect the wake animation before issuing a native menu click.
                assets = installed / "_internal/r2_companion/assets"
                active = json.loads((data / "config.json").read_text(encoding="utf-8"))["active_droid"]
                profiles = (json.loads(path.read_text(encoding="utf-8")) for path in
                            (assets / "droids").glob("*/profile.json"))
                profile = next(profile for profile in profiles if profile["id"] == active)
                manifest = json.loads((assets / profile["manifest"]).read_text(encoding="utf-8"))
                duration = sum(frame["duration_ms"] for frame in manifest["clips"]["WAKE"]["frames"])
                ready_at = completed["monotonic_ns"] / 1e9 + duration / 1000 + 0.15
                wait_until(lambda: time.monotonic() >= ready_at, duration / 1000 + 3)
                report["wake_animation_wait_ms"] = duration
        elif not shipping_baseline:
            time.sleep(3)
        report["native_post_update_tools"] = {}
        native_pages = () if shipping_baseline else ("clock", "timer", "system", "tasks", "notes", "minigames", "diagnostics")
        for page in native_pages:
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
        wait_until(smoke_file.is_file, restart_seconds + 30)
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
        report["staging_cleaned"] = not any(workspace.glob(".r2-update-*"))
        expected_version = original_version if args.fail_startup else version
        common_checks = (
            report["old_exited"] and report["tools_preserved"] and report["all_droid_preferences_preserved"]
            and report["installed_version"] == expected_version and smoke["version"] == expected_version
            and smoke["visible"] and bool(smoke["navigation"]) and all(smoke["navigation"].values())
            and smoke["active_timers_after_shutdown"] == 0 and not smoke["movement_timer_after_shutdown"]
            and not smoke.get("media_worker_after_shutdown") and report["staging_cleaned"]
            and (result.returncode != 0 if args.fail_startup else result.returncode == 0))
        with archive.open("rb") as handle:
            report["sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
        if shipping_baseline:
            ready_path, = (data / "updates").glob("startup-*.json")
            report["restart_startup"] = verified_startup(ready_path, executable, data, expected_version, restarted.pid)
            report["selection_preserved"] = saved["active_droid"] == smoke["active_droid"] == settings.active_droid
            report["companion_document_preserved"] = (data / "companion_state.json").read_bytes() == original_document
            report["passed"] = (common_checks and report["selection_preserved"] and report["companion_document_preserved"]
                                and report["status"]["state"] == ("error" if args.fail_startup else "done"))
            if args.fail_startup:
                report["passed"] = (report["passed"] and report["failed_versions"] == ["9.9.9"]
                                    and not report["backup_versions"])
            elif report["passed"] and report["backup_versions"] == [original_version]:
                report["passed"] = False
                validate_roundtrip(workspace, installed, data, environment, original_version, version, report)
                roundtrip = report["older_version_roundtrip"]
                roundtrip["tools_unchanged"] = (data / "tools.json").read_bytes() == original_tools
                roundtrip["preferences_unchanged"] = (
                    json.loads((data / "config.json").read_text(encoding="utf-8"))["droid_preferences"] == expected_preferences)
                roundtrip["companion_document_unchanged"] = (data / "companion_state.json").read_bytes() == original_document
                roundtrip["overrides_active"] = all(roundtrip["interface_themes"].get(droid) == registry.profiles[provider].theme.name
                                                    for droid, provider in overrides.items())
                report["passed"] = (
                    all(roundtrip[key] for key in ("legacy_preferences_write", "selection_recovered", "personal_catalog_loaded",
                                                   "tools_unchanged", "preferences_unchanged", "companion_document_unchanged", "overrides_active"))
                    and smoke["personal_minigames"] == smoke["personal_minigame_thumbnails"] == 1
                    and not report["failed_versions"])
            else:
                report["passed"] = False
        else:
            (data / "smoke.json").rename(workspace / "after-update-smoke.json")
            direct = subprocess.run([str(executable), "--data-dir", str(data), "--smoke-test", "--smoke-navigation", "--smoke-droids",
                                     "--smoke-seconds", "8"], cwd=workspace, capture_output=True, timeout=40,
                                    creationflags=subprocess.CREATE_NO_WINDOW)
            direct_smoke = json.loads((data / "smoke.json").read_text())
            report["direct_launch"] = direct_smoke
            report["same_navigation_on_first_and_direct_launch"] = smoke["navigation"] == direct_smoke["navigation"]
            installed_droids = {json.loads(path.read_text(encoding="utf-8"))["id"] for path in
                                (installed / "_internal/r2_companion/assets/droids").glob("*/profile.json")}
            report["passed"] = (common_checks
                                and len(report["native_post_update_tools"]) == 7 and all(report["native_post_update_tools"].values())
                                and {item["id"] for item in smoke["droids"]} == installed_droids and all(item["accepted"] for item in smoke["droids"])
                                and direct.returncode == 0 and report["same_navigation_on_first_and_direct_launch"]
                                and (bool(report["failed_versions"]) if args.fail_startup else report["backup_versions"] == [original_version])
                                and (args.legacy_updater or args.fail_startup or bool(report["startup_confirmations"])))
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
        report["passed"] = report["passed"] and not report["residual_processes_after_cleanup"]
        (workspace / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({key: value for key, value in report.items() if key not in {"first_launch", "direct_launch", "old_secondary_windows"}}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
