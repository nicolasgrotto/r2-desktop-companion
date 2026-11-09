import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
from zipfile import ZipFile, ZipInfo

import pytest

from r2_companion.services.updates import UpdateService, read_release

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/update-r2-companion.ps1"
REPOSITORY = "owner/companion"
REQUIRED = ["R2Companion.exe", "_internal/PySide6/Qt6Core.dll", "_internal/PySide6/Qt6Multimedia.dll",
            "_internal/r2_companion/assets/characters/default/manifest.json", "_internal/scripts/update-r2-companion.ps1"]


def quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def ps(tmp_path, body, success=True):
    command = tmp_path / "verify.ps1"
    command.write_text(f"$ErrorActionPreference = 'Stop'\n. {quote(SCRIPT)}\n{body}\n", encoding="utf-8-sig")
    result = subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(command)],
                            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
    if success:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0, result.stdout + result.stderr
    return result


def installation(path, version="0.2.0"):
    path.mkdir(parents=True)
    for name in REQUIRED:
        file = path / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(version, encoding="ascii")
    (path / "release.json").write_text(json.dumps({"schema_version": 1, "version": version, "repository": REPOSITORY}))
    return path


def release(version="0.3.0"):
    name = "R2Companion-Windows-x64.zip"
    return {"draft": False, "prerelease": False, "tag_name": f"v{version}", "assets": [
        {"name": asset, "size": 100, "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/v{version}/{asset}"}
        for asset in (name, name + ".sha256")]}


def mock_release(tmp_path, value):
    fixture = tmp_path / "response.json"
    fixture.write_text(json.dumps(value), encoding="utf-8")
    return f"function Get-R2LatestRelease {{ Get-Content -LiteralPath {quote(fixture)} -Raw | ConvertFrom-Json }}"


pytestmark = pytest.mark.skipif(os.name != "nt", reason="PowerShell 5.1 integration requires Windows")


@pytest.mark.parametrize("value", ["0.3.0", "1.10.0", "10.0.1"])
def test_version_comparison_uses_numeric_components(tmp_path, value):
    ps(tmp_path, f"$v = Convert-R2Version {quote(value)}; if ($v -le [version]'0.2.0') {{ throw 'version' }}")


@pytest.mark.parametrize("value", ["v0.3.0", "1.2", "1.2.3-beta", "01.2.3", "1.2.3;whoami"])
def test_invalid_or_unstable_version_rejected(tmp_path, value):
    ps(tmp_path, f"Convert-R2Version {quote(value)}", success=False)


def test_checksum_success_and_corruption_preserve_original(tmp_path):
    archive = tmp_path / "package.zip"
    archive.write_bytes(b"original download")
    checksum = tmp_path / "package.sha256"
    checksum.write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  R2Companion-Windows-x64.zip\n")
    ps(tmp_path, f"Test-R2Checksum {quote(archive)} {quote(checksum)}")
    archive.write_bytes(b"corrupt")
    ps(tmp_path, f"Test-R2Checksum {quote(archive)} {quote(checksum)}", success=False)


@pytest.mark.parametrize("entry", ["../escape.txt", "R2Companion/../../escape.txt", "C:/escape.txt",
    "/R2Companion/escape.txt", "R2Companion/test.txt:stream", "R2Companion/NUL.txt",
    "R2Companion/alias. /evil.txt", "R2Companion/../bad", "Other/app.exe",
    "R2Companion/COM¹.txt", "R2Companion/CONOUT$"])
def test_zip_paths_rejected_before_extraction(tmp_path, entry):
    archive = tmp_path / "malicious.zip"
    with ZipFile(archive, "w") as output:
        output.writestr(entry, b"payload")
    destination = tmp_path / "staging"
    ps(tmp_path, f"Expand-R2Package {quote(archive)} {quote(destination)}", success=False)
    assert not destination.exists()
    assert not (tmp_path / "escape.txt").exists()


def test_zip_symlinks_duplicates_and_corrupt_archive_rejected(tmp_path):
    archive = tmp_path / "links.zip"
    link = ZipInfo("R2Companion/link")
    link.create_system = 3
    link.external_attr = 0o120777 << 16
    with ZipFile(archive, "w") as output:
        output.writestr(link, "../../outside")
    ps(tmp_path, f"Expand-R2Package {quote(archive)} {quote(tmp_path / 'links')}", success=False)
    with ZipFile(archive, "w") as output:
        output.writestr("R2Companion/File.txt", "one")
        output.writestr("R2Companion/file.txt", "two")
    ps(tmp_path, f"Expand-R2Package {quote(archive)} {quote(tmp_path / 'duplicates')}", success=False)
    archive.write_bytes(b"not a zip")
    ps(tmp_path, f"Expand-R2Package {quote(archive)} {quote(tmp_path / 'corrupt')}", success=False)


