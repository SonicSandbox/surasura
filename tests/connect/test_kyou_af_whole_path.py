"""Kyou-AF with J-SWAP: the whole path of a card asked from the journey (journey v3 D3; SPEC §3.3, row 11).

The journey page's *Add now* posts `card/make` on the door (`app/connect/door_routes.py`); the route asks Swap's one
maker with the line pressed; Connect's look makes the card from that line; Junban's next run places it first among
the new cards (`swap.asked_first` → `reposition._asked_first` → `plan(asked=)`). What these tests hold still, end to
end, Japanese and Chinese:

- **one ask:** the card the route asked is the very next new card once Connect has made it; every other new card keeps
  the place it had before the press;
- **two asks:** they come in the order they were pressed, whatever order Connect made them in;
- **an ask undone:** its Undo deletes the card (Tidy's guarantee) and Swap's record says undone: the other ask is still
  first and nothing else moves;
- **a journey ⇄ is not lifted** (D3 is *Add now* only): its new card takes the place Junban gives it, and its old card,
  suspended by Swap once the new one is made (one out, one in), stays out of reviews and out of the order.

What a wrong answer costs: a card the learner asked for buried at the back of a deck of hundreds; two asks shown in
the wrong order; an undone ask still pushing ahead of the learner's own cards; a ⇄ card jumping the queue, or its
old card back among the new ones. Real lines of tests/Test Resources (the Kantan-SL cases); the ledger and the library
store are real; Connect's Anki is Tidy's fake, Junban's the Junban suite's fake collection (the card in both by the
same note id); the DevTest drill `live_kyou_af_whole_path_drill.py` runs the same path on a real Anki.
"""
import os

import pytest

pytest.importorskip("modules.junban")

from app.connect import library, swap  # noqa: E402
from modules.junban import reposition  # noqa: E402
from modules.junban.tests.connect_scene import CONNECT_TAG, ConnectCollection, scene, settings  # noqa: E402
from modules.junban.tests.test_preview_gate import SCENE  # noqa: E402
from modules.junban.tests.test_reposition import FIRST_CARD, FIRST_NOTE, _patched, _settings  # noqa: E402
from tests import cli_helpers as h  # noqa: E402
from tests.connect.test_j_swap_door import JourneyAnki, _connects_card, _library, _line, _press  # noqa: E402
from tests.connect.test_kantan_sl_swap import (CASES, JA, ZH, Anki, Steps, _make_the_job, _row,  # noqa: E402,F401
                                               ledger)  # (`ledger`: the fixture)

# The second word asked, with the real line it is said in (the case's file)
SECOND = {"ja": ("延長", "延長もできますよ"), "zh": ("价格", "这个价格很合理")}
# Chinese new cards around the asks (simplified, as the library's words): two on the list, one of the learner's own
ZH_DECK = [("发展", "这个城市发展得很快。", 3000, [], 0), ("学习", "我每天晚上学习中文。", 5000, [], 0),
           ("关系", "他们的关系一直很好。", 4000, [], 0)]
ZH_LIST = "Word,Orth,Reading,Tier\n发展,发展,,NOW\n关系,关系,,NOW\n"
NOTE0 = FIRST_NOTE + 700        # the deck's notes from here (card ids from FIRST_CARD + 700)


@pytest.fixture(autouse=True)
def _junbans_own_folder(tmp_path, monkeypatch):
    """Junban's undo snapshots in a folder of this test's (as Junban's own suite isolates them)."""
    persistent = tmp_path / "persistent"
    persistent.mkdir()
    monkeypatch.setattr("app.path_utils.get_persistent_user_data_path", lambda: str(persistent), raising=False)


def _entries(lang):
    return list(SCENE) if lang == "ja" else list(ZH_DECK)


def _deck(lang, extra=()):
    """Junban's view of the learner's deck: the language's new cards, then `extra` (word, sentence, FreqSort, tags,
    queue) — note ids NOTE0 + index, so a made note's id is known before Connect makes it."""
    rows = _entries(lang) + list(extra)
    if lang == "ja":
        fake = scene(h.root(), entries=rows, start=700)
    else:
        folder = os.path.join(h.root(), "results")
        os.makedirs(folder, exist_ok=True)
        with open(os.path.join(folder, "priority_learning_list.csv"), "w", encoding="utf-8-sig") as f:
            f.write(ZH_LIST)
        notes, cards = [], []
        for i, (word, sentence, freqsort, tags, queue) in enumerate(rows):
            notes.append({"noteId": NOTE0 + i, "modelName": "Lapis", "tags": list(tags), "fields": {
                "Expression": {"value": word, "order": 0}, "Sentence": {"value": sentence, "order": 1},
                "FreqSort": {"value": str(freqsort), "order": 2}, "MiscInfo": {"value": "", "order": 3}}})
            cards.append({"cardId": FIRST_CARD + 700 + i, "note": NOTE0 + i, "due": 2800 + i, "type": 0,
                          "queue": queue, "deckName": "TheBank"})
        fake = ConnectCollection(cards, notes)
    return fake


