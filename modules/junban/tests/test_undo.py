# SPDX-License-Identifier: GPL-3.0-or-later
"""The snapshot that is the only way back from a reposition.

Every test here exists because the alternative is unrecoverable. AnkiConnect's
`setSpecificValueOfCard` hardcodes `skip_undo_entry=True`, so after a run Anki's own Undo stack does
not mention us at all — pressing it would revert whatever the user did *before* the run and leave
our `due` writes untouched. `modules/junban/undo.py` is the whole recovery path, which makes
"written before the first write", "restores exactly", and "never overwritten when corrupt" safety
properties rather than niceties.

Nothing here touches Anki, and `conftest.py`'s autouse fixtures redirect both roots at `tmp_path`,
so no test can see the developer's real `User Files/` (`testing.md` §5.1). The card ids are the real
epoch-millisecond shape Anki uses, and the words attached to them are real Japanese pulled from
`tests/Test Resources/ja/expected_output.csv` rather than ASCII placeholders (§1) — the words never
reach the snapshot, but a fake collection built from `"test1"` would hide an encoding fault in the
deck names, which do.
"""
import csv
import glob
import json
import os

import pytest

from modules.junban import undo

# A deck name with Japanese in it, because scope names are stored in the snapshot and a
# non-UTF-8 write (or `ensure_ascii` mangling) would only show up on a name like this one.
BANK = "TheBank"
JAPANESE_DECK = "日本語::本好きの下剋上"


@pytest.fixture
def ja_words():
    """Real words from the shared ja fixture, in list order — never dummy strings (`testing.md` §1)."""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))), "tests", "Test Resources", "ja", "expected_output.csv")
    with open(path, "r", encoding="utf-8-sig", newline="") as handle:
        return [row["Word"] for row in csv.DictReader(handle) if row.get("Word")][:12]


@pytest.fixture
def collection(ja_words):
    """A fake new-card queue: `{card_id: {"word", "due"}}`, ids in Anki's epoch-millisecond shape.

    Plain data on purpose. `testing.md` §5.3: a mocked collection is truthy and would let a bug in
    the restore path read as a pass.
    """
    return {1789711432547 + index: {"word": word, "due": 2832 + index}
            for index, word in enumerate(ja_words)}


def _write_snapshot_file(payload, language="ja"):
    """Put a literal file on disk, bypassing `save`, to stage a corrupt or foreign snapshot."""
    path = undo.snapshot_path(language)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(payload)
    return path


def _quarantined(language="ja"):
    return sorted(glob.glob(undo.snapshot_path(language) + ".corrupt-*"))


# --- the snapshot reaches disk before anything is written (invariant I3) --------------------------- #
def test_the_snapshot_is_complete_on_disk_before_the_first_write(collection):
    """The ordering that makes this module worth having.

    Simulated exactly as WP-G will sequence it: snapshot, then write. The fake writer refuses to
    move a card unless the file on disk ALREADY holds that card's original position — which is the
    real requirement, since a crash between the two leaves the user with a re-ordered queue and no
    record of where anything was.
    """
    original = {card_id: card["due"] for card_id, card in collection.items()}

    undo.save(original, [BANK], "ja")

    seen_before_each_write = []
    for index, card_id in enumerate(sorted(collection)):
        on_disk = json.load(open(undo.snapshot_path("ja"), encoding="utf-8"))
        seen_before_each_write.append(on_disk["cards"].get(str(card_id)))
        collection[card_id]["due"] = 1 + index          # the write itself

    assert seen_before_each_write == [original[card_id] for card_id in sorted(collection)]


def test_the_file_matches_the_documented_shape(collection):
    """WP-G, the panel and any future reader all parse this; the spec's §8 shape is the contract."""
    undo.save({1789711432547: 2832}, [BANK], "ja")

    raw = json.load(open(undo.snapshot_path("ja"), encoding="utf-8"))
    assert raw["schema"] == 1
    assert raw["scope"] == [BANK]
    assert raw["cards"] == {"1789711432547": 2832}
    assert raw["written_at"], "an undo with no date cannot be described to the user"


