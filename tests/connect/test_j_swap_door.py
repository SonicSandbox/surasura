"""J-SWAP: the journey page's ⇄ (`swap/queue`) and *Add now* (`card/make`) on the door (journey v3 SPEC §3.3, row 11).

What each test holds still:
- **one maker:** both presses ask Swap's `make_card` with the line the learner pressed (`by` journey / add now), and
  Connect's look makes the card from that line — Swap's own pick is never asked;
- **the line pressed or nothing:** a line with no item / time, one not in its file now, or the old card's own line is
  refused in words, nothing asked; Connect off, a Known or Ignored word, *Add now* on a word Connect has a card for:
  refused, nothing asked; a second press while the first is open answers the first (never a second card);
- **the old card as the learner left it:** a journey ⇄ never suspends or flags the old card; its Undo takes back only
  the new card and Swap's tag (never unsuspends a card the journey didn't take out, never clears a flag it didn't set);
- **the registry:** both routes are built for `hello` (the page shows ⇄ / Add) and answer through `journey_door`.

What a wrong answer costs: a card from a line the learner didn't press, a second card for a word, a card for a word
they marked Known or Ignored, an old card changed by a press that never asked for it, or a press that says *queued*
when nothing will ever make it. Real Japanese and Chinese lines from tests/Test Resources; the ledger and the library
store are real; Anki is Tidy's fake.
"""
import os

import pytest

from app import cues, door, library_store
from app.connect import door_routes, library, swap, tidy
from app.services import journey_door
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.connect.test_kantan_sl_swap import (CASES, JA, MINING, ZH, Anki, Steps, _lists, _make_the_job, _row,
                                               ledger)  # noqa: F401  (`ledger`: the fixture)


def _library(lang, connect=True):
    """The case's real subtitle as the one item in NOW, Connect on (or off), the word not known -> its item id."""
    path = JA if lang == "ja" else ZH
    h.seed_library(lang, files=[os.path.basename(path)], templates=False)
    h.write_settings(target_language=lang, connect_enabled=connect)
    data_dir, user_files = c.dirs(lang)
    assert library_store.maintain(lang, data_dir, user_files, from_folders=True) == library_store.EXIT_DONE
    _lists(lang)
    with c.store(lang) as s:
        return s.ids("now")[0]


def _line(lang, item, text):
    """The page's id for the line of the case's file that holds `text` (`<item>:<start ms>`, swap.line_id's form)."""
    cue = [q for q in cues.read(JA if lang == "ja" else ZH, lang) if text in (q.text or "")][0]
    return swap.line_id(item, cues.seconds(cue.start)), cue.text


def _connects_card(ledger, lang, item, note=900):
    """The word's card as Connect made it (its batch's outcome, with the line it was cut from)."""
    word, old, _other = CASES[lang]
    job = ledger.queue(lang, item, "user", None, store_id="s1")
    ledger.end_batch(job, 1, "done", [{"word": word, "reading": "", "outcome": "made", "note_id": note,
                                       "sentence": old}], deck=MINING)
    ledger.set_state(job, "done")


def _press(route, lang, word, line_id):
    return journey_door.routes(journey_door.App())[route]({"lang": lang, "word": word, "line_id": line_id,
                                                           "at": 1})


def _refused(route, lang, word, line_id):
    with pytest.raises(door.RouteError) as e:
        _press(route, lang, word, line_id)
    return e.value


def _asks(ledger):
    if not ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'swaps'").fetchone():
        return []
    return swap._rows(ledger, "1 = 1")


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_swap_on_the_page_asks_the_one_maker_with_the_line_pressed_and_leaves_the_old_card_as_it_is(ledger, lang,
                                                                                                   monkeypatch):
    word, _old, other = CASES[lang]
    item = _library(lang)
    _connects_card(ledger, lang, item)
    line_id, text = _line(lang, item, other)
    got = _press("swap/queue", lang, word, line_id)
    assert got["queued"] and not got["already"]
    row = _row(ledger, got["id"])
    assert (row["by"], row["old_note"], row["line_id"], row["ref"]) == (swap.BY_JOURNEY, 900, line_id, None)
    # Connect's look makes it from that line, never Swap's own pick
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: pytest.fail("the learner pressed a line"))
    anki = Anki()
    anki.add(900, "Japanese", word, 1, cards=[{"reps": 3, "type": 2, "queue": 2}])   # in reviews, no flag
    swap.look(Steps(subtitle=JA if lang == "ja" else ZH), ledger, lang, anki=anki, files=5)
    row = _row(ledger, got["id"])
    assert (row["state"], row["item_id"], row["line"]) == (swap.QUEUED, item, text)
    _make_the_job(ledger, row)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert _row(ledger, got["id"])["state"] == swap.MADE
    assert swap.SWAP_TAG in anki.notes_[900]["tags"]                                  # Swap's only write to it
    assert (anki.cards_[9000]["queue"], anki.cards_[9000]["flags"]) == (2, 0)          # never suspended, never flagged


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_add_now_asks_a_card_for_a_word_with_none_from_the_line_pressed_and_tidy_keeps_it(ledger, lang, monkeypatch):
    word, _old, other = CASES[lang]
    item = _library(lang)
    line_id, text = _line(lang, item, other)
    got = _press("card/make", lang, word, line_id)
    assert got["asked"] and not got["already"]
    row = _row(ledger, got["id"])
    assert (row["by"], row["old_note"], row["line_id"]) == (swap.BY_ADD_NOW, None, line_id)
    monkeypatch.setattr(swap, "choose_line", lambda *a, **k: pytest.fail("the learner pressed a line"))
    swap.look(Steps(subtitle=JA if lang == "ja" else ZH), ledger, lang, anki=Anki(), files=5)
    row = _row(ledger, got["id"])
    assert (row["state"], row["item_id"], row["line"]) == (swap.QUEUED, item, text)
    _make_the_job(ledger, row, note=951)
    swap.look(Steps(), ledger, lang, anki=Anki(), files=5)
    assert _row(ledger, got["id"])["new_note"] == 951
    assert tidy.asked_for(ledger, lang, [951]) == {951}             # pinned: an ordinary tidy never takes it (D3)


