"""Kyou-SH3: Tidy's guarantee, made true and pinned (Tidy runs with no switch on one condition: it only ever takes cards
Surasura made that were never reviewed, and every tidy can be undone).

What each test holds still:
- **the guarantee, one function (`tidy.why_kept`):** a card is Tidy's to take only if Connect made it (the library's
  made-words record holds the note and Connect's ledger made it — its tag alone is not enough: you can add a tag), it
  has no review history at all (a card answered once and reset to new is yours), you never changed it (edited,
  tagged, flagged, buried, suspended, in a filtered deck) and you never asked for it (*Add now*, journey v3 D3: the
  named seam, `asked`). Each "never" is pinned through `tidy.run` and through Connect's look, automatic and *Tidy now*
  alike;
- **the backup is read back before anything is deleted:** the package readable and holding every note (count and
  ids), notes.json holding them, each clip's bytes matching its sha1 — a backup that is truncated, damaged or can't be
  written deletes nothing, puts every card home, and the window says so (*Needs you*'s card; *Tidy now*'s line);
- **Undo after a re-mine:** a note whose word has a card Surasura made again since is left out (never two cards for a
  word), and the answer says how many;
- **the words:** the card says the cards were deleted with a copy kept (not "set aside"), and its ? says Tidy clears
  down to your limit.

What a wrong answer costs: a learner's card deleted (one they reviewed, edited, or made by hand with Surasura's tag),
a delete whose backup can't give it back, or two cards for one word after an Undo. Anki is the Kyou-SH2 suite's fake
(a real package: SQLite in a zip); the ledger and the library store are real. ja + zh.
"""
import contextlib
import os
import time

import pytest

from app.connect import library, runner, shelf, status, tidy, undo
from app.services import needs
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.test_kyou_sh2_tidy import WORDS, _anki, _mined, _opener, ledger  # noqa: F401  (the fixture)

DECK = "日本語::Mining"


# --------------------------------------------------------------------------- #
# The guarantee: every "never", one card each (note 104, the lowest), through tidy.run
# --------------------------------------------------------------------------- #
def _answered_once(anki, n, done_at):
    anki.cards_[n * 10].update(reps=1, type=1, queue=1)
    anki.history.add(n * 10)


def _answered_then_reset(anki, n, done_at):
    # Anki's *Reset* (Forget) with *reset repetition and lapse counts*: the card reads new again, its history stays
    anki.cards_[n * 10].update(reps=0, type=0, queue=0, lapses=0)
    anki.history.add(n * 10)


def _edited(anki, n, done_at):
    anki.notes_[n]["fields"]["Word"]["value"] += "（自分のメモ）"
    anki.notes_[n]["mod"] = done_at + 3600


def _tagged(anki, n, done_at):
    anki.notes_[n]["tags"].append("my::favourites")
    anki.notes_[n]["mod"] = done_at + 3600        # a tag added is a note change: its mod moves


def _flagged(anki, n, done_at):
    anki.cards_[n * 10].update(flags=1)


def _suspended(anki, n, done_at):
    anki.cards_[n * 10].update(queue=-1)


def _buried(anki, n, done_at):
    anki.cards_[n * 10].update(queue=-3)


def _filtered(anki, n, done_at):
    anki.filtered.add(n * 10)


NEVER = {"answered_once": (_answered_once, undo.STUDIED),
         "answered_then_reset_to_new": (_answered_then_reset, undo.STUDIED),
         "edited": (_edited, undo.CHANGED),
         "tagged_by_you": (_tagged, undo.CHANGED),
         "flagged": (_flagged, undo.FLAGGED),
         "suspended_by_you": (_suspended, undo.SUSPENDED),
         "buried": (_buried, undo.BURIED),
         "in_a_filtered_deck": (_filtered, tidy.FILTERED)}


@pytest.mark.parametrize("why", [tidy.AUTO, tidy.NOW])
@pytest.mark.parametrize("case", sorted(NEVER))
def test_a_card_you_reviewed_or_changed_is_never_tidied(ledger, case, why):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    make, said = NEVER[case]
    make(anki, 104, done_at)
    done = tidy.run(anki, ledger, "ja", [104, 105], why=why, open_store=_opener("ja"))
    assert 104 in anki.notes_ and 104 not in anki.deleted, f"{case}: the card is yours"
    assert done["deleted"] == [105] and [k for k in done["kept"] if k[0] == 104] == [[104, said]]
    with c.store("ja") as s:
        assert WORDS["ja"][3] in library.made_words_all(s), "its word stays made: its card is still in Anki"


