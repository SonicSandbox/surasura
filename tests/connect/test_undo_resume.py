"""*Undo this batch*, a kill left half-way (P2.5 row 2.5.5; P1.5 02-data-model N9): an undo recorded before Anki was
written is finished by the next look. What each test holds still:

  * a kill after Anki's delete: the next look finds the notes gone, records them, and the job is `undone`;
  * a kill before Anki's delete (every card still there): the next look records nothing gone, and the job stays
    `done` (it can still be undone later) — `finish` must not mark it `undone` or close the shelf for nothing;
  * once the batch's notes are all gone, the item is placed again (the receipt is not held by anything).

Words are real Japanese ones; Anki is a fake (no test reaches Anki); the ledger is a real SQLite file in a temp folder.
"""
import contextlib

import pytest

from app.connect import undo
from app.connect.ledger import Ledger

TAG = "surasura::connect::"
WORDS = [(101, "上層部"), (102, "一生懸命")]


class FakeAnki:
    """Undo's Anki: notes {id: {"noteId", "tags", "mod", "cards", "fields"}}, cards {id: {"reps", "type", "queue"}}.
    Each note has one unstudied card, so `undo.run` deletes it only because it is verified unstudied and unchanged."""

    def __init__(self):
        self.notes_ = {}
        self.cards_ = {}

    def add(self, note_id, tag, word, mod, cards=None):
        cards = cards or [{"reps": 0, "type": 0, "queue": 0}]
        ids = []
        for n, card in enumerate(cards):
            cid = note_id * 10 + n
            self.cards_[cid] = dict(card, cardId=cid, note=note_id)
            ids.append(cid)
        self.notes_[note_id] = {"noteId": note_id, "tags": [tag], "mod": mod, "cards": ids,
                                "fields": {"Word": {"value": word}}}

    def notes(self, ids):
        return [self.notes_[i] for i in ids if i in self.notes_]

    def cards(self, ids):
        return [self.cards_[i] for i in ids if i in self.cards_]

    def reviewing(self):
        return False

    def writer(self, verb):
        return contextlib.nullcontext()

    def delete_notes(self, ids):
        for i in ids:
            note = self.notes_.pop(i, None)
            for c in (note or {}).get("cards", []):
                self.cards_.pop(c, None)


class FakeStore:
    """`library.unmake`'s store: a real SQLite made_words table and an items table with `mined_at`."""

    def __init__(self, path):
        import sqlite3
        self.conn = sqlite3.connect(path, isolation_level=None)
        self.conn.execute("CREATE TABLE made_words (item_id INTEGER, word TEXT, note_ids TEXT, made_at TEXT, "
                          "batch TEXT, PRIMARY KEY (item_id, word))")
        self.conn.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, mined_at TEXT)")
        self.receipts = []
        self.mined = {}             # item id -> its receipt (every item holds one until `receipt` clears it)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    @contextlib.contextmanager
    def _reading(self):
        yield

    @contextlib.contextmanager
    def _command(self, kind, by="user"):
        class Cmd:
            def touch(self):
                pass
        self.conn.execute("BEGIN")
        yield Cmd()
        self.conn.execute("COMMIT")

    def receipt(self, item_id, mined_at):
        self.receipts.append((item_id, mined_at))
        self.mined[item_id] = mined_at

    def item(self, item_id):
        return {"id": item_id, "mined_at": self.mined.get(item_id, "2026-10-08T10:00:00Z")}


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def _batch(ledger, item_id=7):
    """A finished job of item 7 that made the two notes above -> (job id, its tag)."""
    job_id = ledger.queue("ja", item_id, "user", None, store_id="s1")
    ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                         for n, w in WORDS])
    ledger.set_state(job_id, "done")
    return job_id, TAG + ledger.tag_id(job_id)


def _anki_for(tag):
    """Each note last changed in 1970 — long before the job ended — so none is CHANGED (the user never edited it)."""
    anki = FakeAnki()
    for n, w in WORDS:
        anki.add(n, tag, w, mod=1)
    return anki


def test_a_kill_after_anki_deleted_is_finished_by_the_next_look(ledger, tmp_path):
    """The kill came after Anki's delete and before the ledger's finish: the next look records the deleted note,
    marks the job `undone`, frees its word in the library store, and leaves the undo no longer pending."""
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag)
    store = FakeStore(str(tmp_path / "store.sqlite"))
    store.conn.execute("INSERT INTO made_words VALUES (7, '上層部', '[101]', 'x', 'b')")
    ledger.start_undo(job_id, "ja", [101], [])     # written before Anki's delete
    anki.delete_notes([101])                        # Anki deleted it, then the app was killed
    assert undo.finish_pending(anki, ledger, "ja", open_store=lambda: store) == 1
    assert ledger.job_by_id(job_id)["state"] == "undone"
    (record,) = ledger.undos(job_id)
    assert record["deleted"] == [101] and record["finished_at"] is not None
    assert ledger.pending_undos("ja") == []
    assert store.conn.execute("SELECT COUNT(*) FROM made_words WHERE word = '上層部'").fetchone()[0] == 0


