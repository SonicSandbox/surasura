"""J-SWAP: the journey page's ⇄ (`swap/queue`) and *Add now* (`card/make`) on the door (journey v3 SPEC §3.3, row 11).

What each test holds still:
- **one maker:** both presses ask Swap's `make_card` with the line the learner pressed (`by` journey / add now), and
  Connect's look makes the card from that line — Swap's own pick is never asked;
- **the line pressed or nothing:** a line with no item / time, one not in its file now, or the old card's own line is
  refused in words, nothing asked; Connect off, a Known or Ignored word, *Add now* on a word Connect has a card for:
  refused, nothing asked; a second press while the first is open answers the first (never a second card);
- **one out, one in** (the lead's ruling, PROVISIONAL — OPEN-FOR-SONIC § 72 a): a journey ⇄ suspends the old card
  once its new card is made (never at the press: a word still waiting keeps its old card in reviews), through the
  shelf's writer, and tags it; it never flags it. Its Undo takes back the new card and the tag and puts back only what
  the press took out — a card the learner had suspended or flagged stays so; `swap.JOURNEY_TAKES_OLD` off: two cards;
- **the registry:** both routes are built for `hello` (the page shows ⇄ / Add) and answer through `journey_door`.

What a wrong answer costs: a card from a line the learner didn't press, a second card for a word, a card for a word
they marked Known or Ignored, two cards of the word in reviews after one ⇄, an Undo that leaves a card out of reviews
or unsuspends one the learner put away themselves, or a press that says *queued*
when nothing will ever make it. Real Japanese and Chinese lines from tests/Test Resources; the ledger and the library
store are real; Anki is Tidy's fake.
"""
import contextlib
import os
import sqlite3

import pytest

from app import cues, door, library_store
from app.connect import door_routes, library, swap, tidy
from app.services import journey_door
from tests import cli_helpers as h
from tests import connect_helpers as c
from tests.connect.test_kantan_sl_swap import (CASES, JA, MINING, ZH, Anki, Steps, _lists, _make_the_job, _row,
                                               ledger)  # noqa: F401  (`ledger`: the fixture)


