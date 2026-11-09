from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from r2_companion.features.launcher import launch, local_path, validate_executable
from r2_companion.features.locations import open_location, validate_location
from r2_companion.services.system_info import SystemInfo
from r2_companion.services.windows import RUN_KEY, RUN_NAME, StartupService


@pytest.mark.parametrize("path", [r"\\server\share\app.exe", "cmd /c calc", "https://example.com/a.exe",
                                      r"C:\tool.exe:stream", r"C:\a.exe|whoami", r"C:\%TEMP%\a.exe",
                                      r"\\?\C:\app.exe", r"C:\foo.exe\n"])
def test_unsafe_path_forms_rejected(path):
    with pytest.raises((ValueError, OSError)):
        local_path(path)


@pytest.mark.parametrize("name", ["cmd.exe", "powershell.exe", "pwsh.exe", "python.exe", "pythonw.exe",
                                      "python3.13.exe", "wscript.exe", "mshta.exe", "run.bat", "app.lnk"])
def test_interpreters_and_scripts_rejected(tmp_path, name):
    path = tmp_path / name
    path.touch()
    with pytest.raises(ValueError):
        validate_executable(str(path))


def test_valid_application_uses_fields_and_no_shell(tmp_path):
    path = tmp_path / "Editor com espaço 漢.exe"
    path.touch()
    calls = []
    assert launch(str(path), lambda *args: calls.append(args) or (True, 1234))
    assert calls == [(str(path.resolve()), [], str(tmp_path.resolve()))]
    assert not launch(str(path), lambda *args: (False, 0))
    path.unlink()
    with pytest.raises(OSError):
        launch(str(path), lambda *args: pytest.fail("Must not launch a missing file"))


def test_mapped_network_drive_rejected_before_filesystem_access(monkeypatch):
    monkeypatch.setattr("r2_companion.features.launcher.drive_type", lambda anchor: 4)
    with pytest.raises(ValueError, match="rede"):
        local_path(r"Z:\application.exe")


def test_locations_allow_files_and_folders_without_command_strings(qapp, tmp_path):
    assert validate_location(str(tmp_path), "folder") == tmp_path.resolve()
    path = tmp_path / "nota com espaço.txt"
    path.touch()
    urls = []
    assert open_location(str(path), "file", lambda url: urls.append(url) or True)
    assert urls[0].toLocalFile() == str(path.resolve()).replace('\\', '/')
    for name in ("app.exe", "run.ps1", "website.url", "shortcut.lnk"):
        bad = tmp_path / name
        bad.touch()
        with pytest.raises(ValueError):
            validate_location(str(bad), "file")


def test_metrics_prime_and_absent_battery():
    calls = []
    fake = SimpleNamespace(cpu_percent=lambda interval: calls.append(interval) or 15,
                           virtual_memory=lambda: SimpleNamespace(percent=60), sensors_battery=lambda: None)
    service = SystemInfo(fake)
    assert service.sample(battery=True) == {"cpu": None, "ram": 60, "battery": None}
    assert service.sample() == {"cpu": 15, "ram": 60}
    assert calls == [None, None]


class Registry:
    HKEY_CURRENT_USER, KEY_SET_VALUE, REG_SZ = 1, 2, 3

    def __init__(self):
        self.values = {"UnrelatedSound": "DO NOT TOUCH"}
        self.writes = []

    def OpenKey(self, hive, path, *args):
        assert hive == self.HKEY_CURRENT_USER and path == RUN_KEY
        return nullcontext("key")

    CreateKeyEx = OpenKey

    def QueryValueEx(self, key, name):
        if name not in self.values:
            raise FileNotFoundError()
        return self.values[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, kind, value):
        self.writes.append(name)
        self.values[name] = value

    def DeleteValue(self, key, name):
        self.writes.append(name)
        del self.values[name]


def test_startup_is_owned_opt_in_and_reversible(tmp_path):
    executable = tmp_path / "R2Companion.exe"
    executable.touch()
    registry = Registry()
    service = StartupService(executable, registry)
    assert not service.enabled()
    assert not registry.writes
    service.set_enabled(True)
    assert registry.values[RUN_NAME] == f'"{executable.resolve()}"'
    assert service.enabled()
    service.set_enabled(False)
    assert RUN_NAME not in registry.values
    assert registry.values["UnrelatedSound"] == "DO NOT TOUCH"
    registry.values[RUN_NAME] = "other-owner.exe"
    with pytest.raises(ValueError):
        service.set_enabled(True)
    with pytest.raises(ValueError):
        service.set_enabled(False)
    assert registry.values[RUN_NAME] == "other-owner.exe"
    assert set(registry.writes) == {RUN_NAME}
