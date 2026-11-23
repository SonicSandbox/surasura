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
from PyQt6.QtWidgets import QApplication

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
    from app.qt.word_lists_window import _Words                             # (Mado-LT 5) an Ignore tab's row: ✕
    ignore = _Words()
    ignore.fill([("冒険", "list")], ["冒険"])
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


def test_a_circle_whose_undo_is_gone_marks_the_word_known(main, monkeypatch):
    """(Mado-LT 5) ✓ here, then the main window's Undo takes that write (or later writes push it off the stack): the
    ○'s Undo finds nothing — the word is marked Known instead, the row ✓, its held Undo dropped; never "was already
    that way" over a ○ that stays."""
    _write("ja", JA)
    w = _open(main)
    _click_mark(w, "看板")
    assert wait_until(lambda: not w.busy() and "看板" in w.cleared)
    assert not word_marks.undo("ja", w.cleared["看板"]).error                 # the main window's Undo took it
    assert "看板" not in word_marks.learning("ja")
    assert not word_marks.apply("ja", [("看板", "learning")]).error           # and the word Still learning again
    _click_mark(w, "看板")
    assert wait_until(lambda: not w.busy() and w.status.text() == "看板: known again")
    assert dict(_shown(w))["看板"] == "known" and "看板" not in w.cleared
    assert "看板" not in word_marks.learning("ja")


def test_a_read_on_its_way_never_paints_over_a_check_just_pressed(main, monkeypatch):
    """(Mado-LT 5) A read that left before ✓ (the one after an Add, a window shown again) answers with the file as it
    was: dropped, so the row keeps its ○ — not ✓ over a word now Still learning."""
    import threading
    _write("ja", JA)
    w = _open(main)
    gate, real, answered = threading.Event(), word_lists.read, []

    def slow(kind, language):
        listing = real(kind, language)
        gate.wait(5)
        answered.append(True)
        return listing
    monkeypatch.setattr(word_lists, "read", slow)
    w.read()
    _click_mark(w, "灯台")
    assert wait_until(lambda: not w.busy() and "灯台" in w.cleared)
    gate.set()
    assert wait_until(lambda: answered)
    wait_until(lambda: False, 0.3)                                          # (its answer delivered to the window)
    assert dict(_shown(w))["灯台"] == "learning"


def test_a_break_with_no_words_still_ends_the_write_and_says_so(main, monkeypatch):
    """(Mado-LT 5) A worker that raises with an empty message (`RuntimeError()`): the row put back, the window free
    again and the line names what broke — never stuck greyed."""
    _write("ja", JA)
    w = _open(main)

    def broken(language, marks):
        raise RuntimeError()
    monkeypatch.setattr(main.services, "mark_words", broken)
    _click_mark(w, "灯台")
    assert wait_until(lambda: not w.busy() and "RuntimeError" in w.status.text())
    assert dict(_shown(w))["灯台"] == "known"


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


# --- ten thousand words, every step under 4 ms (Mado-LT 6) ------------------------------------------------------ #
# The machine's own speed for the 4 ms (the Qt guide § 4: no step on the window's thread over 4 ms): the idea of
# Flake-F6's `tests/qt/test_guide.py::_speed` (its PR not landed yet: copied, not imported) — a fixed piece of the
# same kind of work, timed by the same clock, the least of 5; REF_DESKTOP_MS its reading on the desktop the 4 ms is set
# on. A slower machine reads it slower by the same ratio, and only then is the budget scaled (never below 4 ms).
REF_TEXT = "この本は、毎日少しずつ読むことで、知らない言葉が自然に覚えられるように作られています。 " * 6
REF_DESKTOP_MS = 3.16


def _budget(own_ms):
    from PyQt6.QtWidgets import QLabel
    label = QLabel(REF_TEXT)
    label.setWordWrap(True)
    label.ensurePolished()
    best = None
    for _ in range(5):
        t0 = own_ms()
        for width in range(200, 420, 11):
            label.heightForWidth(width)
        took = own_ms() - t0
        best = took if best is None else min(best, took)
    label.deleteLater()
    return 4.0 * max(1.0, best / REF_DESKTOP_MS)


def _step(own_ms, fn, *args):
    t0 = own_ms()
    fn(*args)
    return own_ms() - t0


def _after(w, own_ms):
    """The steps the event loop runs after a change, each timed alone on the window's thread's own clock: the window's
    layout (a line shown or hidden, the count's width), the view's delayed layout of its rows (it asks `index()` of
    every row) and the next paint (the rows in view: `data()` of those only). Then anything else posted, untimed."""
    from PyQt6.QtCore import QEvent
    steps = [_step(own_ms, QApplication.sendPostedEvents, None, QEvent.Type.LayoutRequest.value),
             _step(own_ms, w.list.doItemsLayout), _step(own_ms, w.list.viewport().repaint)]
    QApplication.processEvents()
    return steps


