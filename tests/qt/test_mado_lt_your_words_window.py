"""*Your words*' Known tab (Mado-LT 4; `app/qt/word_lists_window.py`): every word you know, newest first, its reading
and where it came from, and its ✓ that makes it Still learning — with the ○ that puts it back.

What a wrong answer would cost a learner: the window opening on a list they didn't ask for; a click on ✓ that waits for
the disk before anything shows (a press must react at once); the wrong word made Still learning, or every row painted
again for one; an Undo that can't find its word; a refusal that leaves the row lying (○ shown, the word still known);
the file touched from the window's thread (a freeze); the other language's words; a control with no tooltip or name.
"""
import json
import os
import shutil

import pytest

pytest.importorskip("PyQt6")
from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtTest import QTest

from app import anki_sync, path_utils
from app.qt import windows
from app.qt import word_lists_strings as s
from app.qt.word_lists_window import FIND, KNOWN_ROW, SOURCE, WORD, WordListsWindow, _RemoveDelegate
from app.services import word_lists, word_marks
from tests.qt.conftest import wait_until
from tests.qt.test_wiring import problems
from tests.qt.test_word_lists_window import _fresh_session, main  # noqa: F401


def _write(language, words):
    path = os.path.join(path_utils.get_user_files_path(language), "KnownWord.json")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"source": "test", "words": words}, f, ensure_ascii=False)
    return path


def _entry(word, source, created, reading="", language="ja", has_card=1):
    return {"dictForm": word, "secondary": reading, "partOfSpeech": "", "language": language, "knownStatus": "KNOWN",
            "hasCard": has_card, "tracked": 0, "created": created, "mod": created, "isModern": 1, "source": source}


JA = [_entry("看板", anki_sync.SOURCE, "2026-11-20T09:15:00", "かんばん"),
      _entry("提灯", anki_sync.MARKED_SOURCE, "2026-11-21T18:02:11", "ちょうちん", has_card=0),
      _entry("コツン", None, 0, "こつん", has_card=0),
      _entry("灯台", anki_sync.SOURCE, "2026-11-22T07:00:00", "とうだい")]


def _open(main):
    w = windows.show(main, "word-lists", WordListsWindow)
    assert wait_until(lambda: w.entries is not None)
    return w


def _shown(w):
    return [(w.shown.index(i, 0).data(WORD), w.shown.index(i, 0).data(SOURCE)) for i in range(w.shown.rowCount())]


def _row(w, word):
    return next(i for i in range(w.shown.rowCount()) if w.shown.index(i, 0).data(WORD) == word)