def test_install_transaction_replaces_only_installation_and_retains_backup(tmp_path):
    old = installation(tmp_path / "installed [R2]", "0.2.0")
    new = installation(tmp_path / "staging/R2Companion", "0.3.0")
    data = tmp_path / "dados do usuário"
    data.mkdir()
    note = data / "tools.json"
    note.write_text("preserve")
    result = ps(tmp_path, f"$backup = Install-R2Package {quote(old)} {quote(new)} {quote(REPOSITORY)} '0.3.0'; Write-Host $backup")
    assert (old / "R2Companion.exe").read_text() == "0.3.0"
    backups = list(tmp_path.glob("installed*.backup-*"))
    assert len(backups) == 1 and (backups[0] / "R2Companion.exe").read_text() == "0.2.0"
    assert note.read_text() == "preserve"


def test_substitution_failure_rolls_back_existing_installation(tmp_path):
    old = installation(tmp_path / "installed", "0.2.0")
    new = installation(tmp_path / "staging/R2Companion", "0.3.0")
    body = f"""
function Move-Item {{
    param([string]$LiteralPath, [string]$Destination)
    if ($LiteralPath -eq {quote(new)}) {{ throw 'simulated permission denial' }}
    Microsoft.PowerShell.Management\\Move-Item -LiteralPath $LiteralPath -Destination $Destination
}}
Install-R2Package {quote(old)} {quote(new)} {quote(REPOSITORY)} '0.3.0'
"""
    ps(tmp_path, body, success=False)
    assert (old / "R2Companion.exe").read_text() == "0.2.0"
    assert (new / "R2Companion.exe").read_text() == "0.3.0"


def test_temporary_windows_file_lock_is_retried_without_losing_files(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "file.txt").write_text("preserved")
    destination = tmp_path / "installed"
    body = f"""
$script:Attempts = 0
function Wait-R2FileAccess {{}}
function Move-Item {{
    param([string]$LiteralPath, [string]$Destination)
    $script:Attempts++
    if ($script:Attempts -lt 3) {{ throw [IO.IOException]::new('sharing violation') }}
    Microsoft.PowerShell.Management\\Move-Item -LiteralPath $LiteralPath -Destination $Destination
}}
Move-R2Directory {quote(source)} {quote(destination)}
if ($script:Attempts -ne 3) {{ throw 'retry count' }}
"""
    ps(tmp_path, body)
    assert (destination / "file.txt").read_text() == "preserved"


def test_start_failure_rolls_back_and_restarts_old_version(tmp_path):
    old = installation(tmp_path / "installed", "0.2.0")
    new = installation(tmp_path / "staging/R2Companion", "0.3.0")
    marker = tmp_path / "restart.txt"
    body = f"""
function Start-R2Installation {{
    param([string]$Directory, [string]$UserData)
    if ((Read-R2Release $Directory).version -eq '0.3.0') {{ throw 'new executable failed' }}
    Set-Content -LiteralPath {quote(marker)} -Value 'restored'
}}
function Stop-R2Installation {{}}
Install-R2Package {quote(old)} {quote(new)} {quote(REPOSITORY)} '0.3.0' -Restart
"""
    ps(tmp_path, body, success=False)
    assert (old / "R2Companion.exe").read_text() == "0.2.0"
    assert marker.read_text().strip() == "restored"
    assert len(list(tmp_path.glob("installed.failed-*"))) == 1


def test_wrong_source_and_incomplete_package_cannot_replace_installation(tmp_path):
    old = installation(tmp_path / "installed")
    new = installation(tmp_path / "staging/R2Companion", "0.3.0")
    ps(tmp_path, f"Install-R2Package {quote(old)} {quote(new)} 'attacker/repo' '0.3.0'", success=False)
    (new / REQUIRED[-1]).unlink()
    ps(tmp_path, f"Install-R2Package {quote(old)} {quote(new)} {quote(REPOSITORY)} '0.3.0'", success=False)
    assert (old / "R2Companion.exe").read_text() == "0.2.0"
    assert not list(tmp_path.glob("installed.backup-*"))