def _note_of(lang, word, extra):
    """The note id `_deck` gives the extra row holding `word` (its first)."""
    return NOTE0 + len(_entries(lang)) + [r[0] for r in extra].index(word)


def _settings_for(lang):
    if lang == "ja":
        return settings()
    return _settings(target_language="zh", zh_script="s", connect_enabled=True)


def _order(fake, lang):
    """The order Junban's run would write, word by word (its preview's own pass, nothing written: two decks compare
    cleanly, as the Junban suite's `_planned`)."""
    with _patched(fake):
        _writes, stats = reposition.dry_run(_settings_for(lang))
    return [row.word for row in stats["order"]]


def _shown(fake, lang):
    """The run itself (written, as the 順 window's run or Connect's `_order` step writes it) -> the new cards' words in
    the order Anki will show them."""
    with _patched(fake):
        report = reposition.run(_settings_for(lang))
    assert report["ok"], report["problems"]
    return fake.queue_order()


def _add_now(lang, item, word, text):
    """*Add now* on the page for `word` from the line holding `text` (the route, as the page posts it) -> the ask's id."""
    line_id, _cue = _line(lang, item, text)
    got = _press("card/make", lang, word, line_id)
    assert got["asked"] and not got["already"]
    return got["id"]


def _look(ledger, lang, anki, swap_id):
    """Connect's look: the ask becomes Connect's job (one swap job at a time: the next once this one ends) -> its row."""
    swap.look(Steps(subtitle=JA if lang == "ja" else ZH), ledger, lang, anki=anki, files=5)
    row = _row(ledger, swap_id)
    assert (row["by"], row["state"]) == (swap.BY_ADD_NOW, swap.QUEUED)
    return row


def _ask_and_make(ledger, lang, item, word, text, note, anki):
    """The press, then Connect's look queues its job -> (the ask's id, its row): `_made` makes it."""
    swap_id = _add_now(lang, item, word, text)
    return swap_id, _look(ledger, lang, anki, swap_id)


def _made(ledger, lang, row, note, anki):
    _make_the_job(ledger, row, note=note, record=True)
    anki.add(note, "surasura::connect::" + ledger.tag_id(row["job_id"]), row["word"], 1, sound=f"{note}.mp3")
    swap.look(Steps(subtitle=JA if lang == "ja" else ZH), ledger, lang, anki=anki, files=5)   # (queues a next ask)
    assert _row(ledger, row["id"])["state"] == swap.MADE


