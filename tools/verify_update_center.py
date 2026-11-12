import argparse
import ctypes
import hashlib
from ctypes import wintypes
import json
from pathlib import Path
import shutil
import subprocess
import sys
import time
import tomllib

import psutil
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from r2_companion.services.update_client import ASSET, REPOSITORY, download_release, validate_release
from r2_companion.ui.updates import UpdateCenter
import r2_companion.ui.updates as update_ui


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"



def visible_windows(pid):
    windows = []
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.EnumWindows.argtypes = [callback_type, wintypes.LPARAM]
    def visit(handle, parameter):
        owner = wintypes.DWORD()
        user32.GetWindowThreadProcessId(handle, ctypes.byref(owner))
        if owner.value == pid and user32.IsWindowVisible(handle):
            windows.append(int(handle))
        return True
    callback = callback_type(visit)
    user32.EnumWindows(callback, 0)
    return windows

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".runtime-update-center-install"))
    parser.add_argument("--previous-install", type=Path, default=Path("dist/1.1.1/R2Companion"))
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    workspace = args.data_dir.resolve()
    if workspace.exists():
        parser.error("Use uma pasta nova para preservar evidências anteriores.")
    workspace.mkdir(parents=True)
    installed = workspace / "installed"
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    source = args.previous_install.resolve()
    shutil.copytree(source, installed)
    metadata = json.loads((installed / "release.json").read_text())
    archive = args.archive.resolve() if args.archive else root / "dist" / ASSET
    if archive.name != ASSET:
        transport = workspace / "transport"
        transport.mkdir()
        source_archive = archive
        archive = transport / ASSET
        shutil.copyfile(source_archive, archive)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if source_archive.with_suffix(".zip.sha256").read_text().split()[0] != digest:
            raise ValueError("Checksum da candidata divergente")
        archive.with_suffix(".zip.sha256").write_text(digest + "  " + ASSET + "\n")
    checksum = archive.with_suffix(".zip.sha256")
    raw = {"tag_name": f"v{version}", "draft": False, "prerelease": False, "body": "Teste local do fluxo de atualização.",
           "assets": [{"name": path.name, "size": path.stat().st_size,
                       "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/v{version}/{path.name}"}
                      for path in (archive, checksum)]}
    fixture = workspace / "release-fixture.json"
    fixture.write_text(json.dumps(raw), encoding="utf-8")
    script = installed / "_internal/scripts/update-r2-companion.ps1"
    text = (root / "scripts/update-r2-companion.ps1").read_text(encoding="utf-8")
    first, last = text.index("function Get-R2LatestRelease("), text.index("function Get-R2Asset(")
    text = text[:first] + f"function Get-R2LatestRelease {{ Get-Content -LiteralPath {quote(fixture)} -Raw -Encoding UTF8 | ConvertFrom-Json }}\n\n" + text[last:]
    first, last = text.index("function Get-R2Download("), text.index("function Test-R2Checksum(")
    text = text[:first] + f"function Get-R2Download {{ param($Url, $Destination) Copy-Item -LiteralPath {quote(checksum)} -Destination $Destination }}\n\n" + text[last:]
    script.write_text(text, encoding="utf-8")
    data = workspace / "dados do usuário"
    data.mkdir()
    content = json.dumps({"schema_version": 1, "tasks": [], "notes": [{"id": "one", "title": "Minha nota", "body": "Preservada"}]})
    (data / "tools.json").write_text(content)
    old = subprocess.Popen([str(installed / "R2Companion.exe"), "--data-dir", str(data), "--smoke-test", "--smoke-seconds", "120"],
                           cwd=installed, creationflags=subprocess.CREATE_NO_WINDOW)
    app = QApplication([])
    app.setQuitOnLastWindowClosed(False)
    def local_download(release, directory, progress, stage, cancelled):
        def opener(request, timeout):
            return (checksum if request.full_url.endswith(".sha256") else archive).open("rb")
        return download_release(release, directory, progress, stage, cancelled, opener)
    update_ui.download_release = local_download
    center = UpdateCenter(data, installed, old.pid, int(psutil.Process(old.pid).create_time()),
                          client=lambda repository: validate_release(raw, repository))
    report = {"transport": "local fixture", "original_version": metadata["version"], "target_version": version,
              "download_counts": [], "states": [], "cloned_gui_detected": False, "cloned_gui_visible": False, "successor_capture": False, "feedback_gap": False}
    original_progress = center.download_progress
    def progress(received, total):
        original_progress(received, total)
        report["download_counts"].append([received, total])
    center.download_progress = progress
    center.show()
    started = time.monotonic()
    launched = False
    timer = QTimer()
    timer.setInterval(250)

    def close_installation(directory):
        close = workspace / "close.ps1"
        close.write_text(f". {quote(root / 'scripts/update-r2-companion.ps1')}\nStop-R2Installation {quote(directory)}", encoding="utf-8-sig")
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(close)],
                       capture_output=True, timeout=25, cwd=workspace)

    def finish(passed, message):
        timer.stop()
        report.update(passed=passed, message=message, duration_seconds=time.monotonic() - started,
                      original_gui_closed=not center.isVisible(), old_exited=old.poll() is not None,
                      installed_version=json.loads((installed / "release.json").read_text())["version"],
                      notes_preserved=(data / "tools.json").read_text() == content)
        close_installation(installed)
        for clone in (data / "updates").glob("center-*/R2Companion"):
            close_installation(clone)
        report["residual_pids"] = []
        for process in psutil.process_iter(["exe"]):
            try:
                if process.info["exe"] and Path(process.info["exe"]).resolve().is_relative_to(workspace):
                    report["residual_pids"].append(process.pid)
            except (psutil.Error, OSError):
                pass
        report["startup_confirmations"] = [json.loads(path.read_text()) for path in (data / "updates").glob("startup-*.json")]
        center.close()
        (workspace / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        app.quit()

    def tick():
        nonlocal launched
        clones = list((data / "updates").glob("center-*/R2Companion"))
        successor_visible = False
        for process in psutil.process_iter(["exe"]):
            try:
                if process.info["exe"] and any(Path(process.info["exe"]).parent == clone for clone in clones):
                    report["cloned_gui_detected"] = True
                    report["successor_pid"] = process.pid
                    windows = visible_windows(process.pid)
                    if windows:
                        successor_visible = True
                        if not center.isVisible() and not report["successor_capture"]:
                            report["successor_capture"] = app.primaryScreen().grabWindow(windows[0]).save(str(workspace / "independent-center.png"))
                        report["cloned_gui_visible"] = True
            except (psutil.Error, OSError):
                pass
        if not launched and center.state == "available" and center.worker is None:
            launched = True
            center.action.click()
        if center.state not in report["states"]:
            report["states"].append(center.state)
        if not center.isVisible() and not successor_visible:
            report["feedback_gap"] = True
        if center.prepared is not None:
            status = center.prepared / "status.json"
            try:
                value = json.loads(status.read_text(encoding="utf-8-sig"))
                if value["state"] in {"done", "error"}:
                    if value["state"] == "done":
                        from verify_post_update import navigation_records, open_wheel, select_item, user32, wait_until, windows
                        report["wheel_with_center_visible"] = successor_visible
                        report["native_post_update_tools"] = {}
                        report["native_post_update_activation"] = {}
                        report["center_visible_during_actions"] = {}
                        user32.GetForegroundWindow.restype = wintypes.HWND
                        try:
                            restarted = next(process for process in psutil.process_iter(["exe"])
                                if process.info["exe"] and Path(process.info["exe"]).resolve() == (installed / "R2Companion.exe").resolve())
                            for page in ("clock", "timer", "system", "tasks", "notes", "minigames", "diagnostics"):
                                wheel = open_wheel(restarted.pid)
                                if page not in {"minigames", "diagnostics"}:
                                    select_item(wheel, "main", "tools")
                                    select_item(wheel, "tools", page)
                                else:
                                    select_item(wheel, "main", page)
                                destination = wait_until(lambda: windows(restarted.pid).get("Central de ferramentas · R2 Companion"), 5)
                                observed = wait_until(lambda: next((r for r in reversed(navigation_records(data, restarted.pid))
                                    if r["event"] == "destination_observed" and r.get("action") == page), None), 3)
                                if not observed["destination_visible"] or observed["destination_page"] != page:
                                    raise RuntimeError("Ferramenta pós-atualização divergente")
                                report["native_post_update_tools"][page] = True
                                report["native_post_update_activation"][page] = user32.GetForegroundWindow() == destination
                                report["center_visible_during_actions"][page] = bool(visible_windows(report["successor_pid"]))
                                if not report["native_post_update_activation"][page] or not report["center_visible_during_actions"][page]:
                                    raise RuntimeError("Ativação do destino ou continuidade da central falhou")
                                user32.PostMessageW(destination, 0x0010, 0, 0)
                                wait_until(lambda: "Central de ferramentas · R2 Companion" not in windows(restarted.pid), 3)
                        except Exception as error:
                            finish(False, type(error).__name__ + ": " + str(error))
                            return
                    finish(value["state"] == "done", value["message"])
                    return
            except (FileNotFoundError, ValueError):
                pass
        if center.state == "error" or time.monotonic() - started > 100:
            finish(False, center.detail.text())

    timer.timeout.connect(tick)
    timer.start()
    app.exec()
    return 0 if (report.get("passed") and report.get("notes_preserved") and report.get("cloned_gui_visible")
                 and report.get("old_exited") and report.get("installed_version") == version
                 and report.get("startup_confirmations") and not report.get("residual_pids") and not report.get("feedback_gap")
                 and report.get("wheel_with_center_visible") and len(report.get("native_post_update_tools", {})) == 7) else 1


if __name__ == "__main__":
    raise SystemExit(main())
