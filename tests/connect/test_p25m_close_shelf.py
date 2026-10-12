"""An undo closes only the shelf rows still on the shelf (P2.5 mutant M3: `undo._close_shelf`).

What each test holds still, and what a wrong answer would cost:

  * when an undo deletes a note, the shelf row of its card that is still on the shelf is recorded as undone;
  * a row of the same card already put back by you keeps its own `back_at` and `back_by` ("you"): a wrong overwrite
    would turn your own choice into an undo, and the shelf would lose the record of what you did.

Real Japanese words, fake Anki, real SQLite in temp folders; no network, no sleeps.
"""
import calendar
import contextlib
import json
import time

import pytest

from app.connect import shelf, undo
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

    def add(self, note_id, tag, word, mod, cards=None):
        cards = cards or [{"reps": 0, "type": 0, "queue": 0}]
        ids = []
        for n, card in enumerate(cards):
            cid = note_id * 10 + n
            self.cards_[cid] = dict(card, cardId=cid, note=note_id)
            ids.append(cid)
        fields = {"Word": {"value": word}, "SentenceAudio": {"value": ""}}
        self.notes_[note_id] = {"noteId": note_id, "tags": [tag], "mod": mod, "cards": ids, "fields": fields}

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


def _batch(ledger, item_id=7):
    """A finished job of item 7 that made one note (上層部) -> (job id, its tag)."""
    job_id = ledger.queue("ja", item_id, "user", None, store_id="s1")
    ledger.end_batch(job_id, 1, "done", [{"word": "上層部", "reading": "", "outcome": "made", "note_id": 101}])
    ledger.set_state(job_id, "done")
    return job_id, TAG + ledger.tag_id(job_id)


def _done_at(ledger, job_id):
    return calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))


def _utc(seconds):
    """A UTC text stamp, the way the ledger and the shelf write them."""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


@pytest.fixture
def ledger(tmp_path):
    led = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield led
    finally:
        led.close()


def test_undo_closes_the_shelf_row_still_on_the_shelf_as_undone(ledger):
    """The note goes with its batch; the shelf row of its card that was still waiting is recorded as undone."""
    job_id, tag = _batch(ledger)
    done_at = _done_at(ledger, job_id)
    anki = FakeAnki()
    anki.add(101, tag, "上層部", done_at - 60)                  # untouched: goes; its card is 1010
    with ledger.transaction():
        shelf.ensure(ledger)
        ledger.conn.execute("INSERT INTO shelf (card_id, note_id, language, item_id, word, run, why, shelved_at, "
                            "mod_shelved) VALUES (1010, 101, 'ja', 7, '上層部', 'run-b', 'the cap', ?, ?)",
                            (_utc(done_at - 400), done_at - 60))
    done = undo.run(anki, ledger, job_id, open_store=None)
    assert done["deleted"] == [101]
    back_at, back_by = ledger.conn.execute(
        "SELECT back_at, back_by FROM shelf WHERE card_id = 1010 AND run = 'run-b'").fetchone()
    assert back_by == "undone" and back_at is not None


def test_undo_leaves_a_row_you_put_back_earlier_with_its_own_time_and_yours(ledger):
    """A card you put back before the undo keeps your record; only the row still on the shelf is closed as undone."""
    job_id, tag = _batch(ledger)
    done_at = _done_at(ledger, job_id)
    anki = FakeAnki()
    anki.add(101, tag, "上層部", done_at - 60)                  # untouched: goes; its card is 1010
    you_at = _utc(done_at - 500)
    with ledger.transaction():
        shelf.ensure(ledger)
        ledger.conn.executemany(
            "INSERT INTO shelf (card_id, note_id, language, item_id, word, run, why, shelved_at, mod_shelved, "
            "back_at, back_by) VALUES (1010, 101, 'ja', 7, '上層部', ?, 'the cap', ?, ?, ?, ?)",
            [("run-a", _utc(done_at - 600), done_at - 60, you_at, "you"),       # shelved, then put back by you
             ("run-b", _utc(done_at - 400), done_at - 60, None, None)])          # still on the shelf
    done = undo.run(anki, ledger, job_id, open_store=None)
    assert done["deleted"] == [101]
    rows = dict((run, (back_at, back_by)) for run, back_at, back_by in ledger.conn.execute(
        "SELECT run, back_at, back_by FROM shelf WHERE card_id = 1010"))
    # your put-back row: your own time and your own name, never overwritten by the undo
    assert rows["run-a"] == (you_at, "you")
    # the row that was still on the shelf: closed as undone, with a time
    assert rows["run-b"][1] == "undone" and rows["run-b"][0] is not None
