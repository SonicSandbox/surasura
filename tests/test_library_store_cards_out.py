"""*Take its new cards out*, the store's half for Anki (P4.1 L2 package T; L2.2 05 §5.7, D14; W1.2 01-scope fc).

The window's *Take its new cards out* sets `in_learning_order` 0; Junban's run (the re-plan's) then suspends and tags
the item's unstudied new cards and records them in `anki_changes`, so *Put back* restores exactly those. What the store
owes that run, checked here on a migrated library of real names, Japanese and Chinese alike:

  * **owed** (T-4): every write that moves `in_learning_order` — the take-out, *Put them back in the order*, *Put
    back*, a part from Finished joined back, and each one's undo — bumps `pins_version`, so the window's re-order host
    (`pins_version > planned_pins_version`) and Connect (`replan.key`) re-order; without it nothing reaches Anki;
  * **read** (`cards_out()`): the items out now, and the open records of items back in the order — never another
    item's, never one already reverted, never a record of an item still out.
"""
import pytest

from tests.test_library_store_support import LANGUAGES, migrated


def _owed(store):
    v = store.versions()
    return v["pins_version"] > v["planned_pins_version"]


def _planned(store):
    v = store.versions()
    store.record_planned(v["order_version"], v["pins_version"])
    assert not _owed(store)


@pytest.mark.parametrize("language", LANGUAGES)
def test_taking_a_finished_items_cards_out_with_no_pin_is_owed_to_anki(language):
    """T-4: the item had no pin to end, so before P4.1 nothing bumped `pins_version` — the window's re-order host owed
    nothing and its cards stayed in Anki's order. Now the take-out is owed, and so is its undo."""
    store = migrated(language)
    a = store.ids("now")[0]
    store.finish([a])
    _planned(store)
    change = store.set_learning_order([a], on=False)
    assert change is not None and store.item(a)["in_learning_order"] == 0
    assert _owed(store), "a take-out with no pin is owed to Anki"
    _planned(store)
    store.undo(change)
    assert store.item(a)["in_learning_order"] == 1 and _owed(store), "its undo is owed too"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_put_them_back_in_the_order_and_put_back_are_owed_to_anki(language):
    """T-4: *Put them back in the order* (in Finished) and *Put back* (to Current) each bump `pins_version`, once per
    command; nothing new to write bumps nothing."""
    store = migrated(language)
    a, b = store.ids("now")[:2]
    store.finish([a, b], keep_cards=False)
    _planned(store)
    pins = store.versions()["pins_version"]
    store.set_learning_order([a], on=True)
    assert store.versions()["pins_version"] == pins + 1 and _owed(store)
    assert store.set_learning_order([a], on=True) is None and store.versions()["pins_version"] == pins + 1
    _planned(store)
    change = store.put_back_finished([b])
    assert store.item(b)["in_learning_order"] == 1 and _owed(store)
    _planned(store)
    store.undo(change)
    assert store.item(b)["in_learning_order"] == 0 and _owed(store), "undoing Put back takes them out again: owed"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_a_part_from_finished_joined_back_is_owed_to_anki(language):
    """T-4: a join that brings a Finished part's cards back in the order (IK-L2-1) is owed like *Put back*."""
    store = migrated(language)
    ids = store.ids("now")
    piece = next(store.item(i)["piece_id"] for i in ids
                 if sum(store.item(j)["piece_id"] == store.item(i)["piece_id"] for j in ids) >= 4)
    members = [i for i in ids if store.item(i)["piece_id"] == piece][:4]
    store.split(piece, members[2])
    second = store.item(members[2])["piece_id"]
    store.finish(members[2:], keep_cards=False)
    _planned(store)
    store.join([piece, second])
    assert [store.item(i)["in_learning_order"] for i in members[2:]] == [1, 1] and _owed(store)
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_connects_plan_key_moves_with_a_take_out(language):
    """T-4: Connect's `replan.key` holds `pins_version`, so its step reads its plan again after a take-out."""
    from app.connect import replan
    store = migrated(language)
    a = store.ids("now")[0]
    store.finish([a])
    before = replan.key(store)
    store.set_learning_order([a], on=False)
    assert replan.key(store) != before
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_cards_out_reads_the_items_out_and_the_records_owed_back(language):
    """`cards_out()`: the items whose cards are out now (any tier), and the open `cards_out` records of items back in
    the order — never a record of an item still out, another action's, or one already reverted."""
    store = migrated(language)
    a, b, c = store.ids("now")[:3]
    assert store.cards_out() == {"out": [], "back": []}
    store.finish([a, b], keep_cards=False)
    store.set_learning_order([c], on=False)                 # Current, its cards out
    got = store.cards_out()
    assert [item for item, _path in got["out"]] == sorted([a, b, c]) and got["back"] == []
    assert dict(got["out"])[a] == store.item(a)["rel_path"]
    ids = store.record_anki_changes([(a, "cards_out", [11], {"queue": 0}, {"queue": -1, "suspended": [101]}),
                                     (b, "cards_out", [12], {"queue": 0}, {"queue": -1, "suspended": [102]}),
                                     (a, "suspend", [13], {"queue": 0}, {"queue": -1})])
    assert store.cards_out()["back"] == [], "both still out: nothing owed back"
    store.put_back_finished([a])
    back = store.cards_out()["back"]
    assert [(r["id"], r["item_id"], r["action"], r["after"]["suspended"]) for r in back] == [(ids[0], a, "cards_out",
                                                                                              [101])]
    assert [item for item, _path in store.cards_out()["out"]] == sorted([b, c])
    store.mark_anki_reverted([ids[0]])
    assert store.cards_out()["back"] == [], "a reverted record is closed"
    store.close()


@pytest.mark.parametrize("language", LANGUAGES)
def test_pinning_an_item_whose_cards_are_out_brings_them_back(language):
    """G2.2-8, the later click wins: an item pinned after its cards were taken out is no longer out, and its open
    records are owed back — *Study its cards first* wants those cards at the front."""
    store = migrated(language)
    a = store.ids("now")[0]
    store.finish([a], keep_cards=False)
    rid = store.record_anki_changes([(a, "cards_out", [21], {"queue": 0}, {"queue": -1, "suspended": [201]})])[0]
    _planned(store)
    store.pin([a])
    assert _owed(store)
    assert store.cards_out()["out"] == [] and [r["id"] for r in store.cards_out()["back"]] == [rid]
    store.close()