def test_ten_thousand_known_words_open_search_and_mark_in_steps_under_4_ms(main, ja_resources_dir, monkeypatch):
    """A learner with a few years of Anki knows this many words: the Known tab on the Migaku export (11,582 entries,
    10,020 known) opens, answers a search keystroke and shows a ✓'s ○ each in steps under the Qt guide's 4 ms on the
    window's thread (its own CPU time: never the time a worker or another process took meanwhile) — the rows made as
    they come into view, never one item per word in the answer's step (~150 ms before)."""
    from tests.qt.test_guide import _own_ms
    own_ms = _own_ms()
    budget = _budget(own_ms)
    steps = {"open": [], "keystroke": [], "press": []}
    moment = ["open"]
    real_show, real_marked = WordListsWindow._show, WordListsWindow._row_marked

    def timed(real):
        def step(self, *a, **k):
            t0 = own_ms()
            try:
                return real(self, *a, **k)
            finally:
                steps[moment[0]].append(own_ms() - t0)
        return step
    monkeypatch.setattr(WordListsWindow, "_show", timed(real_show))
    monkeypatch.setattr(WordListsWindow, "_row_marked", timed(real_marked))
    shutil.copyfile(os.path.join(ja_resources_dir, "KnownWord.json"), _write("ja", []))
    w = _open(main)
    assert w.model.rowCount() == 10020 and len(steps["open"]) == 1          # the answer's own step, timed
    steps["open"] += _after(w, own_ms)
    finds = [w.shown.index(i, 0).data(FIND).casefold() for i in range(10020)]

    moment[0] = "keystroke"
    for text in ("ち", "ちょ", "", "灯", "zz"):                              # narrowing, cleared, a kanji, nothing
        steps["keystroke"].append(_step(own_ms, w.search.setText, text))
        steps["keystroke"] += _after(w, own_ms)
        assert w.shown.rowCount() == sum(text in find for find in finds)  # every word it holds, and only those
    assert w.count.text() == "0 of 10020 words"
    w.search.clear()

    moment[0] = "press"
    word = w.shown.index(5000, 0).data(WORD)                               # a row deep in the list
    w.list.scrollTo(w.shown.index(5000, 0))
    _after(w, own_ms)                                                      # (the scroll's own: not the press)
    steps["press"].append(_step(own_ms, w.mark_known_row, word))
    assert w.shown.index(5000, 0).data(SOURCE) == "learning"               # its ○ at once
    steps["press"] += _after(w, own_ms)                                    # (its marks greyed: not now)
    assert wait_until(lambda: not w.busy() and word in w.cleared, 30)      # the answer's step timed …
    steps["press"] += _after(w, own_ms)                                    # … and the marks back
    worst = {name: round(max(took), 2) for name, took in steps.items()}
    print("Mado-LT 6 worst step, ms:", worst, "budget", round(budget, 2),
          {name: [round(took, 2) for took in took_all] for name, took_all in steps.items()})
    assert all(took < budget for took in worst.values()), (worst, budget)


def test_a_check_pressed_mid_search_paints_its_own_row_and_one_hidden_by_the_next_keystroke_still_lands(main):
    """(Mado-LT 6: the window's own model shows the search's rows.) ✓ on a row the search shows: its ○ at once, that
    row alone changed; a keystroke that hides it before the answer: nothing painted for it, and the search cleared
    shows its ○ where it was — the order kept."""
    _write("ja", JA)
    w = _open(main)
    w.search.setText("提")
    assert _shown(w) == [("提灯", "known")]                                      # the list's second word, shown first
    seen = _changes(w)
    _click_mark(w, "提灯")
    assert _shown(w) == [("提灯", "learning")]                                   # at once
    assert seen["rows"] == 0 and {r for pair in seen["data"] for r in pair} == {0}
    w.search.setText("灯台")                                                     # 提灯 hidden before the answer
    assert _shown(w) == [("灯台", "known")]
    assert wait_until(lambda: not w.busy() and "提灯" in w.cleared)
    assert _shown(w) == [("灯台", "known")]
    w.search.clear()
    assert _shown(w) == [("灯台", "known"), ("提灯", "learning"), ("看板", "known"), ("コツン", "known")]
    assert w.count.text() == "4 words"


def test_the_search_typed_on_one_tab_still_narrows_the_other_tabs_rows(main):
    """(Mado-LT 6) The search stays typed when the tab changes: the other list's rows, made again, are narrowed by it
    at once — never every row under a search that says otherwise."""
    _write("ja", JA)
    with open(word_lists.list_path("ignore", "ja"), "w", encoding="utf-8") as f:
        f.write("冒険\n灯油\n毎日\n")
    w = _open(main)
    w.search.setText("灯")
    assert [word for word, _s in _shown(w)] == ["灯台", "提灯"]
    w.show_kind("ignore")
    assert wait_until(lambda: w.entries is not None and not w.busy())
    assert _shown(w) == [("灯油", "list")] and w.count.text() == "1 of 3 words"
