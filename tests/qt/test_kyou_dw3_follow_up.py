"""The window's half of Kyou-DW 3 (PROVISIONAL words): *Parsing mistake* on a deleted card asks one more thing, in
one more line under that card's line — **The word is wrong** · **Only in this sentence**, Surasura's guess first —
and answers nothing by itself; *All parsing mistakes* asks it once for the whole card, first on the card. Each chip
answers on a worker (`connect.deleted.answer`) and its toast carries the Undo. On the window's seed; real lines
(`tests/Test Resources/ja/library_episode.ass`).

What a wrong answer would cost a learner: a press that answers for them, a follow-up asked twice for one batch, a
follow-up with no way to answer, or chips with no tooltip.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from app.connect import deleted
from app.qt import strings
from app.services import needs as service
from tests.qt.conftest import wait_until
from tests.qt.test_kyou_dw_deleted_needs import ASKED, _connect, _lines
from tests.qt.test_needs_you import button, world  # noqa: F401 (the fixture)

GUESSED = [dict(ASKED[0], likely=deleted.LINE), dict(ASKED[1], likely=deleted.PARSING)]


@pytest.fixture
def page(world, monkeypatch):  # noqa: F811
    main, calls = threading.main_thread(), []

    def answer(lang, notes, why):
        calls.append(("answer", lang, list(notes), why, threading.current_thread() is not main))
        return {"done": [(n, a["word"]) for n in notes for a in ASKED if a["note_id"] == n], "skipped": [],
                "error": None}
    monkeypatch.setattr(deleted, "answer", answer)
    monkeypatch.setattr(deleted, "undo", lambda lang, notes, settings=None: {"done": [(n, "") for n in notes],
                                                                             "skipped": []})
    return calls


def _entry(ny):
    return next(e for e in ny.entries if e.kind == service.DELETED)


def test_parsing_mistake_asks_the_follow_up_under_its_line_and_answers_nothing_yet(world, page):  # noqa: F811
    _seed, _win, _writer, ny = world(connect=_connect(GUESSED))
    note = GUESSED[0]["note_id"]
    chip = next(b for b in _lines(ny, _entry(ny).key, "dw_parsing")
                if b.property("line") == service.deleted_line_key(note))
    chip.click()
    assert wait_until(lambda: any(ln.key == service.deleted_how_key(note) for ln in _entry(ny).lines), 5)
    assert page == [], "the first press only asks: nothing answered for the learner"
    keys = [b.property("action") for b in ny.cards.buttons(_entry(ny).key)
            if b.property("line") == service.deleted_how_key(note)]
    assert keys == ["dw_only_line", "dw_word_wrong"], "the guess (a real word said elsewhere) offered first"
    assert all(b.toolTip() for b in ny.cards.buttons(_entry(ny).key)
               if b.property("line") == service.deleted_how_key(note))


def test_only_in_this_sentence_answers_on_a_worker_with_its_own_words_and_an_undo(world, page, monkeypatch):  # noqa: F811
    _seed, win, _writer, ny = world(connect=_connect(GUESSED))
    toasts = []
    monkeypatch.setattr(win.toasts, "show", lambda text, undo=None, **_k: toasts.append((text, undo)))
    note = GUESSED[1]["note_id"]
    next(b for b in _lines(ny, _entry(ny).key, "dw_parsing")
         if b.property("line") == service.deleted_line_key(note)).click()
    assert wait_until(lambda: any(b.property("action") == "dw_only_line" for b in ny.cards.buttons(_entry(ny).key)), 5)
    order = [b.property("action") for b in ny.cards.buttons(_entry(ny).key)
             if b.property("line") == service.deleted_how_key(note)]
    assert order == ["dw_word_wrong", "dw_only_line"], "no guess for a real word: The word is wrong first"
    next(b for b in ny.cards.buttons(_entry(ny).key) if b.property("action") == "dw_only_line").click()
    assert wait_until(lambda: toasts, 5)
    assert page[0] == ("answer", "ja", [note], deleted.LINE, True)
    assert toasts[0][0] == strings.NEEDS_DELETED_DONE_ONE[deleted.LINE].format(word=GUESSED[1]["word"])
    assert toasts[0][1] is not None, "its Undo"


def test_all_parsing_mistakes_asks_once_for_the_card_and_the_word_is_wrong_answers_every_card(
        world, page, monkeypatch):  # noqa: F811
    _seed, win, _writer, ny = world(connect=_connect(GUESSED))
    toasts = []
    monkeypatch.setattr(win.toasts, "show", lambda text, undo=None, **_k: toasts.append((text, undo)))
    button(ny, _entry(ny).key, "dw_all_parsing").click()
    assert wait_until(lambda: _entry(ny).lines[0].key == service.deleted_how_key(None), 5)
    assert page == []
    first = _entry(ny).lines[0]
    assert first.text == service.STRINGS["deleted_how_all"].format(n=2)
    assert sum(ln.key.startswith(service.DELETED_HOW) for ln in _entry(ny).lines) == 1
    next(b for b in ny.cards.buttons(_entry(ny).key) if b.property("action") == "dw_all_word_wrong").click()
    assert wait_until(lambda: toasts, 5)
    assert page[0][:4] == ("answer", "ja", [a["note_id"] for a in ASKED], deleted.PARSING)
    assert toasts[0][0] == strings.NEEDS_DELETED_DONE[deleted.PARSING].format(n="2")
