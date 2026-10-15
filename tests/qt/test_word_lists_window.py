"""*Words to leave out* (W3.3 P10, n16: `app/qt/word_lists_window.py`) — the Ignore list and the Blacklist.

What a wrong answer would cost: the window's thread reading or writing a list (a freeze); ✕ taking off the wrong word,
or more than one; a dropped chip added anyway, or a word already on the list added again; the other language's list
changed from this one; a name taken off (it is the Ignore names setting's); a control with no tooltip or name.
"""
import json
import os
import threading

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app import path_utils
from app.qt import bridge, confirm, shell, windows
from app.qt import word_lists_strings as s
from app.qt.word_lists_window import SOURCE, WORD, WordListsWindow
from app.services import word_lists
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems


@pytest.fixture
def main(qapp):
    services = shell.Services()
    win = shell.open_window(qapp, services)
    win.show()
    yield win
    win.close()
    services.shutdown(0.5)
    # A list read or write still on the pool resolves its path when it runs, so left running it would land in the
    # next test's root (the PermissionError on IgnoreList.txt seen under load): every worker ends here.
    assert bridge.wait_for_workers(10000)


@pytest.fixture(autouse=True)
def _fresh_session():
    word_lists._BACKED_UP.clear()
    yield


@pytest.fixture
def calls(monkeypatch):
    """Every service call the window makes: (name, args, on the window's thread?)."""
    gui = threading.current_thread()
    seen = []
    for name in ("read", "add", "remove", "find_words"):
        real = getattr(word_lists, name)

        def record(*args, _real=real, _name=name, **kw):
            seen.append((_name, args, threading.current_thread() is gui))
            return _real(*args, **kw)
        monkeypatch.setattr(word_lists, name, record)
    return seen


def _put(text, kind="ignore", language="ja"):
    path = word_lists.list_path(kind, language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))
    return path


def _text(path):
    with open(path, "rb") as f:
        return f.read().decode("utf-8")


def _open(main):
    w = windows.show(main, "word-lists", WordListsWindow)
    assert wait_until(lambda: w.entries is not None)
    return w


def _rows(w):
    """The words as the list shows them (after the search)."""
    return [w.shown.index(i, 0).data(Qt.ItemDataRole.DisplayRole) for i in range(w.shown.rowCount())]


