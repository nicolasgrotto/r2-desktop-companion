import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / "src"))
from r2_companion.core.config import Settings
from r2_companion.services.updates import independent_environment
from verify_post_update import navigation_records, open_wheel, select_item, user32, wait_until, windows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--install", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--startup-hidden", action="store_true")
    args = parser.parse_args()
    output, install = args.data_dir.resolve(), args.install.resolve()
    if output.exists() or not output.is_relative_to(root) or not install.is_relative_to(root):
        parser.error("Use instalação descartável e pasta nova no repositório")
    output.mkdir(parents=True)
    data = output / "data"
    data.mkdir()
    settings = Settings(suppress_fullscreen=False)
    settings.behavior.frequency = "off"
    settings.behavior.movement = False
    (data / "config.json").write_text(json.dumps(settings.to_dict()))
    environment = independent_environment()
    environment["R2_NAV_TRACE"] = "1"
    startup = subprocess.STARTUPINFO()
    if args.startup_hidden:
        startup.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startup.wShowWindow = subprocess.SW_HIDE
    process = subprocess.Popen([str(install / "R2Companion.exe"), "--data-dir", str(data)],
        cwd=output, env=environment, creationflags=subprocess.CREATE_NO_WINDOW, startupinfo=startup)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    report = {"pid": process.pid, "foreground_available": bool(user32.GetForegroundWindow()),
              "startup_hidden": args.startup_hidden,
              "classification": "automated native Windows messages; not manual physical input", "attempts": []}
    try:
        wheel = open_wheel(process.pid)
        pet_handle = next(handle for title, handle in windows(process.pid).items()
                          if title.endswith(" · R2 Companion") and title.startswith(("R2", "Vesper", "Orbita", "Lumo", "Vigia", "Pico", "Tranco")))
        rectangle = wintypes.RECT()
        user32.GetClientRect(pet_handle, ctypes.byref(rectangle))
        from verify_post_update import mouse_click
        mouse_click(pet_handle, rectangle.right / 2, rectangle.bottom * 0.7)
        report["toggle_closes"] = "Acesso rápido · R2 Companion" not in windows(process.pid)
        if not report["toggle_closes"]:
            user32.PostMessageW(wheel, 0x0010, 0, 0)
            wait_until(lambda: "Acesso rápido · R2 Companion" not in windows(process.pid), 3)
        for round_number in range(args.rounds):
            user32.ShowWindow(pet_handle, 6)
            user32.ShowWindow(pet_handle, 9)
            for page in ("clock", "timer", "system", "tasks", "notes", "minigames", "diagnostics"):
                attempt = {"round": round_number, "page": page, "started_ns": time.monotonic_ns(), "passed": False,
                           "stage": "opening_wheel"}
                try:
                    wheel = open_wheel(process.pid)
                    attempt["stage"] = "wheel_open"
                    if page not in {"minigames", "diagnostics"}:
                        select_item(wheel, "main", "tools")
                        select_item(wheel, "tools", page)
                    else:
                        select_item(wheel, "main", page)
                    attempt["stage"] = "awaiting_destination"
                    destination = wait_until(lambda: windows(process.pid).get("Central de ferramentas · R2 Companion"), 5)
                    attempt["passed"] = bool(destination)
                    attempt["destination_hwnd"] = destination
                    attempt["destination_foreground"] = user32.GetForegroundWindow() == destination
                    attempt["activation_result"] = ("confirmed" if attempt["destination_foreground"] else
                        "foreground_unavailable" if not user32.GetForegroundWindow() else "not_activated")
                    if report["foreground_available"] and not attempt["destination_foreground"]:
                        attempt["passed"] = False
                        attempt["activation_failure"] = True
                    if (data / "navigation.jsonl").exists():
                        observed = wait_until(lambda: next((r for r in reversed(navigation_records(data, process.pid))
                            if r["event"] == "destination_observed" and r.get("action") == page
                            and r["monotonic_ns"] >= attempt["started_ns"]), None), 3)
                        assert observed["destination_visible"] and observed["destination_page"] == page
                        attempt["page_verified"] = True
                    else:
                        attempt["page_verified"] = False
                    user32.PostMessageW(destination, 0x0010, 0, 0)
                    wait_until(lambda: "Central de ferramentas · R2 Companion" not in windows(process.pid), 3)
                    attempt["stage"] = "completed"
                except Exception as error:
                    attempt["passed"] = False
                    attempt["error"] = type(error).__name__ + ": " + str(error)
                    attempt["visible_windows_at_failure"] = list(windows(process.pid))
                report["attempts"].append(attempt)
                (output / "progress.json").write_text(json.dumps(report, indent=2))
        report["passed"] = report["toggle_closes"] and all(a["passed"] for a in report["attempts"])
    except Exception as error:
        report["error"] = type(error).__name__ + ": " + str(error)
        report["passed"] = False
    finally:
        for handle in windows(process.pid).values():
            user32.PostMessageW(handle, 0x0010, 0, 0)
        try:
            process.wait(timeout=20)
            report["exit"] = process.returncode
        except subprocess.TimeoutExpired:
            report["shutdown_timeout"] = True
            process.terminate()
            process.wait(timeout=5)
            report["passed"] = False
        report["remaining_owned_processes"] = [p.pid for p in psutil.process_iter(["exe"])
            if p.info["exe"] and Path(p.info["exe"]).resolve().is_relative_to(install)]
        (output / "validation.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "attempts"}, indent=2))
    return 0 if report.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
