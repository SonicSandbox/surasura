"""*Undo this batch* refuses a job in any open state (P2.5 mutant M4; P1.5 02-data-model N9).

The rule: a batch that is still open (queued, waiting, picking, fit-check, mining, filling, ordering) is never undone,
by the plan or by the run: Connect is still making its cards, so an undo now would delete cards the batch has not
finished with. The refusal says "still running" and nothing is deleted. A wrong answer deletes a learner's cards while
Connect is still writing them.

The words are real Japanese ones; Anki is a fake (no test reaches Anki); the ledger is real SQLite in a temp folder.
"""
import calendar
import contextlib
import json
import time

import pytest

from app.connect import undo
from app.connect.ledger import OPEN, Ledger

TAG = "surasura::connect::"

# Every open state of a job, taken from ledger.OPEN so a new open state is tested the moment it is added.
OPEN_STATES = list(OPEN)


class FakeAnki:
    """Undo's Anki: notes {id: {"tags", "mod", "cards", "fields"}}, cards {id: {"reps", "type", "queue", "note"}}."""

    def __init__(self):
        self.notes_ = {}
        self.cards_ = {}
        self.media = set()
        self.busy = False
        self.deleted, self.media_deleted = [], []

    def add(self, note_id, tag, word, mod):
        cid = note_id * 10
        self.cards_[cid] = {"reps": 0, "type": 0, "queue": 0, "cardId": cid, "note": note_id}
        fields = {"Word": {"value": word}, "SentenceAudio": {"value": ""}}
        self.notes_[note_id] = {"noteId": note_id, "tags": [tag], "mod": mod, "cards": [cid], "fields": fields}

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


def _batch_in_state(ledger, state):
    """A job of item 7 that made two notes, then left in an open state (as a batch still being made is) -> (job id, tag)."""
    job_id = ledger.queue("ja", 7, "user", None, store_id="s1")
    ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                         for n, w in [(201, "上層部"), (202, "一生懸命")]])
    ledger.set_state(job_id, state)
    return job_id, TAG + ledger.tag_id(job_id)


def _anki_for(tag, job_id, ledger):
    done_at = calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    anki = FakeAnki()
    anki.add(201, tag, "上層部", done_at - 60)
    anki.add(202, tag, "一生懸命", done_at - 60)
    return anki


@pytest.mark.parametrize("state", OPEN_STATES)
def test_undo_run_refuses_every_open_state_and_deletes_nothing(ledger, state):
    # Why every open state: a batch in "queued" or "ordering" is no less unfinished than one in "filling".
    job_id, tag = _batch_in_state(ledger, state)
    anki = _anki_for(tag, job_id, ledger)
    with pytest.raises(undo.Refused) as err:
        undo.run(anki, ledger, job_id)
    assert err.value.say == undo.STILL_RUNNING
    assert anki.deleted == [] and ledger.job_by_id(job_id)["state"] == state


@pytest.mark.parametrize("state", OPEN_STATES)
def test_undo_plan_refuses_every_open_state_and_writes_nothing(ledger, state):
    # The plan is read-only, but it must say the same thing as the run: a refused job has no plan to show.
    job_id, tag = _batch_in_state(ledger, state)
    anki = _anki_for(tag, job_id, ledger)
    with pytest.raises(undo.Refused) as err:
        undo.plan(anki, ledger, job_id)
    assert err.value.say == undo.STILL_RUNNING
    assert anki.deleted == [] and ledger.job_by_id(job_id)["state"] == state
