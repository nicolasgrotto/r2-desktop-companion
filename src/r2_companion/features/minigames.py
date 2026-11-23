from base64 import b64decode, b64encode
from binascii import Error as Base64Error
from dataclasses import dataclass
from pathlib import Path
import re
from uuid import uuid4

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QImage, QImageReader
from ..core.language import tr


@dataclass(frozen=True)
class Minigame:
    id: str
    name: str
    description: str
    url: str
    glyph: str = "play"
    thumbnail: str = ""


GAMES = (Minigame("duel-of-fates", "Duel of Fates", "Um duelo de reflexos e estratégia, direto no seu navegador.",
                  "https://nicolasgrotto.github.io/duel-of-fates/", "duel"),)

PRESET_ICONS = {"play": "Jogo", "duel": "Duelo", "explore": "Exploração", "clock": "Tempo"}
MAX_NAME = 100
MAX_DESCRIPTION = 500
MAX_URL = 2048
THUMBNAIL_EDGE = 64
MAX_THUMBNAIL = 32 * 1024
MAX_IMAGE_BYTES = 16 * 1024 * 1024
MAX_IMAGE_PIXELS = 16 * 1024 * 1024
GAME_ID = re.compile(r"[a-f0-9]{32}")


def game_url(value):
    if not isinstance(value, str) or not value or len(value) > MAX_URL:
        raise ValueError(tr("Informe um endereço HTTPS válido, sem credenciais."))
    url = QUrl(value.strip(), QUrl.ParsingMode.StrictMode)
    if not url.isValid() or url.scheme() != "https" or not url.host().strip(".") or "@" in url.authority():
        raise ValueError(tr("Informe um endereço HTTPS válido, sem credenciais."))
    return url


def _field(value, limit, error, *, required=False):
    if not isinstance(value, str) or len(value) > limit or required and not value.strip():
        raise ValueError(error)
    return value.strip()


def validate_entries(entries):
    if not isinstance(entries, dict):
        raise ValueError(tr("Catálogo pessoal inválido."))
    for identifier, entry in entries.items():
        if not isinstance(identifier, str) or not GAME_ID.fullmatch(identifier) or not isinstance(entry, dict):
            raise ValueError(tr("Entrada de minigame inválida."))
        _field(entry.get("name"), MAX_NAME, tr("Informe um nome válido."), required=True)
        _field(entry.get("description", ""), MAX_DESCRIPTION, tr("Descrição inválida."))
        game_url(entry.get("url"))
        _field(entry.get("glyph", "play"), 24, tr("Ícone inválido."))
        _field(entry.get("thumbnail", ""), MAX_THUMBNAIL, tr("Miniatura inválida."))


def new_entry(name, url, description, glyph, thumbnail):
    return {
        "name": _field(name, MAX_NAME, tr("Informe o nome do minigame."), required=True),
        "url": game_url(url).toString(QUrl.ComponentFormattingOption.FullyEncoded),
        "description": _field(description, MAX_DESCRIPTION, tr("Descrição muito longa.")),
        "glyph": glyph,
        "thumbnail": thumbnail,
    }


def personal_games(document):
    return tuple(Minigame(identifier, entry["name"], entry.get("description", ""), entry["url"],
                          entry.get("glyph", "play"), entry.get("thumbnail", ""))
                 for identifier, entry in document["minigames"]["entries"].items())


def save_game(store, game, entry):
    key = game.id if game else uuid4().hex
    entries = store.data["minigames"]["entries"]
    if game is not None and key not in entries:
        raise ValueError(tr("O minigame foi removido. Abra o catálogo novamente."))
    if entry is None:
        del entries[key]
    else:
        entries[key] = entries.get(key, {}) | entry
    return store.save_minigames(entries)


def load_thumbnail(path):
    file = Path(path)
    try:
        with file.open("rb") as handle:
            contents = handle.read(MAX_IMAGE_BYTES + 1)
    except OSError as error:
        raise ValueError(tr("Não foi possível ler a imagem.")) from error
    if len(contents) > MAX_IMAGE_BYTES:
        raise ValueError(tr("Escolha uma imagem PNG ou JPEG de até 16 MiB."))
    if contents.startswith(b"\x89PNG\r\n\x1a\n"):
        image_format = b"png"
    elif contents.startswith(b"\xff\xd8\xff"):
        image_format = b"jpeg"
    else:
        raise ValueError(tr("A imagem deve estar no formato PNG ou JPEG."))
    data = QByteArray(contents)
    source = QBuffer(data)
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(source, image_format)
    reader.setAutoDetectImageFormat(False)
    size = reader.size()
    if not size.isValid():
        raise ValueError(tr("A imagem deve estar no formato PNG ou JPEG."))
    if size.width() * size.height() > MAX_IMAGE_PIXELS:
        raise ValueError(tr("A imagem excede o limite de 16 megapixels."))
    size.scale(QSize(THUMBNAIL_EDGE, THUMBNAIL_EDGE), Qt.AspectRatioMode.KeepAspectRatio)
    reader.setAutoTransform(True)
    reader.setScaledSize(size)
    image = reader.read().convertToFormat(QImage.Format.Format_ARGB32)
    output = QBuffer()
    output.open(QIODevice.OpenModeFlag.WriteOnly)
    if image.isNull() or not image.save(output, "PNG"):
        raise ValueError(tr("Não foi possível ler a imagem."))
    return b64encode(bytes(output.data())).decode("ascii")


def thumbnail_image(value):
    if not value or len(value) > MAX_THUMBNAIL:
        return QImage()
    try:
        data = QByteArray(b64decode(value, validate=True))
    except (ValueError, Base64Error):
        return QImage()
    source = QBuffer(data)
    source.open(QIODevice.OpenModeFlag.ReadOnly)
    reader = QImageReader(source, b"png")
    size = reader.size()
    if not size.isValid() or max(size.width(), size.height()) > THUMBNAIL_EDGE:
        return QImage()
    return reader.read()


def open_game(game_id, opener=None, games=GAMES):
    game = next((game for game in games if game.id == game_id), None)
    if game is None:
        raise ValueError(tr("Minigame desconhecido."))
    return (opener or QDesktopServices.openUrl)(game_url(game.url))
