# SPDX-License-Identifier: GPL-3.0-or-later
"""P4.2.2 (P2.2 adversary #9; the intent keeper's S5 on P4.1): a parked card comes back (MR-R3's returning word, ✅
E1.3-2's pin) only when Junban's lasting record says Junban parked it — the first-touch journal
(`first_touch.parked`), never purged, where a run snapshot keeps only the last 20 runs. A card the record never names
that was made before the record began falls back to the tag alone (today's rule: Junban may have parked it before the
record existed); one made since, or one the record names otherwise, is yours.

What a wrong answer would cost: a card you suspended yourself after Junban only tagged it (`Surasura::later` with the
suspend setting off) unsuspended behind your back the day its word comes back on the list ("All suspended cards are
intentional", K39); or the other way, a card Junban parked a month of runs ago left suspended for good once its run
snapshot was let go — D14's 287 parked cards against 142 restorable again.

The scene (`connect_scene`): 老婆 is suspended with Junban's tag, and on the list again. Real Japanese words on real
Lapis fields in the fake AnkiConnect collection; never Anki.
"""
import json
import os

from modules.junban import connect, first_touch, reposition, undo
from modules.junban.tests.connect_scene import scene, settings
from modules.junban.tests.test_reposition import FIRST_CARD, _patched

RETURNING = "老婆"
LATER = "Surasura::later"


