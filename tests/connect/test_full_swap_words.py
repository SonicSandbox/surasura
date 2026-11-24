"""FS-2 (the full Swap's words, SCOPE § 8; every word PROVISIONAL): *Needs you* says an in-place swap as the same card
with a new sentence — never "a new card" — with its own Undo; a swap that fell back to a new card says why once
(decisions 5, 6, 12); *Bad card* says once, while *Same card* is on, that a flag keeps the reviews (decision 11); the
journey's ⇄ is told which kind the setting asks for.

Real lines from `tests/Test Resources/ja|zh` (library_episode.ass, night_market.srt); the record as Connect's
`swap.status_of` writes it.
"""
import pytest

from app.connect import ledger as ledger_mod
from app.connect import swap
from app.services import needs

WORDS = {"ja": "借りる", "zh": "夜市"}


def _record(kind, by=swap.BY_SWAP, why=None, word="借りる", swap_id=7):
    return {"swaps": {"made": [{"id": swap_id, "word": word, "at": "2026-11-23T10:00:00Z", "kind": kind,
                                "kind_why": why, "by": by}], "waits": []}}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_in_place_swap_is_said_as_the_same_card_with_its_own_undo_never_a_new_card(lang):
    """Decision 8: from the flag the card is back in your reviews, its reviews kept; Undo puts the old sentence back on
    the same card. The simple Swap's words (a new card, the old one suspended) are never on it."""
    word = WORDS[lang]
    (entry,) = needs._swap_entries(_record(swap.IN_PLACE, word=word), frozenset())
    assert entry.kind == needs.SWAPPED and word in entry.title
    assert entry.actions == ("undo_swap_same", "leave_swap_same")
    words = entry.title + " " + entry.say
    assert "new card" not in words and "suspended" not in words
    assert "same card" in entry.title and "reviews" in entry.say
    assert entry.data == {"id": 7, "word": word}


def test_a_journey_swap_in_place_says_the_line_you_picked_and_never_that_you_flagged_it():
    (entry,) = needs._swap_entries(_record(swap.IN_PLACE, by=swap.BY_JOURNEY), frozenset())
    assert "journey" in entry.say and "flagged" not in entry.say
    assert entry.actions == ("undo_swap_same", "leave_swap_same")


@pytest.mark.parametrize("why, said", [(swap.HAND_EDITED, "by hand"), (swap.NOT_CONNECTS, "didn't make"),
                                       (swap.NO_RENDER, "Update Anki Miner")])
def test_a_swap_that_fell_back_to_a_new_card_says_why_once_before_the_simple_swaps_words(why, said):
    """Decisions 5, 6, 12: the setting asked for the same card and it couldn't be: a new card, said once on its card —
    the simple Swap's own Undo and words after the why."""
    (entry,) = needs._swap_entries(_record(swap.NEW_CARD, why=why), frozenset())
    assert entry.actions == ("undo_swap", "leave_swap")
    assert said in entry.say and entry.say.endswith(needs.STRINGS["swapped_say"])
    assert entry.title == needs.STRINGS["swapped_title"].format(word="借りる")


def test_a_simple_swap_with_no_why_is_said_exactly_as_before():
    """With *A new card* (the default in the tree) nothing changes on *Needs you*."""
    for rec in (_record(swap.NEW_CARD), {"swaps": {"made": [{"id": 7, "word": "借りる", "at": "x"}], "waits": []}}):
        (entry,) = needs._swap_entries(rec, frozenset())
        assert (entry.title, entry.say, entry.actions) == (needs.STRINGS["swapped_title"].format(word="借りる"),
                                                           needs.STRINGS["swapped_say"], ("undo_swap", "leave_swap"))


def test_an_unknown_why_adds_nothing_and_never_breaks_the_card():
    (entry,) = needs._swap_entries(_record(swap.NEW_CARD, why="something a later version says"), frozenset())
    assert entry.say == needs.STRINGS["swapped_say"]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_connects_record_says_who_asked_each_made_swap(tmp_path, lang):
    """`status_of` hands the window `by` (the flag, the journey, *Bad card*) with each made swap, so its words fit."""
    book = ledger_mod.Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        swap.ensure(book)
        for n, by in enumerate((swap.BY_SWAP, swap.BY_JOURNEY), 1):
            book.conn.execute("INSERT INTO swaps (language, word, by, state, kind, at, updated_at) VALUES "
                              "(?, ?, ?, ?, ?, ?, ?)", (lang, WORDS[lang], by, swap.MADE, swap.IN_PLACE,
                                                       f"2026-11-23T10:0{n}:00Z", f"2026-11-23T10:0{n}:00Z"))
        made = swap.status_of(book.conn, lang)["made"]
        assert [(m["by"], m["kind"]) for m in made] == [(swap.BY_JOURNEY, swap.IN_PLACE), (swap.BY_SWAP, swap.IN_PLACE)]
    finally:
        book.close()


@pytest.mark.parametrize("on", [True, False])
def test_the_journeys_swap_answer_says_which_kind_the_setting_asks_for(monkeypatch, on):
    """The page's ⇄ toast follows the setting at the press (`same`): *Same card, new sentence* → the card gets this
    line; *A new card* → its words as before."""
    from app import settings_manager
    from app.connect import door_routes
    monkeypatch.setattr(door_routes, "_ask", lambda body, journey: {"id": 3, "new": True})
    monkeypatch.setattr(settings_manager, "load_settings", lambda: {"swap_in_place": on})
    assert door_routes.swap_route({"lang": "ja"}, None) == {"queued": True, "id": 3, "already": False, "same": on}


def test_the_journey_page_words_its_swap_toast_by_the_answer():
    """The page's toast: *same* → the card gets the line and keeps its reviews; otherwise the new card's words."""
    import os
    page = open(os.path.join(os.path.dirname(__file__), "..", "..", "templates", "journey", "page.html"),
                encoding="utf-8").read()
    assert "a.same" in page and "keeps its reviews" in page and "new card from this line" in page


@pytest.mark.parametrize("on, said", [(True, True), (False, False)])
def test_bad_card_says_once_that_a_flag_keeps_the_reviews_only_while_same_card_is_on(on, said):
    """Decision 11: a deleted card's reviews are gone, so *Bad card* is always a new card; with *Same card* on, its
    answer's line says once that flagging instead keeps them. With *A new card* a flag wouldn't either: not said."""
    pytest.importorskip("PyQt6")
    from app.qt import needs as qneeds
    from app.qt import strings
    got = {"done": [(901, "借りる")]}
    line = qneeds.deleted_said("bad", got, same_card=on)
    assert line.startswith(strings.NEEDS_DELETED_DONE_ONE["bad"].format(word="借りる"))
    assert (strings.NEEDS_BAD_CARD_FLAG in line) is said
    for why in ("known", "ignore", "parsing", "line"):
        assert strings.NEEDS_BAD_CARD_FLAG not in qneeds.deleted_said(why, got, same_card=True)