def test_due_values_are_stored_as_integers():
    """`due` is an int32 protobuf field. A string replayed through `setSpecificValueOfCard` fails
    with `error: null` and leaves the WRONG position in place — a restore that reports success and
    changes nothing is the worst possible outcome here."""
    undo.save([(1789711432547, "2832")], [BANK], "ja")

    raw = json.load(open(undo.snapshot_path("ja"), encoding="utf-8"))
    assert raw["cards"]["1789711432547"] == 2832
    assert isinstance(raw["cards"]["1789711432547"], int)


def test_the_write_is_atomic_and_leaves_no_temp_file(collection):
    """An interrupted save must not truncate the only undo the user has."""
    undo.save({card_id: card["due"] for card_id, card in collection.items()}, [BANK], "ja")

    assert not os.path.exists(undo.snapshot_path("ja") + ".tmp")
    assert json.load(open(undo.snapshot_path("ja"), encoding="utf-8"))["cards"]


def test_the_snapshot_is_language_isolated():
    """A Chinese library must never restore positions captured from a Japanese one."""
    assert os.path.basename(undo.snapshot_path("ja")) == undo.FILENAME
    assert undo.snapshot_path("ja") != undo.snapshot_path("zh")

    undo.save({1789711432547: 2832}, [BANK], "ja")
    assert undo.load("zh") is None, "the zh side must not see the ja snapshot"


def test_a_japanese_deck_name_survives_the_round_trip(collection):
    """Deck names are the one user string this file stores, and Anki deck names are routinely
    Japanese. `ensure_ascii=False` plus UTF-8 has to hold, or the scope check below would refuse
    every restore on such a deck."""
    undo.save({1789711432547: 2832}, [JAPANESE_DECK], "ja")

    assert JAPANESE_DECK in open(undo.snapshot_path("ja"), encoding="utf-8").read()
    pairs, skipped = undo.restore_pairs(undo.load("ja"), [JAPANESE_DECK])
    assert pairs == [(1789711432547, 2832)] and skipped == []


# --- restore ---------------------------------------------------------------------------------------- #
def test_restore_returns_every_card_to_its_original_due(collection):
    """The promise the feature is sold on. Reposition the whole queue, then replay the snapshot and
    require the collection to be byte-identical to how it started."""
    original = {card_id: card["due"] for card_id, card in collection.items()}
    undo.save(original, [BANK], "ja")

    for index, card_id in enumerate(sorted(collection)):        # the reposition
        collection[card_id]["due"] = 9000 + index
    assert {c: v["due"] for c, v in collection.items()} != original

    pairs, skipped = undo.restore_pairs(undo.load("ja"), [BANK])
    for card_id, due in pairs:                                  # WP-G/WP-C own this write; we replay
        collection[card_id]["due"] = due

    assert {card_id: card["due"] for card_id, card in collection.items()} == original
    assert skipped == []


def test_restore_pairs_are_ordered_by_the_position_being_restored(collection):
    """A restore that dies halfway should have put the FRONT of the queue back first — those are the
    cards the user sees next. Also makes the output deterministic for the panel's progress bar."""
    undo.save({card_id: card["due"] for card_id, card in collection.items()}, [BANK], "ja")

    pairs, _ = undo.restore_pairs(undo.load("ja"), [BANK])
    assert [due for _, due in pairs] == sorted(due for _, due in pairs)


