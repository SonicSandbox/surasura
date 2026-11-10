"""`surasura-cli undo --job N --confirm` (app/cli/connect_verbs.py) owes Anki's sync once.

The rule this pins: an undo that deletes Anki cards changes tomorrow's cards, so a confirmed undo asks for the
session's sync exactly once; the plan (no --confirm) deletes nothing and asks for no sync. A wrong answer here
would leave deleted cards out of the day's sync, or send a sync for a look that changed nothing.

The words are real Japanese ones; Anki is a fake (no test reaches Anki); the ledger is real SQLite in the test root.
"""
import calendar
import contextlib
import json
import os
import time

import pytest

from app.cli import connect_verbs
from app.connect import undo
from app.connect.ledger import Ledger, path
from tests import cli_helpers as h

TAG = "surasura::connect::"
WORDS = [(101, "上層部"), (102, "一生懸命"), (103, "走り出す"), (104, "気配"), (105, "溜め息")]


class FakeAnki:
    """Undo's Anki: notes {id: {"tags", "mod", "cards", "fields"}}, cards {id: {"reps", "type", "queue", "note"}}."""

    def __init__(self):
        self.notes_ = {}
        self.cards_ = {}
        self.media = set()
        self.busy = False
        self.deleted = []

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


@pytest.fixture
def connected(monkeypatch):
    """Preview on, the language set up; the sync is a recorder, so the test sees each call it would send."""
    h.write_settings(connect_enabled=True)
    os.makedirs(os.path.join(h.root(), "User Files", "ja"), exist_ok=True)
    monkeypatch.delenv("SURASURA_NO_ANKI_SYNC", raising=False)
    synced = []
    monkeypatch.setattr(connect_verbs, "_owe_sync", lambda loaded: synced.append(loaded))
    anki = FakeAnki()
    monkeypatch.setattr(undo, "AnkiConnectUndo", lambda url: anki)
    return anki, synced


def _finished_batch(anki):
    """A finished job of item 7 that made the five notes, with note 101 untouched since before the batch ended.
    Returns the job id; `anki` holds the batch's cards."""
    with Ledger(path()) as ledger:
        job_id = ledger.queue("ja", 7, "user", None, store_id="s1")
        ledger.end_batch(job_id, 1, "done", [{"word": w, "reading": "", "outcome": "made", "note_id": n}
                                             for n, w in WORDS])
        ledger.set_state(job_id, "done")
        tag = TAG + ledger.tag_id(job_id)
        done_at = calendar.timegm(time.strptime(ledger.job_by_id(job_id)["updated_at"], "%Y-%m-%dT%H:%M:%SZ"))
    anki.add(101, tag, "上層部", done_at - 60)
    return job_id


def test_undo_plan_without_confirm_owes_no_sync(connected):
    # Only --confirm deletes, so only a confirmed undo changes tomorrow's cards and asks for the sync
    anki, synced = connected
    job_id = _finished_batch(anki)
    code, answer = h.call("undo", "--job", str(job_id))
    assert code == 0 and answer["confirm"] is False
    assert synced == [], "the plan deletes nothing, so no sync is owed"


def test_confirmed_undo_owes_anki_sync_exactly_once(connected):
    # The deletion is followed by one sync request; a second one would send the same write twice
    anki, synced = connected
    job_id = _finished_batch(anki)
    code, answer = h.call("undo", "--job", str(job_id), "--confirm")
    assert code == 0 and answer["confirm"] is True
    assert anki.deleted == [101], "the confirmed undo deleted the card"
    assert len(synced) == 1, "the deletion owes Anki's sync exactly once"
