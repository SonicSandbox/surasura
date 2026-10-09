"""*Undo this batch* (P2.5 row 2.5.5; P1.5 02-data-model N9, 06-edges E31; ✅ Q2-6: undoing a bad batch touches only
cards the suite made and nobody studied; ✅ Sonic 2026-10-08 P2.5-1: the undone cards' words are free again).

What each test holds still — ORDER's proof, "undoing a test batch removes exactly its unstudied cards":

  * of one batch's five cards, the one you studied, the one you edited after it was made, the one you suspended and
    one that lost the batch's tag stay; only the untouched one goes. A wrong answer deletes a learner's work;
  * a card the shelf suspended (Connect's own suspend) is no reason to keep it: it goes;
  * a note with two cards stays when either card was studied;
  * the deleted note's clip and picture go once no other note uses them; a file another note still points at stays;
  * the ledger records the undo (deleted, kept with why) and the job is `undone`; a job still running is refused and
    nothing is written; while you review nothing is deleted;
  * the plan (no `--confirm`) writes nothing: Anki, ledger and store untouched;
  * the store: the deleted note's word is free again (its made-words row goes) and the item's receipt is cleared
    once nothing of it is left; a kept note's word stays made.

The words are real Japanese ones; Anki is a fake (no test reaches Anki); the ledger and the store are real SQLite in
temp folders.
"""
import calendar
import contextlib
import json
import time

import pytest

from app.connect import undo
from app.connect.ledger import Ledger

TAG = "surasura::connect::"


class FakeAnki:
    """Undo's Anki: notes {id: {"tags", "mod", "cards", "fields"}}, cards {id: {"reps", "type", "queue", "note"}}."""

    def __init__(self):
        self.notes_ = {}
        self.cards_ = {}
        self.media = set()
        self.busy = False
        self.deleted, self.media_deleted = [], []

    def add(self, note_id, tag, word, mod, cards=None, sound=None):
        cards = cards or [{"reps": 0, "type": 0, "queue": 0}]
        ids = []
        for n, card in enumerate(cards):
            cid = note_id * 10 + n
            self.cards_[cid] = dict(card, cardId=cid, note=note_id)
            ids.append(cid)
        fields = {"Word": {"value": word}, "SentenceAudio": {"value": f"[sound:{sound}]" if sound else ""}}
        self.notes_[note_id] = {"noteId": note_id, "tags": [tag], "mod": mod, "cards": ids, "fields": fields}
        if sound:
            self.media.add(sound)

    def notes(self, ids):
        return [self.notes_[i] for i in ids if i in self.notes_]

    def cards(self, ids):
        return [self.cards_[i] for i in ids if i in self.cards_]

    def reviewing(self):
        return self.busy

    def writer(self, verb):
        return contextlib.nullcontext()

    def delete_notes(self, ids):
        for i in ids:
            note = self.notes_.pop(i)
            for c in note["cards"]:
                self.cards_.pop(c, None)
            self.deleted.append(i)

    def users(self, name):
        return [n for n, note in self.notes_.items() if name in json.dumps(note["fields"], ensure_ascii=False)]

    def delete_media(self, name):
        self.media.discard(name)
        self.media_deleted.append(name)


WORDS = [(101, "上層部"), (102, "一生懸命"), (103, "走り出す"), (104, "気配"), (105, "溜め息")]


def _batch(ledger, item_id=7, state="done"):
    """A finished job of item 7 that made the five notes above (their outcomes `made`) -> (job id, its tag)."""
    job_id = ledger.queue("ja", item_id, "user", None, store_id="s1")
    ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                         for n, w in WORDS])
    ledger.set_state(job_id, state)
    return job_id, TAG + ledger.tag_id(job_id)


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def _anki_for(tag, done_at):
    anki = FakeAnki()
    anki.add(101, tag, "上層部", done_at - 60, sound="sl-aaaa.mp3")                       # untouched: goes
    anki.add(102, tag, "一生懸命", done_at - 60, cards=[{"reps": 3, "type": 2, "queue": 2}])  # studied: stays
    anki.add(103, tag, "走り出す", done_at + 3600)                                         # edited since: stays
    anki.add(104, tag, "気配", done_at - 60, cards=[{"reps": 0, "type": 0, "queue": -1}])  # you suspended it: stays
    anki.add(105, "my-own-tag", "溜め息", done_at - 60)                                    # not this batch's tag
    return anki


def _done_at(ledger, job_id):
    return calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))


def test_undo_removes_exactly_the_unstudied_untouched_cards_and_lists_the_rest(ledger):
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag, _done_at(ledger, job_id))
    done = undo.run(anki, ledger, job_id)
    assert anki.deleted == [101], "only the untouched card of the batch goes"
    kept = {n: why for n, _w, why in done["keep"]}
    assert kept == {102: undo.STUDIED, 103: undo.CHANGED, 104: undo.SUSPENDED, 105: undo.NOT_ITS_TAG}
    assert ledger.job_by_id(job_id)["state"] == "undone"
    (record,) = ledger.undos(job_id)
    assert record["deleted"] == [101] and {k[0] for k in record["kept"]} == {102, 103, 104, 105}


def test_the_deleted_cards_media_goes_once_no_note_uses_it_and_a_shared_file_stays(ledger):
    job_id, tag = _batch(ledger)
    done_at = _done_at(ledger, job_id)
    anki = _anki_for(tag, done_at)
    anki.notes_[102]["fields"]["SentenceAudio"]["value"] = "[sound:sl-shared.mp3]"
    anki.notes_[101]["fields"]["SentenceAudio"]["value"] = "[sound:sl-aaaa.mp3][sound:sl-shared.mp3]"
    anki.media |= {"sl-shared.mp3"}
    undo.run(anki, ledger, job_id)
    assert anki.media_deleted == ["sl-aaaa.mp3"], "the file the kept card still plays stays in Anki"