def test_a_card_answered_then_reset_to_new_is_yours_in_chinese_too(ledger):
    item, tag, done_at = _mined(ledger, "zh")
    anki = _anki("zh", tag, done_at)
    _answered_then_reset(anki, 106, done_at)
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, "zh", [106], open_store=_opener("zh"))
    assert anki.deleted == [] and anki.cards_[1060]["deckName"] == DECK


def test_a_card_you_made_by_hand_with_surasuras_tag_is_never_tidied(ledger):
    # why: a tag is something a learner can add (or copy with a note): only Connect's own record says it made a card
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.add(107, tag, "手作り", done_at - 60)                  # yours: Surasura's tag, made by your hand
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, "ja", [107], why=tidy.NOW, open_store=_opener("ja"))
    assert 107 in anki.notes_ and anki.deleted == []


def test_a_card_the_library_doesnt_record_as_made_is_never_tidied_even_with_connects_tag_and_ledger_row(ledger):
    # why: the made-words record is the guarantee's first clause — the tag and the ledger's row alone never are
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    with c.store("ja") as s:
        library.unmake(s, item, [104], [WORDS["ja"][3]])      # the library no longer holds 104 as made
    done = tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    assert done["deleted"] == [105] and [k for k in done["kept"] if k[0] == 104] == [[104, tidy.NOT_MADE]]


def test_with_no_library_store_nothing_is_tidied(ledger):
    # JSON mode (no store): there is no made-words record, so no card is Connect's to delete
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, "ja", [104, 105], open_store=lambda: None)
    assert anki.deleted == []


def test_review_history_that_cant_be_read_keeps_every_card(ledger):
    # why: never deleted unread — an Anki that can't say whether a card was reviewed keeps it
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.reviewed = lambda ids: None
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    assert anki.deleted == []


def _info(note_id=104, tag="surasura::connect::t-1", mod=1000):
    return {"noteId": note_id, "tags": [tag], "mod": mod, "cards": [note_id * 10], "fields": {}}


def _card(note_id=104, **values):
    return {note_id * 10: dict({"cardId": note_id * 10, "reps": 0, "type": 0, "queue": 0, "flags": 0}, **values)}


@pytest.mark.parametrize("clause, args, said", [
    ("Connect made it", dict(made=set()), tidy.NOT_MADE),
    ("Connect's ledger made it", dict(done_at=None), tidy.NOT_MADE),
    ("its tag", dict(info=_info(tag="my-own")), undo.NOT_ITS_TAG),
    ("you asked for it (Add now)", dict(asked={104}), tidy.ASKED),
    ("no review history", dict(reviewed={1040}), undo.STUDIED),
    ("never studied", dict(cards=_card(reps=1, type=1, queue=1)), undo.STUDIED),
    ("unchanged", dict(info=_info(mod=99999)), undo.CHANGED),
    ("not flagged", dict(cards=_card(flags=2)), undo.FLAGGED),
    ("not suspended", dict(cards=_card(queue=-1)), undo.SUSPENDED),
    ("not buried", dict(cards=_card(queue=-3)), undo.BURIED),
    ("not in a filtered deck", dict(filtered={1040}), tidy.FILTERED),
])
def test_the_guarantee_is_one_function_and_every_clause_keeps_the_card(clause, args, said):
    # mutants on `why_kept`: each clause alone keeps the card; with none of them it is Tidy's to take
    base = dict(info=_info(), cards=_card(), made={104}, reviewed=set(), filtered=set(), done_at=1000, shelf={},
                asked=frozenset())
    assert tidy.why_kept(**base) is None, "Connect's own, never reviewed, never changed: Tidy's"
    assert tidy.why_kept(**dict(base, **args)) == said, clause


def test_the_asked_for_seam_is_named_and_empty_until_add_now_is_built(ledger):
    # journey v3 D3's *Add now* isn't built yet: the seam is there, in the same check, and asks nothing of Anki
    assert tidy.asked_for(ledger, "ja", [104, 105]) == frozenset()


