"""Connect's level job batch moves the store's state only when it writes a word (P2.4 row 11, L3.3).

A level job's batch has no receipt (`mined_at=None`), so the only thing that tells the copy and the window that a
level raise made new words is `state_version`. A new word must move it by exactly one step; a word already recorded
with the same note id, or an empty batch, must take no write and leave the version alone.

What a wrong answer would cost: a level job that makes words without moving `state_version` leaves the window and
the copy showing stale words until something else writes; a re-recorded word that moves the version (or rewrites its
`made_at` / `batch`) makes every reader reload for nothing, and rewrites the record of when the card was first made.
Real Japanese words (眼鏡, 上層部), synthetic note ids, a temp library.
"""
from app.connect import library
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def test_a_level_batch_with_a_new_word_moves_state_version_by_exactly_one():
    # A level job's batch carries no receipt, so the word's own write is the only thing that moves the version.
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
        library.record_batch(s, item, {}, "2026-10-01T09:00:00", batch="batch-1")  # the item's first receipt
        before = s.versions()["state_version"]
        library.record_batch(s, item, {"眼鏡": [1700000000031]}, None, batch="level-1")
        assert s.versions()["state_version"] == before + 1


def test_a_level_batch_repeating_a_recorded_word_and_note_id_changes_nothing():
    # The same word with the same note id is already recorded: no write, so the version and the row stay as they were.
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
        library.record_batch(s, item, {}, "2026-10-01T09:00:00", batch="batch-1")
        library.record_batch(s, item, {"眼鏡": [1700000000031]}, None, batch="level-1")
        row_before = s.conn.execute("SELECT made_at, batch FROM made_words WHERE item_id = ? AND word = ?",
                                    (item, "眼鏡")).fetchone()
        before = s.versions()["state_version"]
        library.record_batch(s, item, {"眼鏡": [1700000000031]}, None, batch="level-2")
        assert s.versions()["state_version"] == before
        row_after = s.conn.execute("SELECT made_at, batch FROM made_words WHERE item_id = ? AND word = ?",
                                   (item, "眼鏡")).fetchone()
        assert row_after == row_before


def test_an_empty_level_batch_takes_no_write_and_leaves_state_version_alone():
    # A level job with nothing to make (S19: no write at all) must not wake every reader for nothing.
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
        library.record_batch(s, item, {}, "2026-10-01T09:00:00", batch="batch-1")
        before = s.versions()["state_version"]
        library.record_batch(s, item, {}, None)
        assert s.versions()["state_version"] == before
