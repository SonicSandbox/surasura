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
def test_a_bad_card_swap_says_its_old_card_was_deleted_never_that_you_flagged_it_or_that_it_comes_back(lang):
    """*Bad card* (and *Parsing mistake · only this sentence*, through the same door) answers a card you DELETED: there
    is no old card to flag, suspend or put back. Its *Needs you* card says so, and its Undo is its own: the new card
    deleted (a copy kept), the old one stays deleted (what `swap.undo` does for it: `_old_back` finds no note)."""
    word = WORDS[lang]
    (entry,) = needs._swap_entries(_record(swap.NEW_CARD, by=swap.BY_BAD_CARD, word=word), frozenset())
    assert entry.title == needs.STRINGS["swapped_title"].format(word=word)
    assert entry.actions == ("undo_swap_deleted", "leave_swap")
    assert entry.say == needs.STRINGS["swapped_say_deleted"]
    assert "deleted" in entry.say and "copy" in entry.say
    for wrong in ("flagged", "green", "suspended", "back in your reviews", "puts the old one back"):
        assert wrong not in entry.say, wrong
    assert entry.data == {"id": 7, "word": word}


def test_a_bad_card_swaps_undo_button_and_its_line_say_the_old_card_stays_deleted():
    """The window's Undo for it: the same `swap.act_undo` (it reads the swap's own row), its own tip and done line —
    never the simple Swap's *the old one is back in your reviews*."""
    pytest.importorskip("PyQt6")
    from app.qt import needs as qneeds
    from app.qt import strings
    assert "undo_swap_deleted" in qneeds.ANSWERS
    label, tip = strings.NEEDS_ACTIONS["undo_swap_deleted"]
    assert label == "Undo" and "stays deleted" in tip and "reviews" not in tip
    assert "stays deleted" in strings.NEEDS_SWAP_DELETED_UNDONE and "reviews" not in strings.NEEDS_SWAP_DELETED_UNDONE
    pressed = []

    class Window:
        def _do_undo_swap(self, entry, line, name="undo_swap", undone=None):
            pressed.append((entry, line, name, undone))
    qneeds.NeedsYou._do_undo_swap_deleted(Window(), "the entry", None)
    assert pressed == [("the entry", None, "undo_swap_deleted", strings.NEEDS_SWAP_DELETED_UNDONE)]

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
    assert door_routes.swap_route({"lang": "ja"}, None) == {"queued": True, "id": 3, "already": False, "same": on,
                                                             "video": None}   # (no video looked for: SWAP-TIME)


def test_the_journey_page_words_its_swap_toast_by_the_answer():
    """The page's toast: *same* → the card gets the line and keeps its reviews; otherwise the new card's words."""
    import os
    page = open(os.path.join(os.path.dirname(__file__), "..", "..", "templates", "journey", "page.html"),
                encoding="utf-8").read()
    assert "a.same" in page and "card gets this line" in page and "new card from this line" in page


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


# --- review fixes (haiku-lens, FS-2) -------------------------------------------------------------------------------- #
def _write_settings(values):
    import json
    import os
    from app.path_utils import get_settings_path
    path = get_settings_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(values, f, ensure_ascii=False)


@pytest.mark.parametrize("on_disk, read", [
    ({"swap_in_place": False}, True),                                   # a first save wrote the old default: unchosen
    ({}, True),                                                         # never saved
    ({"swap_in_place": False, "swap_in_place_chosen": True}, False),   # *A new card*, the learner's pick: kept
    ({"swap_in_place": True}, True),
])
def test_the_defaults_flip_reaches_everyone_who_never_picked_and_never_a_pick(monkeypatch, on_disk, read):
    """Decision 1 (new installs and updates): a first save writes every default, so a file from a release with the
    default off holds `swap_in_place: false` — read as today's default unless the learner picked it (the marker
    `swap_in_place_chosen`, written beside the pick), as Kantan-B3's and E-LENGTH's. The default is on since
    3.0.18; it is patched on here so the test reads the rule, whatever the shipped default."""
    from app import settings_manager
    monkeypatch.setitem(settings_manager.DEFAULT_SETTINGS, "swap_in_place", True)
    _write_settings(dict(on_disk, connect_enabled=True))
    settings = settings_manager.load_settings()
    assert settings["swap_in_place"] is read and swap.in_place_on(settings) is read