def test_a_card_the_shelf_suspended_is_no_reason_to_keep_it(ledger):
    """The shelf's own suspend is Connect's, not yours: such a card goes with its batch."""
    from app.connect import shelf
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag, _done_at(ledger, job_id))
    with ledger.transaction():
        shelf.ensure(ledger)
        ledger.conn.execute("INSERT INTO shelf (card_id, note_id, language, item_id, word, run, why, shelved_at) "
                            "VALUES (1040, 104, 'ja', 7, '気配', 'shelf-1', 'the cap', ?)",
                            (ledger.job_by_id(job_id)["updated_at"],))
    plan = undo.plan(anki, ledger, job_id)
    assert 104 in plan["delete"]


def test_a_note_with_two_cards_stays_when_either_was_studied(ledger):
    job_id, tag = _batch(ledger)
    done_at = _done_at(ledger, job_id)
    anki = _anki_for(tag, done_at)
    anki.add(101, tag, "上層部", done_at - 60, cards=[{"reps": 0, "type": 0, "queue": 0},
                                                       {"reps": 1, "type": 1, "queue": 1}])
    assert [k[0] for k in undo.plan(anki, ledger, job_id)["keep"]][0] == 101


def test_the_plan_writes_nothing(ledger):
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag, _done_at(ledger, job_id))
    plan = undo.plan(anki, ledger, job_id)
    assert plan["delete"] == [101]
    assert anki.deleted == [] and anki.media_deleted == []
    assert ledger.job_by_id(job_id)["state"] == "done" and ledger.undos(job_id) == []


def test_a_job_still_running_is_refused_and_nothing_is_touched(ledger):
    job_id, tag = _batch(ledger, state="filling")
    anki = _anki_for(tag, _done_at(ledger, job_id))
    with pytest.raises(undo.Refused) as err:
        undo.run(anki, ledger, job_id)
    assert err.value.say == undo.STILL_RUNNING
    assert anki.deleted == [] and ledger.job_by_id(job_id)["state"] == "filling"


def test_nothing_is_deleted_while_you_review(ledger):
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag, _done_at(ledger, job_id))
    anki.busy = True
    with pytest.raises(undo.Reviewing):
        undo.run(anki, ledger, job_id)
    assert anki.deleted == [] and ledger.job_by_id(job_id)["state"] == "done"


def test_an_undone_batch_cannot_be_undone_twice(ledger):
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag, _done_at(ledger, job_id))
    undo.run(anki, ledger, job_id)
    with pytest.raises(undo.Refused):
        undo.plan(anki, ledger, job_id)


class FakeStore:
    """`library.unmake`'s store: a real SQLite made_words table and an items table with `mined_at`."""

    def __init__(self, path):
        import sqlite3
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute("CREATE TABLE made_words (item_id INTEGER, word TEXT, note_ids TEXT, made_at TEXT, "
                          "batch TEXT, PRIMARY KEY (item_id, word))")
        self.conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, mined_at TEXT)")
        self.receipts = []
        self.touched = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @contextlib.contextmanager
    def _reading(self):
        yield

    @contextlib.contextmanager
    def _command(self, kind, by="user"):
        store = self

        class Cmd:
            def touch(self):
                store.touched += 1
        self.conn.execute("BEGIN")
        yield Cmd()
        self.conn.execute("COMMIT")

    def receipt(self, item_id, mined_at):
        self.receipts.append((item_id, mined_at))


def test_the_store_frees_the_deleted_cards_words_and_keeps_the_kept_ones(ledger, tmp_path):
    """✅ P2.5-1: an undo frees its words (Connect may make them again); a kept card's word stays made, so the item
    keeps its receipt."""
    store = FakeStore(str(tmp_path / "store.sqlite"))
    for n, w in WORDS:
        store.conn.execute("INSERT INTO made_words VALUES (7, ?, ?, 'x', 'b')", (w, json.dumps([n])))
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag, _done_at(ledger, job_id))
    done = undo.run(anki, ledger, job_id, open_store=lambda: store)
    assert done["freed"] == ["上層部"]
    left = {r[0] for r in store.conn.execute("SELECT word FROM made_words")}
    assert left == {"一生懸命", "走り出す", "気配", "溜め息"}
    assert store.receipts == [], "cards of the item are still in Anki: its receipt stays"


def test_the_receipt_is_cleared_when_nothing_of_the_item_is_left(ledger, tmp_path):
    store = FakeStore(str(tmp_path / "store.sqlite"))
    store.conn.execute("INSERT INTO made_words VALUES (7, '上層部', '[101]', 'x', 'b')")
    job_id = ledger.queue("ja", 7, "user", None, store_id="s1")
    ledger.end_batch(job_id, 1, "done", [{"word": "上層部", "reading": "", "outcome": "made", "note_id": 101}])
    ledger.set_state(job_id, "done")
    anki = FakeAnki()
    anki.add(101, TAG + ledger.tag_id(job_id), "上層部", _done_at(ledger, job_id) - 60)
    undo.run(anki, ledger, job_id, open_store=lambda: store)
    assert store.conn.execute("SELECT COUNT(*) FROM made_words").fetchone()[0] == 0
    assert store.receipts == [(7, None)]
