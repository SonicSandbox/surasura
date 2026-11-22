"""The window's half of Kyou-DW (PROVISIONAL words): the cards you deleted are ONE quiet *Needs you* card — a line a
card with Known · Ignore · Parsing mistake · Bad card, *Same for all* from two, *Leave them* — its explaining line
behind a ? beside the title (the Qt guide: never a visible line under it). A chip turns at once, its answer runs on a
worker (`connect.deleted.answer`), and its toast carries the Undo (`deleted.undo`, on a worker too). The old deletes'
card, once: *Forget* through the window's writer (`allow_again`: its toast and Undo), *Keep them* answers it for good.
On the window's seed; real lines (`tests/Test Resources/ja/library_episode.ass`).

What a wrong answer would cost a learner: a press that does nothing visible, word lists written from the window's
thread, a Same for all that answers only the lines shown, an Undo that can't be reached, or a wall of text on a card.
"""
import threading

import pytest

pytest.importorskip("PyQt6")

from PyQt6.QtWidgets import QLabel

from app.connect import deleted
from app.qt import strings
from app.qt.tooltip import AboutMark
from app.services import needs as service
from tests.qt.conftest import wait_until
from tests.qt.test_needs_you import button, world  # noqa: F401 (the fixture)

ASKED = [{"note_id": 1_700_000_000_002, "word": "図書", "reading": "としょ", "sentence": "図書カードはお持ちですか？",
          "item_id": None, "gone_at": "2026-11-22T10:00:00Z"},
         {"note_id": 1_700_000_000_001, "word": "図書館", "reading": "としょかん", "sentence": "市立図書館",
          "item_id": None, "gone_at": "2026-11-22T10:00:00Z"}]
OLD = [{"word": "用紙", "sentence": "それでしたらこちらの用紙に", "items": [1]}]


def _connect(asked=ASKED, old=()):
    return {"deleted": {"asked": list(asked), "known": 0, "ignored": 0, "old": list(old)}, "needs": [], "gaps": []}


@pytest.fixture
def page(world, monkeypatch):  # noqa: F811
    main, calls = threading.main_thread(), []

    def answer(lang, notes, why):
        calls.append(("answer", lang, list(notes), why, threading.current_thread() is not main))
        return {"done": [(n, a["word"]) for n in notes for a in ASKED if a["note_id"] == n], "skipped": [],
                "error": None}

    def undo(lang, notes, settings=None):
        calls.append(("undo", lang, list(notes), threading.current_thread() is not main))
        return {"done": [(n, "") for n in notes], "skipped": []}
    monkeypatch.setattr(deleted, "answer", answer)
    monkeypatch.setattr(deleted, "undo", undo)
    return calls


def _lines(ny, key, action):
    return [b for b in ny.cards.buttons(key) if b.property("action") == action and b.property("line")]


def test_the_card_has_four_chips_a_line_same_for_all_and_its_line_behind_a_question_mark(world, page):  # noqa: F811
    _seed, _win, _writer, ny = world(connect=_connect())
    entry = next(e for e in ny.entries if e.kind == service.DELETED)
    assert entry.title == "2 cards you deleted · add a note"
    for name in service.DELETED_ACTIONS:
        chips = _lines(ny, entry.key, name)
        assert len(chips) == 2 and all(b.toolTip() for b in chips), name
    whole = {b.property("action") for b in ny.cards.buttons(entry.key) if not b.property("line")}
    assert whole == set(service.DELETED_ALL) | {"dw_leave"}
    card = ny.cards.card(entry.key)
    mark = card.findChild(AboutMark)
    assert mark is not None and mark.toolTip() == service.STRINGS["deleted_say"]
    shown = [w.text() for w in card.findChildren(QLabel) if not isinstance(w, AboutMark)]
    assert service.STRINGS["deleted_say"] not in shown, "the line stands behind its ?, never shown under the title"


