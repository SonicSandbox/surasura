"""A card deleted in Anki (P2.4 row 2.4.14, L3.3 wiring): the runner's `Steps.notes_gone` tells the store, and the
store keeps the made word but takes the deleted note id out of it; a later level raise that lists the same word for
the same episode still queues no job for it (G1.3-4: a word Connect made is never made again automatically, even
when its card was deleted). What a wrong answer would cost: a deleted card whose note id stays in the store (the word
reads "in Anki" forever), or a deleted card's word made again without the learner asking (a second card the learner
never wanted)."""
import json

from app.connect import library, runner
from app.connect.ledger import LEVEL, Ledger
from tests import connect_helpers as c
from tests.cli_helpers import same_token_store_as_the_children  # noqa: F401  (autouse)
from tests.connect.test_level import BEFORE, RAISED, _check, _line, _mine

NOTE_ID = 1700000000041  # the card Connect made for 眼鏡 (Anki note ids are millisecond timestamps)


class FakeAnki:
    """Only what Steps.notes_gone calls through shelf.gone_notes: find_notes("nid:a,b,...") answers the ids still in
    Anki. Here Anki has none of them: the learner deleted the card."""

    def __init__(self, still_there):
        self.still_there = set(still_there)

    def find_notes(self, query):
        assert query.startswith("nid:"), query
        ids = [int(n) for n in query[len("nid:"):].split(",")]
        return [n for n in ids if n in self.still_there]


def _made_then_deleted():
    """Connect made 眼鏡 for the first episode of the line (mined), then the learner deleted that card in Anki; the
    runner's own step reads Anki and tells the store. Returns (the episode's item id, its file name, what the step
    named as gone)."""
    (a, fa), _b, _d = _line()
    _mine(a)
    with c.store() as s:
        library.record_batch(s, a, {"眼鏡": [NOTE_ID]}, "2026-10-07T09:00:00Z", batch="1")
    steps = runner.Steps({"connect_enabled": True})
    steps._anki = lambda: FakeAnki(still_there=set())
    gone = steps.notes_gone("ja")
    return a, fa, gone


def test_a_deleted_card_is_named_gone_and_its_made_word_row_keeps_no_note_id():
    # The row stays (the word is made once, G1.3-4); only the deleted note id leaves it, so the word no longer reads
    # "in Anki". A mutant that skips the store's notes_gone leaves the id in the row and fails here.
    a, _fa, gone = _made_then_deleted()
    assert NOTE_ID in gone, "the step names the note id Anki no longer has"
    with c.store() as s:
        row = s.conn.execute("SELECT note_ids FROM made_words WHERE item_id = ? AND word = ?", (a, "眼鏡")).fetchone()
    assert row is not None, "the made word's row is kept: the word is never made again by itself"
    assert json.loads(row[0]) == [], "the deleted card's note id is taken out of the row"


def test_a_level_raise_after_a_deleted_card_does_not_make_its_word_again():
    # The raise lists 眼鏡 as new for the mined episode; with the card deleted, Connect still queues only 老婆.
    a, fa, _gone = _made_then_deleted()
    _check(BEFORE, "run-1", {fa: ["眼鏡", "老婆"]})
    _check(RAISED, "run-2", {fa: ["眼鏡", "老婆"]})
    with Ledger() as ledger:
        jobs = [ledger.job_by_id(j["id"]) for j in ledger.jobs("ja") if j["kind"] == LEVEL]
    assert [j["words"] for j in jobs] == [[("老婆", "ロウバ")]], \
        "G1.3-4: a word made once is never made again, even when its card was deleted"
