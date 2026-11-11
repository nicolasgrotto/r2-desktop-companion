import argparse
import ctypes
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
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    workspace = args.data_dir.resolve()
    if workspace.exists():
        parser.error("Use uma pasta nova para preservar evidências anteriores.")
    workspace.mkdir(parents=True)
    installed = workspace / "installed"
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    source = root / "dist" / version / "R2Companion"
    shutil.copytree(source, installed)
    metadata = json.loads((installed / "release.json").read_text())
    metadata["version"] = "1.0.1"
    (installed / "release.json").write_text(json.dumps(metadata), encoding="utf-8")
    archive = root / "dist" / ASSET
    checksum = archive.with_suffix(".zip.sha256")
    raw = {"tag_name": f"v{version}", "draft": False, "prerelease": False, "body": "Teste local do fluxo de atualização.",
           "assets": [{"name": path.name, "size": path.stat().st_size,
                       "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/v{version}/{path.name}"}
                      for path in (archive, checksum)]}
    fixture = workspace / "release-fixture.json"
    fixture.write_text(json.dumps(raw), encoding="utf-8")
    script = installed / "_internal/scripts/update-r2-companion.ps1"
    text = script.read_text(encoding="utf-8")
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
    report = {"transport": "local fixture", "installed_metadata_fixture": "1.0.1", "executable_code": version,
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
                    finish(value["state"] == "done", value["message"])
                    return
            except (FileNotFoundError, ValueError):
                pass
        if center.state == "error" or time.monotonic() - started > 100:
            finish(False, center.detail.text())

    timer.timeout.connect(tick)
    timer.start()
    app.exec()
    return 0 if report.get("passed") and report.get("notes_preserved") and report.get("cloned_gui_visible") and not report.get("feedback_gap") else 1


if __name__ == "__main__":
    raise SystemExit(main())