def test_a_kill_before_anki_deleted_leaves_the_job_done_and_a_later_undo_still_works(ledger):
    """The kill came before Anki's delete: every card is still there, so nothing is gone. The job must stay `done`
    (not `undone`), and a later undo of the same batch must still delete its unstudied note."""
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag)
    ledger.start_undo(job_id, "ja", [101], [])     # written; Anki never deleted anything
    assert undo.finish_pending(anki, ledger, "ja") == 1
    assert anki.notes([101]) != [], "nothing was deleted"
    assert ledger.job_by_id(job_id)["state"] == "done", "no note gone: the job stays as it was, so it can be undone"
    (record,) = ledger.undos(job_id)
    assert record["deleted"] == [] and record["finished_at"] is not None
    assert 101 in undo.plan(anki, ledger, job_id)["delete"], "the unstudied, unchanged note may go"
    done = undo.run(anki, ledger, job_id)
    assert 101 in done["deleted"] and ledger.job_by_id(job_id)["state"] == "undone"


def test_the_batch_is_placed_again_once_all_its_notes_are_gone(ledger, tmp_path):
    """Everything the batch made went: the job is `undone`, the store's made words are freed, its receipt is cleared
    (nothing holds it), so the item is placed again."""
    store = FakeStore(str(tmp_path / "store.sqlite"))
    store.conn.execute("INSERT INTO made_words VALUES (7, '上層部', '[101]', 'x', 'b')")
    store.conn.execute("INSERT INTO made_words VALUES (7, '一生懸命', '[102]', 'x', 'b')")
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag)
    anki.delete_notes([101, 102])
    ledger.start_undo(job_id, "ja", [101, 102], [])
    (pending,) = ledger.pending_undos("ja")
    result = undo.finish(anki, ledger, pending, open_store=lambda: store)
    assert sorted(result["deleted"]) == [101, 102] and result["keep"] == []
    assert result["placed_again"] is True
    assert ledger.job_by_id(job_id)["state"] == "undone"
    assert store.conn.execute("SELECT COUNT(*) FROM made_words").fetchone()[0] == 0
    assert store.receipts == [(7, None)], "the item's receipt is cleared"
    assert store.item(7)["mined_at"] is None


def test_the_batch_is_not_placed_again_while_a_kept_card_of_the_item_is_left(ledger, tmp_path):
    """One card of the item is gone, the other is still in Anki (its word still made in the store): the item keeps
    its receipt, so it is not placed again."""
    store = FakeStore(str(tmp_path / "store.sqlite"))
    store.conn.execute("INSERT INTO made_words VALUES (7, '上層部', '[101]', 'x', 'b')")
    store.conn.execute("INSERT INTO made_words VALUES (7, '一生懸命', '[102]', 'x', 'b')")
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag)
    anki.delete_notes([101])                        # 102 stays in Anki
    ledger.start_undo(job_id, "ja", [101], [[102, "一生懸命", "kept"]])
    (pending,) = ledger.pending_undos("ja")
    result = undo.finish(anki, ledger, pending, open_store=lambda: store)
    assert result["deleted"] == [101] and result["placed_again"] is False
    assert {r[0] for r in store.conn.execute("SELECT word FROM made_words")} == {"一生懸命"}
    assert store.receipts == [], "a kept card is still in Anki: the item's receipt stays"


def _store_with_both(tmp_path):
    store = FakeStore(str(tmp_path / "store.sqlite"))
    store.conn.execute("INSERT INTO made_words VALUES (7, '上層部', '[101]', 'x', 'b')")
    store.conn.execute("INSERT INTO made_words VALUES (7, '一生懸命', '[102]', 'x', 'b')")
    return store


def test_run_says_placing_again_remakes_the_cards_when_everything_of_the_item_went(ledger, tmp_path):
    # through `undo.run` itself (its wiring of the plan, the record and `finish`): both unstudied notes go
    store = _store_with_both(tmp_path)
    job_id, tag = _batch(ledger)
    done = undo.run(_anki_for(tag), ledger, job_id, open_store=lambda: store)
    assert sorted(done["deleted"]) == [101, 102] and done["placed_again"] is True
    assert store.receipts == [(7, None)]


def test_run_says_placing_again_makes_nothing_while_a_studied_card_stays(ledger, tmp_path):
    # 102 was studied: the plan keeps it, so its word stays made and the item keeps its receipt
    store = _store_with_both(tmp_path)
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag)
    anki.add(102, tag, "一生懸命", mod=1, cards=[{"reps": 2, "type": 2, "queue": 2}])
    done = undo.run(anki, ledger, job_id, open_store=lambda: store)
    assert done["deleted"] == [101] and done["placed_again"] is False
    assert [k[0] for k in done["keep"]] == [102] and store.receipts == []


def test_a_busy_library_leaves_the_undo_pending_and_the_next_look_frees_the_words(ledger, tmp_path, monkeypatch):
    # the store can't be opened just after Anki's delete: the words aren't freed, so the undo must stay pending
    # (finished by the next look), never closed with its words still held
    monkeypatch.setattr(undo, "_no_store", lambda language: False)     # a library exists; it's busy just now
    store = _store_with_both(tmp_path)
    job_id, tag = _batch(ledger)
    anki = _anki_for(tag)
    done = undo.run(anki, ledger, job_id, open_store=lambda: None)
    assert sorted(done["deleted"]) == [101, 102] and done["pending"] is True and done["placed_again"] is False
    assert ledger.job_by_id(job_id)["state"] == "undone"
    assert len(ledger.pending_undos("ja")) == 1
    assert undo.finish_pending(anki, ledger, "ja", open_store=lambda: store) == 1
    assert ledger.pending_undos("ja") == []
    assert store.conn.execute("SELECT COUNT(*) FROM made_words").fetchone()[0] == 0
