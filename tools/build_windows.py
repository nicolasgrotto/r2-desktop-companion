"""Build only inside the Companion workspace, including the packager cache."""
import os
from pathlib import Path
import subprocess
import sys
import tomllib

root = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
environment["PYINSTALLER_CONFIG_DIR"] = str(root / ".runtime-buildcache")
version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
raise SystemExit(subprocess.call([sys.executable, "-m", "PyInstaller", "--noconfirm",
                                 "--distpath", str(root / "dist" / version),
                                 "--workpath", str(root / "build" / version),
                                 str(root / "packaging/R2Companion.spec")],
                                cwd=root, env=environment))
