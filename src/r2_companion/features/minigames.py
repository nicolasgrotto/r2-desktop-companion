from dataclasses import dataclass

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices


@dataclass(frozen=True)
class Minigame:
    id: str
    name: str
    description: str
    url: str
    glyph: str = "play"


GAMES = (Minigame("duel-of-fates", "Duel of Fates", "Um duelo de reflexos e estratégia, direto no seu navegador.",
                  "https://nicolasgrotto.github.io/duel-of-fates/", "duel"),)


def open_game(game_id, opener=None, games=GAMES):
    game = next((game for game in games if game.id == game_id), None)
    if game is None:
        raise ValueError("Minigame desconhecido.")
    url = QUrl(game.url)
    if not url.isValid() or url.scheme() != "https" or not url.host() or url.userInfo():
        raise ValueError("Endereço do minigame inválido.")
    return (opener or QDesktopServices.openUrl)(url)
