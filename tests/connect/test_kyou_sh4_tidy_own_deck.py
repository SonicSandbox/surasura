"""Kyou-SH4: a card you moved into a deck of your own is yours — Tidy keeps it (Sonic 2026-11-22: yes; his rule P3: a
card you changed, flagged, buried, suspended or put in a filtered deck is yours, and moving a card is changing it).

What each test holds still:
- **the rule is one clause of the guarantee (`tidy.why_kept`):** a card is Tidy's only while every card of its note
  is in its home — the deck Surasura last put it in (Connect's ledger, `homes`: the deck its batch made it in, or the
  deck *Move them to X* moved it to) — or in the deck Surasura shows for new cards now (a card there is in Surasura's
  deck, never one of yours). Anywhere else (a deck of yours, a subdeck you made, a deck renamed since) it is kept;
- **Surasura's own moves never make a card yours:** Connect's placement (the batch's deck, recorded by
  `ledger.end_batch`), *Move them to X* (`decks.move`, and its Undo puts the record back as it was), Tidy's own deck
  while it backs a card up, an Undo that gives a card a new id — and Junban, which never moves a deck at all: its
  reorder moves a card's due and the card's `mod`, the trap the guarantee's third review found (register G3);
- **moved and moved back:** Tidy's again, unless something else of P3 holds (a flag, a suspend …);
- **a card made before this change** (no record of its home) is kept, unless it sits in the deck Surasura shows now:
  Tidy never deletes on a guess;
- unchanged: a filtered deck keeps its own reason; a deck deleted in Anki takes its cards with it; Anki absent → no
  tidy.

What a wrong answer costs: a card the learner filed in a deck of their own deleted (with Undo, but deleted), or Tidy
mistaking Junban's or Connect's own moves for the learner's and never clearing the pile. Anki is the Kyou-SH2 suite's
fake (a real package), *Move them to X* the one-deck suite's fake AnkiConnect; the ledger and the library store are
real. ja + zh.
"""
import contextlib
import json
import os
from unittest import mock

import pytest

from app import anki_connect
from app.connect import decks, runner, tidy, undo
from app.connect.ledger import Ledger
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.fake_steps import FakeSteps
from tests.connect.test_kyou_sh2_tidy import FakeAnki, _anki, _mined, _opener, ledger  # noqa: F401  (the fixture)
from tests.connect import test_one_deck as one

DECK = "日本語::Mining"                                    # where the suite's batch made every card (`_mined`)
OWN = {"ja": "日本語::自分の単語帳", "zh": "中文::我的生词本"}       # a deck of the learner's own
SHOWN = "Japanese::Mining Deck"                           # the deck Surasura shows for new cards (順's), when set


def _kept(done, note):
    return [k for k in done["kept"] if k[0] == note]


def _made_before_this_change(ledger):
    ledger.conn.execute("DELETE FROM homes")              # a card made before homes were recorded


def _check(anki, ledger, lang, notes, ours=()):
    """`tidy.check` on its own (no write): {note id: why kept}, and the notes that may go."""
    go, kept, _i, _c = tidy.check(anki, ledger, notes, tidy._made_notes(_opener(lang), notes), ours=frozenset(ours))
    return go, dict((n, why) for n, why in kept)


# --------------------------------------------------------------------------- #
# A card you moved: yours
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("why", [tidy.AUTO, tidy.NOW])
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_you_moved_to_a_deck_of_your_own_is_kept(ledger, lang, why):
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    anki.change_deck([1040], OWN[lang])                 # your move in Anki's browser: only the card's deck changes
    done = tidy.run(anki, ledger, lang, [104, 105], why=why, open_store=_opener(lang))
    assert 104 in anki.notes_ and anki.cards_[1040]["deckName"] == OWN[lang], "yours: kept, where you put it"
    assert done["deleted"] == [105], "the one left in Surasura's deck is still Tidy's (through its own deck and back)"
    assert _kept(done, 104) == [[104, tidy.MOVED]]


def test_a_subdeck_you_made_under_surasuras_deck_is_a_deck_of_your_own(ledger):
    # why: Junban orders a subdeck with its parent, but a subdeck you made and filed a card in is your own filing
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.change_deck([1040], DECK + "::後で見る")
    done = tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    assert done["deleted"] == [105] and _kept(done, 104) == [[104, tidy.MOVED]]


