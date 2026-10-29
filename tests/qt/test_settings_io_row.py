"""Settings › App › *Your settings* (alpha 6, Mattias's note 8; `app/qt/settings_io.py`) and the *Needs you* card an
imported video folder that isn't on this PC becomes (`app/qt/needs.py`, SI-3).

What a wrong answer would cost: an import that replaces the settings before it asks, or asks twice; a refused file that
asks anyway (or says nothing); a restart that stops a running Generate (B2-3); a Yes that doesn't restart, leaving the
window on the old settings; a missing folder that breaks Connect quietly, or a *Find it…* that writes nothing.

The page is the real `SettingsPage` over `test_settings_page`'s settings recorder; the service is the real one over the
test root's settings.json (a learner's real 3.0 settings from tests/Test Resources/settings/); the window for *Needs
you* is `test_needs_gone_folder`'s.
"""
import json
import os
from types import SimpleNamespace

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtWidgets import QApplication

from app import path_utils, settings_manager
from app.qt import settings_catalog as catalog
from app.qt import settings_io as row_io
from app.qt import settings_page as sp
from app.qt import settings_strings as S
from app.qt import strings
from app.services import needs as service
from app.services import settings_io
from tests.qt.conftest import wait_until
from tests.qt.test_needs_gone_folder import world  # noqa: F401  (the fixture)
from tests.qt.test_settings_page import ALL_ON, EVERYTHING, Recorder
from tests.qt.test_settings_store import Bar

RESOURCES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Test Resources", "settings")


def _learner():
    with open(os.path.join(RESOURCES, "settings_ja_learner.json"), encoding="utf-8") as f:
        return json.load(f)


