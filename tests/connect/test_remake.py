"""REMAKE (3.0.19): *Make my new cards again…* — every card in Surasura's deck that was never reviewed removed (a
backup read back first), its words freed and queued again as best-sentence jobs, one Undo putting the notes back.

What each test holds still:
- **the selection** (`tidy.why_kept`'s REMAKE mode, one function): a card with any line in Anki's review log stays — a
  reviewed card, a suspended card once studied, a card reset to new, a legacy card someone studied; a suspended,
  buried or edited card never studied goes (the lead's ruling 1: edits go, kept in the backup); a card carrying a
  daily-loop move stays (Ignore's red flag, Swap's green, Known's suspend + mark: ruling 2); a card from before
  Surasura goes only with the tick and only in Connect's own note type (ruling 3); a subdeck, a filtered deck, a
  swap's new card stay; an unreadable review log keeps every card;
- **the syncs** (ruling 5): Anki syncs under the write lock before anything is read, at the count and again at the
  delete; a sync that fails, or one Anki wants as a full sync, deletes nothing and says why;
- **the record** (ruling 4): only the removed cards' words are freed and each is queued again as a best-sentence job
  (`level.BEST`) at its best line — a word whose card the learner deleted on purpose keeps its empty row and is never
  queued;
- **Undo**: the notes back field for field (note type, tags, deck), their words made again; a card from before whose
  word Connect has made again since is left out (never two cards for one word);
- **the waste on Tidy's path**: one outcomes query a chunk (an index on the note), never one a note.

What a wrong answer costs: a card the learner studied (or studied on the phone, not yet synced) deleted, edits lost
with no copy, a word they deleted on purpose mined again, or two cards for one word after Undo. Anki is the Kyou-SH2
suite's fake (a real package: SQLite in a zip); the ledger and the library store are real. ja + zh.
"""
import json
import time
import types

import pytest

from app.connect import level, library, sentences, tidy, undo
from app.connect.ledger import Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.test_kyou_sh2_tidy import WORDS, FakeAnki, _mined, _opener, ledger  # noqa: F401  (the fixture)

DECK = "日本語::Mining"
LEGACY = {"ja": ["雰囲気", "溜息"], "zh": ["气氛", "叹息"]}


class RemakeAnki(FakeAnki):
    """Tidy's fake with the remake's two asks: the deck's new cards (`deck:"D" -deck:"D::*" is:new`) and Anki's sync
    (`sync_answer`); every read is logged, so the sync's place in the order is seen."""

    def __init__(self):
        super().__init__()
        self.sync_answer = "synced"

    def sync(self):
        self.log.append(("sync",))
        return self.sync_answer

    def notes(self, ids):
        self.log.append(("notes",))
        return super().notes(ids)

    def find_notes(self, query):
        if query.endswith(" is:new"):
            deck = query.split('deck:"', 1)[1].split('"', 1)[0]
            assert f'-deck:"{deck}::*"' in query, "never a subdeck"
            return sorted({card["note"] for card in self.cards_.values()
                           if card["deckName"] == deck and int(card.get("type") or 0) == 0})
        return super().find_notes(query)


def _anki(lang, tag, done_at):
    anki = RemakeAnki()
    for i, w in enumerate(WORDS[lang]):
        anki.add(101 + i, tag, w, done_at - 60, sound=f"sl-{i:016x}.mp3")
    return anki


def _studied(anki, n):
    anki.cards_[n * 10].update(reps=3, type=2, queue=2)
    anki.history.add(n * 10)


def _legacy(anki, lang, n, word_at=0, model="Lapis", reviewed=False):
    """A card from before Connect: made by hand with Anki Miner, no made-words row, no Connect tag."""
    anki.add(n, "anki_miner", LEGACY[lang][word_at], 1_600_000_000, deck=DECK)
    anki.notes_[n]["modelName"] = model
    if reviewed:
        _studied(anki, n)


