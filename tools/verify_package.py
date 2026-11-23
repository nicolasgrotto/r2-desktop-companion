import argparse
import hashlib
import json
from pathlib import Path
import stat
import subprocess
import tomllib
from uuid import uuid4
from zipfile import ZipFile

from verify_media_probe_package import clean_environment


MEDIA_LICENSES = {"typing_extensions", "winrt-runtime", "winrt-Windows.Foundation",
                  "winrt-Windows.Foundation.Collections", "winrt-Windows.Media.Control",
                  "winrt-Windows.Storage.Streams"}
WINRT_TABLES = {"foundation", "foundation/collections", "media/control", "storage/streams"}


def smoke_run(executable, data, work, environment, seconds, version, language, title, media, expected_droids):
    updates = data / "updates"
    updates.mkdir(parents=True)
    state = {"schema_version": 1, "appearance": {"language": language}, "media": {"enabled": media}}
    (data / "companion_state.json").write_text(json.dumps(state), encoding="utf-8")
    startup = updates / f"startup-{uuid4().hex}.json"
    with (work / f"{language}.log").open("wb") as log:
        process = subprocess.run([str(executable), "--data-dir", str(data), "--smoke-test",
                                  "--smoke-seconds", str(seconds), "--smoke-droids", "--smoke-navigation",
                                  "--startup-ready-file", str(startup)],
                                 cwd=work, env=environment, creationflags=subprocess.CREATE_NO_WINDOW,
                                 stdout=log, stderr=subprocess.STDOUT, timeout=seconds + 45)
    if process.returncode:
        raise RuntimeError(f"{language} smoke exit: {process.returncode}")
    ready = json.loads(startup.read_text(encoding="utf-8"))
    expected_identity = {"initialized": True, "version": version, "executable": str(executable),
                         "bundle": str(executable.parent / "_internal"), "data_directory": str(data)}
    if any(ready.get(key) != value for key, value in expected_identity.items()):
        raise RuntimeError(f"{language} startup confirmation mismatch")
    smoke = json.loads((data / "smoke.json").read_text(encoding="utf-8"))
    if (not smoke["visible"] or smoke["active_timers_after_shutdown"]
            or smoke["movement_timer_after_shutdown"] or smoke["media_worker_after_shutdown"]):
        raise RuntimeError(f"{language} smoke failed: visibility or shutdown")
    if not smoke["navigation"] or not all(smoke["navigation"].values()):
        raise RuntimeError(f"{language} packaged navigation smoke failed")
    if {item["id"] for item in smoke["droids"]} != expected_droids or not all(item["accepted"] for item in smoke["droids"]):
        raise RuntimeError(f"{language} packaged droid smoke failed")
    if smoke["audio_effects"] == 0 or smoke["audio_output_available"] and (
            smoke["audio_errors"] or smoke["audio_loaded_effects"] != smoke["audio_effects"]):
        raise RuntimeError(f"{language} packaged audio resources did not load")
    if smoke["interface_language"] != language or smoke["tools_title"] != title:
        raise RuntimeError(f"{language} catalog did not load")
    if smoke["media_status"] not in ({"ready", "no_session"} if media else {"disabled"}):
        raise RuntimeError(f"{language} unexpected media status: {smoke['media_status']}")
    return {"smoke": smoke, "startup": ready, "exit": process.returncode}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=Path(".runtime-package-verification"))
    parser.add_argument("--artifact-label")
    parser.add_argument("--smoke-seconds", type=int, default=55,
                        help="Time for all seven droids and navigation to finish (5-120 seconds)")
    args = parser.parse_args()
    if not 5 <= args.smoke_seconds <= 120:
        parser.error("--smoke-seconds must be between 5 and 120")
    root = Path(__file__).resolve().parents[1]
    version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    output = args.data_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    work = output / "working directory"
    temporary = output / "temporary"
    work.mkdir()
    temporary.mkdir()
    suffix = "-" + args.artifact_label if args.artifact_label else ""
    directory = root / "dist" / (version + suffix) / "R2Companion"
    archive = root / ("dist/R2Companion-Windows-x64" + suffix + ".zip")
    environment = clean_environment(temporary)
    unpack = output / "portátil isolado"
    with archive.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if archive.with_suffix(".zip.sha256").read_text().split()[0] != digest:
        raise RuntimeError("Checksum mismatch")
    with ZipFile(archive) as bundle:
        names = bundle.namelist()
        if (len(names) != len({name.rstrip("/").casefold() for name in names})
                or any(not item.filename.startswith("R2Companion/") or "\\" in item.filename
                       or ":" in item.filename or ".." in item.filename.split("/")
                       or stat.S_ISLNK(item.external_attr >> 16) for item in bundle.infolist())
                or bundle.testzip() is not None):
            raise RuntimeError("ZIP integrity failed")
        if bundle.read("R2Companion/R2Companion.exe") != (directory / "R2Companion.exe").read_bytes():
            raise RuntimeError("Executable mismatch")
        script = "R2Companion/_internal/scripts/update-r2-companion.ps1"
        if bundle.read(script) != (root / "scripts/update-r2-companion.ps1").read_bytes():
            raise RuntimeError("Updater mismatch")
        resources = 0
        assets = root / "src/r2_companion/assets"
        for resource in assets.rglob("*"):
            if resource.is_file():
                name = "R2Companion/_internal/r2_companion/assets/" + resource.relative_to(assets).as_posix()
                if bundle.read(name) != resource.read_bytes():
                    raise RuntimeError(f"Packaged resource mismatch: {resource.name}")
                resources += 1
        sounds = sum("/assets/sounds/" in name and name.endswith(".wav") for name in names)
        internal = "R2Companion/_internal/"
        licenses = {name.removeprefix(internal).split("/")[1] for name in names
                    if name.startswith(internal + "licenses/") and name.count("/") >= 4 and not name.endswith("/")}
        if sounds < 15 or not (MEDIA_LICENSES | {"PySide6-Addons", "Python"}) <= licenses:
            raise RuntimeError("Missing sounds or licenses")
        tables = {name.removeprefix(internal + "winrt/windows/").removesuffix("/_table.pywinrt")
                  for name in names if name.endswith("/_table.pywinrt")}
        module_names = {Path(name).name for name in names}
        if (tables != WINRT_TABLES or "QtMultimedia.pyd" not in module_names
                or any(name.lower().startswith(("qt6qml", "qt6quick", "qt6virtualkeyboard", "qtvirtualkeyboard",
                                               "qtmultimediawidgets", "qt6multimediawidgets", "qtwebengine", "qt6webengine"))
                       for name in module_names)
                or module_names.intersection({"QtQml.pyd", "QtQuick.pyd", "QtTest.pyd"})):
            raise RuntimeError("Unexpected media or Qt modules")
        bundle.extractall(unpack)
        report = {"smoke_seconds": args.smoke_seconds, "zip_files": len(names),
                  "zip_bytes": archive.stat().st_size, "uncompressed_bytes": sum(item.file_size for item in bundle.infolist()),
                  "sha256": digest, "integrity": "passed", "clean_path": environment["PATH"], "sounds": sounds,
                  "verified_resources": resources, "winrt_tables": sorted(tables), "licenses": sorted(licenses), "runs": {}}
    expected_droids = {json.loads(path.read_text(encoding="utf-8"))["id"]
                       for path in (assets / "droids").glob("*/profile.json")}
    executable = unpack / "R2Companion/R2Companion.exe"
    for language, title, media in (("pt-BR", "Central de ferramentas · R2 Companion", False),
                                   ("en", "Tools Center · R2 Companion", True)):
        report["runs"][language] = smoke_run(executable, output / f"dados {language}", work, environment,
                                             args.smoke_seconds, version, language, title, media, expected_droids)
        (output / "package-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    report["smoke"] = report["runs"]["pt-BR"]["smoke"]
    report["exe_exit"] = report["runs"]["pt-BR"]["exit"]
    (output / "package-validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