def _install(settings):
    with open(path_utils.get_settings_path(), "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=4)


def _file():
    with open(path_utils.get_settings_path(), encoding="utf-8") as f:
        return json.load(f)


def make():
    store = Recorder(dict({"target_language": "ja"}, **ALL_ON))
    shell = SimpleNamespace(services=SimpleNamespace(settings=store), bar_line=Bar(), restarts=[],
                            generating=lambda: False)
    shell.restart = lambda: shell.restarts.append(True)
    page = sp.SettingsPage(shell, "ja", found=EVERYTHING)
    rows = row_io.attach(page)
    page.resize(1100, 700)
    page.show()
    assert wait_until(lambda: page.built, 20)
    QApplication.processEvents()
    return page, rows, shell


def _close(page):
    page.close()
    page.deleteLater()
    QApplication.processEvents()


@pytest.fixture
def exported(tmp_path):
    """A learner's settings exported to a non-ASCII folder; the settings now another's (a different PC's)."""
    folder = tmp_path / "設定 バックアップ"
    folder.mkdir()
    out = str(folder / "Surasura settings.json")
    _install(_learner())
    assert settings_io.export(out).ok
    _install({"target_language": "ja", "words_per_day": 2})
    return out


def test_the_row_sits_in_app_with_two_buttons_each_with_its_tooltip(qapp):
    page, rows, _shell = make()
    try:
        assert catalog.ROW["settings_file"].section == "app"
        slot = page.custom_row("settings_file").layout()
        assert slot.indexOf(rows.export) >= 0 and slot.indexOf(rows.import_) >= 0
        assert rows.export.text() == "Export settings…" and rows.import_.text() == "Import settings…"
        assert rows.export.toolTip() == S.SETTINGS_EXPORT_TIP and rows.import_.toolTip() == S.SETTINGS_IMPORT_TIP
    finally:
        _close(page)


def test_export_saves_the_file_named_for_today_and_the_bar_says_where(qapp, tmp_path):
    page, rows, shell = make()
    try:
        asked = []
        target = str(tmp_path / "Mattias")
        rows.save_as = lambda title, name: (asked.append((title, name)), target)[1]
        _install(_learner())
        rows.export_settings()
        assert wait_until(lambda: shell.bar_line.lines, 10)
        assert asked == [(S.SETTINGS_EXPORT_TITLE, settings_io.default_name())]
        assert os.path.isfile(target + ".json")                   # .json added
        assert shell.bar_line.lines == [f"Settings saved to {os.path.normpath(target + '.json')}"]
    finally:
        _close(page)


def test_export_cancelled_writes_nothing(qapp, tmp_path):
    page, rows, shell = make()
    try:
        rows.save_as = lambda title, name: ""
        assert rows.export_settings() is None and shell.bar_line.lines == []
    finally:
        _close(page)


def test_import_asks_once_before_anything_is_replaced_and_yes_replaces_then_restarts(qapp, exported):
    page, rows, shell = make()
    try:
        rows.open_file = lambda title: exported
        rows.import_settings()
        assert wait_until(lambda: rows.asking is not None, 10)
        card = rows.asking
        assert card.title.text() == "Replace your settings?"
        assert "nothing is mixed in" in card.body.text() and "restarts" in card.body.text()
        assert card.yes.text() == "Import and restart" and card.no.text() == S.SETTINGS_IMPORT_NO
        assert card.yes.toolTip() and card.no.toolTip()
        assert _file() == {"target_language": "ja", "words_per_day": 2}     # nothing before the answer
        card.yes.click()
        assert wait_until(lambda: shell.restarts, 10)
        assert shell.restarts == [True]
        assert _file()["words_per_day"] == 12 and _file()["anki_sync_decks"] == {"ja": ["日本語::採掘", "日本語::アニメ"]}
        assert shell.bar_line.lines[-1].startswith("Settings imported. Your settings before are in ")
    finally:
        _close(page)


@pytest.mark.parametrize("how", ["cancel", "esc"])
def test_cancel_or_esc_replaces_nothing_and_restarts_nothing(qapp, exported, how):
    page, rows, shell = make()
    try:
        rows.open_file = lambda title: exported
        rows.import_settings()
        assert wait_until(lambda: rows.asking is not None, 10)
        if how == "cancel":
            rows.asking.no.click()
        else:
            rows.asking.close()
        for _ in range(5):
            QApplication.processEvents()
        assert _file() == {"target_language": "ja", "words_per_day": 2} and shell.restarts == []
        trash = os.path.join(os.path.dirname(path_utils.get_settings_path()), ".trash")
        assert not os.path.isdir(trash) or os.listdir(trash) == []
    finally:
        _close(page)


def test_a_newer_file_is_refused_in_the_bar_and_nothing_is_asked(qapp, tmp_path, monkeypatch):
    monkeypatch.setattr(settings_io, "app_version", lambda: "2.9.0.6")
    path = tmp_path / "newer.json"
    path.write_text(json.dumps({settings_io.MARK: 1, "version": "2.9.0.7", "settings": {}}), encoding="utf-8")
    page, rows, shell = make()
    try:
        rows.open_file = lambda title: str(path)
        rows.import_settings()
        assert wait_until(lambda: shell.bar_line.lines, 10)
        assert rows.asking is None and shell.restarts == []
        assert shell.bar_line.lines == ["These settings come from Surasura 2.9.0.7, newer than this one (2.9.0.6). "
                                        "Update Surasura first, then import them."]
    finally:
        _close(page)


def test_B2_3_no_import_while_a_generate_runs_before_the_picker_or_at_the_answer(qapp, exported):
    page, rows, shell = make()
    try:
        running = [True]
        shell.generating = lambda: running[0]
        picked = []
        rows.open_file = lambda title: (picked.append(title), exported)[1]
        rows.import_settings()
        assert picked == [] and shell.bar_line.lines == [S.SETTINGS_IMPORT_AFTER_GENERATE]
        running[0] = False
        rows.import_settings()
        assert wait_until(lambda: rows.asking is not None, 10)
        running[0] = True                                          # a Generate started while the card was open
        rows.asking.yes.click()
        for _ in range(5):
            QApplication.processEvents()
        assert _file() == {"target_language": "ja", "words_per_day": 2} and shell.restarts == []
        assert shell.bar_line.lines[-1] == S.SETTINGS_IMPORT_AFTER_GENERATE
    finally:
        _close(page)


def test_a_shell_that_cant_restart_says_restart_to_apply(qapp, exported):
    page, rows, shell = make()
    try:
        del shell.restart
        rows.open_file = lambda title: exported
        rows.import_settings()
        assert wait_until(lambda: rows.asking is not None, 10)
        rows.asking.yes.click()
        assert wait_until(lambda: strings.RESTART_TO_APPLY in shell.bar_line.lines, 10)
        assert _file()["words_per_day"] == 12
    finally:
        _close(page)


# --- Needs you: an imported folder not on this PC ------------------------------------------------------------------ #
GONE = "Z:\\アニメ\\字幕と動画"


def _imported_gone(here):
    settings_manager.save_keys({"connect_video_folders": {"ja": [str(here), GONE], "zh": []}})
    with open(settings_io.record_path(), "w", encoding="utf-8") as f:
        json.dump({"version": 1, "folders": [GONE]}, f, ensure_ascii=False)


def _card(ny):
    return next((e for e in ny.entries if e.kind == service.SETTINGS_FOLDER), None)


def _button(ny, key, action):
    return next((b for b in ny.cards.buttons(key) if b.property("action") == action), None)


@pytest.mark.parametrize("answer", ["find", "drop"])
def test_an_imported_folder_not_here_is_a_needs_you_card_and_each_answer_writes_the_setting(world, tmp_path,  # noqa
                                                                                            answer):
    here = tmp_path / "動画"
    here.mkdir()
    found = tmp_path / "新しい 動画"
    found.mkdir()
    _imported_gone(here)                                           # imported before this start (the restart's)
    seed, win, _writer, ny = world("ja")
    ny.refresh()
    assert wait_until(lambda: _card(ny) is not None, 10)
    card = _card(ny)
    assert GONE in card.title
    win.show_tab("needs")
    action = "find_settings_folder" if answer == "find" else "drop_settings_folder"
    assert wait_until(lambda: _button(ny, card.key, action) is not None, 5)
    ny.pick_folder = lambda title, start: str(found)
    _button(ny, card.key, action).click()
    folders = win.services.settings.get()["connect_video_folders"]
    assert list(folders["ja"]) == ([str(here), str(found)] if answer == "find" else [str(here)])
    assert wait_until(lambda: _card(ny) is None, 10)
    win.services.settings.flush(5)
    on_disk = settings_manager.load_settings()["connect_video_folders"]["ja"]
    assert on_disk == list(folders["ja"])


def test_find_it_cancelled_writes_nothing_and_the_card_stays(world, tmp_path):  # noqa: F811
    here = tmp_path / "動画"
    here.mkdir()
    _imported_gone(here)                                           # imported before this start (the restart's)
    seed, win, _writer, ny = world("ja")
    ny.refresh()
    assert wait_until(lambda: _card(ny) is not None, 10)
    card = _card(ny)
    win.show_tab("needs")
    assert wait_until(lambda: _button(ny, card.key, "find_settings_folder") is not None, 5)
    before = win.services.settings.pending()
    ny.pick_folder = lambda title, start: ""
    _button(ny, card.key, "find_settings_folder").click()
    assert win.services.settings.pending() == before and _card(ny) is not None
