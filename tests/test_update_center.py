import hashlib
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtTest import QTest

from r2_companion.services.update_client import ASSET, REPOSITORY, check_release, download_release, validate_release, version_tuple
from r2_companion.ui.updates import UpdateCenter
from test_updates import ps, quote, installation, release, mock_release, REPOSITORY as FIXTURE_REPOSITORY


def response(package=b"verified package", version="9.0.0"):
    checksum = f"{hashlib.sha256(package).hexdigest()}  {ASSET}\n".encode()
    raw = {"tag_name": f"v{version}", "draft": False, "prerelease": False, "body": "Novidades\n\nTexto simples.",
           "assets": [{"name": name, "size": len(data), "browser_download_url": f"https://github.com/{REPOSITORY}/releases/download/v{version}/{name}"}
                      for name, data in ((ASSET, package), (ASSET + ".sha256", checksum))]}
    def opener(request, timeout):
        if request.full_url.startswith("https://api.github.com"):
            return io.BytesIO(json.dumps(raw).encode())
        return io.BytesIO(checksum if request.full_url.endswith(".sha256") else package)
    return raw, opener


def test_query_and_download_use_real_byte_counts_and_sha256(tmp_path):
    raw, opener = response(package=b"p" * 150000)
    result = check_release(REPOSITORY, opener)
    counts, stages = [], []
    directory = download_release(result, tmp_path / "prepared", lambda got, total: counts.append((got, total)),
                                 lambda state, text: stages.append(state), opener=opener)
    assert counts[-1] == (150000, 150000)
    assert all(a < b for (a, _), (b, _) in zip(counts, counts[1:]))
    assert stages[-1] == "integrity"
    assert json.loads((directory / "candidate.json").read_text()) == raw


@pytest.mark.parametrize("change", ["origin", "duplicate", "prerelease", "version", "oversize"])
def test_release_metadata_rejects_untrusted_or_invalid_assets(change):
    raw, _ = response()
    if change == "origin":
        raw["assets"][0]["browser_download_url"] = "https://attacker.invalid/file.zip"
    elif change == "duplicate":
        raw["assets"].append(raw["assets"][0].copy())
    elif change == "prerelease":
        raw["prerelease"] = True
    elif change == "version":
        raw["tag_name"] = "v9.0.0-beta"
    else:
        raw["assets"][0]["size"] = 2 ** 40
    with pytest.raises(ValueError):
        validate_release(raw, REPOSITORY)


def test_download_detects_corruption_truncation_excess_and_cancellation(tmp_path):
    raw, valid = response(package=b"good")
    result = validate_release(raw, REPOSITORY)
    def corrupt(request, timeout):
        return valid(request, timeout) if request.full_url.endswith(".sha256") else io.BytesIO(b"evil")
    with pytest.raises(ValueError, match="SHA-256"):
        download_release(result, tmp_path / "corrupt", lambda *a: None, lambda *a: None, opener=corrupt)
    for name, payload in (("short", b"x"), ("long", b"too long")):
        with pytest.raises(ValueError):
            download_release(result, tmp_path / name, lambda *a: None, lambda *a: None,
                             opener=lambda *a, **kw: io.BytesIO(payload))
    with pytest.raises(InterruptedError):
        download_release(result, tmp_path / "cancel", lambda *a: None, lambda *a: None, cancelled=lambda: True, opener=valid)


def wait_for_worker(dialog):
    for _ in range(100):
        QTest.qWait(10)
        if dialog.worker is None:
            return
    pytest.fail("Update worker did not finish")


def test_update_window_checks_async_shows_notes_and_retries_without_native_dialog(qapp, tmp_path):
    raw, _ = response()
    calls = []
    def client(repository):
        calls.append(repository)
        if len(calls) == 1:
            raise ValueError("Conexão indisponível")
        return validate_release(raw, repository)
    dialog = UpdateCenter(tmp_path, client=client)
    dialog.startup.stop()
    try:
        dialog.check()
        assert dialog.state == "checking" and dialog.progress.minimum() == dialog.progress.maximum() == 0
        wait_for_worker(dialog)
        assert dialog.state == "error" and "Conexão" in dialog.detail.text()
        dialog.act()
        wait_for_worker(dialog)
        assert dialog.state == "available" and "9.0.0" in dialog.status.text()
        assert dialog.notes.toPlainText() == raw["body"]
        dialog.download_progress(1200, 3000)
        assert dialog.progress.value() == 1200 and dialog.progress.maximum() == 3000
        dialog.download()
        assert dialog.state == "error" and "executável" in dialog.detail.text()
    finally:
        dialog.close()
    assert not dialog.animation.timer.isActive() and not dialog.poll.isActive()


def test_update_window_current_and_failed_installer_show_honest_states(qapp, tmp_path):
    raw, _ = response(version="0.0.1")
    dialog = UpdateCenter(tmp_path)
    dialog.startup.stop()
    try:
        dialog.checked(validate_release(raw, REPOSITORY))
        assert dialog.state == "current"
        status = tmp_path / "status.json"
        status.write_text(json.dumps({"state": "error", "message": "Backup recuperado"}))
        dialog.status_path = status
        dialog.child = SimpleNamespace(poll=lambda: 1, returncode=1)
        dialog.poll_install()
        assert dialog.state == "error" and dialog.detail.text() == "Backup recuperado"
    finally:
        dialog.close()


def test_prepared_package_is_rechecked_against_published_checksum(tmp_path):
    old = installation(tmp_path / "installed")
    prepared = tmp_path / "data/updates/download-test"
    prepared.mkdir(parents=True)
    archive = prepared / ASSET
    archive.write_bytes(b"tampered")
    (prepared / (ASSET + ".sha256")).write_text(f"{hashlib.sha256(b'tampered').hexdigest()}  {ASSET}")
    published = tmp_path / "published.sha256"
    published.write_text(f"{hashlib.sha256(b'original').hexdigest()}  {ASSET}")
    raw = release()
    raw["assets"][0]["size"] = len(b"tampered")
    status = prepared / "status.json"
    body = f"""
{mock_release(tmp_path, raw)}
function Get-R2Download {{ param($Url, $Destination) Copy-Item -LiteralPath {quote(published)} -Destination $Destination }}
function Stop-R2Installation {{ throw 'must not stop old installation' }}
function Show-R2Message {{}}
$InstallDirectory = {quote(old)}
$DataDirectory = {quote(tmp_path / 'data')}
$PreparedDirectory = {quote(prepared)}
$PreparedVersion = '0.3.0'
$StatusPath = {quote(status)}
$Yes = $true
Invoke-R2Update
"""
    result = ps(tmp_path, body, success=False)
    assert "SHA-256" in result.stdout + result.stderr
    assert (old / "R2Companion.exe").read_text() == "0.2.0"


def test_version_order_uses_numeric_components():
    assert version_tuple("1.10.0") > version_tuple("1.9.0")
    with pytest.raises(ValueError):
        version_tuple("1.0.0;command")