def _click_mark(w, row):
    """A click on row `row`'s ✕."""
    rect = w.list.visualRect(w.shown.index(row, 0))
    point = QPoint(rect.right() - rect.height() // 2, rect.center().y())
    QTest.mouseClick(w.list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, point)


def _chips(w):
    return [(w.chips.item(i).text(), w.chips.item(i).checkState() == Qt.CheckState.Checked,
             bool(w.chips.item(i).flags() & Qt.ItemFlag.ItemIsEnabled)) for i in range(w.chips.count())]


# --- the window, its controls --------------------------------------------------------------------------------------- #
def test_every_control_is_wired_tipped_and_named(main):
    w = _open(main)
    assert w.windowTitle() == "Words to leave out — Surasura"
    assert [b.text() for b in w.kind_buttons.values()] == ["Ignore list", "Blacklist"]
    assert w.kind_buttons["ignore"].isChecked() and not w.kind_buttons["blacklist"].isChecked()
    for field in (w.search, w.add_field, w.text, w.list, w.chips, w.kinds):
        assert field.accessibleName()
    for tipped in (w.list, w.chips, w.add_field):
        assert tipped.toolTip()
    found, walked = problems(w)
    assert walked >= 4 and found == []


def test_the_door_is_registered_and_opens_one_window(main):
    door = next(op for op in windows.OPENERS if op.name == "word-lists")
    assert door.label == s.WORD_LISTS_NAME and door.tip == s.WORD_LISTS_TIP
    first = windows.launch(main, door)
    assert isinstance(first, WordListsWindow) and first.isVisible()
    assert windows.launch(main, door) is first
    row = windows.launchers(main, main.page_widgets["settings"])
    assert row.buttons["word-lists"].text() == s.WORD_LISTS_NAME


def test_esc_closes_it_and_never_the_main_window(main):
    w = _open(main)
    QTest.keyClick(w, Qt.Key.Key_Escape)
    assert windows.opened(main, "word-lists") is None and main.isVisible()


def test_an_empty_list_says_how_to_fill_it(main):
    w = _open(main)
    assert _rows(w) == [] and w.status.text() == s.WORD_LISTS_EMPTY
    assert w.count.text() == s.WORD_LISTS_COUNT.format(n=0)


# --- the words, search and count ------------------------------------------------------------------------------------ #
def test_it_shows_the_lists_words_in_order_with_their_count(main):
    _put("# 無視する単語\n冒険\n\n毎日\nストレート\n")
    w = _open(main)
    assert _rows(w) == ["冒険", "毎日", "ストレート"]
    assert w.count.text() == s.WORD_LISTS_COUNT.format(n=3)


def test_the_search_shows_the_matching_words_and_says_how_many(main):
    _put("冒険\n冒険家\n毎日\n")
    w = _open(main)
    paints = w.list_paints
    w.search.setText("冒険")
    assert _rows(w) == ["冒険", "冒険家"]
    assert w.count.text() == s.WORD_LISTS_COUNT_SHOWN.format(shown=2, n=3)
    w.search.clear()
    assert len(_rows(w)) == 3 and w.list_paints == paints          # a search rebuilds nothing


def test_the_blacklist_tab_shows_the_blacklist(main):
    _put("冒険\n", "ignore")
    _put("# ja Blacklist\n毎日\n", "blacklist")
    w = _open(main)
    w.kind_buttons["blacklist"].click()
    assert wait_until(lambda: _rows(w) == ["毎日"])
    assert w.kind == "blacklist" and not w.kind_buttons["ignore"].isChecked()
    w.add_field.setText("準備")
    w.add_typed()
    assert wait_until(lambda: _rows(w) == ["毎日", "準備"])
    assert _text(word_lists.list_path("blacklist", "ja")) == "# ja Blacklist\n毎日\n準備\n"
    assert _text(word_lists.list_path("ignore", "ja")) == "冒険\n"  # the other list untouched


def test_reading_the_same_words_again_repaints_nothing(main):
    _put("冒険\n")
    w = _open(main)
    before = w.list_paints
    w.read()
    QTest.qWait(200)
    assert w.list_paints == before


# --- ✕ takes one word off ---------------------------------------------------------------------------------------------- #
def test_the_mark_takes_off_that_word_alone_on_a_worker(main, calls):
    path = _put("# 無視する単語\n冒険\n毎日\nストレート\n")
    w = _open(main)
    _click_mark(w, 1)
    assert wait_until(lambda: _rows(w) == ["冒険", "ストレート"])
    assert _text(path) == "# 無視する単語\n冒険\nストレート\n"
    removes = [c for c in calls if c[0] == "remove"]
    assert removes == [("remove", ("ignore", "ja", ["毎日"], "list"), False)]
    assert s.WORD_LISTS_REMOVED.format(words="毎日") in w.status.text()


def test_a_click_on_the_word_not_the_mark_takes_nothing_off(main, calls):
    path = _put("冒険\n毎日\n")
    w = _open(main)
    rect = w.list.visualRect(w.shown.index(0, 0))
    QTest.mouseClick(w.list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(rect.left() + 4, rect.center().y()))
    QTest.qWait(100)
    assert [c for c in calls if c[0] == "remove"] == [] and _text(path) == "冒険\n毎日\n"


def test_delete_takes_off_the_current_word(main):
    path = _put("冒険\n毎日\n")
    w = _open(main)
    w.list.setCurrentIndex(w.shown.index(0, 0))
    QTest.keyClick(w.list, Qt.Key.Key_Delete)
    assert wait_until(lambda: _rows(w) == ["毎日"])
    assert _text(path) == "毎日\n"


def test_backspace_takes_nothing_off(main, calls):
    # Backspace corrects a mistyped keyboard search in the list: it must never remove the current word.
    path = _put("冒険\n毎日\n")
    w = _open(main)
    w.list.setCurrentIndex(w.shown.index(0, 0))
    QTest.keyClick(w.list, Qt.Key.Key_Backspace)
    QTest.qWait(100)
    assert [c for c in calls if c[0] == "remove"] == [] and _text(path) == "冒険\n毎日\n"
    assert _card(w) is None


def test_a_list_line_is_taken_off_with_no_question(main, calls):
    # A list line comes back by adding it again: no confirmation in its way.
    _put("冒険\n毎日\n")
    w = _open(main)
    _click_mark(w, 0)
    assert _card(w) is None
    assert wait_until(lambda: _rows(w) == ["毎日"])


def _card(w):
    cards = [c for c in w.findChildren(confirm.Confirm) if c.isVisible()]
    return cards[0] if cards else None


@pytest.fixture
def known_file(ja_resources_dir):
    """The real Migaku export (46 IGNORED entries) as this language's KnownWord.json."""
    import shutil
    dst = os.path.join(path_utils.get_user_files_path("ja"), "KnownWord.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(os.path.join(ja_resources_dir, "KnownWord.json"), dst)
    return dst


def _known_row(w, word):
    """Search for `word`; -> the shown row of its known-words entry."""
    w.search.setText(word)
    for i in range(w.shown.rowCount()):
        index = w.shown.index(i, 0)
        if index.data(WORD) == word and index.data(SOURCE) == "known":
            return i
    raise AssertionError(f"no known-words row for {word}")


def _ignored(path, word):
    with open(path, "rb") as f:
        return any(e.get("dictForm") == word and e.get("knownStatus") == "IGNORED"
                   for e in json.loads(f.read().decode("utf-8"))["words"])


def test_a_known_words_row_is_taken_off_only_after_the_question(main, calls, known_file):
    # KnownWord.json's entry can't come back from here (adding puts the word on the Ignore list): Delete asks first,
    # in the window, Cancel the default; only Yes removes it, on a worker.
    w = _open(main)
    w.list.setCurrentIndex(w.shown.index(_known_row(w, "良い"), 0))
    QTest.keyClick(w.list, Qt.Key.Key_Delete)
    card = _card(w)
    assert card is not None and "良い" in card.title.text() and card.default is card.no
    QTest.qWait(100)
    assert [c for c in calls if c[0] == "remove"] == [] and _ignored(known_file, "良い")
    card.yes.click()
    # Waited on through the window (its read after the write), never by opening the file while it is replaced.
    assert wait_until(lambda: not w.busy() and w.entries is not None and ("良い", "known") not in w.entries)
    assert [c for c in calls if c[0] == "remove"] == [("remove", ("ignore", "ja", ["良い"], "known"), False)]
    assert not _ignored(known_file, "良い")


def test_no_on_the_known_words_question_changes_nothing(main, calls, known_file):
    with open(known_file, "rb") as f:
        old = f.read()
    w = _open(main)
    _click_mark(w, _known_row(w, "良い"))
    card = _card(w)
    assert card is not None
    QTest.keyClick(QApplication.focusWidget(), Qt.Key.Key_Escape)
    assert card.answer is False and w.isVisible()
    QTest.qWait(100)
    assert [c for c in calls if c[0] == "remove"] == []
    with open(known_file, "rb") as f:
        assert f.read() == old


def test_a_switch_with_the_known_words_question_open_drops_it(main, calls, known_file):
    # The question named a ja entry: once the window shows the Blacklist it is dropped, never answered.
    w = _open(main)
    _click_mark(w, _known_row(w, "良い"))
    card = _card(w)
    yes = card.yes
    w.show_kind("blacklist")
    assert _card(w) is None and w.question is None
    try:
        yes.click()
    except RuntimeError:
        pass
    QTest.qWait(100)
    assert [c for c in calls if c[0] == "remove"] == [] and _ignored(known_file, "良い")


def test_the_mark_on_a_searched_list_takes_off_the_word_shown(main):
    path = _put("冒険\n冒険家\n毎日\n")
    w = _open(main)
    w.search.setText("毎")
    _click_mark(w, 0)
    assert wait_until(lambda: _text(path) == "冒険\n冒険家\n")


def test_a_name_has_no_mark_and_is_never_taken_off(main, calls, monkeypatch):
    from app import token_index
    monkeypatch.setattr(token_index, "ignored_names", lambda language: ["スドウ"])
    w = _open(main)
    assert _rows(w) == [s.WORD_LISTS_MARK_NAMES.format(word="スドウ")]
    _click_mark(w, 0)
    QTest.qWait(100)
    assert [c for c in calls if c[0] == "remove"] == []


# --- the Add field ------------------------------------------------------------------------------------------------- #
def test_enter_in_the_add_field_adds_its_words(main, calls):
    path = _put("冒険\n")
    w = _open(main)
    w.add_field.setText("毎日 ストレート")
    QTest.keyClick(w.add_field, Qt.Key.Key_Return)
    assert wait_until(lambda: _rows(w) == ["冒険", "毎日", "ストレート"])
    assert _text(path) == "冒険\n毎日\nストレート\n" and w.add_field.text() == ""
    assert [c for c in calls if c[0] == "add"] == [("add", ("ignore", "ja", ["毎日", "ストレート"]), False)]


def test_a_word_already_there_is_said_and_not_added_again(main):
    path = _put("冒険\n")
    w = _open(main)
    w.add_field.setText("冒険")
    w.add_button.click()
    assert wait_until(lambda: s.WORD_LISTS_ALREADY.format(words="冒険") in w.status.text())
    assert _text(path) == "冒険\n"


# --- Paste text -> chips -> Add N words ------------------------------------------------------------------------------ #
def test_pasted_text_becomes_chips_and_only_the_kept_ones_are_added(main, calls):
    path = _put("冒険\n")
    w = _open(main)
    w.paste_button.click()
    assert w.text.isVisible() and w.find_button.isVisible()
    w.text.setPlainText("冒険の準備で灯台の砂時計を見た。")
    w.find_button.click()
    assert wait_until(lambda: w.candidates is not None, 60)   # the paste's child process
    chips = _chips(w)
    assert ("冒険", True, False) in chips                           # on the list already: shown, fixed
    assert ("灯台", True, True) in chips and ("砂時計", True, True) in chips
    assert ("見る", True, True) in chips                            # 見た, by its dictionary form
    assert w.add_kept_button.isVisible()
    for i in range(w.chips.count()):                               # drop all but 灯台
        item = w.chips.item(i)
        if item.flags() & Qt.ItemFlag.ItemIsEnabled and item.text() != "灯台":
            item.setCheckState(Qt.CheckState.Unchecked)
    assert w.add_kept_button.text() == s.WORD_LISTS_ADD_KEPT_ONE
    w.add_kept_button.click()
    assert wait_until(lambda: _rows(w) == ["冒険", "灯台"])
    assert _text(path) == "冒険\n灯台\n"
    assert [c[1] for c in calls if c[0] == "add"] == [("ignore", "ja", ["灯台"])]
    assert not any(gui for _n, _a, gui in calls)                  # every read, find and write on a worker
    assert {n for n, _a, _g in calls} == {"read", "find_words", "add"}


def test_a_chip_adds_the_words_dictionary_form_shown_by_its_spelling(main):
    path = _put("")
    w = _open(main)
    w.paste_button.click()
    w.text.setPlainText("彼は毎日冒険に出かけます。")
    w.find_button.click()
    assert wait_until(lambda: w.candidates is not None, 60)   # the paste's child process
    for i in range(w.chips.count()):
        item = w.chips.item(i)
        item.setCheckState(Qt.CheckState.Checked if item.text() == "出かける" else Qt.CheckState.Unchecked)
    w.add_kept_button.click()
    assert wait_until(lambda: "出掛ける" in _text(path), 20)          # a worker’s write, under a loaded machine
    assert _text(path) == "出掛ける\n"                             # the lemma, the identity the list compares


def test_a_known_word_comes_as_a_dropped_chip(main, ja_resources_dir):
    import shutil
    dst = os.path.join(path_utils.get_user_files_path("ja"), "KnownWord.json")
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(os.path.join(ja_resources_dir, "KnownWord.json"), dst)
    w = _open(main)
    w.paste_button.click()
    w.text.setPlainText("準備と砂時計")
    w.find_button.click()
    assert wait_until(lambda: w.candidates is not None, 60)   # the paste's child process
    assert ("準備", False, True) in _chips(w) and ("砂時計", True, True) in _chips(w)
    assert w.add_kept_button.text() == s.WORD_LISTS_ADD_KEPT_ONE


def test_text_with_no_words_says_so(main):
    w = _open(main)
    w.paste_button.click()
    w.text.setPlainText("。、！？")
    w.find_button.click()
    assert wait_until(lambda: w.candidates is not None, 60)   # the paste's child process
    assert w.candidates == [] and w.status.text() == s.WORD_LISTS_FOUND_NONE
    assert not w.add_kept_button.isVisible()


# --- the language --------------------------------------------------------------------------------------------------- #
def test_the_window_follows_the_main_windows_language_and_drops_the_chips(main):
    _put("冒険\n", "ignore", "ja")
    _put("东西\n", "ignore", "zh")
    w = _open(main)
    w.paste_button.click()
    w.text.setPlainText("冒険")
    w.find_button.click()
    assert wait_until(lambda: w.candidates is not None, 60)   # the paste's child process
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: _rows(w) == ["东西"])
    assert w.language == "zh" and w.candidates is None and not w.add_kept_button.isVisible()


def test_a_write_the_window_closed_on_still_says_its_line_in_the_bar(main):
    path = _put("冒険\n")
    w = _open(main)
    w.add_field.setText("毎日")
    w.add_typed()
    w.close()
    assert wait_until(lambda: main.bar_line.full() == s.WORD_LISTS_ADDED.format(words="毎日")
                      + " · " + s.WORD_LISTS_BACKUP)
    assert _text(path) == "冒険\n毎日\n"


def test_an_unreadable_list_shows_its_words_and_says_it_cant_be_changed(main):
    path = word_lists.list_path("ignore", "ja")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    damaged = "冒険\n".encode("utf-8") + b"\xa0\x80\n"
    with open(path, "wb") as f:
        f.write(damaged)
    w = _open(main)
    assert _rows(w)[0] == "冒険" and "can't be read" in w.status.text()
    _click_mark(w, 0)
    assert wait_until(lambda: not w.busy() and "can't be read" in w.status.text())
    with open(path, "rb") as f:
        assert f.read() == damaged
    QApplication.processEvents()