@pytest.mark.parametrize("shipped", [True, False])
def test_a_pick_in_settings_writes_the_marker_and_the_shown_choice_again_writes_nothing(monkeypatch, shipped):
    from app import settings_manager
    from app.qt import settings_catalog as catalog
    from app.services.settings import freeze
    monkeypatch.setitem(settings_manager.DEFAULT_SETTINGS, "swap_in_place", shipped)
    row = catalog.ROW["swap_in_place"]
    _write_settings({"connect_enabled": True})
    changes, _update = catalog.change(row, freeze(settings_manager.load_settings()), "ja", not shipped)
    assert changes == {"swap_in_place": not shipped, "swap_in_place_chosen": True}
    settings_manager.save_keys(changes)
    assert settings_manager.load_settings()["swap_in_place"] is (not shipped)
    assert catalog.change(row, freeze(settings_manager.load_settings()), "ja", not shipped)[0] == {}


def test_the_marker_is_state_no_row_shows_and_no_signature_reads():
    from app import analyzer, settings_manager, settings_placement
    from app.qt import settings_catalog as catalog
    assert settings_manager.DEFAULT_SETTINGS["swap_in_place_chosen"] is False
    assert settings_placement.PLACED["swap_in_place_chosen"] == "neither"
    assert "swap_in_place_chosen" in catalog.NOT_SHOWN
    base = settings_manager.load_settings()
    assert analyzer.settings_signature(dict(base, swap_in_place_chosen=True), "ja") == \
        analyzer.settings_signature(dict(base, swap_in_place_chosen=False), "ja")


def test_the_journey_toast_never_promises_the_reviews_the_job_may_still_fall_back_from():
    """Decisions 5, 6, 12 are decided when the job is made: the toast says the card gets the line, nothing more."""
    import os
    page = open(os.path.join(os.path.dirname(__file__), "..", "..", "templates", "journey", "page.html"),
                encoding="utf-8").read()
    assert "keeps its reviews" not in page and "card gets this line" in page


def test_a_journey_swap_that_made_a_new_card_never_says_you_flagged_it():
    for why in (None, swap.HAND_EDITED):
        (entry,) = needs._swap_entries(_record(swap.NEW_CARD, by=swap.BY_JOURNEY, why=why), frozenset())
        assert "flagged" not in entry.say and "journey" in entry.say
        assert entry.actions == ("undo_swap", "leave_swap")


def test_the_journeys_answer_says_queued_even_when_the_setting_cant_be_read(monkeypatch):
    """The ask is kept before the words are read: a settings read that fails never turns it into a failure."""
    from app import settings_manager
    from app.connect import door_routes
    monkeypatch.setattr(door_routes, "_ask", lambda body, journey: {"id": 3, "new": True})

    def broken():
        raise OSError("settings.json is locked")
    monkeypatch.setattr(settings_manager, "load_settings", broken)
    assert door_routes.swap_route({"lang": "ja"}, None) == {"queued": True, "id": 3, "already": False, "same": False,
                                                             "video": None}   # (no video looked for: SWAP-TIME)


def test_a_ledger_with_kind_but_not_kind_why_still_lists_its_swaps(tmp_path):
    """`ensure`'s ALTERs are one by one: stopped between them, the record still reads (kind_why None)."""
    book = ledger_mod.Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        book.conn.execute(swap._SQL)
        book.conn.execute("ALTER TABLE swaps ADD COLUMN kind TEXT")
        book.conn.execute("INSERT INTO swaps (language, word, by, state, kind, at, updated_at) VALUES "
                          "('ja', '借りる', 'swap', 'made', 'in place', 'x', 'x')")
        (made,) = swap.status_of(book.conn, "ja")["made"]
        assert (made["kind"], made["kind_why"], made["by"]) == (swap.IN_PLACE, None, swap.BY_SWAP)
    finally:
        book.close()
