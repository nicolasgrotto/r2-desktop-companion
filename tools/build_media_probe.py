"""Build an isolated onedir WinRT probe without touching stable dist artifacts."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]
TABLES = ("foundation", "foundation/collections", "media/control", "storage/streams")


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True, help="New directory, never reused")
    args = parser.parse_args()
    if sys.platform != "win32" or platform.machine() != "AMD64":
        parser.error("Use Windows x64 and the isolated build requirements")
    expected = {}
    for filename in ("requirements-media-probe.txt", "requirements-media-probe-build.txt"):
        for line in (ROOT / "tools" / filename).read_text().splitlines():
            if line.strip() and not line.startswith(("#", "-r")):
                name, version = line.split("==")
                expected[name] = version
    for name, version in expected.items():
        if importlib.metadata.version(name) != version:
            parser.error(f"Install the pinned build requirements: {name}")
    namespaces = {d.metadata["Name"].lower() for d in importlib.metadata.distributions()
                  if d.metadata["Name"].lower().startswith("winrt-")}
    if namespaces != {name.lower() for name in expected if name.startswith("winrt-")}:
        parser.error("Unexpected WinRT packages; use a clean build environment without player fixtures")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    command = [sys.executable, "-m", "PyInstaller", "--noconfirm",
               "--distpath", str(output / "dist"), "--workpath", str(output / "build"),
               str(ROOT / "packaging/MediaProbe.spec")]
    report = {"started_utc": datetime.now(timezone.utc).isoformat(), "python": sys.version,
              "dependencies": expected, "command": command,
              "source_sha256": {p: digest(ROOT / p) for p in (
                  "tools/media_probe.py", "tools/media_probe.md", "packaging/MediaProbe.spec", "tools/build_media_probe.py",
                  "tools/requirements-media-probe.txt", "tools/requirements-media-probe-build.txt")}}
    with (output / "build.log").open("wb") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                                creationflags=subprocess.CREATE_NO_WINDOW)
    report["build_exit"] = result.returncode
    (output / "build-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    if result.returncode:
        return result.returncode
    directory = output / "dist/R2MediaProbe"
    for namespace in TABLES:
        table = directory / "_internal/winrt/windows" / namespace / "_table.pywinrt"
        if not table.is_file():
            raise RuntimeError(f"Missing projection table: {namespace}")
    shutil.copy2(ROOT / "tools/media_probe.md", directory / "README.md")
    archive = output / "R2MediaProbe-Windows-x64.zip"
    with ZipFile(archive, "x", compression=ZIP_DEFLATED) as bundle:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                bundle.write(path, path.relative_to(directory.parent).as_posix())
    checksum = digest(archive)
    archive.with_suffix(".zip.sha256").write_text(f"{checksum}  {archive.name}\n", encoding="ascii")
    report.update(finished_utc=datetime.now(timezone.utc).isoformat(), sha256=checksum,
                  zip_bytes=archive.stat().st_size,
                  files={p.relative_to(directory).as_posix(): {"bytes": p.stat().st_size, "sha256": digest(p)}
                         for p in sorted(directory.rglob("*")) if p.is_file()})
    (output / "build-report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"archive": str(archive), "sha256": checksum, "zip_bytes": report["zip_bytes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