# --------------------------------------------------------------------------- #
# Automatic and *Tidy now* alike: Connect's look over a pile of nothing but "nevers"
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("now", [False, True])
def test_connects_look_and_tidy_now_take_none_of_the_nevers(ledger, monkeypatch, now):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    for n, case in zip(range(101, 107), ["answered_once", "answered_then_reset_to_new", "edited", "flagged",
                                         "suspended_by_you", "in_a_filtered_deck"]):
        NEVER[case][0](anki, n, done_at)
    anki.add(107, tag, "手作り", done_at - 60)                  # made by hand with Surasura's tag
    words = WORDS["ja"]
    steps = runner.Steps({"connect_enabled": True})
    steps.cap = lambda _l: 1
    steps.waiting_count = lambda _l: None                     # *Tidy now* reads the count again: kept as seen
    steps._open = lambda _l: contextlib.nullcontext(object())
    monkeypatch.setattr(shelf, "finished_items", lambda store, made: set())
    steps._places = lambda lang, loaded, keys: (lambda word, item_, ahead_only=False: words.index(word)
                                                if word in words else runner.OFF_LIST)
    steps._listed_keys = lambda _l: {w: True for w in words}
    with c.store("ja") as s:
        made = shelf.made_notes(s)
    notes = list(range(101, 108))
    steps._waiting_seen = {"ja": (frozenset(notes), dict(made), frozenset(),
                                  {n: (made[n][1], made[n][0]) if n in made else (None, runner.YOURS) for n in notes})}
    monkeypatch.setattr(tidy, "AnkiConnectTidy", lambda url, wait=10.0: anki)
    steps.after_write = lambda _l: None
    with pytest.raises(tidy.Refused) as e:
        steps.tidy("ja", ledger, now=now)
    assert e.value.say == tidy.ALL_KEPT and anki.deleted == []
    assert all(card["deckName"] == DECK for card in anki.cards_.values()), "every card in its own deck"


# --------------------------------------------------------------------------- #
# F4: the backup read back before anything is deleted
# --------------------------------------------------------------------------- #
def _damaging(anki, damage):
    export = anki.export_package

    def export_then_damage(deck, path):
        ok = export(deck, path)
        damage(os.path.dirname(path), path)
        return ok
    anki.export_package = export_then_damage


def _truncate(path, keep=20):
    with open(path, "rb") as f:
        data = f.read()
    with open(path, "wb") as f:
        f.write(data[:keep])


BAD_BACKUPS = {
    "the package truncated": lambda folder, package: _truncate(package),
    "a clip truncated": lambda folder, package: _truncate(os.path.join(folder, "media", f"sl-{4:016x}.mp3"), 3),
    "a clip missing": lambda folder, package: os.remove(os.path.join(folder, "media", f"sl-{4:016x}.mp3")),
    "notes.json truncated": lambda folder, package: _truncate(os.path.join(folder, "notes.json")),
}


@pytest.mark.parametrize("bad", sorted(BAD_BACKUPS))
def test_a_backup_that_doesnt_read_back_deletes_nothing_and_puts_every_card_home(ledger, bad):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    media = dict(anki.media)
    _damaging(anki, BAD_BACKUPS[bad])
    with pytest.raises(tidy.Refused) as e:
        tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    assert e.value.say == tidy.NOT_READ_BACK, bad
    assert anki.deleted == [] and anki.media == media, "nothing deleted: no note, no clip"
    assert {anki.cards_[1040]["deckName"], anki.cards_[1050]["deckName"]} == {DECK}, "back in their deck"
    assert ledger.conn.execute("SELECT state FROM tidies").fetchone()[0] == tidy.UNSAVED
    with c.store("ja") as s:
        assert set(WORDS["ja"]) <= library.made_words_all(s), "no word freed"


def test_a_package_with_one_note_twice_is_no_backup(ledger, monkeypatch):
    # the read-back counts the notes too, not only their ids
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    monkeypatch.setattr(tidy, "_package_note_ids", lambda path: [104, 105, 105])
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    assert anki.deleted == []


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_backup_folder_that_cant_be_written_deletes_nothing_and_moves_nothing(ledger, lang):
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    blocker = tidy._folder(ledger)
    os.makedirs(os.path.dirname(blocker), exist_ok=True)
    with open(blocker, "w", encoding="utf-8") as f:           # a file where the backups' folder should be
        f.write("not a folder")
    with pytest.raises(tidy.Refused) as e:
        tidy.run(anki, ledger, lang, [104, 105], open_store=_opener(lang))
    assert e.value.say == tidy.NOT_READ_BACK
    assert anki.deleted == [] and not any(entry[0] == "change_deck" for entry in anki.log)
    assert ledger.conn.execute("SELECT state FROM tidies").fetchone()[0] == tidy.UNSAVED