def _click_mark(w, word):
    rect = w.list.visualRect(w.shown.index(_row(w, word), 0))
    QTest.mouseClick(w.list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier,
                     QPoint(rect.right() - rect.height() // 2, rect.center().y()))


def _changes(w):
    seen = {"data": [], "reset": 0, "rows": 0}
    w.model.dataChanged.connect(lambda a, b, _roles=(): seen["data"].append((a.row(), b.row())))
    w.model.modelReset.connect(lambda: seen.__setitem__("reset", seen["reset"] + 1))
    w.model.rowsInserted.connect(lambda *_a: seen.__setitem__("rows", seen["rows"] + 1))
    w.model.rowsRemoved.connect(lambda *_a: seen.__setitem__("rows", seen["rows"] + 1))
    return seen


# --- what it shows ------------------------------------------------------------------------------------------------ #
def test_it_opens_on_known_every_word_newest_first_with_its_reading_and_where_it_came_from(main):
    _write("ja", JA)
    w = _open(main)
    assert w.kind == "known" and w.kind_buttons["known"].isChecked()
    assert [b.text() for b in w.kind_buttons.values()] == ["Known", "Ignore"]
    assert _shown(w) == [("灯台", "known"), ("提灯", "known"), ("看板", "known"), ("コツン", "known")]
    texts = [w.shown.index(i, 0).data(Qt.ItemDataRole.DisplayRole) for i in range(4)]
    assert texts == ["灯台   とうだい   · Anki card", "提灯   ちょうちん   · marked in Surasura",
                     "看板   かんばん   · Anki card", "コツン   · imported"]          # a word in kana: no reading
    tips = [w.shown.index(i, 0).data(Qt.ItemDataRole.ToolTipRole) for i in range(4)]
    assert tips[2] == "看板: known since 20 Nov 2026\n• Click ✓: still learning"
    assert tips[3] == "コツン: known (no date kept)\n• Click ✓: still learning"
    assert w.count.text() == "4 words"
    assert w.list.toolTip() == s.WORD_LISTS_LIST_TIPS["known"]
    found, walked = problems(w)
    assert walked >= 4 and found == []


def test_the_search_finds_a_word_by_its_reading_too(main):
    _write("ja", JA)
    w = _open(main)
    w.search.setText("ちょうちん")
    assert _shown(w) == [("提灯", "known")] and w.count.text() == "1 of 4 words"
    w.search.setText("灯")
    assert [word for word, _s in _shown(w)] == ["灯台", "提灯"]


def test_each_rows_mark_is_a_lit_check_or_a_violet_circle_never_the_ignore_tabs_cross(main):
    _write("ja", JA)
    assert not word_marks.apply("ja", [("看板", "learning")]).error
    w = _open(main)
    assert dict(_shown(w))["看板"] == "learning"
    delegate = w.list.itemDelegate()
    assert isinstance(delegate, _RemoveDelegate)
    for word, ink in (("灯台", "accent"), ("看板", "accent-2")):
        index = w.shown.index(_row(w, word), 0)
        assert index.data(KNOWN_ROW) is True
        assert delegate.mark_glyph(index) == {"accent": "✓", "accent-2": "○"}[ink]
        from PyQt6.QtWidgets import QStyleOptionViewItem
        from app.qt import style
        assert delegate.mark_colour(QStyleOptionViewItem(), index) == style.qcolor(style.colours()[ink])
    assert w.shown.index(_row(w, "看板"), 0).data(Qt.ItemDataRole.ToolTipRole) == \
        "看板: still learning\n• Click ○: known again"
    from PyQt6.QtGui import QStandardItemModel                              # (Mado-LT 5) an Ignore tab's row: ✕
    from app.qt.word_lists_window import _item
    ignore = QStandardItemModel()
    ignore.appendRow(_item("冒険", "list"))
    assert delegate.mark_glyph(ignore.index(0, 0)) == s.WORD_LISTS_REMOVE_MARK


# --- ✓ → Still learning, ○ → back ------------------------------------------------------------------------------- #
@pytest.mark.parametrize("by", ["click", "delete"])
def test_the_lit_check_makes_the_word_still_learning_at_once_and_its_circle_undoes_it(main, monkeypatch, by):
    """✓ (or Delete on the row): the ○ shows before the worker answers, the write is `mark_words([(word,
    "learning")])` on a worker, only that row changes; the file's Anki entry is kept, turned not known. Then ○: that
    write undone by its own id — the word known again, the file's entry known again."""
    path = _write("ja", JA)
    w = _open(main)
    seen = _changes(w)
    calls = []
    real_mark, real_undo = main.services.mark_words, main.services.undo_marks
    import threading
    gui = threading.current_thread()

    def mark(language, marks):
        calls.append(("mark", language, list(marks), threading.current_thread() is gui))
        return real_mark(language, marks)

    def undo(language, undo_id=None):
        calls.append(("undo", language, undo_id, threading.current_thread() is gui))
        return real_undo(language, undo_id)
    monkeypatch.setattr(main.services, "mark_words", mark)
    monkeypatch.setattr(main.services, "undo_marks", undo)
    if by == "click":
        _click_mark(w, "看板")
    else:
        w.list.setCurrentIndex(w.shown.index(_row(w, "看板"), 0))
        QTest.keyClick(w.list, Qt.Key.Key_Delete)
    assert dict(_shown(w))["看板"] == "learning"                          # at once, before the answer
    assert wait_until(lambda: not w.busy() and calls)
    assert calls == [("mark", "ja", [("看板", "learning")], False)]
    assert wait_until(lambda: w.status.text() == "看板: still learning · its ○ puts it back")
    assert "看板" in word_marks.learning("ja") and "看板" in w.cleared
    with open(path, encoding="utf-8") as f:
        kept = [e for e in json.load(f)["words"] if e["dictForm"] == "看板"]
    assert len(kept) == 1 and not anki_sync._is_known(kept[0])              # kept, turned not known
    assert seen["reset"] == 0 and seen["rows"] == 0 and {r for pair in seen["data"] for r in pair} == {2}
    _click_mark(w, "看板")
    assert dict(_shown(w))["看板"] == "known"                              # at once
    assert wait_until(lambda: not w.busy() and len(calls) == 2)
    assert calls[1][0] == "undo" and calls[1][2] is not None and calls[1][3] is False
    assert wait_until(lambda: w.status.text() == "看板: known again")
    assert "看板" not in word_marks.learning("ja") and "看板" not in w.cleared
    with open(path, encoding="utf-8") as f:
        assert anki_sync._is_known(next(e for e in json.load(f)["words"] if e["dictForm"] == "看板"))
    assert seen["reset"] == 0 and seen["rows"] == 0


def test_a_word_still_learning_from_before_is_known_again_by_its_circle(main):
    """Still learning from an earlier session (no Undo held here): ○ marks it Known (the word card's rule)."""
    _write("ja", JA)
    assert not word_marks.apply("ja", [("看板", "learning")]).error
    w = _open(main)
    assert dict(_shown(w))["看板"] == "learning" and w.cleared == {}
    _click_mark(w, "看板")
    assert dict(_shown(w))["看板"] == "known"
    assert wait_until(lambda: not w.busy() and w.status.text() == "看板: known again")
    assert "看板" not in word_marks.learning("ja")


def test_a_refused_write_puts_the_row_back_and_says_why(main, monkeypatch):
    _write("ja", JA)
    w = _open(main)
    monkeypatch.setattr(main.services, "mark_words",
                        lambda language, marks: word_marks.Marked(error="KnownWord.json is held by another program"))
    _click_mark(w, "灯台")
    assert wait_until(lambda: not w.busy() and "held by another program" in w.status.text())
    assert dict(_shown(w))["灯台"] == "known" and "灯台" not in w.cleared
    assert w.status.text() == "Nothing was changed: KnownWord.json is held by another program"


def test_a_write_that_breaks_puts_the_row_back_too(main, monkeypatch):
    _write("ja", JA)
    w = _open(main)

    def broken(language, marks):
        raise OSError("disk gone")
    monkeypatch.setattr(main.services, "mark_words", broken)
    _click_mark(w, "灯台")
    assert wait_until(lambda: not w.busy() and "disk gone" in w.status.text())
    assert dict(_shown(w))["灯台"] == "known"


def test_a_click_while_a_write_runs_does_nothing(main, monkeypatch):
    """One write at a time (the window's rule): a second ✓ while the first is on its way changes no row."""
    import threading
    _write("ja", JA)
    w = _open(main)
    gate = threading.Event()
    real = main.services.mark_words

    def slow(language, marks):
        gate.wait(5)
        return real(language, marks)
    monkeypatch.setattr(main.services, "mark_words", slow)
    _click_mark(w, "灯台")
    assert w.busy()
    _click_mark(w, "提灯")
    assert dict(_shown(w))["提灯"] == "known"
    gate.set()
    assert wait_until(lambda: not w.busy())
    assert dict(_shown(w))["灯台"] == "learning" and dict(_shown(w))["提灯"] == "known"


# --- the other language, and a big list ------------------------------------------------------------------------- #
def test_a_language_change_drops_the_circles_undo_held_for_the_other_language(main, monkeypatch):
    """(Mado-LT 5) ✓ on 看板 in Japanese holds that write's Undo for its ○; the main window turned to Chinese, where
    看板 is Still learning from before, its ○ marks it Known in Chinese — never the Japanese write's Undo."""
    _write("ja", JA)
    _write("zh", [_entry("看板", None, "2026-11-19T10:00:00", "kàn bǎn", language="zh")])
    assert not word_marks.apply("zh", [("看板", "learning")]).error
    w = _open(main)
    _click_mark(w, "看板")
    assert wait_until(lambda: not w.busy() and "看板" in w.cleared)
    calls = []
    real_mark = main.services.mark_words
    monkeypatch.setattr(main.services, "undo_marks", lambda language, undo_id=None: calls.append(("undo", language)))
    monkeypatch.setattr(main.services, "mark_words",
                        lambda language, marks: calls.append(("mark", language, list(marks))) or real_mark(language, marks))
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w.language == "zh" and w.entries is not None and w.model.rowCount() == 1)
    assert w.cleared == {} and dict(_shown(w))["看板"] == "learning"
    _click_mark(w, "看板")
    assert wait_until(lambda: not w.busy() and calls)
    assert calls == [("mark", "zh", [("看板", "known")])]
    assert "看板" in word_marks.learning("ja")                              # the Japanese write left as it was


def test_a_chinese_learners_known_tab_shows_pinyin_and_writes_only_chinese(main, zh_resources_dir):
    shutil.copyfile(os.path.join(zh_resources_dir, "KnownWords.json"), _write("zh", []))
    _write("ja", JA)
    w = _open(main)
    main.services.settings.set({"target_language": "zh"})
    assert wait_until(lambda: w.language == "zh" and w.entries is not None and w.model.rowCount() == 5)
    first = w.shown.index(0, 0)
    assert first.data(WORD) == "学习" and first.data(Qt.ItemDataRole.DisplayRole) == "学习   xué xí   · imported"
    assert first.data(FIND) == "学习 xué xí"
    _click_mark(w, "学习")
    assert wait_until(lambda: not w.busy() and w.status.text() == "学习: still learning · its ○ puts it back")
    assert word_marks.learning("ja") == set()                              # the Japanese file untouched


def test_eleven_thousand_known_words_open_as_one_list(main, ja_resources_dir):
    """The Migaku export (10,020 known words): one read, every row in the model, the view's rows all one height (it
    lays out and paints only the rows in view); the count says them all."""
    shutil.copyfile(os.path.join(ja_resources_dir, "KnownWord.json"), _write("ja", []))
    w = _open(main)
    assert w.model.rowCount() == 10020 and w.count.text() == "10020 words"
    assert w.list.uniformItemSizes()
    assert w.list.indexWidget(w.shown.index(0, 0)) is None