def test_a_snapshot_from_a_different_scope_is_refused_with_a_clear_message(collection):
    """The wrong-deck disaster. Replaying TheBank's positions during an all-decks run would write
    real positions into cards the snapshot never covered, and there would be no second undo."""
    undo.save({card_id: card["due"] for card_id, card in collection.items()}, [BANK], "ja")

    with pytest.raises(undo.RestoreRefused) as refusal:
        undo.restore_pairs(undo.load("ja"), [BANK, "The Accelerator"])

    message = str(refusal.value)
    assert BANK in message and "The Accelerator" in message, "say which scope, don't just refuse"
    assert collection, "nothing was written — the refusal happens before any pair is handed back"


def test_scope_comparison_ignores_order_and_duplicates(collection):
    """`deckNames` returns decks in whatever order it likes. Refusing a valid restore because the
    same two decks arrived the other way round would be a self-inflicted outage."""
    undo.save({1789711432547: 2832}, [BANK, JAPANESE_DECK], "ja")

    pairs, _ = undo.restore_pairs(undo.load("ja"), [JAPANESE_DECK, BANK, BANK])
    assert pairs == [(1789711432547, 2832)]


def test_a_snapshot_written_by_a_newer_version_is_refused_not_guessed_at():
    """An unknown format could mean anything; writing `due` on a guess is not recoverable. Refuse,
    and leave the file where it is so a later version can still read it."""
    _write_snapshot_file(json.dumps(
        {"schema": 99, "written_at": "2026-09-17T22:00:00", "scope": [BANK],
         "cards": {"1789711432547": 2832}}))

    with pytest.raises(undo.RestoreRefused) as refusal:
        undo.restore_pairs(undo.load("ja"), [BANK])
    assert "99" in str(refusal.value)
    assert os.path.exists(undo.snapshot_path("ja")), "a readable future snapshot must not be moved"


# --- corruption is quarantined, never overwritten --------------------------------------------------- #
def test_a_corrupt_snapshot_is_quarantined_not_overwritten():
    """CLAUDE.md §4: nothing under `User Files/` is destroyed. The user may still need this file —
    it is the only record of where their cards were, and a half-written one can be repaired by hand
    or by a later version. Silently replacing it throws that away."""
    body = '{"schema":1,"scope":["TheBank"],"cards":{"1789711432547":2832'    # truncated mid-write
    _write_snapshot_file(body)

    assert undo.load("ja") is None, "an unreadable snapshot reads as 'nothing to restore'"

    quarantined = _quarantined()
    assert len(quarantined) == 1, "the corrupt file must be moved aside, not deleted"
    assert open(quarantined[0], encoding="utf-8").read() == body, "moved intact, byte for byte"
    assert not os.path.exists(undo.snapshot_path("ja")), "and not left in place to be read again"


def test_a_snapshot_with_unreplayable_values_is_also_quarantined():
    """Parsing is not the same as being replayable. A `due` that is not a whole number cannot be
    written back, and discovering that MID-restore leaves the queue half-repositioned with no way to
    finish — so it is caught at load, before a single write."""
    _write_snapshot_file(json.dumps(
        {"schema": 1, "scope": [BANK], "cards": {"1789711432547": "later"}}))

    assert undo.load("ja") is None
    assert len(_quarantined()) == 1


def test_quarantining_does_not_block_the_next_snapshot(collection):
    """After a corrupt file is moved aside the next run must still be able to protect itself."""
    _write_snapshot_file("{not json at all")
    undo.load("ja")

    undo.save({card_id: card["due"] for card_id, card in collection.items()}, [BANK], "ja")
    reloaded = undo.load("ja")

    assert len(reloaded["cards"]) == len(collection)
    assert len(_quarantined()) == 1, "the quarantined copy is still there"


# --- empty states ------------------------------------------------------------------------------------ #
def test_no_snapshot_at_all_reads_as_none_and_creates_nothing():
    """First run, or a fresh profile. Not an error, and merely asking must not create a file."""
    assert undo.load("ja") is None
    assert not os.path.exists(undo.snapshot_path("ja"))