def test_add_now_on_a_word_connect_has_a_card_for_is_refused_and_asks_nothing(ledger):
    lang, (word, _old, other) = "ja", CASES["ja"]
    item = _library(lang)
    _connects_card(ledger, lang, item)
    e = _refused("card/make", lang, word, _line(lang, item, other)[0])
    assert e.message == door_routes.HAS_CARD and _asks(ledger) == []


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_swap_on_the_old_cards_own_line_is_refused_and_asks_nothing(ledger, lang):
    word, old, _other = CASES[lang]
    item = _library(lang)
    _connects_card(ledger, lang, item)
    e = _refused("swap/queue", lang, word, _line(lang, item, old)[0])
    assert e.message == door_routes.SAME and _asks(ledger) == []


def test_a_line_with_no_time_or_gone_from_its_file_is_refused_never_swaps_own_pick(ledger):
    lang, word = "ja", CASES["ja"][0]
    item = _library(lang)
    # the page names a line it can't time (a book's line, no item) by a hash: no card can be cut from it
    assert _refused("card/make", lang, word, "2166136261").message == door_routes.NO_LINE
    assert _refused("card/make", lang, word, None).message == door_routes.NO_LINE
    # an id whose start isn't a line of the item's file now (the journey older than the library)
    gone = _refused("card/make", lang, word, f"{item}:999999")
    assert (gone.message, gone.kind) == (door_routes.GONE, "gone")
    assert _refused("card/make", lang, word, "99999:1000").message == door_routes.GONE       # no such item
    assert _asks(ledger) == []


def test_with_connect_off_nothing_is_asked_and_the_page_is_told_why(ledger):
    lang, (word, _old, other) = "ja", CASES["ja"]
    item = _library(lang, connect=False)
    e = _refused("card/make", lang, word, _line(lang, item, other)[0])
    assert (e.message, e.kind) == (door_routes.OFF, "off") and _asks(ledger) == []


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_word_known_or_ignored_now_is_refused_in_words_and_no_card_is_asked(ledger, lang):
    word, _old, other = CASES[lang]
    item = _library(lang)
    line_id = _line(lang, item, other)[0]
    _lists(lang, known=[word])
    e = _refused("card/make", lang, word, line_id)
    assert (e.message, e.kind) == (door_routes.KNOWN.format(word), "known")
    _lists(lang, ignored=[word])
    e = _refused("swap/queue", lang, word, line_id)
    assert (e.message, e.kind) == (door_routes.IGNORED.format(word), "ignored")
    assert all(r["state"] == swap.DROPPED for r in _asks(ledger))                  # Swap's record says why


def test_a_second_press_while_the_first_ask_is_open_answers_the_first_never_a_second_card(ledger):
    lang, (word, _old, other) = "ja", CASES["ja"]
    item = _library(lang)
    line_id = _line(lang, item, other)[0]
    first = _press("card/make", lang, word, line_id)
    again = _press("card/make", lang, word, line_id)
    assert (again["id"], again["already"]) == (first["id"], True) and len(_asks(ledger)) == 1


def test_a_body_the_page_never_sends_is_refused_and_writes_nothing(ledger):
    item = _library("ja")
    line_id = _line("ja", item, CASES["ja"][2])[0]
    for body in ({"lang": "fr", "word": "借りる", "line_id": line_id}, {"lang": "ja", "word": "", "line_id": line_id},
                 {"lang": "ja", "word": ["借りる"], "line_id": line_id},
                 {"lang": "ja", "word": "借" * (door_routes.WORD_MAX + 1), "line_id": line_id}):
        with pytest.raises(door.RouteError) as e:
            door_routes.card_route(body, journey_door.App())
        assert e.value.message == door_routes.NOT_READ
    assert _asks(ledger) == []


def test_undo_of_a_journey_swap_takes_back_the_new_card_and_the_tag_only(ledger, monkeypatch):
    # the old card was suspended and flagged by the learner for reasons of their own: the journey's ⇄ took nothing out
    lang, (word, _old, other) = "ja", CASES["ja"]
    item = _library(lang)
    _connects_card(ledger, lang, item)
    got = _press("swap/queue", lang, word, _line(lang, item, other)[0])
    anki = Anki()
    anki.add(900, "Japanese", word, 1, cards=[{"reps": 3, "type": 2, "queue": -1, "flags": 3}])
    swap.look(Steps(subtitle=JA), ledger, lang, anki=anki, files=5)
    row = _row(ledger, got["id"])
    _make_the_job(ledger, row, record=True)
    anki.add(950, "surasura::connect::" + ledger.tag_id(row["job_id"]), word, 1, sound="swap-new.mp3")
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    swap.undo(anki, ledger, lang, got["id"], open_store=lambda: library.open_store(lang))
    assert anki.deleted == [950] and swap.SWAP_TAG not in anki.notes_[900]["tags"]
    assert (anki.cards_[9000]["queue"], anki.cards_[9000]["flags"]) == (-1, 3)        # as the learner left it


def test_hello_lists_both_routes_so_the_page_shows_swap_and_add_now():
    routes = journey_door.hello({"lang": "ja"}, journey_door.App())["routes"]
    assert {"swap/queue", "card/make"} <= set(routes)