class JourneyAnki(Anki):
    """Kantan-SL's fake Anki with the shelf's suspend: a suspended card is queue -1; unsuspend puts it back in its
    type's queue, as Anki does."""

    def suspend(self, ids):
        self.log.append(("suspend", tuple(ids)))
        for i in ids:
            self.cards_[int(i)]["queue"] = -1

    def unsuspend(self, ids):
        self.log.append(("unsuspend", tuple(ids)))
        for i in ids:
            self.cards_[int(i)]["queue"] = self.cards_[int(i)].get("type", 0)


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
def test_swap_on_the_page_asks_the_one_maker_with_the_line_pressed_and_takes_the_old_card_out_once_made(ledger, lang,
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
    anki = JourneyAnki()
    anki.add(900, "Japanese", word, 1, cards=[{"reps": 3, "type": 2, "queue": 2}])   # in reviews, no flag
    swap.look(Steps(subtitle=JA if lang == "ja" else ZH), ledger, lang, anki=anki, files=5)
    row = _row(ledger, got["id"])
    assert (row["state"], row["item_id"], row["line"]) == (swap.QUEUED, item, text)
    assert anki.cards_[9000]["queue"] == 2                          # asked, not made: the old card is still in reviews
    _make_the_job(ledger, row)
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert _row(ledger, got["id"])["state"] == swap.MADE
    assert swap.SWAP_TAG in anki.notes_[900]["tags"]
    assert (anki.cards_[9000]["queue"], anki.cards_[9000]["flags"]) == (-1, 0)         # one out, one in; never flagged
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    assert [e for e in anki.log if e[0] == "suspend"] == [("suspend", (9000,))]       # once


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


@contextlib.contextmanager
def _another_program_holds_the_library(lang):
    """The language's store held as another program's save holds it: an exclusive-locking connection in a write
    transaction, so a reader's open waits out the store's own wait and finds it busy. Let go of in `finally`, so a
    failing assert never leaves it held."""
    data_dir, _user_files = c.dirs(lang)
    other = sqlite3.connect(library_store.library_db_path(lang, data_dir), isolation_level=None, timeout=0.1)
    try:
        other.execute("PRAGMA locking_mode=EXCLUSIVE")
        other.execute("BEGIN EXCLUSIVE")
        other.execute("SELECT count(*) FROM sqlite_master").fetchone()
        yield
    finally:
        other.execute("ROLLBACK")
        other.close()


@pytest.mark.parametrize("lang", ["ja", "zh"])
@pytest.mark.parametrize("route", ["swap/queue", "card/make"])
def test_a_press_while_the_library_is_busy_says_busy_and_press_again_never_that_the_line_is_gone(ledger, lang, route):
    # J-FIX: the line's file is found through the library store; a store busy with another program's save is no line
    # gone. Told *gone*, the learner would think the journey is older than the library and give up on a good line;
    # told *busy*, they press again. Nothing is asked while it is busy, and the same press goes through once it isn't.
    word, _old, other = CASES[lang]
    item = _library(lang)
    if route == "swap/queue":
        _connects_card(ledger, lang, item)
    line_id = _line(lang, item, other)[0]
    with _another_program_holds_the_library(lang):
        e = _refused(route, lang, word, line_id)
    assert (e.message, e.kind) == (door_routes.BUSY, "busy")
    assert _asks(ledger) == []
    got = _press(route, lang, word, line_id)                       # pressed again: nothing was lost
    assert not got["already"] and [r["line_id"] for r in _asks(ledger)] == [line_id]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_store_read_locked_mid_press_is_busy_and_any_other_failure_still_says_the_line_is_gone(ledger, lang,
                                                                                                 monkeypatch):
    # the open can find the store free and its read still meet another save's lock (SQLite's "database is locked"):
    # busy as well. A read that fails any other way (a damaged row, a file error) is no moment's state: still *gone*,
    # as before, so a press is never told to try again for ever
    from app.connect import runner
    word, _old, other = CASES[lang]
    item = _library(lang)
    line_id = _line(lang, item, other)[0]
    for error, said in ((sqlite3.OperationalError("database is locked"), (door_routes.BUSY, "busy")),
                        (sqlite3.OperationalError("no such column: rel_path"), (door_routes.GONE, "gone")),
                        (runner.Wait(runner.ON_BATTERY), (door_routes.GONE, "gone"))):
        def fails(self, lang_, job, error=error):
            raise error
        monkeypatch.setattr(runner.Steps, "subtitle", fails)
        e = _refused("card/make", lang, word, line_id)
        assert (e.message, e.kind) == said, error
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


def _made_journey_swap(ledger, lang, cards, anki=None):
    """A journey ⇄ on the case's word made into note 950 (the old card: note 900 with `cards`) -> (swap id, anki)."""
    word, _old, other = CASES[lang]
    item = _library(lang)
    _connects_card(ledger, lang, item)
    got = _press("swap/queue", lang, word, _line(lang, item, other)[0])
    anki = anki or JourneyAnki()
    anki.add(900, "Japanese", word, 1, cards=cards)
    swap.look(Steps(subtitle=JA if lang == "ja" else ZH), ledger, lang, anki=anki, files=5)
    row = _row(ledger, got["id"])
    _make_the_job(ledger, row, record=True)
    anki.add(950, "surasura::connect::" + ledger.tag_id(row["job_id"]), word, 1, sound="swap-new.mp3")
    swap.look(Steps(), ledger, lang, anki=anki, files=5)
    return got["id"], anki


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_undo_of_a_journey_swap_puts_the_old_card_back_exactly_as_it_was(ledger, lang):
    # the note's first card was in reviews (the press took it out); its second the learner had suspended and flagged
    # orange themselves: it stays so through the press and the Undo
    swap_id, anki = _made_journey_swap(ledger, lang, [{"reps": 3, "type": 2, "queue": 2},
                                                      {"reps": 5, "type": 2, "queue": -1, "flags": 2}])
    assert [(anki.cards_[c]["queue"], anki.cards_[c]["flags"]) for c in (9000, 9001)] == [(-1, 0), (-1, 2)]
    swap.undo(anki, ledger, lang, swap_id, open_store=lambda: library.open_store(lang))
    assert anki.deleted == [950] and swap.SWAP_TAG not in anki.notes_[900]["tags"]
    assert [(anki.cards_[c]["queue"], anki.cards_[c]["flags"]) for c in (9000, 9001)] == [(2, 0), (-1, 2)]
    assert ("unsuspend", (9000,)) in anki.log and not [e for e in anki.log if e[0] == "set_flag"]


def test_undo_of_a_journey_swap_on_a_card_the_learner_had_put_away_leaves_it_put_away(ledger):
    # suspended and green by the learner for reasons of their own: the press took nothing out, so Undo puts nothing back
    swap_id, anki = _made_journey_swap(ledger, "ja", [{"reps": 3, "type": 2, "queue": -1, "flags": 3}])
    swap.undo(anki, ledger, "ja", swap_id, open_store=lambda: library.open_store("ja"))
    assert anki.deleted == [950] and swap.SWAP_TAG not in anki.notes_[900]["tags"]
    assert (anki.cards_[9000]["queue"], anki.cards_[9000]["flags"]) == (-1, 3)
    assert not [e for e in anki.log if e[0] in ("suspend", "unsuspend", "set_flag")]


def test_a_tag_write_that_fails_after_the_suspend_keeps_what_the_press_took_for_the_undo(ledger):
    # the next look tags it; what was taken out is the first record, never the now-suspended card read again
    class Flaky(JourneyAnki):
        failed = False

        def add_tags(self, ids, tag):
            if not self.failed:
                self.failed = True
                raise OSError("Anki stopped")
            super().add_tags(ids, tag)

    swap_id, anki = _made_journey_swap(ledger, "ja", [{"reps": 3, "type": 2, "queue": 2}], anki=Flaky())
    assert anki.cards_[9000]["queue"] == -1 and swap.SWAP_TAG not in anki.notes_[900]["tags"]
    swap.look(Steps(), ledger, "ja", anki=anki, files=5)
    assert swap.SWAP_TAG in anki.notes_[900]["tags"]
    swap.undo(anki, ledger, "ja", swap_id, open_store=lambda: library.open_store("ja"))
    assert anki.cards_[9000]["queue"] == 2                                              # back in reviews


def test_with_two_cards_ruled_the_journey_swap_leaves_the_old_card_in_reviews(ledger, monkeypatch):
    # the one place the ruling turns (Sonic may say two cards): the old card is only tagged, and Undo takes the tag
    monkeypatch.setattr(swap, "JOURNEY_TAKES_OLD", False)
    swap_id, anki = _made_journey_swap(ledger, "ja", [{"reps": 3, "type": 2, "queue": 2}])
    assert anki.cards_[9000]["queue"] == 2 and swap.SWAP_TAG in anki.notes_[900]["tags"]
    swap.undo(anki, ledger, "ja", swap_id, open_store=lambda: library.open_store("ja"))
    assert anki.cards_[9000]["queue"] == 2 and swap.SWAP_TAG not in anki.notes_[900]["tags"]
    assert not [e for e in anki.log if e[0] in ("suspend", "unsuspend", "set_flag")]


def test_a_look_that_takes_the_old_card_while_undo_runs_is_put_back_by_that_undo(ledger, monkeypatch):
    # Anki was busy at the look that made it (untagged, nothing taken); the press's Undo deletes the new card, and a
    # look takes the writer in the gap before Undo's own: Undo reads what that look took, under its lock
    anki = JourneyAnki()
    anki.busy = True
    swap_id, anki = _made_journey_swap(ledger, "ja", [{"reps": 3, "type": 2, "queue": 2}], anki=anki)
    assert _row(ledger, swap_id)["took"] is None and anki.cards_[9000]["queue"] == 2
    anki.busy = False
    run = tidy.run

    def then_a_look(*a, **k):
        got = run(*a, **k)
        swap._tag_waiting(ledger, "ja", anki)
        return got

    monkeypatch.setattr(tidy, "run", then_a_look)
    swap.undo(anki, ledger, "ja", swap_id, open_store=lambda: library.open_store("ja"))
    assert anki.deleted == [950] and anki.cards_[9000]["queue"] == 2


def test_a_loop_swap_undone_while_a_journey_swap_holds_the_old_card_leaves_it_out_until_that_one_is_undone(ledger):
    # the journey ⇄ took the card out; the loop's swap of the same card (its twin: the same new card) is undone first
    swap_id, anki = _made_journey_swap(ledger, "ja", [{"reps": 3, "type": 2, "queue": 2}])
    loop = swap.make_card("ja", CASES["ja"][0], old_note=900, old_card=9000, ledger=ledger, wake=False)
    swap._set(ledger, loop["id"], state=swap.MADE, new_note=950, tagged=1)
    swap.undo(anki, ledger, "ja", loop["id"], open_store=lambda: library.open_store("ja"))
    assert anki.cards_[9000]["queue"] == -1 and anki.deleted == []          # one out while the journey's card stands
    swap.undo(anki, ledger, "ja", swap_id, open_store=lambda: library.open_store("ja"))
    assert anki.deleted == [950] and anki.cards_[9000]["queue"] == 2


def test_a_loop_swap_undone_hands_the_card_it_would_put_back_to_the_journey_swap_still_holding_it(ledger):
    # the learner had put the card away with the loop's move (suspended, green): the journey ⇄ took nothing; the loop's
    # Undo takes its flag off but leaves the card out while the journey's card stands; that one's Undo puts it back
    swap_id, anki = _made_journey_swap(ledger, "ja", [{"reps": 3, "type": 2, "queue": -1, "flags": 3}])
    assert _row(ledger, swap_id)["took"] == "[]"
    loop = swap.make_card("ja", CASES["ja"][0], old_note=900, old_card=9000, ledger=ledger, wake=False)
    swap._set(ledger, loop["id"], state=swap.MADE, new_note=950, tagged=1)
    swap.undo(anki, ledger, "ja", loop["id"], open_store=lambda: library.open_store("ja"))
    assert (anki.cards_[9000]["queue"], anki.cards_[9000]["flags"]) == (-1, 0)
    swap.undo(anki, ledger, "ja", swap_id, open_store=lambda: library.open_store("ja"))
    assert (anki.cards_[9000]["queue"], anki.cards_[9000]["flags"]) == (2, 0)


def test_a_loop_swap_made_never_suspends_its_old_card(ledger):
    # the loop's Suspend + Green already took it out; one the learner put back in reviews before it was made stays there
    lang, word = "ja", CASES["ja"][0]
    _library(lang)
    got = swap.make_card(lang, word, old_note=900, old_card=9000, ledger=ledger, wake=False)
    swap._set(ledger, got["id"], state=swap.MADE, new_note=950)
    anki = JourneyAnki()
    anki.add(900, "Japanese", word, 1, cards=[{"reps": 3, "type": 2, "queue": 2}])
    swap._tag_waiting(ledger, lang, anki)
    assert swap.SWAP_TAG in anki.notes_[900]["tags"] and anki.cards_[9000]["queue"] == 2
    assert not [e for e in anki.log if e[0] == "suspend"]


def test_a_line_id_too_long_to_be_a_line_or_a_padded_word_is_answered_in_words(ledger):
    lang, (word, _old, other) = "ja", CASES["ja"]
    item = _library(lang)
    assert _refused("card/make", lang, word, "1:" + "9" * 5000).message == door_routes.NO_LINE
    got = _press("card/make", lang, " " * 70 + word, _line(lang, item, other)[0])        # the word, its spaces off
    assert got["asked"] and _row(ledger, got["id"])["word"] == word


def test_a_ledger_from_before_the_ruling_gains_the_record_of_what_a_press_took(ledger):
    # a 3.0.18 ledger's swaps table has no `took`: without it every journey ⇄'s look would fail its write, untagged
    ledger.conn.execute(swap._SQL.replace(",\n  took TEXT)", ")"))
    assert "took" not in {r[1] for r in ledger.conn.execute("PRAGMA table_info(swaps)")}
    swap_id, anki = _made_journey_swap(ledger, "ja", [{"reps": 3, "type": 2, "queue": 2}])
    assert _row(ledger, swap_id)["took"] == "[9000]" and anki.cards_[9000]["queue"] == -1


def test_hello_lists_both_routes_so_the_page_shows_swap_and_add_now():
    routes = journey_door.hello({"lang": "ja"}, journey_door.App())["routes"]
    assert {"swap/queue", "card/make"} <= set(routes)
