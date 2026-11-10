"""Connect's one store write per batch (P2.4, G1.1-10): the receipt and the made words land together, and a level job's
batch never clears a receipt.

What a wrong answer would cost: a receipt written without its made words (or the reverse) leaves a card made with no
record that it was, so the next run makes it again; a word recorded twice that loses its first note ids can no longer
find its own cards; a level job's batch that clears an item's receipt un-mines an episode the user already had. Real
Japanese words (上層部, 一生懸命), synthetic note ids, a temp library.
"""
from app.connect import library
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)


def test_a_batch_writes_its_receipt_and_made_words_in_one_state_step():
    # One transaction means one state_version step; two separate writes would move it twice.
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
        before = s.versions()["state_version"]
        library.record_batch(s, item, {"上層部": [1700000000001, 1700000000002]},
                             "2026-10-01T09:00:00", batch="batch-1")
        assert s.versions()["state_version"] == before + 1
        assert s.item(item)["mined_at"] == "2026-10-01T09:00:00"
        rows = s.conn.execute("SELECT word, note_ids, batch FROM made_words WHERE item_id = ?", (item,)).fetchall()
        assert rows == [("上層部", "[1700000000001, 1700000000002]", "batch-1")]


def test_a_word_made_again_keeps_its_first_note_ids_and_gains_the_new_ones():
    # A word made in an earlier batch must still point at its first cards, so the new note ids are added, not replaced.
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
        library.record_batch(s, item, {"一生懸命": [1700000000011]}, "2026-10-01T09:00:00", batch="batch-1")
        library.record_batch(s, item, {"一生懸命": [1700000000012]}, None, batch="batch-2")
        ids = s.conn.execute("SELECT note_ids FROM made_words WHERE item_id = ? AND word = ?",
                             (item, "一生懸命")).fetchone()[0]
        assert ids == "[1700000000011, 1700000000012]"


def test_a_level_job_batch_keeps_the_items_first_receipt():
    # mined_at=None is a level job's batch: it must leave the receipt the item already has, never clear it.
    c.library()
    with c.store() as s:
        item = s.ids("now")[0]
        library.record_batch(s, item, {}, "2026-10-01T09:00:00", batch="batch-1")
        library.record_batch(s, item, {"上層部": [1700000000021]}, None, batch="level-1")
        assert s.item(item)["mined_at"] == "2026-10-01T09:00:00"
