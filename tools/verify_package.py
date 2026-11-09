import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tomllib
from zipfile import ZipFile


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".runtime-package-verification"))
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    output = args.data_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    work = output / "working directory"
    work.mkdir(exist_ok=True)
    directory = root / "dist" / version / "R2Companion"
    archive = root / "dist/R2Companion-Windows-x64.zip"
    executable = directory / "R2Companion.exe"
    environment = {key: value for key, value in os.environ.items()
                   if not key.upper().startswith(("PYTHON", "QT_")) and key != "VIRTUAL_ENV"}
    environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    data = output / "dados isolados"
    process = subprocess.run([str(executable), "--data-dir", str(data), "--smoke-test", "--smoke-seconds", "5"],
                             cwd=work, env=environment, creationflags=subprocess.CREATE_NO_WINDOW, timeout=45)
    if process.returncode:
        raise RuntimeError(f"Smoke exit: {process.returncode}")
    smoke = json.loads((data / "smoke.json").read_text(encoding="utf-8"))
    if not smoke["visible"] or smoke["active_timers_after_shutdown"]:
        raise RuntimeError("Smoke failed: visibility or shutdown")
    with archive.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if archive.with_suffix(".zip.sha256").read_text().split()[0] != digest:
        raise RuntimeError("Checksum mismatch")
    with ZipFile(archive) as bundle:
        names = bundle.namelist()
        if (bundle.testzip() is not None or len(names) != len({name.casefold() for name in names})
                or not all(name.startswith("R2Companion/") for name in names)):
            raise RuntimeError("ZIP integrity failed")
        if bundle.read("R2Companion/R2Companion.exe") != executable.read_bytes():
            raise RuntimeError("Executable mismatch")
        script = "R2Companion/_internal/scripts/update-r2-companion.ps1"
        if bundle.read(script) != (root / "scripts/update-r2-companion.ps1").read_bytes():
            raise RuntimeError("Updater mismatch")
        sounds = sum("/assets/sounds/" in name and name.endswith(".wav") for name in names)
        if sounds < 15 or not any("/licenses/PySide6-Addons/" in name for name in names):
            raise RuntimeError("Missing sounds or licenses")
        report = {"exe_exit": process.returncode, "smoke": smoke, "zip_files": len(names),
                  "zip_bytes": archive.stat().st_size, "uncompressed_bytes": sum(item.file_size for item in bundle.infolist()),
                  "sha256": digest, "integrity": "passed", "clean_path": environment["PATH"], "sounds": sounds}
    (output / "package-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
