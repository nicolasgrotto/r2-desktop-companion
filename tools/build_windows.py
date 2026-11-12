import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tomllib
from zipfile import ZIP_DEFLATED, ZipFile
import re

root = Path(__file__).resolve().parents[1]
environment = os.environ.copy()
environment["PYINSTALLER_CONFIG_DIR"] = str(root / ".runtime-buildcache")
parser = argparse.ArgumentParser()
parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
parser.add_argument("--package-only", action="store_true")
parser.add_argument("--artifact-label")
args = parser.parse_args()
if args.artifact_label and not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,39}", args.artifact_label):
    parser.error("Rótulo de artefato inválido.")
repository = args.repository
if not repository:
    git = ["git", "-c", f"safe.directory={root.as_posix()}"]
    names = subprocess.check_output(git + ["remote"], cwd=root, text=True).split()
    remote_name = "origin" if "origin" in names else names[0] if len(names) == 1 else None
    if remote_name is None:
        parser.error("Informe --repository owner/repo para a origem das atualizacoes.")
    remote = subprocess.check_output(git + ["remote", "get-url", remote_name], cwd=root, text=True).strip()
    match = re.fullmatch(r"(?:https://github.com/|git@github.com:)([^/]+/[^/]+?)(?:\.git)?", remote)
    if not match:
        parser.error("Informe --repository owner/repo para a origem das atualizacoes.")
    repository = match[1]
if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repository):
    parser.error("Repositorio invalido.")
version = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
if not re.fullmatch(r"\d+\.\d+\.\d+", version):
    parser.error("Versao deve usar X.Y.Z.")
if os.environ.get("GITHUB_REF_TYPE") == "tag" and os.environ.get("GITHUB_REF_NAME") != f"v{version}":
    parser.error("A tag deve corresponder a versao do projeto.")
if not args.package_only:
    result = subprocess.call([sys.executable, "-m", "PyInstaller", "--noconfirm",
                                 "--distpath", str(root / "dist" / (version + ("-" + args.artifact_label if args.artifact_label else ""))),
                                 "--workpath", str(root / "build" / (version + ("-" + args.artifact_label if args.artifact_label else ""))),
                                 str(root / "packaging/R2Companion.spec")],
                                cwd=root, env=environment)
    if result:
        raise SystemExit(result)
directory = root / "dist" / (version + ("-" + args.artifact_label if args.artifact_label else "")) / "R2Companion"
if not (directory / "R2Companion.exe").is_file():
    raise SystemExit("Executavel nao encontrado.")
metadata = {"schema_version": 1, "version": version, "repository": repository}
if args.artifact_label:
    metadata["build"] = args.artifact_label
(directory / "release.json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
archive = root / ("dist/R2Companion-Windows-x64" + ("-" + args.artifact_label if args.artifact_label else "") + ".zip")
with ZipFile(archive, "w", compression=ZIP_DEFLATED, compresslevel=6) as output:
    for path in sorted(directory.rglob("*")):
        if path.is_symlink():
            raise ValueError("Links nao sao permitidos no pacote.")
        if path.is_file():
            output.write(path, path.relative_to(directory.parent).as_posix())
with ZipFile(archive) as output:
    if output.testzip() is not None:
        raise ValueError("Falha de integridade no ZIP.")
with archive.open("rb") as input_file:
    digest = hashlib.file_digest(input_file, "sha256").hexdigest()
archive.with_suffix(".zip.sha256").write_text(f"{digest}  {archive.name}\n", encoding="ascii")
print(json.dumps({"version": version, "repository": repository, "package": str(archive), "sha256": digest}))
