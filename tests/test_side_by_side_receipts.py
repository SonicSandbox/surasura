"""Kyou-E (train 40's intent keeper, notes 2 and 3): with *New cards come from: Current's top two, side by side* on,
Connect's receipt never sets a title aside on a count Junban took before that file was mined, and so never moves the
order (G1.1-10: a receipt is `state_version` only) — unless the count had seen the file and the receipt takes that
back (its cards deleted in Anki, or the file mined again since). Junban's count carries the time it began reading
Anki (`SIDE_CARDS`' "at", `library_store.side_seen`): a file mined after it is one the count never saw, so the title
keeps its turn until Junban's next count, which then decides by the cards it did see.

What a wrong answer would cost a learner: the window's top and Connect's top 20 flickering — a title set aside the
moment Connect mines it, its queued jobs dropped as "left the top", and brought back by the next Junban run (two order
bumps, Generate and the re-plan made to follow twice); or, the other way, a title Junban saw nothing new in keeping
its turn for good. And a receipt that reads all of Current twice under the write lock (89 ms at 4k files) though it
can't move anything.

Every store test runs for Japanese and Chinese alike under the per-test SURASURA_TEST_ROOT, on libraries named with
real words from tests/Test Resources/ (`library_store_support.names`).
"""
import json

import pytest

from app import library_store as ls
from tests.test_library_store_support import LANGUAGES
from tests.test_side_by_side import _library
from tests.test_side_by_side_cards import _in_top, _view, _write

COUNT = {"a": 0, "b": 2, "loose": 1, "d": 3}      # A: nothing new in Anki; B, the loose file and D: cards


def _agree(store, n=4):
    """The window's top is what Connect mines (the same rule on the feed's rows and the count's time)."""
    assert _in_top(_view(store)) == set(store._mine_ids(n))


# --- the rule, pure ------------------------------------------------------------------------------------------------ #
def test_the_count_keeps_its_time_and_drops_one_it_cannot_read():
    at = "2026-11-17T10:00:00.250000Z"
    assert ls.side_cards(json.dumps({"w12": 0, "i5": 3, ls.SIDE_AT: at})) == {"w12": 0, "i5": 1, ls.SIDE_AT: at}
    assert ls.side_cards({"w12": 1, ls.SIDE_AT: 5}) == {"w12": 1}, "a time that isn't text: no time"
    assert ls.side_cards({"w12": 1, ls.SIDE_AT: ""}) == {"w12": 1}
    assert ls.side_cards({"w12": 1, ls.SIDE_AT: "garbage"}) == {"w12": 1}, "not a date: no time (it would sort last)"


def test_a_file_mined_after_the_counts_time_is_one_the_count_never_saw():
    """Connect's receipts carry whole seconds ("…:26Z"), the count microseconds: a file mined in the count's own second
    counts as seen (Connect records before its Junban step reads Anki); later, never; no receipt, never; a count with
    no time (3.0.15's) saw every mined file."""
    cards = {"w12": 0, ls.SIDE_AT: "2026-11-17T10:00:26.300000Z"}
    assert ls.side_seen(cards, "2026-11-17T10:00:26Z") and ls.side_seen(cards, "2026-11-17T09:59:59Z")
    assert ls.side_seen(cards, cards[ls.SIDE_AT]), "mined at the count's own instant: seen"
    assert ls.side_seen(cards, "2026-11-16"), "a date alone: before the count"
    assert not ls.side_seen(cards, "2026-11-17T10:00:27Z") and not ls.side_seen(cards, "2026-11-17T10:00:26.400000Z")
    assert not ls.side_seen(cards, None)
    assert ls.side_seen({"w12": 0}, "2030-01-01T00:00:00Z") and not ls.side_seen({"w12": 0}, None)


