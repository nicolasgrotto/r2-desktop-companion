import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAccessible, QDesktopServices, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialogButtonBox, QMessageBox

from r2_companion.features.minigames import GAMES, game_url, load_thumbnail, new_entry, open_game, personal_games, save_game, thumbnail_image
from r2_companion.services.companion_state import CompanionStateStore, validate_document
from r2_companion.services.storage import ConfigStore
from r2_companion.ui.minigames import GameEditor, MinigamesPage, game_icon
from test_context_v03 import pet
from test_focus_ui import tab_to
from test_data_transfer import wait_for_backups


@pytest.mark.parametrize("url", ["example.org", "https://", "http://example.org", "https://user:pass@example.org",
                                 "https://@example.org", "file:///C:/game.exe", "https://example.org/a%xx"])
def test_game_url_requires_valid_https_without_credentials(url):
    with pytest.raises(ValueError, match="HTTPS"):
        game_url(url)


def test_exploration_icon_differs_from_game_icon(qapp):
    play = game_icon("play", "").pixmap(48, 48).toImage()
    compass = game_icon("explore", "").pixmap(48, 48).toImage()
    assert not compass.isNull() and compass != play


@pytest.fixture
def catalog(qapp, tmp_path):
    config = ConfigStore(tmp_path)
    assert config.acquire()
    config.load()
    state = CompanionStateStore(config)
    yield state
    state.close()
    config.close()


def test_preset_custom_image_restart_and_atomic_failure(catalog, tmp_path, monkeypatch):
    assert validate_document({"schema_version": 1})["minigames"]["entries"] == {}
    page = MinigamesPage(store=catalog)
    path = tmp_path / "own.png"
    image = QImage(160, 120, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.red)
    assert image.save(str(path))
    jpeg = tmp_path / "own.jpg"
    assert image.save(str(jpeg))
    assert not thumbnail_image(load_thumbnail(jpeg)).isNull()
    thumb = load_thumbnail(path)
    path.unlink()
    assert thumbnail_image(thumb).size().width() == 64
    invalid = tmp_path / "bad.jpg"
    invalid.write_bytes(b"bad image")
    with pytest.raises(ValueError, match="PNG ou JPEG"):
        load_thumbnail(invalid)
    assert thumbnail_image("invalid").isNull()
    address = "https://example.org/play?mode=web&difficulty=2#round"
    first = new_entry("Reflexos", address, "", "duel", thumb)
    second = new_entry("Memória", address, "Descrição", "clock", "")
    assert save_game(catalog, None, first)
    assert save_game(catalog, None, second)
    game1, game2 = page.personal
    assert game1.id != game2.id and page.games[0] == GAMES[0]
    calls = []
    assert not open_game(game1.id, lambda url: calls.append(url.toString()) or False, page.games)
    assert calls == [address]
    assert save_game(catalog, game1, first | {"name": "Editado"})
    assert page.personal[0].id == game1.id
    backup = catalog.read_document_file(catalog.backup)["minigames"]["entries"][game1.id]
    assert backup["name"] == "Reflexos" and backup["thumbnail"] == thumb
    reopened = CompanionStateStore(catalog.config_store)
    assert reopened.data["minigames"] == catalog.data["minigames"]
    assert not thumbnail_image(personal_games(reopened.data)[0].thumbnail).isNull()
    reopened.close()

    before = catalog.path.read_bytes()
    monkeypatch.setattr(ConfigStore, "atomic_write", lambda *args: (_ for _ in ()).throw(OSError()))
    assert not save_game(catalog, game2, None)
    assert page.personal[1] == game2 and catalog.path.read_bytes() == before
    monkeypatch.setattr(catalog.config_store, "read_only", True)
    page.refresh()
    assert not page.add_game.isEnabled() and "somente leitura" in page.feedback.text()
    page.close()


def test_catalog_keyboard_save_cancel_remove_and_restore_at_three_scales(pet, qapp, monkeypatch):
    pet.show_tools_page("minigames")
    assert QTest.qWaitForWindowActive(pet.tools)
    page = pet.tools.minigames_page
    state = pet.companion_state
    for scale in (100, 125, 150):
        state.update("accessibility", {"ui_scale": scale})
        assert page.add_game.isVisible() and page.add_game.isEnabled()
        assert page.add_game.isVisibleTo(pet.tools)
        tab_to(qapp, pet.tools, page.add_game)
        assert QAccessible.queryAccessibleInterface(page.add_game).text(QAccessible.Text.Name) == "Adicionar minigame"

    def fill():
        editor = qapp.activeModalWidget()
        assert isinstance(editor, GameEditor)
        QTimer.singleShot(9000, editor.reject)
        assert QTest.qWaitForWindowActive(editor)
        editor.name.setFocus()
        QTest.keyClicks(editor.name, "Jogo de teste")
        tab_to(qapp, editor, editor.url)
        QTest.keyClicks(editor.url, "https://example.org/game?round=1")
        tab_to(qapp, editor, editor.icons)
        QTest.keyClick(editor.icons, Qt.Key.Key_End)
        save = editor.buttons.button(QDialogButtonBox.StandardButton.Save)
        tab_to(qapp, editor, save)
        QTest.keyClick(save, Qt.Key.Key_Space)

    QTimer.singleShot(0, fill)
    QTest.keyClick(page.add_game, Qt.Key.Key_Space)
    assert QTest.qWaitForWindowActive(pet.tools)
    qapp.processEvents()
    created, = page.personal
    assert created.name == "Jogo de teste" and created.glyph == "clock"
    urls = []

    def capture(url):
        urls.append(url.toString())
        return True

    with monkeypatch.context() as session:
        session.setattr(QDesktopServices, "openUrl", staticmethod(capture))
        play = next(button for button in page.findChildren(type(page.add_game))
                    if button.isVisible() and button.accessibleName() == "Jogar Jogo de teste no navegador")
        tab_to(qapp, pet.tools, play)
        QTest.keyClick(play, Qt.Key.Key_Space)
        assert urls == ["https://example.org/game?round=1"]
    edit = next(button for button in page.findChildren(type(page.add_game))
                if button.isVisible() and button.accessibleName() == "Editar Jogo de teste")
    tab_to(qapp, pet.tools, edit)

    def cancel():
        editor = qapp.activeModalWidget()
        assert isinstance(editor, GameEditor)
        QTimer.singleShot(9000, editor.reject)
        assert QTest.qWaitForWindowActive(editor)
        editor.name.setText("Rascunho")
        QTest.keyClick(editor, Qt.Key.Key_Escape)

    QTimer.singleShot(0, cancel)
    QTest.keyClick(edit, Qt.Key.Key_Space)
    assert QTest.qWaitForWindowActive(pet.tools)
    assert page.personal == (created,)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *args, **kwargs: QMessageBox.StandardButton.Yes))
    remove = next(button for button in page.findChildren(type(page.add_game))
                  if button.isVisible() and button.accessibleName() == "Remover Jogo de teste")
    tab_to(qapp, pet.tools, remove)
    QTest.keyClick(remove, Qt.Key.Key_Space)
    assert page.games == GAMES
    data_page = pet.tools.pages["data"]
    data_page.restore("companion_state")
    wait_for_backups(data_page)
    assert page.personal == (created,)
    assert state.data["minigames"]["entries"][created.id]["url"].endswith("?round=1")
