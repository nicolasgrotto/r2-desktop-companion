"""Extract and exercise the portable probe with a restricted runtime environment."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]


def clean_environment(directory):
    environment = {k: v for k, v in os.environ.items()
                   if not k.upper().startswith(("PYTHON", "QT_", "_PYI"))
                   and k.upper() not in ("VIRTUAL_ENV", "VIRTUAL_ENV_PROMPT")}
    environment["PATH"] = str(Path(os.environ["SystemRoot"]) / "System32")
    environment["TEMP"] = environment["TMP"] = str(directory)
    return environment


def read_events(directory):
    return [json.loads(line) for line in (directory / "events.jsonl").read_text(encoding="utf-8").splitlines()]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.data_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    archive = args.archive.resolve()
    with archive.open("rb") as handle:
        checksum = hashlib.file_digest(handle, "sha256").hexdigest()
    if archive.with_suffix(".zip.sha256").read_text().split()[0] != checksum:
        raise ValueError("Archive checksum mismatch")
    unpack = output / "portable relocated ç"
    with ZipFile(archive) as bundle:
        names = bundle.namelist()
        if (bundle.testzip() is not None or len(names) != len({n.casefold() for n in names})
                or any(not n.startswith("R2MediaProbe/") or ".." in Path(n).parts or ":" in n for n in names)):
            raise ValueError("Invalid archive")
        bundle.extractall(unpack)
    executable = unpack / "R2MediaProbe/R2MediaProbe.exe"
    work, temporary = output / "working directory", output / "temporary"
    work.mkdir()
    temporary.mkdir()
    environment = clean_environment(temporary)
    expected = {name.lower().replace("_", "-"): version
                for line in (ROOT / "tools/requirements-media-probe.txt").read_text().splitlines()
                if line and not line.startswith("#") for name, version in [line.split("==")]}
    report = {"archive_sha256": checksum, "executable": str(executable),
              "path": environment["PATH"], "runs": [], "passed": False}

    def run(name, action, *extra):
        destination = output / name
        command = [str(executable), action, "--data-dir", str(destination), *extra]
        started = time.monotonic()
        with (output / f"{name}.log").open("wb") as log:
            result = subprocess.run(command, cwd=work, env=environment, stdout=log, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW, timeout=15)
        events = read_events(destination)
        record = {"name": name, "command": command, "exit_code": result.returncode,
                  "seconds": time.monotonic() - started, "events": events}
        report["runs"].append(record)
        (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        identity = events[0]
        assert identity["frozen"] and identity["architecture"] == "AMD64"
        assert identity["windows_identity"] == {"elevated": False, "has_package_identity": False}
        assert {k.lower().replace("_", "-"): v for k, v in identity["packages"].items()} == expected
        assert events[-1]["event"] == "closed"
        assert events[-1]["subscriptions_remaining"] == events[-1]["cleanup_errors"] == 0
        return record

    try:
        snapshot = run("snapshot", "snapshot")
        assert snapshot["exit_code"] == 0 and any(e["event"] == "snapshot" for e in snapshot["events"])
        watch = run("watch", "watch", "--seconds", "2")
        assert watch["exit_code"] == 0
        cancel = run("cancel", "cancel")
        assert cancel["exit_code"] == 0
        report["native_cancel"] = next(e["outcome"] for e in cancel["events"] if e["event"] == "cancel_result")
        # Force a real async deadline; completion is allowed to win the race.
        report["native_timeout_observed"] = False
        for attempt in range(3):
            timed = run(f"timeout-{attempt + 1}", "snapshot", "--timeout", "0.000000001")
            if timed["exit_code"] == 1 and any(e.get("error_type") == "TimeoutError" for e in timed["events"]):
                assert timed["seconds"] < 5
                report["native_timeout_observed"] = True
                break
            assert timed["exit_code"] == 0  # Only normal completion is an acceptable race.
        report["passed"] = report["native_timeout_observed"]
    finally:
        (output / "verification.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "native_timeout_observed": report["native_timeout_observed"],
                      "executable": str(executable)}))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
