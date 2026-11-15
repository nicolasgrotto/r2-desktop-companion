"""Standalone investigation artifact; never substitutes the Companion package."""
from importlib.metadata import distribution
from pathlib import Path
import sys

from PyInstaller.utils.hooks import copy_metadata

root = Path(SPECPATH).parent
packages = ("typing_extensions", "winrt-runtime", "winrt-Windows.Foundation",
            "winrt-Windows.Foundation.Collections", "winrt-Windows.Media.Control",
            "winrt-Windows.Storage.Streams")
data = []
for name in (*packages, "pyinstaller"):
    if name in packages:
        data += copy_metadata(name)
    dist = distribution(name)
    for entry in dist.files or []:
        if "licenses" in str(entry).lower() or Path(str(entry)).name.lower().startswith(("license", "copying", "notice")):
            source = Path(dist.locate_file(entry))
            if source.is_file():
                data.append((str(source), f"licenses/{name}/{Path(str(entry)).parent.name}"))
python_license = Path(sys.base_prefix) / "LICENSE.txt"
if python_license.is_file():
    data.append((str(python_license), "licenses/Python"))

# winrt-runtime's registered hook collects the installed projection namespaces
# and their real _table.pywinrt files. Build only in the minimal isolated venv.
a = Analysis([str(root / "tools/media_probe.py")], pathex=[str(root / "tools")],
             binaries=[], datas=data, hiddenimports=[],
             excludes=["PySide6", "pytest", "tkinter"], noarchive=False)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="R2MediaProbe",
          debug=False, bootloader_ignore_signals=False, strip=False, upx=False,
          console=True, uac_admin=False, uac_uiaccess=False)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="R2MediaProbe")
