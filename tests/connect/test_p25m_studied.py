"""Undo keeps a note as studied when any one of its cards was studied or is in learning.

The rule: a note stays (as "you've studied it") when ANY of its cards has reps > 0 OR a
type other than new (type != 0), each condition alone. A wrong answer costs the user a
card they learned from: the undo would delete a note in learning, or one studied once
and then reset to new, along with the untouched notes it is meant to remove.
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


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def _batch(ledger):
    """A finished job of item 7 that made three notes (101 in learning, 102 studied once, 103 untouched)."""
    words = [(101, "上層部"), (102, "一生懸命"), (103, "走り出す"), (104, "見つけ出す")]
    job_id = ledger.queue("ja", 7, "user", None, store_id="s1")
    ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                         for n, w in words])
    ledger.set_state(job_id, "done")
    return job_id, TAG + ledger.tag_id(job_id)


def _done_at(ledger, job_id):
    return calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))


def test_a_note_in_learning_or_studied_once_is_kept_as_studied_and_only_the_untouched_goes(ledger):
    # Each of 101 and 102 trips a different condition: 101 is in learning (type 1, no review
    # counted), 102 was studied once and reset to new (reps 1, type 0). Neither may be deleted.
    job_id, tag = _batch(ledger)
    done_at = _done_at(ledger, job_id)
    anki = FakeAnki()
    anki.add(101, tag, "上層部", done_at - 60, cards=[{"reps": 0, "type": 1, "queue": 1}])
    anki.add(102, tag, "一生懸命", done_at - 60, cards=[{"reps": 1, "type": 0, "queue": 0}])
    anki.add(103, tag, "走り出す", done_at - 60)
    # 104 has two cards: the first untouched, the second reviewed. The note is studied because
    # ANY of its cards was, so it is kept even though its first card looks new.
    anki.add(104, tag, "見つけ出す", done_at - 60,
             cards=[{"reps": 0, "type": 0, "queue": 0}, {"reps": 2, "type": 2, "queue": 2}])
    planned = undo.plan(anki, ledger, job_id)
    assert planned["delete"] == [103], "only the note nobody has touched goes"
    kept = {n: why for n, _w, why in planned["keep"]}
    assert kept == {101: undo.STUDIED, 102: undo.STUDIED, 104: undo.STUDIED}