def test_a_note_with_one_card_of_two_moved_is_kept_whole(ledger):
    # why: a deck is a card's; the note goes only whole, so one card filed elsewhere keeps both
    item, tag, done_at = _mined(ledger, "zh")
    anki = FakeAnki()
    anki.add(104, tag, "约定", done_at - 60, deck=DECK, cards=[{"reps": 0, "type": 0, "queue": 0}] * 2)
    anki.add(105, tag, "叹气", done_at - 60, deck=DECK)
    anki.change_deck([1041], OWN["zh"])
    done = tidy.run(anki, ledger, "zh", [104, 105], open_store=_opener("zh"))
    assert done["deleted"] == [105] and _kept(done, 104) == [[104, tidy.MOVED]] and 1040 in anki.cards_


def test_a_deck_renamed_in_anki_keeps_its_cards_tidy_cant_tell_it_is_the_same_deck(ledger):
    # why: the record names the deck; a deck renamed since is no deck Surasura put a card in — kept, never a guess
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.change_deck(sorted(anki.cards_), "日本語::採掘")
    go, kept = _check(anki, ledger, "ja", [104, 105])
    assert go == [] and kept == {104: tidy.MOVED, 105: tidy.MOVED}
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, "ja", [104, 105], open_store=_opener("ja"))
    assert anki.deleted == []


def test_a_deck_deleted_in_anki_took_its_cards_so_there_is_nothing_to_tidy(ledger):
    # Anki deletes a deck's cards with it: their notes are gone, neither kept nor tidied
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.delete_notes([104])
    go, kept = _check(anki, ledger, "ja", [104, 105])
    assert go == [105] and kept == {}


