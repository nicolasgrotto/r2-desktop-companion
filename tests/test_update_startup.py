import json
import os

import pytest

from test_updates import installation, ps, quote, REPOSITORY

pytestmark = pytest.mark.skipif(os.name != "nt", reason="PowerShell integration requires Windows")


@pytest.mark.parametrize("field", [None, "pid", "version", "bundle", "executable", "data_directory", "initialized"])
def test_restart_requires_matching_ready_process_and_resets_bootloader(tmp_path, field):
    installed = installation(tmp_path / "installed", "1.1.2")
    data = tmp_path / "dados com espaço"
    marker = tmp_path / "launched.json"
    change = "" if field is None else f"$value.{field} = {'$false' if field == 'initialized' else '999' if field == 'pid' else quote('wrong')}"
    body = f"""
function Start-Process {{
    param($FilePath, $WorkingDirectory, $WindowStyle, $PassThru, $ArgumentList)
    if ($env:PYINSTALLER_RESET_ENVIRONMENT -ne '1') {{ throw 'missing reset' }}
    if ($WindowStyle -ne 'Hidden') {{ throw 'visible console' }}
    $ready = $ArgumentList[[Array]::IndexOf($ArgumentList, '--startup-ready-file') + 1].Trim('"')
    $value = @{{ pid = 12345; version = '1.1.2'; executable = $FilePath;
        bundle = (Join-Path $WorkingDirectory '_internal'); data_directory = {quote(data)}; initialized = $true }}
    {change}
    $value | ConvertTo-Json | Set-Content -LiteralPath $ready -Encoding UTF8
    $value | ConvertTo-Json | Set-Content -LiteralPath {quote(marker)} -Encoding UTF8
    $process = [pscustomobject]@{{ Id = 12345 }}
    $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{ param($Timeout) return $false }}
    return $process
}}
$env:PYINSTALLER_RESET_ENVIRONMENT = 'original'
try {{ Start-R2Installation {quote(installed)} {quote(data)} }} finally {{
    if ($env:PYINSTALLER_RESET_ENVIRONMENT -ne 'original') {{ throw 'parent environment changed' }}
}}
"""
    result = ps(tmp_path, body, success=field is None)
    assert marker.exists()
    if field is None:
        assert "Inicializacao confirmada" in result.stdout
    else:
        assert "nao confirmou" in result.stdout + result.stderr


def test_restart_exiting_before_ready_is_rejected(tmp_path):
    installed = installation(tmp_path / "installed", "1.1.2")
    body = f"""
function Start-Process {{
    $process = [pscustomobject]@{{ Id = 12345; ExitCode = 2 }}
    $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{ param($Timeout) return $true }}
    return $process
}}
Start-R2Installation {quote(installed)} {quote(tmp_path / 'data')}
"""
    result = ps(tmp_path, body, success=False)
    assert "antes de confirmar" in result.stdout + result.stderr


def test_unconfirmed_start_rolls_back_and_preserves_failed_package(tmp_path):
    old = installation(tmp_path / "installed", "1.1.1")
    new = installation(tmp_path / "stage/R2Companion", "1.1.2")
    body = f"""
function Start-Process {{
    param($FilePath, $WorkingDirectory, $WindowStyle, $PassThru, $ArgumentList)
    $process = [pscustomobject]@{{ Id = 12345; ExitCode = 1; Version = (Read-R2Release $WorkingDirectory).version }}
    $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{ param($Timeout) return $this.Version -eq '1.1.2' }}
    return $process
}}
Install-R2Package {quote(old)} {quote(new)} {quote(REPOSITORY)} '1.1.2' {quote(tmp_path / 'data')} -Restart
"""
    ps(tmp_path, body, success=False)
    assert json.loads((old / "release.json").read_text())["version"] == "1.1.1"
    failed, = tmp_path.glob("installed.failed-*")
    assert json.loads((failed / "release.json").read_text())["version"] == "1.1.2"


def test_install_does_not_move_files_until_all_old_processes_exit(tmp_path):
    old = installation(tmp_path / "installed", "1.1.1")
    new = installation(tmp_path / "stage/R2Companion", "1.1.2")
    body = f"""
function Get-Process {{
    $process = [pscustomobject]@{{ Id = 12345; Path = {quote(old / 'R2Companion.exe')} }}
    $process | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value {{ param($Timeout) return $false }}
    return $process
}}
Install-R2Package {quote(old)} {quote(new)} {quote(REPOSITORY)} '1.1.2'
"""
    result = ps(tmp_path, body, success=False)
    assert "nao encerrou" in result.stdout + result.stderr
    assert not list(tmp_path.glob("installed.backup-*"))
    assert json.loads((old / "release.json").read_text())["version"] == "1.1.1"
