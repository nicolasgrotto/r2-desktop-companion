import hashlib
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ASSET = "R2Companion-Windows-x64.zip"
REPOSITORY = "nicolasgrotto/r2-desktop-companion"


def version_tuple(value):
    if not isinstance(value, str) or not re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", value):
        raise ValueError("Versão estável inválida.")
    parts = tuple(map(int, value.split(".")))
    if max(parts) > 2147483647:
        raise ValueError("Versão fora do intervalo permitido.")
    return parts


def validate_release(raw, repository):
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repositório inválido.")
    if not isinstance(raw, dict) or raw.get("draft") is not False or raw.get("prerelease") is not False:
        raise ValueError("A resposta não é uma release estável.")
    tag = raw.get("tag_name", "")
    if not isinstance(tag, str) or not tag.startswith("v"):
        raise ValueError("Tag de release inválida.")
    version_tuple(tag[1:])
    assets = raw.get("assets")
    if not isinstance(assets, list):
        raise ValueError("Lista de arquivos inválida.")
    selected = {}
    for name in (ASSET, ASSET + ".sha256"):
        matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
        if len(matches) != 1:
            raise ValueError(f"Arquivo da release ausente ou duplicado: {name}")
        asset = matches[0]
        if (asset.get("browser_download_url") != f"https://github.com/{repository}/releases/download/{tag}/{name}"
                or type(asset.get("size")) is not int or not 0 < asset["size"] <= (1024 if name.endswith(".sha256") else 512 * 1024 * 1024)):
            raise ValueError("Origem ou tamanho do arquivo inválido.")
        selected[name] = asset
    body = raw.get("body") or "Nenhuma novidade informada nesta release."
    if not isinstance(body, str):
        raise ValueError("Novidades da release inválidas.")
    return {"version": tag[1:], "repository": repository, "notes": body[:20000], "assets": selected, "raw": raw}


def check_release(repository, opener=urlopen):
    if not re.fullmatch(r"[A-Za-z0-9_-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Repositório inválido.")
    request = Request(f"https://api.github.com/repos/{repository}/releases/latest",
                      headers={"User-Agent": "R2Companion-Updater", "Accept": "application/vnd.github+json"})
    try:
        with opener(request, timeout=10) as response:
            content = response.read(1024 * 1024 + 1)
        if len(content) > 1024 * 1024:
            raise ValueError("Resposta da release muito extensa.")
        return validate_release(json.loads(content), repository)
    except HTTPError as error:
        messages = {404: "Nenhuma release pública estável foi encontrada.", 403: "O GitHub limitou a consulta. Tente novamente mais tarde."}
        raise ValueError(messages.get(error.code, f"O GitHub respondeu com erro HTTP {error.code}.")) from error
    except (URLError, TimeoutError) as error:
        raise ValueError("Não foi possível conectar ao GitHub. Confira a conexão e tente novamente.") from error


def download_release(release, directory: Path, progress, stage, cancelled=lambda: False, opener=urlopen):
    directory.mkdir(parents=True, exist_ok=False)
    for name, asset in release["assets"].items():
        if cancelled():
            raise InterruptedError("Operação cancelada.")
        stage("download", "Baixando pacote" if name == ASSET else "Baixando checksum")
        target = directory / name
        count = 0
        with opener(Request(asset["browser_download_url"], headers={"User-Agent": "R2Companion-Updater"}), timeout=10) as response:
            with target.with_suffix(target.suffix + ".part").open("xb") as output:
                while True:
                    if cancelled():
                        raise InterruptedError("Operação cancelada.")
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    count += len(chunk)
                    if count > asset["size"]:
                        raise ValueError("O download excedeu o tamanho publicado.")
                    output.write(chunk)
                    if name == ASSET:
                        progress(count, asset["size"])
        if count != asset["size"]:
            raise ValueError("O download terminou antes de receber todo o arquivo.")
        target.with_suffix(target.suffix + ".part").replace(target)
    stage("integrity", "Verificando SHA-256 do pacote")
    checksum = (directory / (ASSET + ".sha256")).read_text(encoding="utf-8-sig").strip()
    match = re.fullmatch(r"([a-fA-F0-9]{64})\s+\*?" + re.escape(ASSET), checksum)
    with (directory / ASSET).open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if match is None or digest != match[1].lower():
        raise ValueError("Checksum SHA-256 incorreto. A instalação atual foi preservada.")
    (directory / "candidate.json").write_text(json.dumps(release["raw"], ensure_ascii=False), encoding="utf-8")
    return directory