def test_deck_names_are_compared_as_anki_compares_them_case_ignored(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.change_deck([1040], DECK.upper())
    assert _check(anki, ledger, "ja", [104]) == ([104], {})


# --------------------------------------------------------------------------- #
# Surasura's own moves: still Tidy's
# --------------------------------------------------------------------------- #
def test_junbans_reorder_moves_a_cards_due_and_mod_never_its_deck_so_the_card_is_still_tidys(ledger):
    # why: register G3 — the card's `mod` moves with Junban's (and Connect's) repositions too, so it can't say
    # whether you touched the card; the deck can
    item, tag, done_at = _mined(ledger, "zh")
    anki = _anki("zh", tag, done_at)
    anki.cards_[1040].update(mod=done_at + 3600, due=3)
    done = tidy.run(anki, ledger, "zh", [104], open_store=_opener("zh"))
    assert done["deleted"] == [104]


def test_a_card_surasura_moved_to_its_deck_for_you_is_tidys_in_that_deck(ledger):
    # *Move them to X* records X as the card's home: still Tidy's there, even once Settings shows another deck
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    ledger.set_homes([104], SHOWN)
    anki.change_deck([1040], SHOWN)
    assert _check(anki, ledger, "ja", [104], ours=["日本語::新しい"]) == ([104], {})
    assert _check(anki, ledger, "ja", [105], ours=["日本語::新しい"]) == ([105], {}), "105 is still at its home"


def test_the_deck_surasura_shows_now_is_never_a_deck_of_your_own(ledger):
    # why: a card in the deck Surasura mines into and Junban orders is where Surasura puts its cards — moved there by
    # you or by *Move them to X*, it is no filing of yours
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.change_deck([1040], SHOWN)
    assert _check(anki, ledger, "ja", [104], ours=[SHOWN])[1] == {104: tidy.MOVED}, "a home on record: only it counts"
    _made_before_this_change(ledger)
    assert _check(anki, ledger, "ja", [104], ours=[SHOWN.lower()]) == ([104], {}), "no record: the shown deck"


def test_moved_and_moved_back_is_tidys_again_unless_you_changed_it_otherwise(ledger):
    # lean (PROVISIONAL): the deck is all a move changes; back home, nothing of yours is left on the card — unless
    # another of P3's marks is (here a flag)
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    for card in (1040, 1050):
        anki.change_deck([card], OWN["ja"])
        anki.change_deck([card], DECK)
    anki.cards_[1050].update(flags=4)
    go, kept = _check(anki, ledger, "ja", [104, 105])
    assert go == [104] and kept == {105: undo.FLAGGED}


def test_the_filtered_deck_keeps_its_own_reason(ledger):
    # a Custom Study session is a deck Anki moved the card to (and moves it back from): already P3's, unchanged
    item, tag, done_at = _mined(ledger, "zh")
    anki = _anki("zh", tag, done_at)
    anki.change_deck([1040], "Filtered Deck 1")
    anki.filtered.add(1040)
    assert _check(anki, ledger, "zh", [104]) == ([], {104: tidy.FILTERED})


# --------------------------------------------------------------------------- #
# Made before this change: no record of its home
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_card_made_before_homes_were_recorded_is_kept_unless_it_is_in_the_deck_surasura_shows(ledger, lang):
    item, tag, done_at = _mined(ledger, lang)
    anki = _anki(lang, tag, done_at)
    _made_before_this_change(ledger)
    assert _check(anki, ledger, lang, [104, 105]) == ([], {104: tidy.NO_HOME, 105: tidy.NO_HOME}), "in doubt: kept"
    anki.change_deck([1050], OWN[lang])
    assert _check(anki, ledger, lang, [104, 105], ours=[DECK]) == ([104], {105: tidy.NO_HOME})
    with pytest.raises(tidy.Refused):
        tidy.run(anki, ledger, lang, [104, 105], open_store=_opener(lang))      # no deck shown: none goes
    assert anki.deleted == []
    done = tidy.run(anki, ledger, lang, [104, 105], open_store=_opener(lang), ours=DECK)
    assert done["deleted"] == [104] and _kept(done, 105) == [[105, tidy.NO_HOME]]


def _info(note_id=104, tag="surasura::connect::t-1", mod=1000):
    return {"noteId": note_id, "tags": [tag], "mod": mod, "cards": [note_id * 10], "fields": {}}


def _card(note_id=104, **values):
    return {note_id * 10: dict({"cardId": note_id * 10, "reps": 0, "type": 0, "queue": 0, "flags": 0,
                                "deckName": DECK}, **values)}


@pytest.mark.parametrize("clause, args, said", [
    ("in its home", dict(cards=_card(deckName=OWN["ja"])), tidy.MOVED),
    ("a home on record", dict(home=None), tidy.NO_HOME),
    ("a card with no deck named", dict(cards=_card(deckName=None)), tidy.MOVED),
    ("filtered before moved", dict(cards=_card(deckName="Filtered Deck 1"), filtered={1040}), tidy.FILTERED),
])
def test_the_home_is_one_clause_of_the_one_function(clause, args, said):
    base = dict(info=_info(), cards=_card(), made={104}, reviewed=set(), filtered=set(), done_at=1000, shelf={},
                home=DECK)
    assert tidy.why_kept(**base) is None
    assert tidy.why_kept(**dict(base, **args)) == said, clause


def test_the_deck_surasura_shows_counts_as_home_in_the_one_function():
    base = dict(info=_info(), cards=_card(deckName=SHOWN), made={104}, reviewed=set(), filtered=set(), done_at=1000,
                shelf={})
    assert tidy.why_kept(**dict(base, home=None, ours=frozenset({SHOWN.lower()}))) is None, "case ignored"
    assert tidy.why_kept(**dict(base, home=DECK, ours=frozenset({SHOWN}))) == tidy.MOVED, "lens #2: a home wins"
    assert tidy.why_kept(**dict(base, home=DECK, tidying=frozenset({SHOWN}))) is None, "Tidy's own deck"
    assert tidy.why_kept(**dict(base, home=DECK)) == tidy.MOVED


def test_a_card_you_move_while_tidy_writes_its_copy_is_never_overwritten_by_tidys_own_move(ledger):
    # lens #1: Tidy moves the cards into its own deck by id; a move of yours just before would be lost, then read as
    # Tidy's own — the decks are read again first: nothing is deleted, every card stays where it is
    item, tag, done_at = _mined(ledger, "zh")
    anki = _anki("zh", tag, done_at)
    real = anki.media_bytes

    def your_move_meanwhile(name):
        anki.cards_[1040]["deckName"] = OWN["zh"]
        return real(name)
    anki.media_bytes = your_move_meanwhile
    with pytest.raises(tidy.Refused) as e:
        tidy.run(anki, ledger, "zh", [104, 105], why=tidy.NOW, open_store=_opener("zh"))
    assert e.value.say == tidy.MOVED_MEANWHILE and anki.deleted == []
    assert anki.cards_[1040]["deckName"] == OWN["zh"] and anki.cards_[1050]["deckName"] == DECK
    assert ledger.conn.execute("SELECT state FROM tidies").fetchone()[0] == tidy.FAILED, "never *Needs you*'s unsaved"


# --------------------------------------------------------------------------- #
# The record: where Surasura's writers put it
# --------------------------------------------------------------------------- #
class DeckSteps(FakeSteps):
    """The suite's Connect stand-in, its batch answering with the deck it mined into, as `Steps._mine_one` does."""

    def mine(self, lang, job, picked, words, attempt):
        got = super().mine(lang, job, picked, words, attempt)
        return dict(got, deck=self.plan.get("deck"))


def test_connects_batch_records_the_deck_it_made_each_card_in(tmp_path):
    with Ledger(str(tmp_path / "ledger.sqlite")) as book:
        steps = DeckSteps(str(tmp_path), {"line": {"ja": [1]}, "queue": {"ja": [1]}, "deck": DECK})
        runner.run({}, ["ja"], steps=steps, ledger=book, sleep=lambda s: None, looks=1)
        made = [r[0] for r in book.conn.execute("SELECT note_id FROM outcomes WHERE outcome = 'made'")]
        assert len(made) == 3, "the episode's three words"
        assert book.homes(made) == {n: DECK for n in made}


@pytest.mark.parametrize("answer", [{"outcomes": [], "app": "3.7.0"},
                                    "crashed", "cancelled"])
def test_steps_batch_answers_with_the_deck_it_mined_into(monkeypatch, answer):
    # the real `Steps.mine`: its answer names the run's deck (Surasura's shown one, else Anki Miner's), a crash's too
    # (its cards are found by tag and recorded with that batch)
    from types import SimpleNamespace
    from app.cli import verbs
    from app.connect import anki_miner
    monkeypatch.setattr(anki_miner, "find", lambda loaded: "am.exe")
    monkeypatch.setattr(verbs, "_anki_miner_setup", lambda loaded, lang, run_dir, held=None: (
        None, None, SimpleNamespace(word="Word", deck=SHOWN)))

    def batch(*a, **k):
        if answer == "crashed":
            raise anki_miner.AnkiMinerError("crashed", "Anki Miner stopped")
        if answer == "cancelled":
            e = anki_miner.AnkiMinerError("cancelled", "stopped")
            e.stopped = True
            raise e
        return answer
    monkeypatch.setattr(anki_miner, "mine_batch", batch)
    words = [{"word": "一生懸命", "reading": "イッショウケンメイ", "line_start": 3.0}]
    got = runner.Steps({}).mine("ja", {"id": 1, "item_id": 1, "tag": "ab-1"},
                                {"video": "v.mkv", "subtitle": "s.srt", "profile": None}, words, 1)
    assert got["deck"] == SHOWN


def test_a_batch_whose_deck_isnt_known_records_none_and_a_later_record_never_overwrites_a_move(ledger):
    job = ledger.queue("ja", 1, "user", None, store_id="s1")
    ledger.end_batch(job, 1, "uncertain", [{"word": "勇気", "reading": "", "outcome": "made", "note_id": 7}])
    assert ledger.homes([7]) == {}, "a kill's batch read back by its tag: its deck unknown"
    ledger.set_homes([7], SHOWN)
    ledger.end_batch(job, 2, "done", [{"word": "勇気", "reading": "", "outcome": "made", "note_id": 7}], deck=DECK)
    assert ledger.homes([7]) == {7: SHOWN}


def test_steps_tidy_hands_tidy_the_deck_surasura_shows(ledger, monkeypatch):
    from tests.connect.test_kyou_sh2_tidy import _by_list, _seen, WORDS
    from app.connect import shelf
    words = WORDS["ja"]
    took = []
    monkeypatch.setattr(shelf, "finished_items", lambda store, made: set())
    monkeypatch.setattr(tidy, "run", lambda *a, **k: took.append(k.get("ours")) or {"deleted": [], "id": 3})
    for lang, ours in (("ja", SHOWN), ("zh", None)):
        steps = runner.Steps(dict(one._ja(junban_deck=SHOWN, junban_replan_deck=SHOWN), connect_enabled=True))
        steps.cap = lambda _l: 1
        steps._open = lambda _l: contextlib.nullcontext(object())
        steps._places = _by_list(words)
        steps._listed_keys = lambda _l: {w: True for w in words}
        _seen(steps, lang, [101, 102, 103], {101: (1, words[0]), 102: (1, words[1]), 103: (1, words[2])})
        steps.tidy(lang, ledger)
        assert took[-1] == ours, "Chinese never takes the deck recorded for Japanese (AD-1)"


def test_an_undo_that_gives_a_card_a_new_id_carries_its_home(ledger):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)
    anki.keep_ids = False                                # Anki's import gave the notes new ids
    done = tidy.run(anki, ledger, "ja", [104], open_store=_opener("ja"))
    tidy.restore(anki, ledger, done["id"], _opener("ja"))
    assert 104 + 999 in anki.notes_ and ledger.homes([104 + 999]) == {104 + 999: DECK}