def test_restoring_with_no_snapshot_is_refused_with_an_explanation():
    """The panel shows this message when the button is pressed before any reposition has happened."""
    with pytest.raises(undo.RestoreRefused) as refusal:
        undo.restore_pairs(undo.load("ja"), [BANK])
    assert "no saved order" in str(refusal.value).lower()


def test_an_empty_snapshot_restores_nothing_and_does_not_raise():
    """A run where the plan turned out to be a no-op (idempotence, §7 step 8) still snapshots. Its
    restore is legitimately empty — that must read as 'nothing to do', not as a failure."""
    undo.save({}, [BANK], "ja")

    pairs, skipped = undo.restore_pairs(undo.load("ja"), [BANK])
    assert pairs == [] and skipped == []


def test_cards_that_no_longer_exist_are_skipped_and_reported(collection):
    """Notes get deleted between a reposition and a restore. Writing `due` by a stale card id is a
    write we cannot reason about, so those are dropped — but reported, so the panel can say how many
    rather than quietly restoring fewer cards than it promised."""
    undo.save({card_id: card["due"] for card_id, card in collection.items()}, [BANK], "ja")

    gone = sorted(collection)[:3]
    still_here = [card_id for card_id in collection if card_id not in gone]

    pairs, skipped = undo.restore_pairs(undo.load("ja"), [BANK], existing_ids=still_here)

    assert skipped == sorted(gone)
    assert sorted(card_id for card_id, _ in pairs) == sorted(still_here)


def test_describe_speaks_plainly_in_both_states(collection):
    """The panel's one-line summary. With nothing saved it must say so rather than render '0 cards
    from ()', which reads like a broken snapshot instead of a fresh install."""
    assert "no saved order" in undo.describe(None).lower()

    undo.save({card_id: card["due"] for card_id, card in collection.items()}, [BANK], "ja")
    line = undo.describe(undo.load("ja"))
    assert f"{len(collection)} cards" in line and BANK in line


# --- Junban_Backlog_Spec §13: the cards not on the list ------------------------------------------- #
def test_the_suspended_cards_and_the_flags_before_round_trip_and_an_ordinary_run_writes_neither():
    """Additive, like WP-L's keys: a run with "No action" writes exactly the file it always did, and
    one that suspends and flags records which cards and each flag before — nothing else, and nothing
    garbled (a flag outside Anki's 0-7, `true` for a card id) survives a load."""
    undo.save({1789711432547: 2832}, [BANK], "ja")
    raw = json.load(open(undo.snapshot_path("ja"), encoding="utf-8"))
    assert "suspended" not in raw and "flags" not in raw

    undo.save({1789711432547: 2832, 1789711432548: 2833}, [BANK], "ja",
              suspended=[1789711432548, 1789711432548, True],
              flags={1789711432548: 0, 1789711432547: 9, "x": 1})
    snapshot = undo.load("ja")

    assert snapshot["suspended"] == [1789711432548]
    assert snapshot["flags"] == {"1789711432548": 0}
    assert undo.restore_suspended(snapshot) == [1789711432548]
    assert "1 suspended" in undo.describe(snapshot) and "1 flagged" in undo.describe(snapshot)


def test_a_flag_comes_back_only_while_it_is_still_junbans():
    """Purple (Junban's) → the flag before; the user's own re-flag since → kept and counted, as an
    edited field is; a card gone from Anki → simply not written."""
    undo.save({}, [BANK], "ja", flags={1: 0, 2: 1, 3: 0})
    snapshot = undo.load("ja")

    pairs, skipped = undo.restore_flags(snapshot, {1: 7, 2: 7, 3: 4}, ours=7)

    assert pairs == [(1, 0), (2, 1)] and skipped == 1


def test_the_scope_can_be_checked_before_anything_is_written():
    """A restore unsuspends before it can see positions, so the refusal has to come first — the same
    refusal `restore_pairs` gives, on its own."""
    undo.save({1789711432547: 2832}, [BANK], "ja", suspended=[1789711432547])
    snapshot = undo.load("ja")

    undo.check_restorable(snapshot, [BANK])
    with pytest.raises(undo.RestoreRefused, match="different scope"):
        undo.check_restorable(snapshot, [JAPANESE_DECK])


