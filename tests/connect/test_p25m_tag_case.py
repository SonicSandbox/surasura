"""Undo's tag match ignores capitals: Anki's tags are case-insensitive, so a note carrying this batch's tag
written with other capitals is still this batch's note and goes, while a note with another tag stays.

What a wrong answer would cost: a batch's untouched cards with a re-capitalised tag (Anki writes tags as it
likes) would be kept forever and never undone, or, reversed, a note of another tag would be deleted.
"""
import calendar
import contextlib
import json
import time

import pytest

from app.connect import undo
from app.connect.ledger import Ledger


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


WORDS = [(101, "上層部"), (102, "一生懸命")]


def _batch(ledger, item_id=7, state="done"):
    """A finished job of item 7 that made the two notes above -> job id."""
    job_id = ledger.queue("ja", item_id, "user", None, store_id="s1")
    ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                         for n, w in WORDS])
    ledger.set_state(job_id, state)
    return job_id


@pytest.fixture
def ledger(tmp_path):
    book = Ledger(str(tmp_path / "ledger.sqlite"))
    try:
        yield book
    finally:
        book.close()


def _done_at(ledger, job_id):
    return calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))


def test_undo_matches_the_batch_tag_in_any_capitals_and_keeps_another_tag(ledger):
    # Anki treats tags case-insensitively, so a note whose tag is re-capitalised by Anki is still this batch's note.
    job_id = _batch(ledger)
    done_at = _done_at(ledger, job_id)
    anki = FakeAnki()
    anki.add(101, "Surasura::Connect::" + ledger.tag_id(job_id), "上層部", done_at - 60)
    anki.add(102, "my-own-tag", "一生懸命", done_at - 60)  # another tag: never this batch's, stays
    plan = undo.plan(anki, ledger, job_id)
    assert 101 in plan["delete"], "a capitalised batch tag still counts as this batch's note"
    assert 102 not in plan["delete"], "a note with another tag is never deleted"
    assert {n: why for n, _w, why in plan["keep"]}.get(102) == undo.NOT_ITS_TAG