def _remake(anki, ledger, lang, before=False, settings=None):
    return tidy.remake(anki, ledger, lang, settings or {}, _opener(lang), before=before)


# --------------------------------------------------------------------------- #
# The selection
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_remake_removes_every_never_reviewed_card_and_keeps_every_reviewed_one(ledger, lang):
    # why: Sonic's § 98 — "clean out Anki's backlog cards … if they were not reviewed but suspended, they would be
    # deleted as well"; a card with any review is never touched (a reviewed card, a suspended one once studied, a
    # legacy card someone studied)
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    _studied(anki, 101)                                         # reviewed
    _studied(anki, 102)
    anki.cards_[1020]["queue"] = -1                             # reviewed, then suspended
    anki.cards_[1030]["queue"] = -1                             # suspended, never studied
    anki.cards_[1040]["queue"] = -3                             # buried, never studied
    anki.notes_[105]["fields"]["Word"]["value"] += "（メモ）"     # edited: its edit goes with it, kept in the backup
    anki.notes_[105]["mod"] = done_at + 3600
    _legacy(anki, lang, 201, reviewed=True)                     # from before, studied
    _legacy(anki, lang, 202, word_at=1)                         # from before, never studied
    done = _remake(anki, ledger, lang, before=True)
    assert sorted(done["deleted"]) == [103, 104, 105, 106, 202]
    assert {101, 102, 201} <= set(anki.notes_) and not {103, 104, 105, 106, 202} & set(anki.notes_)
    assert not {101, 102, 201} & {n for n, _w in done["kept"]}, "a studied card isn't new: never even read"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_answered_then_reset_to_new_stays(ledger, lang):
    # why: `is:new` alone is never trusted — Anki's Forget makes a studied card new again; its review log stays
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    anki.history.add(1010)                                      # answered once, reset: type 0, reps 0
    done = _remake(anki, ledger, lang)
    assert 101 in anki.notes_ and [101, undo.STUDIED] in done["kept"]