def test_a_backup_that_didnt_read_back_is_said_in_needs_you_and_by_tidy_now(ledger, tmp_path, monkeypatch):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    _damaging(anki, BAD_BACKUPS["a clip truncated"])
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    rec = status.read(["ja"], path=str(tmp_path / "connect" / "ledger.sqlite"))["languages"]["ja"]
    assert rec["tidied"] is None and rec["tidy_unsaved"]["cards"] == 2
    entry = needs._tidy_unsaved_entry(rec, frozenset())
    assert entry.kind == needs.TIDIED and entry.actions == ("leave_tidy",), "nothing to undo: only OK"
    assert entry.title == needs.STRINGS["tidy_unsaved_title"].format(n=2) and entry.say
    assert needs._tidy_unsaved_entry(rec, frozenset(), frozenset({entry.key})) is None, "OK answers it"
    # a later tidy that went through: the old failure is no longer the news
    anki.export_package = type(anki).export_package.__get__(anki)
    done = tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    rec = status.read(["ja"], path=str(tmp_path / "connect" / "ledger.sqlite"))["languages"]["ja"]
    assert rec["tidy_unsaved"] is None and rec["tidied"]["id"] == done["id"]
    # *Tidy now* says it in its own line (`act` → the Settings row's *Not tidied: …*)
    from app.cli.contract import CliError
    with pytest.raises(CliError) as e:
        tidy._guarded({}, lambda _l: (_ for _ in ()).throw(tidy.Refused(tidy.NOT_READ_BACK)),
                      lambda: contextlib.nullcontext(ledger))
    assert e.value.message == tidy.NOT_READ_BACK


# --------------------------------------------------------------------------- #
# F5: Undo after the word was mined again
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("keep_ids", [True, False])
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_undo_leaves_out_a_card_whose_word_was_mined_again_and_says_how_many(ledger, lang, keep_ids):
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    done = tidy.run(anki, ledger, lang, [104, 105, 106], open_store=_opener(lang))
    # the word of 105 climbed back and Connect made a card for it again, from another episode
    again = int(time.time() * 1000)
    with c.store(lang) as s:
        other = s.ids("now")[1]
        library.record_batch(s, other, {WORDS[lang][4]: [again]}, "2026-11-22T10:00:00Z", batch="t-2")
    anki.add(again, tag, WORDS[lang][4], done_at + 10)
    anki.keep_ids = keep_ids
    back = tidy.restore(anki, ledger, done["id"], _opener(lang))
    assert back["back"] == 2 and back["skipped"] == [105] and back["missing"] == []
    by_word = {}
    for note in anki.notes_.values():
        by_word.setdefault(note["fields"]["Word"]["value"], []).append(note["noteId"])
    assert by_word[WORDS[lang][4]] == [again], "one card for the word: the new one"
    assert len(by_word[WORDS[lang][3]]) == 1 and len(by_word[WORDS[lang][5]]) == 1, "the others back"
    assert not any(card["deckName"].startswith("Surasura Tidy") for card in anki.cards_.values())
    with c.store(lang) as s:
        rows = {r[1]: r[2] for r in library.made_rows(s, [again])["words"]}
        assert rows[WORDS[lang][4]] == [again], "the word's record holds only its new card"
    assert tidy.tidy_row(ledger, done["id"])["state"] == tidy.UNDONE