class NotesFake(one.FakeAnki):
    """The one-deck suite's AnkiConnect, answering `cardsToNotes` too (*Move them to X* records each note's home)."""

    def __call__(self, request, timeout=None):
        payload = json.loads(request.data.decode("utf-8"))
        if payload["action"] != "cardsToNotes":
            return super().__call__(request, timeout)
        self.requests.append(("cardsToNotes", payload["params"], None))
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps(
            {"result": sorted({self.cards[int(c)][0] for c in payload["params"]["cards"]}), "error": None}).encode()
        return response


@pytest.fixture
def moved(monkeypatch):
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    fake = NotesFake(one.CARDS, filtered={"Filtered Deck 1"})
    from app.connect import library
    monkeypatch.setattr(library, "made_notes_of", lambda lang: {"ja": one.JA_MADE, "zh": one.ZH_MADE}.get(lang, {}))
    decks.forget()
    with Ledger() as book:                               # Connect's ledger, where *Move them to X* records homes
        book.set_homes([101], one.MINER_DECK)
    with mock.patch("urllib.request.urlopen", fake):
        yield fake
    decks.forget()


def test_move_them_to_x_records_x_as_home_and_its_undo_puts_the_record_back(moved):
    got = decks.move(one._ja(), "ja")
    assert got["moved"] == 2
    with Ledger() as book:
        assert book.homes([101, 102, 103]) == {101: one.JA_DECK, 102: one.JA_DECK}, "103 was never moved"
    back = decks.move_back(one._ja(), got["id"])
    assert back["back"] == 2
    with Ledger() as book:
        assert book.homes([101, 102]) == {101: one.MINER_DECK}, "as it was before the move"