def test_a_chip_answers_on_a_worker_and_its_toast_carries_the_undo(world, page, monkeypatch):  # noqa: F811
    _seed, win, _writer, ny = world(connect=_connect())
    toasts = []
    monkeypatch.setattr(win.toasts, "show", lambda text, undo=None, **_k: toasts.append((text, undo)))
    entry = next(e for e in ny.entries if e.kind == service.DELETED)
    chip = next(b for b in _lines(ny, entry.key, "dw_ignore") if b.property("line") ==
                service.deleted_line_key(ASKED[1]["note_id"]))
    chip.click()
    assert wait_until(lambda: toasts, 5)
    assert page[0] == ("answer", "ja", [ASKED[1]["note_id"]], "ignore", True), "that card, never the window's thread"
    assert toasts[0][0] == strings.NEEDS_DELETED_DONE_ONE["ignore"].format(word="図書館")
    assert service.deleted_line_key(ASKED[1]["note_id"]) in service.read_answered("ja")
    toasts[0][1]()
    assert wait_until(lambda: any(c[0] == "undo" for c in page), 5)
    assert next(c for c in page if c[0] == "undo") == ("undo", "ja", [ASKED[1]["note_id"]], True)
    assert wait_until(lambda: service.deleted_line_key(ASKED[1]["note_id"]) not in service.read_answered("ja"), 5)


def test_same_for_all_answers_every_card_of_the_card(world, page, monkeypatch):  # noqa: F811
    _seed, win, _writer, ny = world(connect=_connect())
    toasts = []
    monkeypatch.setattr(win.toasts, "show", lambda text, undo=None, **_k: toasts.append((text, undo)))
    entry = next(e for e in ny.entries if e.kind == service.DELETED)
    button(ny, entry.key, "dw_all_parsing").click()
    assert wait_until(lambda: toasts, 5)
    assert page[0][:4] == ("answer", "ja", [a["note_id"] for a in ASKED], "parsing")
    assert toasts[0][0] == strings.NEEDS_DELETED_DONE["parsing"].format(n="2")


def test_an_answer_that_did_nothing_says_why_and_offers_no_undo(world, page, monkeypatch):  # noqa: F811
    _seed, win, _writer, ny = world(connect=_connect())
    monkeypatch.setattr(deleted, "answer", lambda lang, notes, why: {
        "done": [], "skipped": [(notes[0], "図書", deleted.REFUSED["known"])], "error": None})
    toasts, said = [], []
    monkeypatch.setattr(win.toasts, "show", lambda text, undo=None, **_k: toasts.append((text, undo)))
    win.say = said.append
    entry = next(e for e in ny.entries if e.kind == service.DELETED)
    _lines(ny, entry.key, "dw_known")[0].click()
    assert wait_until(lambda: said, 5)
    assert said == [strings.NEEDS_DELETED_NONE + strings.NEEDS_DELETED_SKIPPED_ONE.format(
        word="図書", why=deleted.REFUSED["known"])]
    assert toasts == []


def test_leave_them_answers_every_line(world, page):  # noqa: F811
    _seed, _win, _writer, ny = world(connect=_connect())
    entry = next(e for e in ny.entries if e.kind == service.DELETED)
    button(ny, entry.key, "dw_leave").click()
    keys = {service.deleted_line_key(a["note_id"]) for a in ASKED}
    assert wait_until(lambda: keys <= set(service.read_answered("ja")), 5)
    assert wait_until(lambda: not any(e.kind == service.DELETED for e in ny.entries), 5)


def test_one_card_has_no_same_for_all(world, page):  # noqa: F811
    _seed, _win, _writer, ny = world(connect=_connect(asked=ASKED[:1]))
    entry = next(e for e in ny.entries if e.kind == service.DELETED)
    assert entry.title == "A card you deleted · add a note"
    assert {b.property("action") for b in ny.cards.buttons(entry.key) if not b.property("line")} == {"dw_leave"}


def test_the_old_deletes_card_forgets_through_the_writer_and_keep_them_answers_it(world, page):  # noqa: F811
    _seed, _win, writer, ny = world(connect=_connect(asked=(), old=OLD))
    entry = next(e for e in ny.entries if e.kind == service.OLD_DELETES)
    assert entry.title == "A card you deleted before Surasura asked why"
    assert {b.property("action") for b in ny.cards.buttons(entry.key)} == {"dw_forget", "dw_forget_all",
                                                                           "dw_keep_old"}
    assert ny.cards.card(entry.key).findChild(AboutMark).toolTip() == service.STRINGS["old_deletes_say"]
    button(ny, entry.key, "dw_keep_old").click()
    assert wait_until(lambda: service.OLD_DELETES in service.read_answered("ja"), 5)
    assert wait_until(lambda: not any(e.kind == service.OLD_DELETES for e in ny.entries), 5)