@pytest.mark.parametrize("tidied", [[104, 105], [105]])
def test_a_kill_after_the_left_out_copy_went_finishes_with_it_still_left_out(ledger, monkeypatch, tidied):
    # own read O1: the next look's `_restored` no longer finds the deleted copy; it is left out, never "missing";
    # state lens #2: when every tidied card was left out, the Undo still ends `undone` (never offered again)
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    done = tidy.run(anki, ledger, "ja", tidied, open_store=_opener("ja"))
    again = int(time.time() * 1000)
    with c.store("ja") as s:
        library.record_batch(s, s.ids("now")[1], {WORDS["ja"][4]: [again]}, "2026-11-22T10:00:00Z", batch="t-2")
    anki.add(again, tag, WORDS["ja"][4], done_at + 10)
    with monkeypatch.context() as killed:
        killed.setattr(tidy, "_cards_home", lambda *a, **k: (_ for _ in ()).throw(KeyboardInterrupt()))
        with pytest.raises(KeyboardInterrupt):
            tidy.restore(anki, ledger, done["id"], _opener("ja"))
    assert 105 not in anki.notes_ and tidy.tidy_row(ledger, done["id"])["state"] == tidy.RESTORING
    row = tidy.tidy_row(ledger, done["id"])
    back = tidy._restored(anki, ledger, row, _opener("ja"))
    assert back["back"] == len(tidied) - 1 and back["skipped"] == [105] and back["missing"] == []
    assert tidy.tidy_row(ledger, done["id"])["state"] == tidy.UNDONE


def test_a_second_card_the_word_had_before_the_tidy_doesnt_keep_the_tidied_one_out(ledger):
    # bounds lens #1: only a card made after the tidy is "mined again"; the word's two cards before it come back as two
    item, tag, done_at = _mined(ledger, "ja")
    with c.store("ja") as s:
        library.record_batch(s, item, {WORDS["ja"][4]: [107]}, "2026-11-21T10:00:00Z", batch="t-1")
    anki = _anki("ja", tag, done_at)
    anki.add(107, tag, WORDS["ja"][4], done_at - 60, cards=[{"reps": 3, "type": 2, "queue": 2}])    # studied: kept
    done = tidy.run(anki, ledger, "ja", [105], open_store=_opener("ja"))
    back = tidy.restore(anki, ledger, done["id"], _opener("ja"))
    assert back["back"] == 1 and back["skipped"] == [] and 105 in anki.notes_


def test_undo_never_deletes_a_copy_whose_card_has_a_review_line(ledger):
    # contract lens #3: answered in Anki's reviewer the moment it came back — it is yours now, so it stays (two cards
    # for the word beat a deleted card you answered)
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    done = tidy.run(anki, ledger, "ja", [105], open_store=_opener("ja"))
    again = int(time.time() * 1000)
    with c.store("ja") as s:
        library.record_batch(s, s.ids("now")[1], {WORDS["ja"][4]: [again]}, "2026-11-22T10:00:00Z", batch="t-2")
    anki.add(again, tag, WORDS["ja"][4], done_at + 10)
    anki.history.add(1050)                      # the copy's card (the import keeps its id) answered
    back = tidy.restore(anki, ledger, done["id"], _opener("ja"))
    assert back["skipped"] == [] and 105 in anki.notes_ and back["back"] == 1


def test_undo_with_nothing_mined_again_leaves_nothing_out(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    done = tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    back = tidy.restore(anki, ledger, done["id"], _opener("ja"))
    assert back["back"] == 2 and back["skipped"] == []


def test_a_card_mined_again_then_deleted_by_you_doesnt_keep_the_old_one_out(ledger):
    # the record may still name a card you deleted since: only a card Anki has counts as "a card again"
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    done = tidy.run(anki, ledger, "ja", [105], open_store=_opener("ja"))
    with c.store("ja") as s:
        library.record_batch(s, s.ids("now")[1], {WORDS["ja"][4]: [int(time.time() * 1000)]}, "2026-11-22T10:00:00Z",
                             batch="t-2")
    back = tidy.restore(anki, ledger, done["id"], _opener("ja"))
    assert back["back"] == 1 and back["skipped"] == [] and 105 in anki.notes_


# --------------------------------------------------------------------------- #
# The words a learner sees (PROVISIONAL)
# --------------------------------------------------------------------------- #
def test_the_card_says_deleted_with_a_copy_kept_never_set_aside_and_the_help_says_down_to_your_limit():
    for key in ("tidied_title", "tidied_title_one", "tidied_say", "tidied_say_now"):
        assert "set aside" not in needs.STRINGS[key].lower() and "set-aside" not in needs.STRINGS[key].lower()
    assert "deleted" in needs.STRINGS["tidied_title"] and "copy" in needs.STRINGS["tidied_title"]
    assert "down to your limit" in needs.STRINGS["tidied_say"]
    from app.qt import settings_strings as S
    assert "down to your limit" in S.ROWS["connect_tidy"][1]