def test_no_update_or_check_only_does_not_download_or_stop(tmp_path):
    old = installation(tmp_path / "installed", "0.3.0")
    body = f"""
{mock_release(tmp_path, release())}
function Get-R2Download {{ throw 'must not download' }}
function Stop-R2Installation {{ throw 'must not stop' }}
function Show-R2Message {{ param($Message, [switch]$Question) Write-Host $Message }}
$InstallDirectory = {quote(old)}
$DataDirectory = {quote(tmp_path / 'data')}
Invoke-R2Update
"""
    result = ps(tmp_path, body)
    assert "atualizado" in result.stdout
    (old / "release.json").write_text(json.dumps({"schema_version": 1, "version": "0.2.0", "repository": REPOSITORY}))
    result = ps(tmp_path, "$CheckOnly = $true\n" + body)
    assert "disponivel" in result.stdout


def test_network_failure_and_rejected_download_origin_leave_installation(tmp_path):
    old = installation(tmp_path / "installed")
    common = f"$InstallDirectory = {quote(old)}; $DataDirectory = {quote(tmp_path / 'data')}; Invoke-R2Update"
    ps(tmp_path, "function Get-R2LatestRelease { throw 'network unavailable' }\n" + common, success=False)
    bad = release()
    bad["assets"][0]["browser_download_url"] = "https://attacker.invalid/package.zip"
    ps(tmp_path, mock_release(tmp_path, bad) + "\n" + common, success=False)
    assert (old / "R2Companion.exe").read_text() == "0.2.0"


def test_full_update_with_local_transport_and_preserved_data(tmp_path):
    old = installation(tmp_path / "installed")
    new = installation(tmp_path / "source/R2Companion", "0.3.0")
    archive = tmp_path / "download.zip"
    with ZipFile(archive, "w") as output:
        for path in new.rglob("*"):
            if path.is_file():
                output.write(path, path.relative_to(new.parent).as_posix())
    checksum = tmp_path / "checksum.txt"
    checksum.write_text(f"{hashlib.sha256(archive.read_bytes()).hexdigest()}  R2Companion-Windows-x64.zip\n")
    response = release()
    response["assets"][0]["size"] = archive.stat().st_size
    response["assets"][1]["size"] = checksum.stat().st_size
    data = tmp_path / "data"
    data.mkdir()
    (data / "tools.json").write_text("notes")
    body = f"""
{mock_release(tmp_path, response)}
function Get-R2Download {{
    param($Url, $Destination)
    $source = if ($Url.EndsWith('.sha256')) {{ {quote(checksum)} }} else {{ {quote(archive)} }}
    Copy-Item -LiteralPath $source -Destination $Destination
}}
function Stop-R2Installation {{}}
function Show-R2Message {{}}
$InstallDirectory = {quote(old)}
$DataDirectory = {quote(data)}
$Yes = $true
$NoRestart = $true
Invoke-R2Update
"""
    ps(tmp_path, body)
    assert (old / "R2Companion.exe").read_text() == "0.3.0"
    assert (data / "tools.json").read_text() == "notes"
    assert not list(tmp_path.glob(".r2-update-*"))
    assert "Atualizado" in (data / "updates/update.log").read_text(encoding="utf-8-sig")


def test_python_launcher_uses_copied_script_and_no_shell(tmp_path, monkeypatch):
    installed = installation(tmp_path / "installed")
    data = tmp_path / "data"
    calls = []
    process = SimpleNamespace(poll=lambda: None)
    service = UpdateService(data, installed / "R2Companion.exe", SCRIPT,
                            lambda *args, **kwargs: calls.append((args, kwargs)) or process)
    monkeypatch.setattr("r2_companion.services.updates.psutil.Process", lambda: SimpleNamespace(create_time=lambda: 1000))
    assert service.launch() is process
    args, kwargs = calls[0]
    assert "-File" in args[0] and "-ExpectedProcessId" in args[0]
    assert not kwargs.get("shell", False)
    copied = Path(args[0][args[0].index("-File") + 1])
    assert copied.read_bytes() == SCRIPT.read_bytes() and copied.parent == data / "updates"
    with pytest.raises(ValueError, match="andamento"):
        service.launch()
    (installed / "release.json").write_text('{"schema_version":1,"repository":"https://bad","version":"0.3.0"}')
    with pytest.raises(ValueError):
        read_release(installed / "release.json")