# --- end_baseline is best-effort: a corrupt baseline is never raised on, never rewritten ---------- #
@pytest.mark.parametrize("raw", [
    b'{"day": "2026-10-06", "cards": {',   # truncated JSON: a json.JSONDecodeError (a ValueError)
    b"\xff\xfe\x00",                        # not UTF-8: a UnicodeDecodeError (also a ValueError)
], ids=["truncated-json", "not-utf8"])
def test_ending_a_corrupt_baseline_returns_false_and_leaves_the_file_untouched(raw):
    """`end_baseline` is called from a Restore: a damaged baseline must answer False, not crash the
    Restore, and must not be rewritten (it may be the only record of today's positions)."""
    path = undo.snapshot_path("ja", "baseline")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(raw)

    assert undo.end_baseline("ja") is False
    with open(path, "rb") as handle:
        assert handle.read() == raw


def test_a_ladder_value_that_is_not_a_whole_number_of_one_or_more_reads_as_none():
    """A damaged or hand-edited ladder record must not be trusted: 0, a negative number, True (an int in
    Python, but not a count) and "2800" (text) each read as None, so the next run starts from its default."""
    from app.path_utils import get_user_files_path
    path = os.path.join(get_user_files_path("ja"), undo.LADDER_FILENAME)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    # Positive control: a whole number of one or more must read through, or the rejections below
    # could pass for a wrong reason (a ladder that always returns None would look correct).
    with open(path, "w", encoding="utf-8") as handle:
        json.dump({"schema": 1, "scopes": {BANK: {"floor": 2800, "seen": 2800}}}, handle)
    assert undo.ladder("ja", [BANK]) == {"floor": 2800, "seen": 2800}
    for bad in (0, -3, True, "2800"):
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"schema": 1, "scopes": {BANK: {"floor": bad, "seen": bad}}}, handle)
        assert undo.ladder("ja", [BANK]) == {"floor": None, "seen": None}


def test_a_ladder_floor_at_the_ceiling_is_recorded_and_one_above_it_is_refused():
    """The floor may be as high as 999,999 (the ceiling of 1–999,999) and is kept; 1,000,000 is refused and
    leaves the recorded floor as it was."""
    assert undo.record_ladder("ja", [BANK], floor=999_999) is True
    assert undo.ladder_floor("ja", [BANK]) == 999_999
    assert undo.record_ladder("ja", [BANK], floor=1_000_000) is False
    assert undo.ladder_floor("ja", [BANK]) == 999_999


def test_a_snapshot_write_cut_off_mid_way_leaves_the_previous_file_whole(monkeypatch):
    """A write that dies inside json.dump must not truncate the undo already on disk: the new data goes
    to a temporary file and only replaces the snapshot once it is complete."""
    path = undo.snapshot_path("ja")
    undo._write_json(path, {"cards": {"1789712080000": 2800}})

    def boom(data, handle, **kw):
        handle.write('{"car')
        raise OSError("disk full")

    with monkeypatch.context() as m:
        m.setattr(undo.json, "dump", boom)
        with pytest.raises(OSError):
            undo._write_json(path, {"cards": {}})

    assert json.load(open(path, encoding="utf-8")) == {"cards": {"1789712080000": 2800}}


# --------------------------------------------------------------------------- #
# 3.0: a snapshot taking over a cut automatic run's (`save(cut=)`)
# --------------------------------------------------------------------------- #
def _cut_snapshot(tag="Surasura::later"):
    """An automatic acting run's window snapshot, cut by Anki closing: unfinished, marked automatic."""
    undo.save({1789712080001: 5, 1789712080002: 6}, ["TheBank"], language="ja", automatic=True,
              suspended=[1789712080011], unsuspended=[1789712080021], flags={1789712080012: 3},
              tags=[1789712090001], tag=tag, marker_tags={"Surasura::star": [1789712090011]})
    cut = undo.load("ja")
    assert cut["complete"] is False and cut["automatic"] is True
    return cut