def test_a_home_the_ledger_cant_write_never_holds_the_move(moved, monkeypatch):
    # the cards sit in the deck Surasura shows, which is home by itself: only the record is missing
    monkeypatch.setattr(Ledger, "set_homes", lambda self, *a: 1 / 0)
    got = decks.move(one._ja(), "ja")
    assert got["ok"] and got["moved"] == 2


# --------------------------------------------------------------------------- #
# Anki absent; the words
# --------------------------------------------------------------------------- #
def test_with_anki_absent_nothing_is_tidied_or_recorded(ledger, monkeypatch):
    item, tag, done_at = _mined(ledger, "ja")
    anki = _anki("ja", tag, done_at)

    def closed(ids):
        raise anki_connect.AnkiError("Anki isn't open")
    anki.notes = closed
    with pytest.raises(anki_connect.AnkiError):
        tidy.run(anki, ledger, "ja", [104], open_store=_opener("ja"))
    assert ledger.conn.execute("SELECT COUNT(*) FROM tidies").fetchone()[0] == 0 and anki.deleted == []
    monkeypatch.setenv("SURASURA_NO_ANKI_SYNC", "1")
    assert tidy.act({"connect_enabled": True}, "ja") == {"cards": 0, "say": undo.NO_ANKI}


def test_tidy_now_says_a_card_you_moved_is_yours_to_keep():
    # PROVISIONAL (For Sonic, kyou-sh4-register): *Tidy now*'s line when every card past the limit is yours
    assert "moved" in tidy.ALL_KEPT and tidy.ALL_KEPT.startswith("the cards past your limit are yours to keep")