def _journal(*lines, since=FIRST_CARD):
    """The first-touch journal as earlier runs left it: `lines` (their items), the first one at `since` (ms)."""
    path = os.path.join(first_touch.folder("ja"), first_touch.JOURNAL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for n, items in enumerate(lines):
            f.write(json.dumps(dict({"at": "2026-09-18T09:00:00", "ms": since + n, "kind": "reorder",
                                     "profile": "DevTest", "deck": ["TheBank"]}, **items), ensure_ascii=False) + "\n")


def _unsuspended(fake):
    return [card for call in fake.suspend_calls if call[0] == "unsuspend" for card in call[1]]


def test_a_card_junban_only_tagged_then_you_suspended_stays_suspended(tmp_path):
    fake = scene(tmp_path)
    card = fake.card_of(RETURNING)
    _journal({"tags": {LATER: [card["note"]]}}, since=card["cardId"] + 1)  # the tag Junban put on; no suspend of it
    with _patched(fake):
        report = reposition.run(settings())
    assert report["ok"], report["problems"]
    assert fake.card_of(RETURNING)["queue"] == -1 and card["cardId"] not in _unsuspended(fake), \
        "yours: you suspended it, Junban only tagged it"
    assert "Back on your list" not in report["message"]


def test_a_card_junban_parked_21_runs_ago_comes_back(tmp_path):
    fake = scene(tmp_path)
    card = fake.card_of(RETURNING)
    _journal({"suspended": [card["cardId"]], "landed": True, "with_tag": LATER}, since=card["cardId"] - 5)
    first = undo.new_run_id("reorder")
    undo.save({card["cardId"]: 2806}, ["TheBank"], suspended=[card["cardId"]], run_id=first)   # the run that parked it
    undo.mark_complete("ja", run_id=first)
    for n in range(21):                                                                       # 21 runs since
        run_id = undo.new_run_id("reorder")
        undo.save({FIRST_CARD + 300: 2800 + n}, ["TheBank"], run_id=run_id)
        undo.mark_complete("ja", run_id=run_id)
    assert first not in [run_id for run_id, _saved in undo.runs("ja")] and len(undo.runs("ja")) == undo.KEEP_RUNS, \
        "its run snapshot is long gone"
    with _patched(fake):
        report = reposition.run(settings())
    assert report["ok"], report["problems"]
    assert fake.card_of(RETURNING)["queue"] == 0 and card["cardId"] in _unsuspended(fake)


def test_a_card_made_since_the_record_began_that_it_never_names_stays_suspended(tmp_path):
    fake = scene(tmp_path)
    card = fake.card_of(RETURNING)
    _journal({"tags": {LATER: [10]}}, since=card["cardId"] - 5)        # the record began before the card was made
    with _patched(fake):
        reposition.run(settings())
    assert fake.card_of(RETURNING)["queue"] == -1, "Junban never parked it: you suspended it (and tagged it)"


def test_a_card_put_back_since_and_suspended_again_by_you_stays_suspended(tmp_path):
    fake = scene(tmp_path)
    card = fake.card_of(RETURNING)
    _journal({"suspended": [card["cardId"]], "landed": True, "with_tag": LATER},
             {"unsuspended": [card["cardId"]]}, since=card["cardId"] - 5)      # a Restore unsuspended it
    with _patched(fake):
        reposition.run(settings())
    assert fake.card_of(RETURNING)["queue"] == -1


def test_with_no_record_yet_the_tag_alone_decides(tmp_path):
    # the fallback, stated: no journal (Surasura never wrote this language's cards with it) — today's rule
    fake = scene(tmp_path)
    with _patched(fake):
        reposition.run(settings())
    assert fake.card_of(RETURNING)["queue"] == 0


def test_a_card_older_than_the_record_it_never_names_falls_back_to_the_tag(tmp_path):
    fake = scene(tmp_path)
    card = fake.card_of(RETURNING)
    _journal({"tags": {LATER: [10]}}, since=card["cardId"] + 1000)     # made before the record: maybe Junban's
    with _patched(fake):
        reposition.run(settings())
    assert fake.card_of(RETURNING)["queue"] == 0


def test_a_pinned_items_card_comes_back_only_when_junban_parked_it():
    """✅ E1.3-2's pin reads the same set (one function, `connect.junbans`): a pin brings back a card Junban parked,
    never one you suspended."""
    cards = [{"card_id": 101, "note": 11, "word": "上層部", "parked": True},
             {"card_id": 102, "note": 12, "word": "一生懸命", "parked": True}]
    parked = {"cards": {101}, "named": {101}, "notes": {12}, "since": 50}
    kept, back = connect.returning([dict(c) for c in cards], {}, "ja", pinned={101, 102}, parked=parked)
    assert back == [101] and [c["card_id"] for c in kept] == [101]
    kept, back = connect.returning([dict(c) for c in cards], {}, "ja", pinned={101, 102})
    assert back == [101, 102], "no record handed in: the tag alone (as before)"


def test_parked_reads_the_journal_once_and_an_unreadable_one_as_none(tmp_path):
    assert first_touch.parked("ja") == {"cards": set(), "named": set(), "notes": set(), "since": None}
    path = os.path.join(first_touch.folder("ja"), first_touch.JOURNAL)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("{torn\n" + json.dumps({"ms": 77, "suspended": [5], "landed": True, "with_tag": LATER}) + "\n")
    assert first_touch.parked("ja") == {"cards": {5}, "named": {5}, "notes": set(), "since": 77}


def test_a_journal_that_cant_be_read_brings_no_parked_card_back(tmp_path):
    # why (adversary AD-2): an unreadable journal read as none, so the tag alone decided and a card you suspended
    # after Junban only tagged it came back; now it reads as the safe side — nothing parked comes back by the record.
    # (A run that can't write the journal refuses anyway: undo.save journals first.)
    fake = scene(tmp_path)
    card = fake.card_of(RETURNING)
    os.makedirs(os.path.join(first_touch.folder("ja"), first_touch.JOURNAL))   # there, and it won't open as a file
    parked = first_touch.parked("ja")
    assert parked["since"] == 0 and not parked["cards"]
    assert connect.junbans({"card_id": card["cardId"], "note": card["note"], "parked": True}, parked) is False
    assert connect.junbans({"card_id": card["cardId"], "parked": True}, first_touch.parked("zh")) is True, \
        "no journal at all (zh): the tag rule, as before the record"


def test_a_card_older_than_the_record_that_it_names_as_put_back_stays_suspended_by_you(tmp_path):
    # why (mutant M17): a card made before the record began, that the record names since (a Restore unsuspended it),
    # then suspended again by you, is yours — the record's word wins over the made-before fallback (the tag)
    fake = scene(tmp_path)
    card = fake.card_of(RETURNING)
    _journal({"unsuspended": [card["cardId"]]}, since=card["cardId"] + 1000)
    with _patched(fake):
        reposition.run(settings())
    assert fake.card_of(RETURNING)["queue"] == -1 and card["cardId"] not in _unsuspended(fake)
