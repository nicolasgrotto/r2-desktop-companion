from importlib.metadata import distribution
from pathlib import Path
import sys

from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).parent
assets = root / "src/r2_companion/assets"
data = [(str(assets), "r2_companion/assets"),
        (str(root / "scripts/update-r2-companion.ps1"), "scripts"),
        (str(root / "packaging/docs/THIRD_PARTY_NOTICES.md"), ".")]
media_packages = ("typing_extensions", "winrt-runtime", "winrt-Windows.Foundation",
                  "winrt-Windows.Foundation.Collections", "winrt-Windows.Media.Control",
                  "winrt-Windows.Storage.Streams")
# The winrt-runtime hook also collects the projection modules and their native tables.
for name in media_packages:
    data += copy_metadata(name)
for name in ("PySide6-Essentials", "PySide6-Addons", "shiboken6", "psutil", "pyinstaller", *media_packages):
    dist = distribution(name)
    for entry in dist.files or []:
        if "licenses" in str(entry).lower() or Path(str(entry)).name.lower().startswith(("license", "copying", "notice")):
            source = Path(dist.locate_file(entry))
            if source.is_file():
                data.append((str(source), f"licenses/{name}/{Path(str(entry)).parent.name}"))
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.is_file():
    data.append((str(python_license), "licenses/Python"))

a = Analysis([str(root / "run_companion.py")], pathex=[str(root / "src")],
             binaries=[], datas=data, hiddenimports=[],
             excludes=["PySide6.QtQml", "PySide6.QtQuick",
                       "PySide6.QtTest", "PySide6.QtSvg", "tkinter", "pytest"],
             noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="R2Companion",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=False, icon=str(assets / "icons/companion.ico"),
          manifest=str(root / "packaging/windows.manifest"))
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="R2Companion")