# --- a receipt after the count ------------------------------------------------------------------------------------- #
@pytest.mark.parametrize("language", LANGUAGES)
def test_a_receipt_after_the_count_moves_nothing_and_the_next_count_decides(language):
    """A (counted none: Connect never mined it) keeps its turn; Connect mines its next file. The receipt is a status
    write only — the order, Connect's top and the window's stay — because the count never saw that file's cards. Junban's
    next count does: still none, and A steps aside then, the order moving once (Generate and the re-plan follow); had
    the file made cards, A would have kept its turn with no bump at all."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    assert _write(store, a, b, loose, d, COUNT) is True
    top = store._mine_ids(4)
    assert top == [a[0], b[0], a[1], b[1]], "nothing of A mined yet: by its files"
    v = store.versions()
    store.receipt(a[0], ls._now())
    after = store.versions()
    assert after["order_version"] == v["order_version"], "G1.1-10: a receipt never moves the order"
    assert after["state_version"] > v["state_version"]
    assert store._mine_ids(4) == top and store._mine_ids(20)[:4] == top
    _agree(store)
    assert _write(store, a, b, loose, d, COUNT) is True, "the same count, now having seen A's file: written"
    moved = store.versions()
    assert moved["order_version"] > after["order_version"], "who takes turns moved: the order did, once"
    assert a[0] not in store._mine_ids(4) and store._mine_ids(4)[:2] == [b[0], loose]
    _agree(store)
    assert _write(store, a, b, loose, d, COUNT) is False and store.versions() == moved, "and then nothing (S19)"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_receipt_whose_file_made_cards_keeps_the_title_turning_with_no_bump(language):
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    _write(store, a, b, loose, d, COUNT)
    v = store.versions()["order_version"]
    store.receipt(a[0], ls._now())
    assert _write(store, a, b, loose, d, dict(COUNT, a=4)) is True, "A's count changed: written"
    assert store.versions()["order_version"] == v and store._mine_ids(4) == [a[0], b[0], a[1], b[1]]
    _agree(store)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_receipt_landing_while_junban_read_anki_is_one_the_count_never_saw(language):
    """The re-plan host's Junban run began reading Anki, Connect (another process) mined A's next file meanwhile, then
    the run recorded its count (A: none — its new cards weren't there when it looked). The count's time is the read's
    start: A keeps its turn, so A isn't set aside on cards Junban never looked at."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    began = ls._now()
    store.receipt(a[0], ls._now())
    store.set_side_cards([(a, 0), (b, 2), ([loose], 1), (d, 3)], at=began)
    assert store._mine_ids(4) == [a[0], b[0], a[1], b[1]]
    assert store._side_cards()[ls.SIDE_AT] == began
    _agree(store)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_the_same_count_writes_nothing_when_no_receipt_since_moves_anyone(language):
    """S19 with the time: the same count again, after a receipt of a title with cards (B) or none at all, is no write —
    who takes turns is the same under the newer time; an older time than the one kept is never written over it."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    store.receipt(a[0], ls._now())
    assert _write(store, a, b, loose, d, COUNT) is True
    kept = store._side_cards()[ls.SIDE_AT]
    v = store.versions()
    assert _write(store, a, b, loose, d, COUNT) is False and store.versions() == v
    store.receipt(b[0], ls._now())
    v = store.versions()
    assert v["order_version"] == store.versions()["order_version"]
    assert _write(store, a, b, loose, d, COUNT) is False and store.versions() == v
    assert store.set_side_cards([(a, 0), (b, 2), ([loose], 1), (d, 3)], at="2020-01-01T00:00:00.000000Z") is False
    assert store._side_cards()[ls.SIDE_AT] == kept
    store.close()


# --- a receipt that takes back what the count saw ------------------------------------------------------------------ #
@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("how", ["cards_deleted", "mined_again"])
def test_a_receipt_taking_back_a_file_the_count_saw_still_moves_the_order(language, how):
    """A stepped aside (its next file mined before the count, nothing new). Its cards deleted in Anki (the receipt
    cleared) or the file mined again after the count (*Mine it too*): the count no longer speaks for that file, A takes
    its turn again, and the order moves — Generate and the re-plan must follow, so here the receipt still bumps it."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    store.receipt(a[0], ls._now())
    _write(store, a, b, loose, d, COUNT)
    assert a[0] not in store._mine_ids(4)
    v = store.versions()["order_version"]
    store.receipt(a[0], None if how == "cards_deleted" else ls._now())
    assert store.versions()["order_version"] > v
    assert store._mine_ids(4) == [a[0], b[0], a[1], b[1]]
    _agree(store)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_count_from_before_its_time_was_kept_reads_every_mined_file_as_seen(language):
    """A count 3.0.15 wrote (no time): every mined file is one it saw, as then — a receipt still moves the order
    there until Junban's next count, which carries the time: the same count again gains it (one write, no order bump),
    and from then on a receipt moves nothing."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    _write(store, a, b, loose, d, COUNT)
    old = {k: v for k, v in store._side_cards().items() if k != ls.SIDE_AT}

    def as_3_0_15():
        with store._writing():
            store._set_meta({ls.SIDE_CARDS: json.dumps(old, sort_keys=True)})
    as_3_0_15()
    v = store.versions()["order_version"]
    store.receipt(a[0], ls._now())
    assert store.versions()["order_version"] > v and a[0] not in store._mine_ids(4)
    _agree(store)
    store.receipt(a[0], None)                           # back as it was (A's cards deleted): A takes its turn
    as_3_0_15()
    v = store.versions()
    assert _write(store, a, b, loose, d, COUNT) is True, "the same count, now with its time"
    assert ls.SIDE_AT in store._side_cards() and store.versions()["order_version"] == v["order_version"]
    store.receipt(a[0], ls._now())
    assert store.versions()["order_version"] == v["order_version"] and store._mine_ids(4)[0] == a[0]
    store.close()


# --- the cost ------------------------------------------------------------------------------------------------------ #
@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("side", ["on", "off"])
def test_a_receipt_that_cannot_move_who_takes_turns_reads_none_of_current(language, side, monkeypatch):
    """Train 40's keeper: a receipt read Current twice more under the write lock with side by side on (32 -> 89 ms at
    4k files). Now only a receipt that changes what the count saw reads it: a fresh one after the count reads none,
    on or off."""
    store, a, b, loose, d = _library(language)
    store.set_library_options(mine_line=4, side_by_side=True)
    _write(store, a, b, loose, d, COUNT)
    if side == "off":
        store.set_library_options(side_by_side=False)
    reads = []
    real = ls.Store._current_rows
    monkeypatch.setattr(ls.Store, "_current_rows", lambda self: reads.append(1) or real(self))
    for item_id in (a[0], b[0], loose):
        store.receipt(item_id, ls._now())
    assert reads == []
    store.close()