def test_a_snapshot_taking_over_a_cut_one_keeps_every_way_back_from_both_runs():
    """One Restore undoes both runs: the cut run's values win where both hold one (a card's original due, a card's
    flag from before it), and every list is the union — what each run suspended, what each unsuspended (a returning
    word's card, set aside again on Restore), the notes each tagged and every marker tag."""
    cut = _cut_snapshot()
    undo.save({1789712080001: 90, 1789712080003: 7}, ["TheBank"], language="ja", automatic=True, cut=cut,
              suspended=[1789712080013], unsuspended=[1789712080023],
              flags={1789712080012: 7, 1789712080014: 0}, tags=[1789712090002], tag="Surasura::later",
              marker_tags={"Surasura::star": [1789712090012], "Surasura::book": [1789712090013]})
    saved = undo.load("ja")
    assert saved["cards"] == {"1789712080001": 5, "1789712080002": 6, "1789712080003": 7}
    assert saved["suspended"] == [1789712080011, 1789712080013]
    assert saved["unsuspended"] == [1789712080021, 1789712080023]
    assert saved["flags"] == {"1789712080012": 3, "1789712080014": 0}
    assert saved["tag"] == "Surasura::later" and saved["tags"] == [1789712090001, 1789712090002]
    assert saved["marker_tags"] == {"Surasura::star": [1789712090011, 1789712090012],
                                    "Surasura::book": [1789712090013]}


def test_taking_over_two_cut_runs_lets_the_oldest_ones_numbers_win_and_marks_a_run_taken_over():
    """Lead 2026-11-07: an automatic job may take over the window's own cut run AND one of Connect's (`cut=[...]`) —
    the order from before the OLDER one wins for a card both hold (it is how the deck was before either), whichever
    list position it comes in; `mark_complete(taken_over=True)` marks Connect's run, never as restored."""
    newer = {"written_at": "2026-11-07T10:00:05", "cards": {"1789712080001": 50}}
    older = {"written_at": "2026-11-07T10:00:01", "cards": {"1789712080001": 5, "1789712080002": 6}}
    for cuts in ([newer, older], [older, newer]):
        undo.save({1789712080001: 90, 1789712080003: 7}, ["TheBank"], language="ja", automatic=True, cut=cuts)
        assert undo.load("ja")["cards"] == {"1789712080001": 5, "1789712080002": 6, "1789712080003": 7}
    run_id = undo.new_run_id("reorder")
    undo.save({1789712080001: 5}, ["TheBank"], language="ja", run_id=run_id, after={1789712080001: 9})
    assert undo.unfinished("ja", "reorder") == run_id
    assert undo.mark_complete("ja", run_id=run_id, taken_over=True)
    run = undo.load("ja", run_id=run_id)
    assert run["complete"] is True and run["taken_over_at"] and "restored_at" not in run
    assert undo.unfinished("ja", "reorder") is None


def test_a_cut_runs_tag_of_another_name_is_kept_with_the_marker_tags():
    """The tag's name changed between the runs (the user renamed Junban's tag): the cut run's notes keep their own tag
    under the marker tags, which a Restore takes off exactly the same way, and this run's tag stays its own."""
    cut = _cut_snapshot(tag="Junban::later")
    undo.save({1789712080003: 7}, ["TheBank"], language="ja", automatic=True, cut=cut,
              tags=[1789712090002], tag="Surasura::later")
    saved = undo.load("ja")
    assert saved["tag"] == "Surasura::later" and saved["tags"] == [1789712090002]
    assert saved["marker_tags"] == {"Surasura::star": [1789712090011], "Junban::later": [1789712090001]}