def test_an_unreadable_review_log_keeps_every_card(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.reviewed = lambda card_ids: None                       # Anki's answer couldn't be read
    with pytest.raises(tidy.Refused) as e:
        _remake(anki, ledger, "ja")
    assert e.value.say == tidy.REMAKE_ALL_KEPT and anki.deleted == []


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_carrying_a_daily_loop_move_stays(ledger, lang):
    # why: the lead's ruling 2 — the loop's move is read from that card (Ignore: Suspend + red; Swap: Suspend + green;
    # Known: Suspend + Mark, the setting's default terms); a plain suspend goes
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    anki.cards_[1010].update(queue=-1, flags=1)                 # Ignore
    anki.cards_[1020].update(queue=-1, flags=3)                 # Swap
    anki.cards_[1030].update(queue=-1)                          # Known
    anki.notes_[103]["tags"].append("marked")
    anki.cards_[1040].update(queue=-1)                          # a plain suspend: goes
    anki.notes_[105]["tags"].append("marked")                   # marked, not suspended: not Known's move — goes
    done = _remake(anki, ledger, lang)
    kept = dict((n, w) for n, w in done["kept"])
    assert kept == {101: undo.FLAGGED, 102: undo.FLAGGED, 103: tidy.KNOWN_MOVE}
    assert sorted(done["deleted"]) == [104, 105, 106]


def test_known_s_move_is_the_learners_own_terms_and_none_when_the_signal_is_off(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.cards_[1010].update(queue=-1)                          # suspended alone: Known's move under ["suspended"]
    done = _remake(anki, ledger, "ja", settings={"known_from_anki": ["suspended"]})
    assert [101, tidy.KNOWN_MOVE] in done["kept"]
    item2, tag2, done2 = _mined(ledger, "zh")
    anki = _anki("zh", tag2, done2)
    anki.cards_[1010].update(queue=-1)
    anki.notes_[101]["tags"].append("marked")
    done = _remake(anki, ledger, "zh", settings={"known_from_anki": []})
    assert 101 in done["deleted"], "the signal off: a suspended, marked card is a plain suspend"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_cards_from_before_stay_while_the_tick_is_off(ledger, lang):
    # why: the lead's ruling 3 — another learner's deck can hold a premade deck's thousands of new cards: off by
    # default
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    _legacy(anki, lang, 201)
    done = _remake(anki, ledger, lang)
    assert 201 in anki.notes_ and [201, tidy.NOT_MADE] in done["kept"]
    assert sorted(done["deleted"]) == [101, 102, 103, 104, 105, 106]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_with_the_tick_only_connects_note_type_goes(ledger, lang):
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    _legacy(anki, lang, 201)                                    # Connect's note type
    _legacy(anki, lang, 202, word_at=1, model="Basic")          # another note type: never offered
    done = _remake(anki, ledger, lang, before=True)
    assert 201 in done["deleted"] and 202 in anki.notes_ and [202, tidy.NOT_MADE] in done["kept"]


def s_item(lang):
    with c.store(lang) as s:
        return s.ids("now")[1]


def test_a_subdeck_card_a_filtered_card_and_a_swaps_new_card_stay(ledger):
    # why: a subdeck is a deck of yours (the search never reaches it); a filtered deck takes the card out of
    # Surasura's deck for now; a swap's new card is one you asked for
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.cards_[1010]["deckName"] = DECK + "::Mine"            # moved into a subdeck of yours
    anki.filtered.add(1020)
    info, cards = anki.notes([103])[0], {1030: anki.cards_[1030]}
    base = dict(info=info, cards=cards, made={103}, reviewed=set(), filtered=set(), done_at=done_at, shelf={},
                home=DECK, ours=frozenset({DECK}), mode=tidy.REMAKE)
    assert tidy.why_kept(**base) is None
    assert tidy.why_kept(**dict(base, asked=frozenset({103}))) == tidy.ASKED
    assert tidy.why_kept(**dict(base, home="Mine::Elsewhere", ours=frozenset())) == tidy.MOVED
    assert tidy.why_kept(**dict(base, home="Older deck")) is None, "in Surasura's deck itself: in place"
    done = _remake(anki, ledger, "ja")
    assert 101 in anki.notes_ and 101 not in done["deleted"], "the subdeck's card isn't even read"
    assert [102, tidy.FILTERED] in done["kept"]


def test_tidy_by_itself_is_unchanged_an_edited_or_suspended_card_is_still_kept_there(ledger):
    # why: the relaxed clauses are the remake's alone — Tidy's own guarantee (no switch) never loosens
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.cards_[1010]["queue"] = -1
    anki.notes_[102]["mod"] = done_at + 3600
    done = tidy.run(anki, ledger, "ja", [101, 102, 103], why=tidy.NOW, open_store=_opener("ja"))
    assert done["deleted"] == [103] and dict((n, w) for n, w in done["kept"]) == {101: undo.SUSPENDED,
                                                                                  102: undo.CHANGED}


def test_an_empty_deck_has_nothing_to_make_again(ledger):
    item, tag, done_at = _mined(ledger, "zh")
    anki = RemakeAnki()
    with pytest.raises(tidy.Refused) as e:
        _remake(anki, ledger, "zh")
    assert e.value.say == tidy.NOTHING_NEW and anki.deleted == []


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_plan_counts_by_kind_and_why_and_deletes_nothing(ledger, lang):
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    _studied(anki, 101)
    anki.cards_[1020]["flags"] = 1
    _legacy(anki, lang, 201)
    plan = tidy.remake_plan(anki, ledger, lang, {}, _opener(lang))
    assert plan["made"] == [103, 104, 105, 106] and plan["before"] == [201]
    assert plan["kept"] == {undo.FLAGGED: 1} and plan["decks"] == [DECK], "a studied card isn't new: not read"
    anki.cards_[1010].update(reps=0, type=0, queue=0)          # ... unless it was reset to new: read, and kept
    assert tidy.remake_plan(anki, ledger, lang, {}, _opener(lang))["kept"] == {undo.STUDIED: 1, undo.FLAGGED: 1}
    assert anki.deleted == [] and not [e for e in anki.log if e[0] == "change_deck"]


# --------------------------------------------------------------------------- #
# The syncs
# --------------------------------------------------------------------------- #
def test_anki_syncs_under_the_lock_before_anything_is_read_for_the_delete(ledger):
    # why: the lead's ruling 5 — a phone review not yet synced must never read as never reviewed
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    _remake(anki, ledger, "ja")
    names = [e[0] for e in anki.log]
    held = names.index("writer")
    first_read = next(i for i, n in enumerate(names) if n == "notes" and i > held)
    assert held < names.index("sync") < first_read, "under the write lock, before the delete's reads"


@pytest.mark.parametrize("answer, said", [("failed: AnkiWeb unreachable", tidy.SYNC_FAILED),
                                          ("full-sync", tidy.SYNC_FULL), ("busy", tidy.SYNC_BUSY)])
def test_a_sync_that_didnt_run_deletes_nothing_and_says_why(ledger, answer, said):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.sync_answer = answer
    with pytest.raises(tidy.Refused) as e:
        _remake(anki, ledger, "ja")
    assert e.value.say == said and anki.deleted == [] and ("export", tidy.TEMP_DECK.format(id=1)) not in anki.log


def test_a_profile_with_no_ankiweb_login_goes_on(ledger):
    item, tag, done_at = _mined(ledger, "zh")
    anki = _anki("zh", tag, done_at)
    anki.sync_answer = "not-signed-in"
    assert len(_remake(anki, ledger, "zh")["deleted"]) == 6


class PhoneAnki(RemakeAnki):
    """Anki whose second sync brings a review made on the phone while the copy was written (`phone`: note ids whose
    card the phone studied); every deck a card is in at each sync is logged."""

    def __init__(self, phone=(), second="synced"):
        super().__init__()
        self.phone, self.second, self.syncs = list(phone), second, 0

    def sync(self):
        self.syncs += 1
        self.log.append(("sync", tuple(sorted({card["deckName"] for card in self.cards_.values()}))))
        if self.syncs == 2:
            for n in self.phone:
                _studied(self, n)
            return self.second
        return self.sync_answer


def _phone_anki(lang, tag, done_at, phone=(), second="synced"):
    anki = PhoneAnki(phone, second)
    for i, w in enumerate(WORDS[lang]):
        anki.add(101 + i, tag, w, done_at - 60, sound=f"sl-{i:016x}.mp3")
    return anki


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_studied_on_the_phone_while_the_copy_was_made_is_kept_and_named(ledger, lang):
    # why: the lead's ruling on session 1's question — check again right before the delete, never rely on a warning:
    # after the copy, the cards go home, Anki syncs again, each one's reviews are read again, and only those still
    # never reviewed go; one reviewed meanwhile is dropped from the delete, named, its backup entry marked kept
    item, tag, done_at = _mined(ledger, lang)
    anki = _phone_anki(lang, tag, done_at, phone=[103])
    done = _remake(anki, ledger, lang)
    assert anki.syncs == 2, "once before the count, once after the copy"
    assert sorted(done["deleted"]) == [101, 102, 104, 105, 106] and 103 in anki.notes_
    assert done["meanwhile"] == [[103, undo.STUDIED]], "named in the result"
    assert [103, undo.STUDIED] in done["kept"]
    row = tidy.tidy_row(ledger, done["id"])
    assert json.loads(row["notes"])["103"]["kept"] == undo.STUDIED, "its backup entry stays, marked kept"
    assert "kept" not in json.loads(row["notes"])["104"]
    assert anki.cards_[1030]["deckName"] == DECK, "home, never left in the temporary deck"
    assert WORDS[lang][2] not in set(done["freed"]), "its word stays made"


def test_the_cards_are_home_before_the_second_sync_so_nothing_temporary_is_uploaded(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _phone_anki("ja", tag, done_at)
    _remake(anki, ledger, "ja")
    temp = tidy.TEMP_DECK.format(id=1)
    syncs = [e for e in anki.log if e[0] == "sync"]
    assert len(syncs) == 2 and temp not in syncs[1][1], "no card in the temporary deck while Anki uploads"
    names = [e[0] for e in anki.log]
    second = [i for i, n in enumerate(names) if n == "sync"][1]
    assert names.index("export") < second, "the copy first"
    assert any(n == "notes" for n in names[second:]), "the cards read again after the second sync"


@pytest.mark.parametrize("answer, said", [("failed: AnkiWeb unreachable", tidy.SYNC_FAILED),
                                          ("full-sync", tidy.SYNC_FULL), ("busy", tidy.SYNC_BUSY)])
def test_a_second_sync_that_didnt_run_deletes_nothing_and_every_card_is_home(ledger, answer, said):
    item, tag, done_at = _mined(ledger, "zh")
    anki = _phone_anki("zh", tag, done_at, second=answer)
    with pytest.raises(tidy.Refused) as e:
        _remake(anki, ledger, "zh")
    assert e.value.say == said and anki.deleted == [] and len(anki.notes_) == 6
    assert {card["deckName"] for card in anki.cards_.values()} == {DECK}
    assert tidy.tidy_row(ledger, 1)["state"] == tidy.FAILED, "said in Needs you; no Undo offered for nothing"


def test_ordinary_tidy_syncs_never_and_deletes_from_its_own_deck_as_before(ledger):
    # why: the re-check is the remake's (it syncs); Tidy by itself keeps its one read in its own deck
    item, tag, done_at = _mined(ledger, "ja")
    anki = _phone_anki("ja", tag, done_at)
    tidy.run(anki, ledger, "ja", [106, 105], open_store=_opener("ja"), limit=2)
    assert anki.syncs == 0 and sorted(anki.deleted) == [105, 106]


# --------------------------------------------------------------------------- #
# The record: only the removed cards' words freed, each queued again at its best line
# --------------------------------------------------------------------------- #
class Steps:
    """What `requeue` reads of Connect's runner: no video anywhere, the library's store id, no books mined."""

    def video(self, lang, job):
        return None

    def store_id(self, lang):
        return "s1"

    def mines(self, lang, kind):
        return False


def _best_jobs(ledger, lang):
    return {j["item_id"]: sorted(tuple(w) for w in json.loads(j["words"])) for j in ledger.jobs(lang)
            if j["kind"] == "level" and j["source"] == level.BEST}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_freed_words_are_queued_again_at_their_best_line(ledger, lang, monkeypatch):
    # why: the lead's ruling 4 — freeing a word queues nothing (a finished job counts as work); each word comes back
    # as a best-sentence job at its best line, even from a watched episode
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    other = s_item(lang)
    best_word = WORDS[lang][0]
    asked = []

    def choose(language, keys, **kw):
        asked.append(sorted(keys))
        return {k: [types.SimpleNamespace(item_id=other)] if k[0] == best_word else [] for k in keys}
    monkeypatch.setattr(sentences, "choose", choose)
    done = _remake(anki, ledger, lang)
    again = tidy.requeue(Steps(), ledger, lang, done, {}, _opener(lang))
    assert len(asked) == 1, "one pick for every word"
    jobs = _best_jobs(ledger, lang)
    assert jobs[other] == [(best_word, "")]
    assert jobs[item] == sorted((w, "") for w in WORDS[lang][1:]), "no better line: the card's own episode"
    assert again == {"queued": 6, "ahead": 0}
    with c.store(lang) as s:
        assert not set(WORDS[lang]) & library.made_words_all(s), "every removed card's word is free"


def test_nearest_queues_each_word_on_its_own_episode(ledger, monkeypatch):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    monkeypatch.setattr(sentences, "choose", lambda *a, **k: pytest.fail("Nearest never asks for the best line"))
    done = _remake(anki, ledger, "ja")
    tidy.requeue(Steps(), ledger, "ja", done, {sentences.SETTING: sentences.NEAREST}, _opener("ja"))
    assert _best_jobs(ledger, "ja") == {item: sorted((w, "") for w in WORDS["ja"])}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_the_learner_deleted_on_purpose_stays_gone(ledger, lang, monkeypatch):
    # why: G1.3-4 — a word whose card you deleted is never made again unless you ask; the remake frees only the
    # cards it removed, so that word's empty row stays and no job names it
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    anki.delete_notes([106])                                    # the learner deleted it in Anki
    anki.deleted.clear()
    with c.store(lang) as s:
        library.notes_gone(s, [106])                            # Connect's deleted-card look: its row emptied
    monkeypatch.setattr(sentences, "choose", lambda language, keys, **kw: {k: [] for k in keys})
    done = _remake(anki, ledger, lang)
    tidy.requeue(Steps(), ledger, lang, done, {}, _opener(lang))
    words = {w for ws in _best_jobs(ledger, lang).values() for w, _r in ws}
    assert WORDS[lang][5] not in words and words == set(WORDS[lang][:5])
    with c.store(lang) as s:
        assert s.conn.execute("SELECT note_ids FROM made_words WHERE word = ?", (WORDS[lang][5],)).fetchone() == ("[]",)


def test_a_word_with_another_card_still_in_anki_isnt_queued(ledger, monkeypatch):
    # why: only a word the record freed comes back — one with a second card (studied, kept) still has a card
    item, tag, done_at = _mined(ledger, "ja")
    with c.store("ja") as s:
        library.record_batch(s, s_item("ja"), {WORDS["ja"][2]: [301]}, "2026-11-22T10:00:00Z", batch="t-9")
    anki = _anki("ja", tag, done_at)
    anki.add(301, tag, WORDS["ja"][2], done_at - 60)
    _studied(anki, 301)
    monkeypatch.setattr(sentences, "choose", lambda language, keys, **kw: {k: [] for k in keys})
    done = _remake(anki, ledger, "ja")
    tidy.requeue(Steps(), ledger, "ja", done, {}, _opener("ja"))
    assert WORDS["ja"][2] not in {w for ws in _best_jobs(ledger, "ja").values() for w, _r in ws}


def test_a_word_from_before_is_queued_only_while_the_list_holds_it(ledger, monkeypatch):
    item, tag, done_at = _mined(ledger, "ja")
    ledger.conn.execute("INSERT INTO listed (language, word, reading) VALUES ('ja', ?, 'ふんいき')", (LEGACY["ja"][0],))
    ledger.conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('listed:ja', 'sig')")
    anki = _anki("ja", tag, done_at)
    _legacy(anki, "ja", 201)                                    # on the list
    _legacy(anki, "ja", 202, word_at=1)                         # not on the list: met again ahead
    other = s_item("ja")
    monkeypatch.setattr(sentences, "choose", lambda language, keys, **kw: {
        k: [types.SimpleNamespace(item_id=other)] if k[0] == LEGACY["ja"][0] else [] for k in keys})
    done = _remake(anki, ledger, "ja", before=True)
    again = tidy.requeue(Steps(), ledger, "ja", done, {}, _opener("ja"))
    assert (LEGACY["ja"][0], "ふんいき") in _best_jobs(ledger, "ja")[other]
    assert again["queued"] == 7 and again["ahead"] == 0


def test_a_word_no_job_can_take_now_is_said_as_ahead(ledger, monkeypatch):
    item, tag, done_at = _mined(ledger, "zh")
    anki = _anki("zh", tag, done_at)
    monkeypatch.setattr(sentences, "choose", lambda language, keys, **kw: {k: [] for k in keys})
    done = _remake(anki, ledger, "zh")
    running = ledger.queue_level("zh", item, [("别的", "")], source="level")      # a raise's job, already started
    ledger.set_state(running, "mining")
    again = tidy.requeue(Steps(), ledger, "zh", done, {}, _opener("zh"))
    assert again == {"queued": 0, "ahead": 6}


# --------------------------------------------------------------------------- #
# Undo
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_undo_puts_the_notes_back_field_for_field(ledger, lang):
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    anki.cards_[1030]["queue"] = -1
    anki.notes_[104]["fields"]["Word"]["value"] += "（メモ）"
    _legacy(anki, lang, 201)
    before = {n: (json.loads(json.dumps(anki.notes_[n])), dict(anki.cards_[n * 10])) for n in anki.notes_}
    done = _remake(anki, ledger, lang, before=True)
    back = tidy.restore(anki, ledger, done["id"], _opener(lang), word_of=tidy.card_word_of({}, lang))
    assert back["back"] == 7 and back["skipped"] == []
    for n, (note, card) in before.items():
        assert anki.notes_[n]["fields"] == note["fields"] and anki.notes_[n]["tags"] == note["tags"]
        assert anki.notes_[n]["modelName"] == note["modelName"]
        assert anki.cards_[n * 10]["deckName"] == card["deckName"] and anki.cards_[n * 10]["queue"] == card["queue"]
    with c.store(lang) as s:
        assert set(WORDS[lang]) <= library.made_words_all(s), "their words made again: no second card for them"


def test_undo_leaves_out_a_card_from_before_whose_word_has_a_new_card(ledger):
    # why: a card from before has no made-words row, so Tidy's F5 couldn't see its word re-made: read by its word
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    _legacy(anki, "ja", 201)
    done = _remake(anki, ledger, "ja", before=True)
    remade = int(time.time() * 1000) + 60_000                   # Connect made it again since (a later note id)
    with c.store("ja") as s:
        library.record_batch(s, s_item("ja"), {LEGACY["ja"][0]: [remade]}, "2026-11-26T10:00:00Z", batch="t-3")
    anki.add(remade, tag, LEGACY["ja"][0], done_at)
    back = tidy.restore(anki, ledger, done["id"], _opener("ja"), word_of=tidy.card_word_of({}, "ja"))
    assert back["skipped"] == [201] and 201 not in anki.notes_ and remade in anki.notes_


# --------------------------------------------------------------------------- #
# The waste on Tidy's path (the standard floor)
# --------------------------------------------------------------------------- #
def test_the_made_jobs_end_is_read_once_a_chunk_by_its_index(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    assert ledger.conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'index' AND name = 'outcomes_note'").fetchone()
    plan = ledger.conn.execute("EXPLAIN QUERY PLAN SELECT o.note_id FROM outcomes o WHERE o.note_id IN (101, 102)")
    assert "outcomes_note" in " ".join(str(r) for r in plan.fetchall())
    seen = []
    ledger.conn.set_trace_callback(lambda sql: seen.append(sql) if "FROM outcomes" in sql else None)
    try:
        go, _k, _i, _c = tidy.check(anki, ledger, list(range(101, 107)), tidy._made_notes(_opener("ja"), range(101, 107)))
    finally:
        ledger.conn.set_trace_callback(None)
    assert go == [101, 102, 103, 104, 105, 106] and len(seen) == 1, seen
    assert tidy._done_ats(ledger, [101, 999]) == {101: done_at} and tidy._done_at(ledger, 999) is None


def test_the_newest_made_job_gives_the_end(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    job = ledger.queue("ja", s_item("ja"), "user", None, store_id="s1")
    ledger.end_batch(job, 1, "done", [{"word": "別", "reading": "", "outcome": "made", "note_id": 101}], deck=DECK)
    ledger.conn.execute("UPDATE jobs SET updated_at = '2030-01-01T00:00:00Z' WHERE id = ?", (job,))
    assert tidy._done_ats(ledger, [101])[101] == undo._epoch("2030-01-01T00:00:00Z")


def test_a_package_of_thousands_waits_longer():
    assert tidy.package_timeout(40) == tidy.PACKAGE_S
    assert tidy.package_timeout(3600) == tidy.PACKAGE_S + 3000 * tidy.PACKAGE_NOTE_S


# --------------------------------------------------------------------------- #
# The window's two presses (on a worker): the count, then the yes
# --------------------------------------------------------------------------- #
@pytest.fixture
def home_ledger(monkeypatch):
    """Connect's own ledger (`ledger.path()`, inside the suite's root): the presses open it themselves; Anki not
    switched off for the run (the suite's guard; the presses are handed the fake)."""
    from app.connect.ledger import path
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    book = Ledger(path())
    try:
        yield book
    finally:
        book.close()


ON = {"connect_enabled": True}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_count_syncs_and_counts_under_the_write_lock_and_deletes_nothing(home_ledger, lang):
    item, tag, done_at = _mined(home_ledger, lang)
    anki = _anki(lang, tag, done_at)
    _legacy(anki, lang, 201)
    plan = tidy.act_remake_plan(ON, lang, anki=anki)
    assert len(plan["made"]) == 6 and plan["before"] == [201] and anki.deleted == []
    names = [e[0] for e in anki.log]
    assert names[0] == "writer" and names[1] == "sync", "the sync first, under the lock"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_yes_removes_queues_the_words_and_says_how_many(home_ledger, lang, monkeypatch):
    item, tag, done_at = _mined(home_ledger, lang)
    anki = _anki(lang, tag, done_at)
    _studied(anki, 101)
    _legacy(anki, lang, 201)
    monkeypatch.setattr(sentences, "choose", lambda language, keys, **kw: {k: [] for k in keys})
    done = tidy.act_remake(ON, lang, before=False, steps=Steps(), anki=anki)
    assert done["cards"] == 5 and done["queued"] == 5 and done["ahead"] == 0 and 201 in anki.notes_
    assert _best_jobs(home_ledger, lang) == {item: sorted((w, "") for w in WORDS[lang][1:])}


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_the_yes_names_a_card_studied_while_the_copy_was_made(home_ledger, lang, monkeypatch):
    # why: the lead's ruling — a card reviewed in the meantime is dropped from the delete and named in the result
    item, tag, done_at = _mined(home_ledger, lang)
    anki = _phone_anki(lang, tag, done_at, phone=[104])
    _legacy(anki, lang, 201)
    anki.phone.append(201)
    monkeypatch.setattr(sentences, "choose", lambda language, keys, **kw: {k: [] for k in keys})
    done = tidy.act_remake(ON, lang, before=True, steps=Steps(), anki=anki)
    assert done["cards"] == 5 and {104, 201} <= set(anki.notes_)
    assert done["studied"] == sorted({WORDS[lang][3], LEGACY[lang][0]})
    assert WORDS[lang][3] not in {w for ks in _best_jobs(home_ledger, lang).values() for w, _r in ks}


def test_the_yes_refuses_in_words_when_anki_didnt_sync(home_ledger):
    from app.cli.contract import CliError
    item, tag, done_at = _mined(home_ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.sync_answer = "failed: timed out"
    with pytest.raises(CliError) as e:
        tidy.act_remake(ON, "ja", steps=Steps(), anki=anki)
    assert tidy.SYNC_FAILED in str(e.value) and anki.deleted == []


def test_with_connect_off_neither_press_reads_anki(home_ledger):
    anki = RemakeAnki()
    assert tidy.act_remake_plan({}, "ja", anki=anki) == {"cards": 0, "say": undo.PREVIEW_OFF}
    assert tidy.act_remake({}, "ja", steps=Steps(), anki=anki) == {"cards": 0, "say": undo.PREVIEW_OFF}
    assert anki.log == []