def _without(order, *words):
    return [w for w in order if w not in words]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_add_now_on_the_journey_is_made_by_connect_and_is_the_next_new_card_junban_shows(ledger, lang):
    word, _old, other = CASES[lang]
    extra = [(word, other, 8000, [CONNECT_TAG], 0)]
    item = _library(lang)
    plain = _order(_deck(lang, extra), lang)
    assert plain[0] != word, "the case must start away from the front, or the test proves nothing"
    anki = Anki()
    _id, row = _ask_and_make(ledger, lang, item, word, other, _note_of(lang, word, extra), anki)
    assert _order(_deck(lang, extra), lang) == plain, "asked, not made yet: nothing moves"
    _made(ledger, lang, row, _note_of(lang, word, extra), anki)
    assert swap.asked_first(lang) == [_note_of(lang, word, extra)]
    order = _order(_deck(lang, extra), lang)
    assert order[0] == word
    assert order[1:] == _without(plain, word)
    assert _shown(_deck(lang, extra), lang)[0] == word, "what Anki shows next"


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_two_asks_come_first_in_the_order_pressed_not_by_their_notes(ledger, lang):
    """Two presses before Connect looks: it makes them one job at a time, and they come first in the order pressed —
    the first pressed has the newer note here, so an order by note would put it second."""
    word, _old, other = CASES[lang]
    second, said = SECOND[lang]
    extra = [(second, said, 8500, [CONNECT_TAG], 0), (word, other, 8000, [CONNECT_TAG], 0)]
    item = _library(lang)
    plain = _order(_deck(lang, extra), lang)
    anki = Anki()
    first, then = _add_now(lang, item, word, other), _add_now(lang, item, second, said)
    _made(ledger, lang, _look(ledger, lang, anki, first), _note_of(lang, word, extra), anki)
    _made(ledger, lang, _look(ledger, lang, anki, then), _note_of(lang, second, extra), anki)
    assert _note_of(lang, word, extra) > _note_of(lang, second, extra)
    order = _order(_deck(lang, extra), lang)
    assert order[:2] == [word, second]
    assert order[2:] == _without(plain, word, second)
    assert _shown(_deck(lang, extra), lang)[:2] == [word, second]


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_an_ask_undone_deletes_its_card_and_the_other_ask_stays_first_with_nothing_else_moved(ledger, lang):
    word, _old, other = CASES[lang]
    second, said = SECOND[lang]
    extra = [(word, other, 8000, [CONNECT_TAG], 0), (second, said, 8500, [CONNECT_TAG], 0)]
    item = _library(lang)
    plain = _order(_deck(lang, extra), lang)
    anki = Anki()
    first, then = _add_now(lang, item, word, other), _add_now(lang, item, second, said)
    _made(ledger, lang, _look(ledger, lang, anki, first), _note_of(lang, word, extra), anki)
    _made(ledger, lang, _look(ledger, lang, anki, then), _note_of(lang, second, extra), anki)
    assert swap.asked_first(lang) == [_note_of(lang, word, extra), _note_of(lang, second, extra)]
    swap.undo(anki, ledger, lang, first, open_store=lambda: library.open_store(lang))
    assert anki.deleted == [_note_of(lang, word, extra)] and _row(ledger, first)["state"] == swap.UNDONE
    assert swap.asked_first(lang) == [_note_of(lang, second, extra)]
    # the record alone: had the card stayed in the deck, the undone ask would lift it no more
    order = _order(_deck(lang, extra), lang)
    assert order[0] == second and order[1:] == _without(plain, second)
    fake = _deck(lang, extra)
    gone = _note_of(lang, word, extra)                          # Anki deleted it: Junban's deck no longer has it
    fake.cards = {cid: c for cid, c in fake.cards.items() if c["note"] != gone}
    fake.notes.pop(gone)
    order = _order(fake, lang)
    assert order[0] == second
    assert order[1:] == _without(plain, word, second)
    assert _shown(fake, lang)[0] == second


@pytest.mark.parametrize("lang", ["ja", "zh"])
def test_a_journey_swap_is_not_lifted_and_its_suspended_old_card_leaves_the_order_alone(ledger, lang):
    """The word's Connect card (still new) gets ⇄ on the page; Connect makes the new card and Swap suspends the old one.
    With an *Add now* for another word made too: that one first, the ⇄ card where Junban puts it without any ask, the
    old card out of reviews before and after the run."""
    word, old, other = CASES[lang]
    second, said = SECOND[lang]
    extra = [(word, old, 8000, [CONNECT_TAG, swap.SWAP_TAG], -1),         # the old card, as Swap leaves it
             (word, other, 8000, [CONNECT_TAG], 0),                       # the ⇄'s new card
             (second, said, 8500, [CONNECT_TAG], 0)]
    old_note, new_note, asked_note = (NOTE0 + len(_entries(lang)) + i for i in range(3))
    item = _library(lang)
    plain = _order(_deck(lang, extra), lang)

    _connects_card(ledger, lang, item, note=old_note)
    line_id, _cue = _line(lang, item, other)
    got = _press("swap/queue", lang, word, line_id)
    anki = JourneyAnki()
    anki.add(old_note, "Japanese", word, 1)                               # still new in Connect's Anki
    swap.look(Steps(subtitle=JA if lang == "ja" else ZH), ledger, lang, anki=anki, files=5)
    _made(ledger, lang, _row(ledger, got["id"]), new_note, anki)
    assert anki.cards_[old_note * 10]["queue"] == -1                      # one out, one in
    assert _row(ledger, got["id"])["by"] == swap.BY_JOURNEY

    _b, asked_row = _ask_and_make(ledger, lang, item, second, said, asked_note, anki)
    _made(ledger, lang, asked_row, asked_note, anki)
    assert swap.asked_first(lang) == [asked_note]                         # the ⇄'s new card is not an ask

    order = _order(_deck(lang, extra), lang)
    assert order[0] == second
    assert order[1:] == _without(plain, second), "the ⇄ card keeps the place it had with no ask at all"
    fake = _deck(lang, extra)
    shown = _shown(fake, lang)
    assert shown[0] == second and shown.count(word) == 1, "the ⇄'s new card only, never its old one"
    old_card = fake.cards[FIRST_CARD + 700 + len(_entries(lang))]
    assert old_card["queue"] == -1, "Junban never brings Swap's suspended old card back"
